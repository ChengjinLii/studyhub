from __future__ import annotations

import json

from app.api.deps import get_material_asset_store, get_material_repo
from app.core.config import get_settings
from app.core.db import session_scope
from app.services.material_security_service import MaterialSecurityService


def main() -> int:
    settings = get_settings()
    if not settings.resolved_material_security_scan_enabled:
        print(json.dumps({"enabled": False}))
        return 0
    service = MaterialSecurityService(settings, get_material_repo(), get_material_asset_store())
    with session_scope() as session:
        result = service.run_once(session)
    print(json.dumps({"enabled": True, **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
