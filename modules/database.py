from __future__ import annotations

import json
import os
import time
from typing import Any

import psycopg
from psycopg.rows import dict_row


class EconomyDatabase:
    """PostgreSQL storage for balances, statistics, history and active bets."""

    def __init__(self, history_retention_days: int = 90) -> None:
        self.url = os.environ.get("DATABASE_URL", "").strip()
        self.history_retention_days = max(7, int(history_retention_days))
        self.enabled = bool(self.url)
        self.last_cleanup_at = 0.0

        if self.enabled:
            self._init_schema()
            self.cleanup(force=True)

    def _connect(self):
        return psycopg.connect(self.url, autocommit=True, row_factory=dict_row)

    def _init_schema(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS economy_players (
                    vk_id BIGINT PRIMARY KEY,
                    name TEXT NOT NULL,
                    balance BIGINT NOT NULL DEFAULT 0,
                    last_salary_at DOUBLE PRECISION NOT NULL DEFAULT 0,
                    bets_count BIGINT NOT NULL DEFAULT 0,
                    wins BIGINT NOT NULL DEFAULT 0,
                    losses BIGINT NOT NULL DEFAULT 0,
                    total_bet BIGINT NOT NULL DEFAULT 0,
                    total_won BIGINT NOT NULL DEFAULT 0,
                    total_lost BIGINT NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS economy_history (
                    id BIGSERIAL PRIMARY KEY,
                    vk_id BIGINT NOT NULL REFERENCES economy_players(vk_id) ON DELETE CASCADE,
                    entry TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS economy_history_vk_id_idx ON economy_history(vk_id, created_at DESC)"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS economy_state (
                    key TEXT PRIMARY KEY,
                    value JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

    def load_players(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM economy_players")
            players = list(cur.fetchall())
            for player in players:
                cur.execute(
                    "SELECT entry FROM economy_history WHERE vk_id = %s ORDER BY created_at DESC LIMIT 20",
                    (player["vk_id"],),
                )
                player["history"] = [row["entry"] for row in reversed(cur.fetchall())]
            return players

    def save_player(self, player: Any) -> None:
        if not self.enabled:
            return
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO economy_players (
                    vk_id, name, balance, last_salary_at, bets_count, wins, losses,
                    total_bet, total_won, total_lost, updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (vk_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    balance = EXCLUDED.balance,
                    last_salary_at = EXCLUDED.last_salary_at,
                    bets_count = EXCLUDED.bets_count,
                    wins = EXCLUDED.wins,
                    losses = EXCLUDED.losses,
                    total_bet = EXCLUDED.total_bet,
                    total_won = EXCLUDED.total_won,
                    total_lost = EXCLUDED.total_lost,
                    updated_at = NOW()
                """,
                (
                    player.vk_id, player.name, player.balance, player.last_salary_at,
                    player.bets_count, player.wins, player.losses, player.total_bet,
                    player.total_won, player.total_lost,
                ),
            )

    def add_history(self, vk_id: int, entry: str) -> None:
        if not self.enabled:
            return
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO economy_history (vk_id, entry) VALUES (%s, %s)",
                (vk_id, entry),
            )

    def save_event(self, event: Any | None) -> None:
        if not self.enabled:
            return
        with self._connect() as conn, conn.cursor() as cur:
            if event is None:
                cur.execute("DELETE FROM economy_state WHERE key = 'active_event'")
                return
            payload = {
                "title": event.title,
                "outcomes": event.outcomes,
                "bets_open": event.bets_open,
                "bets": [
                    {"user_id": bet.user_id, "outcome": bet.outcome, "amount": bet.amount}
                    for bet in event.bets.values()
                ],
            }
            cur.execute(
                """
                INSERT INTO economy_state (key, value, updated_at)
                VALUES ('active_event', %s::jsonb, NOW())
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (json.dumps(payload, ensure_ascii=False),),
            )

    def load_event(self) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT value FROM economy_state WHERE key = 'active_event'")
            row = cur.fetchone()
            return dict(row["value"]) if row else None

    def reset_all(self) -> None:
        if not self.enabled:
            return
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("TRUNCATE economy_history, economy_players RESTART IDENTITY CASCADE")
            cur.execute("DELETE FROM economy_state")

    def cleanup(self, force: bool = False) -> int:
        """Delete expendable history only. Balances and statistics are never auto-deleted."""
        if not self.enabled:
            return 0
        now = time.time()
        if not force and now - self.last_cleanup_at < 6 * 60 * 60:
            return 0
        self.last_cleanup_at = now
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM economy_history WHERE created_at < NOW() - (%s * INTERVAL '1 day')",
                (self.history_retention_days,),
            )
            deleted = cur.rowcount
            cur.execute("VACUUM ANALYZE economy_history")
            return max(0, deleted)
