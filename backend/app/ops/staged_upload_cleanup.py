from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

from app.api.deps import get_material_asset_store, get_material_repo
from app.core.db import session_scope


def main() -> int:
    with session_scope() as session:
        protected_keys = get_material_repo().list_referenced_asset_keys(session)
    removed = get_material_asset_store().cleanup_staged_uploads(
        protected_keys=protected_keys,
        older_than=datetime.now(UTC) - timedelta(hours=24),
    )
    print(json.dumps({"removed": removed, "protected": len(protected_keys)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
