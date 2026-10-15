from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.repos.material_repo import _table_columns, _table_names


class MaterialPreviewRepository:
    """Only preview_manifest is written; legacy file columns remain untouched."""

    def list_rows(self, session: Session, material_id: int | None = None) -> list[dict]:
        columns = _table_columns(session, "materials")
        names = [name for name in (
            "id", "uploader_id", "file_type", "file_storage_key", "file_key", "preview_source", "preview_manifest",
            "preview_watermark_enabled", "manual_preview_keys_json", "custom_preview_images_json", "custom_preview_images",
            "status", "review_status", "deleted_at", "tags_json",
        ) if name in columns]
        where = " WHERE id = :id" if material_id is not None else ""
        rows = session.execute(text(f"SELECT {', '.join(names)} FROM materials{where} ORDER BY id"), {"id": material_id})
        result = [dict(row) for row in rows.mappings()]
        if "material_tags" in _table_names(session) and "tag" in _table_columns(session, "material_tags"):
            condition = " AND material_id = :id" if material_id is not None else ""
            experiences = set(session.execute(text(
                "SELECT material_id FROM material_tags WHERE tag = :tag" + condition
            ), {"tag": "经验分享", "id": material_id}).scalars())
            for row in result:
                row["_is_experience"] = row["id"] in experiences
        return result

    def compare_and_set(self, session: Session, row: dict, value: str) -> bool:
        params = {"id": row["id"], "value": value}
        predicates = ["id = :id"]
        # Snapshot every input, including moderation, to reject stale workers.
        for i, (name, old) in enumerate(row.items()):
            if name == "id" or name.startswith("_"):
                continue
            if old is None:
                predicates.append(f"{name} IS NULL")
            else:
                param = f"old_{i}"
                if name in {"preview_manifest", "manual_preview_keys_json", "custom_preview_images_json",
                            "custom_preview_images", "tags_json"} and session.get_bind().dialect.name == "mysql":
                    predicates.append(f"CAST({name} AS CHAR) = :{param}")
                else:
                    predicates.append(f"{name} = :{param}")
                params[param] = old
        result = session.execute(text("UPDATE materials SET preview_manifest = :value WHERE " + " AND ".join(predicates)), params)
        return result.rowcount == 1

    def scan_allows_preview(self, session: Session, row: dict) -> bool:
        if "material_security_scans" not in _table_names(session):
            return True
        scan = session.execute(text(
            "SELECT object_key, status FROM material_security_scans WHERE material_id = :id"
        ), {"id": row["id"]}).mappings().first()
        if scan is None:
            return True  # Legacy published files are also checked inside the isolated renderer.
        return scan["status"] == "CLEAN" and scan["object_key"] == (row.get("file_storage_key") or row.get("file_key"))
