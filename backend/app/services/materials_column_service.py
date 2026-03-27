from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.repos.material_catalog_repo import MaterialCatalogRepository


class MaterialsColumnService:
    def __init__(self, settings: Settings, repo: MaterialCatalogRepository) -> None:
        self.settings = settings
        self.repo = repo

    def get_column(self, topic: str | None, page: int, size: int | None) -> tuple[dict[str, Any], str, str]:
        seed = self.repo.load_seed()
        normalized_topic = (topic or self.settings.default_column_topic).strip() or self.settings.default_column_topic
        topics = seed.get("topics", {})
        items = topics.get(normalized_topic) or topics.get(self.settings.default_column_topic) or []

        safe_page = max(page, 1)
        safe_size = size or self.settings.default_column_page_size
        safe_size = max(1, min(safe_size, self.settings.max_column_page_size))
        start = (safe_page - 1) * safe_size
        end = start + safe_size

        payload = {
            "items": items[start:end],
            "meta": {
                "topic": normalized_topic,
                "page": safe_page,
                "size": safe_size,
                "total": len(items),
            },
        }
        seed_version = seed.get("seedVersion", "disabled" if not seed else "demo-v1")
        etag = f'W/"materials-column:{normalized_topic}:{safe_page}:{safe_size}:{seed_version}"'
        return payload, etag, self.settings.column_cache_control
