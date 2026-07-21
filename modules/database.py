from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row

SCHEMA_VERSION = 3


class EconomyDatabase:
    def __init__(self, history_retention_days: int = 90) -> None:
        self.url = os.environ.get("DATABASE_URL", "").strip()
        self.history_retention_days = max(7, int(history_retention_days))
        self.enabled = bool(self.url)
        self.last_cleanup_at = 0.0
        self.schema_version = 0
        if self.enabled:
            self._run_migrations()
            self.cleanup(force=True)

    def _connect(self):
        return psycopg.connect(self.url, autocommit=True, row_factory=dict_row)

    def _run_migrations(self) -> None:
        migrations: list[tuple[int, str, tuple[str, ...]]] = [
            (1, "initial economy schema", (
                """CREATE TABLE IF NOT EXISTS economy_players (
                    vk_id BIGINT PRIMARY KEY, name TEXT NOT NULL, balance BIGINT NOT NULL DEFAULT 0,
                    last_salary_at DOUBLE PRECISION NOT NULL DEFAULT 0, bets_count BIGINT NOT NULL DEFAULT 0,
                    wins BIGINT NOT NULL DEFAULT 0, losses BIGINT NOT NULL DEFAULT 0,
                    total_bet BIGINT NOT NULL DEFAULT 0, total_won BIGINT NOT NULL DEFAULT 0,
                    total_lost BIGINT NOT NULL DEFAULT 0, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
                """CREATE TABLE IF NOT EXISTS economy_history (
                    id BIGSERIAL PRIMARY KEY, vk_id BIGINT NOT NULL REFERENCES economy_players(vk_id) ON DELETE CASCADE,
                    entry TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
                """CREATE TABLE IF NOT EXISTS economy_state (
                    key TEXT PRIMARY KEY, value JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
            )),
            (2, "economy indexes and data guards", (
                "CREATE INDEX IF NOT EXISTS economy_history_vk_id_idx ON economy_history(vk_id, created_at DESC)",
                "CREATE INDEX IF NOT EXISTS economy_players_balance_idx ON economy_players(balance DESC)",
                "ALTER TABLE economy_players DROP CONSTRAINT IF EXISTS economy_players_balance_nonnegative",
                "ALTER TABLE economy_players ADD CONSTRAINT economy_players_balance_nonnegative CHECK (balance >= 0) NOT VALID",
                "ALTER TABLE economy_players VALIDATE CONSTRAINT economy_players_balance_nonnegative",
            )),
            (3, "transactions and casino statistics", (
                "ALTER TABLE economy_players ADD COLUMN IF NOT EXISTS casino_games BIGINT NOT NULL DEFAULT 0",
                "ALTER TABLE economy_players ADD COLUMN IF NOT EXISTS casino_wins BIGINT NOT NULL DEFAULT 0",
                "ALTER TABLE economy_players ADD COLUMN IF NOT EXISTS casino_losses BIGINT NOT NULL DEFAULT 0",
                "ALTER TABLE economy_players ADD COLUMN IF NOT EXISTS casino_wagered BIGINT NOT NULL DEFAULT 0",
                "ALTER TABLE economy_players ADD COLUMN IF NOT EXISTS casino_profit BIGINT NOT NULL DEFAULT 0",
                "ALTER TABLE economy_players ADD COLUMN IF NOT EXISTS biggest_win BIGINT NOT NULL DEFAULT 0",
                "ALTER TABLE economy_players ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
                """CREATE TABLE IF NOT EXISTS economy_transactions (
                    id UUID PRIMARY KEY, kind TEXT NOT NULL, actor_vk_id BIGINT,
                    source_vk_id BIGINT, target_vk_id BIGINT, amount BIGINT NOT NULL,
                    reason TEXT NOT NULL, metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    reversed_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
                "CREATE INDEX IF NOT EXISTS economy_transactions_created_idx ON economy_transactions(created_at DESC)",
                "CREATE INDEX IF NOT EXISTS economy_transactions_source_idx ON economy_transactions(source_vk_id, created_at DESC)",
                "CREATE INDEX IF NOT EXISTS economy_transactions_target_idx ON economy_transactions(target_vk_id, created_at DESC)",
            )),
        ]
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
            cur.execute("SELECT version FROM schema_migrations")
            applied = {int(row["version"]) for row in cur.fetchall()}
            for version, name, statements in migrations:
                if version in applied:
                    continue
                with conn.transaction():
                    for statement in statements:
                        cur.execute(statement)
                    cur.execute("INSERT INTO schema_migrations (version, name) VALUES (%s, %s)", (version, name))
                print(f"Миграция БД {version} применена: {name}", flush=True)
            cur.execute("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations")
            row = cur.fetchone()
            self.schema_version = int(row["version"] if row else 0)
        if self.schema_version != SCHEMA_VERSION:
            raise RuntimeError(f"Некорректная версия схемы БД: {self.schema_version}, ожидалась {SCHEMA_VERSION}")

    def load_players(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM economy_players")
            players = list(cur.fetchall())
            for player in players:
                cur.execute("SELECT entry FROM economy_history WHERE vk_id=%s ORDER BY created_at DESC LIMIT 20", (player["vk_id"],))
                player["history"] = [row["entry"] for row in reversed(cur.fetchall())]
            return players

    def save_player(self, player: Any) -> None:
        if not self.enabled:
            return
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO economy_players (
                vk_id,name,balance,last_salary_at,bets_count,wins,losses,total_bet,total_won,total_lost,
                casino_games,casino_wins,casino_losses,casino_wagered,casino_profit,biggest_win,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (vk_id) DO UPDATE SET name=EXCLUDED.name,balance=EXCLUDED.balance,
                last_salary_at=EXCLUDED.last_salary_at,bets_count=EXCLUDED.bets_count,wins=EXCLUDED.wins,
                losses=EXCLUDED.losses,total_bet=EXCLUDED.total_bet,total_won=EXCLUDED.total_won,
                total_lost=EXCLUDED.total_lost,casino_games=EXCLUDED.casino_games,casino_wins=EXCLUDED.casino_wins,
                casino_losses=EXCLUDED.casino_losses,casino_wagered=EXCLUDED.casino_wagered,
                casino_profit=EXCLUDED.casino_profit,biggest_win=EXCLUDED.biggest_win,updated_at=NOW()""",
                (player.vk_id, player.name, player.balance, player.last_salary_at, player.bets_count, player.wins,
                 player.losses, player.total_bet, player.total_won, player.total_lost, player.casino_games,
                 player.casino_wins, player.casino_losses, player.casino_wagered, player.casino_profit, player.biggest_win))

    def add_history(self, vk_id: int, entry: str) -> None:
        if self.enabled:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute("INSERT INTO economy_history (vk_id, entry) VALUES (%s,%s)", (vk_id, entry))

    def add_transaction(self, *, kind: str, amount: int, reason: str, actor_vk_id: int | None = None,
                        source_vk_id: int | None = None, target_vk_id: int | None = None,
                        metadata: dict[str, Any] | None = None) -> str:
        tx_id = str(uuid.uuid4())
        if self.enabled:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute("""INSERT INTO economy_transactions
                    (id,kind,actor_vk_id,source_vk_id,target_vk_id,amount,reason,metadata)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                    (tx_id, kind, actor_vk_id, source_vk_id, target_vk_id, amount, reason,
                     json.dumps(metadata or {}, ensure_ascii=False)))
        return tx_id

    def get_transactions(self, vk_id: int | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        with self._connect() as conn, conn.cursor() as cur:
            if vk_id is None:
                cur.execute("SELECT * FROM economy_transactions ORDER BY created_at DESC LIMIT %s", (limit,))
            else:
                cur.execute("""SELECT * FROM economy_transactions
                    WHERE source_vk_id=%s OR target_vk_id=%s OR actor_vk_id=%s
                    ORDER BY created_at DESC LIMIT %s""", (vk_id, vk_id, vk_id, limit))
            return list(cur.fetchall())

    def get_transaction(self, tx_id: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM economy_transactions WHERE id=%s", (tx_id,))
            return cur.fetchone()

    def mark_reversed(self, tx_id: str, reverse_id: str) -> None:
        if self.enabled:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute("UPDATE economy_transactions SET reversed_by=%s WHERE id=%s", (reverse_id, tx_id))

    def save_event(self, event: Any | None) -> None:
        if not self.enabled:
            return
        with self._connect() as conn, conn.cursor() as cur:
            if event is None:
                cur.execute("DELETE FROM economy_state WHERE key='active_event'")
                return
            payload = {"title": event.title, "outcomes": event.outcomes, "bets_open": event.bets_open,
                       "bets": [{"user_id": b.user_id, "outcome": b.outcome, "amount": b.amount} for b in event.bets.values()]}
            cur.execute("""INSERT INTO economy_state(key,value,updated_at) VALUES('active_event',%s::jsonb,NOW())
                ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=NOW()""",
                (json.dumps(payload, ensure_ascii=False),))

    def load_event(self) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT value FROM economy_state WHERE key='active_event'")
            row = cur.fetchone()
            return dict(row["value"]) if row else None

    def reset_all(self) -> None:
        if self.enabled:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute("TRUNCATE economy_history,economy_players,economy_transactions RESTART IDENTITY CASCADE")
                cur.execute("DELETE FROM economy_state")

    def export_snapshot(self) -> dict[str, Any]:
        if not self.enabled:
            return {"error": "database disabled"}
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM economy_players ORDER BY vk_id")
            players = [dict(x) for x in cur.fetchall()]
            cur.execute("SELECT * FROM economy_transactions ORDER BY created_at DESC LIMIT 5000")
            transactions = [dict(x) for x in cur.fetchall()]
            for collection in (players, transactions):
                for row in collection:
                    for key, value in list(row.items()):
                        if hasattr(value, "isoformat"):
                            row[key] = value.isoformat()
                        elif isinstance(value, uuid.UUID):
                            row[key] = str(value)
            return {"schema_version": self.schema_version, "players": players, "transactions": transactions}

    def cleanup(self, force: bool = False) -> int:
        if not self.enabled:
            return 0
        now = time.time()
        if not force and now - self.last_cleanup_at < 21600:
            return 0
        self.last_cleanup_at = now
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM economy_history WHERE created_at < NOW()-(%s*INTERVAL '1 day')", (self.history_retention_days,))
            deleted = cur.rowcount
            cur.execute("VACUUM ANALYZE economy_history")
            return max(0, deleted)
