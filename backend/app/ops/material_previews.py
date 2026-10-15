from __future__ import annotations

import argparse
import fcntl
import json
from collections import Counter

from app.api.deps import get_material_asset_store
from app.core.config import get_settings
from app.core.db import session_scope
from app.services.material_preview_service import MaterialPreviewService
from app.services.material_preview_state import RENDER_VERSION, manifest_payload, preview_plan, preview_supported, preview_blocked


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate cached previews without altering originals or publication state")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--material-id", type=int)
    parser.add_argument("--audit", action="store_true", help="Read-only aggregate preview state")
    args = parser.parse_args()
    settings = get_settings()
    service = MaterialPreviewService(settings, get_material_asset_store())
    if args.audit:
        with session_scope() as session:
            rows = service.repo.list_rows(session, args.material_id)
            manifests = [manifest_payload(row.get("preview_manifest")) for row in rows]
            print(json.dumps({"materials": len(rows), "watermarks": dict(Counter(str(m.get("watermark")) for m in manifests)),
                              "states": dict(Counter(str(m.get("status")) for m in manifests)),
                              "currentVersion": sum(m.get("renderVersion") == RENDER_VERSION for m in manifests),
                              "eligible": sum(preview_supported(preview_plan(row)) and not preview_blocked(row) for row in rows)}))
        return 0
    root = settings.private_dir / "preview-work"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (root / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"skipped": "worker already running"}))
            return 0
        with session_scope() as session:
            result = service.run_once(session, limit=max(1, min(args.limit, 5)), material_id=args.material_id)
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
