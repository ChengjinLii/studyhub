from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from sqlalchemy import select

from app.api.deps import get_material_asset_store, get_material_repo
from app.core.db import session_scope
from app.models.batch_submissions import BatchSubmissionItemRecord
from app.core.config import get_settings


def main() -> int:
    with session_scope() as session:
        protected_keys = get_material_repo().list_referenced_asset_keys(session)
        protected_keys.update(session.scalars(select(BatchSubmissionItemRecord.object_key).where(
            BatchSubmissionItemRecord.object_key.is_not(None)
        )))
    removed = get_material_asset_store().cleanup_staged_uploads(
        protected_keys=protected_keys,
        older_than=datetime.now(UTC) - timedelta(hours=24),
    )
    store = get_material_asset_store()
    orphaned = store.storage_provider.cleanup_staged_uploads(
        root=get_settings().resolved_material_asset_dir, namespace="bulk", protected_keys=protected_keys,
        older_than=datetime.now(UTC) - timedelta(days=max(7, get_settings().batch_submission_draft_retention_days)),
    )
    print(json.dumps({"removed": removed, "bulkOrphansRemoved": orphaned, "protected": len(protected_keys)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
