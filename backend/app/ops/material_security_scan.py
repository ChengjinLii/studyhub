from __future__ import annotations

import json

from app.api.deps import get_material_asset_store, get_material_repo
from app.core.config import get_settings
from app.core.db import session_scope
from app.services.material_security_service import MaterialSecurityService
from app.api.routes.batch_submissions import get_batch_submission_service


def main() -> int:
    settings = get_settings()
    service = MaterialSecurityService(settings, get_material_repo(), get_material_asset_store())
    with session_scope() as session:
        result = service.run_once(session) if settings.resolved_material_security_scan_enabled else {}
    with session_scope() as session:
        batch_result = get_batch_submission_service().run_once(session, limit=1)
    print(json.dumps({"enabled": settings.resolved_material_security_scan_enabled, **result, "batches": batch_result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
