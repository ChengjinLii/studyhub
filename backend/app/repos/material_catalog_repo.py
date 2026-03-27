from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import get_settings


class MaterialCatalogRepository:
    def __init__(self, seed_path: Path) -> None:
        self.seed_path = seed_path

    @lru_cache(maxsize=1)
    def load_seed(self) -> dict[str, Any]:
        if not get_settings().seed_data_enabled:
            return {}
        return json.loads(self.seed_path.read_text(encoding="utf-8"))
