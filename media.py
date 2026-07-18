import json
from pathlib import Path
from typing import Optional

from vk_api import VkUpload


class MediaManager:
    def __init__(self, vk_session, cache_path):
        self.upload = VkUpload(vk_session)
        self.cache_path = Path(cache_path)
        self.base_dir = self.cache_path.parent.parent
        self.cache = self._load_cache()

    def _load_cache(self) -> dict[str, str]:
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self.cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def resolve_attachment(
        self,
        trigger: str,
        attachment: Optional[str],
        image_path: Optional[str],
    ) -> Optional[str]:
        if attachment:
            return str(attachment)

        if not image_path:
            return None

        path = Path(str(image_path))
        if not path.is_absolute():
            path = self.base_dir / path

        cache_key = f"{trigger}|{path.name}"
        cached = self.cache.get(cache_key) or self.cache.get(trigger)
        if cached:
            return cached

        if not path.exists():
            print(f"Картинка не найдена: {path}", flush=True)
            return None

        try:
            photo = self.upload.photo_messages(photos=str(path))[0]
            access_key = photo.get("access_key")
            result = f"photo{photo['owner_id']}_{photo['id']}"
            if access_key:
                result += f"_{access_key}"

            self.cache[cache_key] = result
            self._save_cache()
            print(
                f"Изображение для триггера «{trigger}» загружено и сохранено.",
                flush=True,
            )
            return result
        except Exception as error:
            print(
                f"Ошибка загрузки картинки {path}: "
                f"{type(error).__name__}: {error}",
                flush=True,
            )
            return None
