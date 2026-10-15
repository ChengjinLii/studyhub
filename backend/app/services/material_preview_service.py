from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.repos.material_preview_repo import MaterialPreviewRepository
from app.services.material_preview_state import (
    RENDER_VERSION, manifest_payload, plan_fingerprint, preview_blocked, preview_plan, preview_supported,
)


class MaterialPreviewService:
    def __init__(self, settings, asset_store) -> None:
        self.settings = settings
        self.asset_store = asset_store
        self.repo = MaterialPreviewRepository()

    def get_preview(self, session: Session, material_id: int, user_id: int, can_manage_all: bool) -> dict:
        rows = self.repo.list_rows(session, material_id)
        if not rows:
            raise HTTPException(404, "资料不存在")
        row = rows[0]
        if preview_blocked(row) and not (can_manage_all or row.get("uploader_id") == user_id):
            raise HTTPException(404, "资料不存在")
        plan = preview_plan(row, self.settings.material_preview_pages_small)
        manifest = manifest_payload(row.get("preview_manifest"))
        result = {"status": "processing", "pageCount": None, "previewPages": None, "images": [], "message": None}
        if not preview_supported(plan):
            return {**result, "status": "unsupported", "message": "当前资料暂不支持自动预览。"}
        if preview_blocked(row) or not self.repo.scan_allows_preview(session, row):
            return {**result, "message": "安全检查或审核完成后，将在后台生成预览。"}
        current = manifest.get("fingerprint") == plan_fingerprint(plan) and manifest.get("renderVersion") == RENDER_VERSION
        # Genuine historical images remain available until the background upgrade,
        # but a manifest without page keys is never represented as a ready preview.
        pages = manifest.get("pages") or []
        ready = manifest.get("status") in (None, "done") and pages and all(isinstance(p, dict) and p.get("key") for p in pages)
        if ready and (current or not str(manifest.get("renderVersion") or "").startswith("studyhub-")):
            images = [self._image_payload(material_id, page) for page in pages]
            return {**result, "status": "done", "pageCount": manifest.get("pageCount") or len(images),
                    "previewPages": len(images), "images": images}
        if current and manifest.get("status") == "failed":
            return {**result, "status": "failed", "message": "暂时无法生成预览，资料文件仍可按原规则获取。"}
        return {**result, "message": "预览已加入后台队列，无需停留等待，不影响资料获取。"}

    def resolve_asset(self, session: Session, material_id: int, index: int, token: str) -> tuple[dict, dict]:
        claims = self.asset_store.verify_preview_token(material_id=material_id, token=token)
        rows = self.repo.list_rows(session, material_id)
        if not rows or preview_blocked(rows[0]):
            raise HTTPException(404, "预览图片不存在")
        row = rows[0]
        manifest = manifest_payload(row.get("preview_manifest"))
        pages = (manifest.get("pages") or []) + (manifest.get("customPages") or [])
        valid_page = any(isinstance(p, dict) and p.get("index") == index and p.get("key") == claims.get("key") for p in pages)
        current = manifest.get("renderVersion") != RENDER_VERSION or manifest.get("fingerprint") == plan_fingerprint(
            preview_plan(row, self.settings.material_preview_pages_small)
        )
        if (claims.get("kind") != "preview-image" or claims.get("index") != index or not claims.get("key")
                or manifest.get("status") != "done" or not valid_page or not current
                or not self.repo.scan_allows_preview(session, row)):
            raise HTTPException(403, "预览链接已失效，请重新打开预览")
        return row, claims

    def _image_payload(self, material_id: int, page: dict) -> dict:
        return {"index": page["index"], "width": page.get("width"), "height": page.get("height"),
                "img": {"src": self.asset_store.build_preview_url(material_id=material_id, index=page["index"],
                                                                key=page["key"], placeholder=False),
                        "srcSet": None, "sizes": None}, "webp": None, "avif": None, "lqip": None}

    def run_once(self, session: Session, *, limit: int = 1, material_id: int | None = None) -> dict:
        stats = {"done": 0, "failed": 0, "skipped": 0}
        # A small catalogue scan outside request handling needs no new schema or index.
        for row in self.repo.list_rows(session, material_id):
            plan = preview_plan(row, self.settings.material_preview_pages_small)
            if not preview_supported(plan) or preview_blocked(row) or not self.repo.scan_allows_preview(session, row):
                continue
            manifest = manifest_payload(row.get("preview_manifest"))
            fingerprint = plan_fingerprint(plan)
            same = manifest.get("fingerprint") == fingerprint and manifest.get("renderVersion") == RENDER_VERSION
            age = time.time() - float(manifest.get("attemptedAt") or 0)
            if same and manifest.get("status") == "processing" and age >= 600 and manifest.get("attempts", 0) >= 3:
                manifest["status"] = "failed"
                self.repo.compare_and_set(session, row, json.dumps(manifest, sort_keys=True))
                session.commit()
                continue
            if same and (manifest.get("status") == "done" or manifest.get("attempts", 0) >= 3
                         or (manifest.get("status") == "processing" and age < 600)
                         or (manifest.get("status") == "failed" and age < 3600)):
                continue
            claim = {"renderVersion": RENDER_VERSION, "fingerprint": fingerprint, "status": "processing",
                     "attempts": int(manifest.get("attempts") or 0) + 1 if same else 1,
                     "attemptedAt": time.time(), "pages": []}
            encoded_claim = json.dumps(claim, sort_keys=True)
            if not self.repo.compare_and_set(session, row, encoded_claim):
                session.rollback()
                continue
            session.commit()
            # MySQL JSON normalizes spacing/key order, so use the persisted snapshot.
            claimed_rows = self.repo.list_rows(session, row["id"])
            if not claimed_rows or manifest_payload(claimed_rows[0].get("preview_manifest")) != claim:
                session.rollback()
                continue
            claimed_row = claimed_rows[0]
            session.commit()  # Release the DB connection before downloading/rendering.
            new_keys: list[str] = []
            try:
                rendered = self._generate(row["id"], plan, new_keys)
                fresh = self.repo.list_rows(session, row["id"])
                if (not fresh or preview_blocked(fresh[0]) or not self.repo.scan_allows_preview(session, fresh[0])
                        or plan_fingerprint(preview_plan(fresh[0], self.settings.material_preview_pages_small)) != fingerprint):
                    raise ValueError("source or moderation changed")
                completed = {**claim, **rendered, "status": "done", "watermark": "StudyHub" if plan["watermark"] else None,
                             "previewPages": len(rendered["pages"]), "generatedAt": datetime.now(UTC).isoformat()}
                if not self.repo.compare_and_set(session, claimed_row, json.dumps(completed, sort_keys=True)):
                    raise ValueError("preview claim no longer current")
                session.commit()
                stats["done"] += 1
            except Exception as exc:  # Storage/parser errors are retried without affecting publication or downloads.
                logging.getLogger(__name__).warning("Preview generation failed material_id=%s category=%s", row["id"], type(exc).__name__)
                session.rollback()
                claim["status"] = "failed"
                self.repo.compare_and_set(session, claimed_row, json.dumps(claim, sort_keys=True))
                session.commit()
                # A lost commit acknowledgement must not delete already-published images.
                try:
                    persisted = self.repo.list_rows(session, row["id"])
                    active = manifest_payload(persisted[0].get("preview_manifest")) if persisted else {}
                    protected = {p.get("key") for group in ("pages", "customPages") for p in active.get(group, [])}
                    for key in new_keys:
                        if key not in protected:
                            self.asset_store.delete_key(key)
                except Exception:
                    session.rollback()  # Keep uncertain objects for operator inspection, never risk a live preview.
                stats["failed"] += 1
            if stats["done"] + stats["failed"] >= limit:
                break
        return stats

    def _generate(self, material_id: int, plan: dict, new_keys: list[str]) -> dict:
        root = self.settings.private_dir / "preview-work"
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if shutil.disk_usage(root).free < 256 * 1024**2:
            raise ValueError("insufficient preview temporary disk space")
        with tempfile.TemporaryDirectory(prefix="preview-", dir=root) as temporary:
            directory = Path(temporary)
            if plan["pdf"]:
                self.asset_store.copy_to_path(plan["pdf"], directory / "source.pdf",
                                              max_size_bytes=self.settings.material_file_max_size_bytes)
            for group, keys in (("pages", plan["images"]), ("customPages", plan["customImages"])):
                for n, key in enumerate(keys):
                    if key.startswith(("http://", "https://", "//")):
                        raise ValueError("remote preview imports require administrator review")
                    self.asset_store.copy_to_path(key, directory / f"{group}-source-{n}",
                                                  max_size_bytes=self.settings.material_preview_image_max_size_bytes)
            (directory / "plan.json").write_text(json.dumps(plan))
            # No database/OSS/model secrets are inherited by the native parser.
            result = subprocess.run([sys.executable, "-m", "app.services.material_preview_renderer", str(directory)],
                                    cwd=Path(__file__).resolve().parents[2], env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=40)
            if result.returncode:
                raise ValueError("preview renderer failed")
            rendered = json.loads((directory / "result.json").read_text())
            if not rendered.get("pages"):
                raise ValueError("renderer produced no preview")
            for group in ("pages", "customPages"):
                for page in rendered[group]:
                    filename = page.pop("file")
                    if Path(filename).name != filename:
                        raise ValueError("invalid renderer output")
                    with (directory / filename).open("rb") as handle:
                        key, _size = self.asset_store.save_upload(material_id=material_id, slot="generated-preview",
                                                                 upload=UploadFile(file=handle, filename=filename))
                    new_keys.append(key)
                    page["key"] = key
            if plan["galleryFromPages"]:
                rendered["customPages"] = rendered["pages"]
            return rendered
