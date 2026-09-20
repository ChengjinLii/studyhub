"""Private batch intake. Caller identities must come from authenticated dependencies.

Mutations commit their transaction; downloads return a private temporary stream,
never an object URL. The regular worker may call run_once after higher priority work.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import secrets
from tempfile import SpooledTemporaryFile
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

from app.core.upload_validation import validate_material_upload
from app.repos.auth_repo import resolve_user_model
from app.models.materials import MaterialRecord
from app.services.read_support import ROLE_ADMIN, ROLE_DEVELOPER
from app.models.batch_submissions import (
    BatchSubmissionRecord as Batch,
    BatchSubmissionItemRecord as Item,
    BatchPublicationRecord as Publication,
    BatchAuditRecord as Audit,
)
from app.schemas.materials import MaterialCreatePayload
from app.schemas.upload_authorization import UploadFileDescriptorPayload


MIB = 1024 * 1024


def _now():
    return datetime.now(UTC)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _fail(code, message):
    raise HTTPException(status_code=code, detail=message)


class BatchSubmissionService:
    def __init__(self, settings, asset_store, materials_service, upload_authorization):
        self.settings = settings
        self.asset_store = asset_store
        self.materials_service = materials_service
        self.upload_authorization = upload_authorization

    def _user(self, session, user_id, *, admin=False, lock=False):
        model = resolve_user_model(session)
        query = select(model).where(model.id == user_id)
        if lock:
            query = query.with_for_update()
        user = session.scalar(query.execution_options(populate_existing=True))
        if user is None or user.status != "active":
            _fail(403, "Active authenticated user required")
        if admin and not (user.role_mask & (ROLE_ADMIN | ROLE_DEVELOPER)):
            _fail(403, "Administrator required")
        return user

    def _batch(self, session, batch_id, *, user_id=None, lock=False):
        query = select(Batch).where(Batch.id == batch_id)
        if user_id is not None:
            query = query.where(Batch.uploader_id == user_id)
        if lock:
            query = query.with_for_update()
        batch = session.scalar(query.execution_options(populate_existing=True))
        if batch is None:
            _fail(404, "Batch not found")
        return batch

    def _items(self, session, batch_id, *, lock=False):
        session.flush()
        query = select(Item).where(Item.batch_id == batch_id).order_by(Item.id)
        if lock:
            query = query.with_for_update()
        return session.scalars(query.execution_options(populate_existing=True)).all()

    def _item(self, session, batch_id, item_id):
        item = session.scalar(select(Item).where(Item.batch_id == batch_id, Item.id == item_id)
                              .with_for_update().execution_options(populate_existing=True))
        if item is None:
            _fail(404, "Item not found")
        return item

    def _audit(self, session, batch, operator_id, action, ids=()):
        # Never persist filenames, object keys, URLs, notes, tokens or scanner output.
        session.add(Audit(batch_id=batch.id, operator_id=operator_id if operator_id is not None else 0, action=action,
                          detail=json.dumps({"itemIds": sorted(ids)})))

    def _serialize(self, session, batch, *, admin=False, created=False):
        session.flush()
        items = self._items(session, batch.id)
        result = {"id": batch.id, "status": batch.status, "deliveryMethod": batch.delivery_method,
                  "publicationIntent": batch.publication_intent, "createdAt": batch.created_at,
                  "updatedAt": batch.updated_at, "itemCount": len(items),
                  "totalBytes": sum(i.size_bytes for i in items),
                  "items": [{"id": i.id, "status": i.status, "scanStatus": i.scan_status,
                             "sizeBytes": i.size_bytes,
                             **({"name": i.name, "contentType": i.content_type} if admin or created else {}),
                             "reason": i.reason} for i in items]}
        result["publications"] = [
            {"id": publication.id, "materialId": publication.material_id,
             "title": title, "url": f"/materials/{publication.material_id}"}
            for publication, title in session.execute(
                select(Publication, MaterialRecord.title)
                .join(MaterialRecord, MaterialRecord.id == Publication.material_id)
                .where(Publication.batch_id == batch.id, Publication.status == "PUBLISHED")
            )
        ]
        if admin:
            result.update(uploaderId=batch.uploader_id, note=batch.note, pricingNote=batch.pricing_note,
                          netdiskUrl=batch.netdisk_url, netdiskPassword=batch.netdisk_password)
        return result

    def create(self, session: Session, *, user_id: int, payload: dict) -> dict:
        self._user(session, user_id, lock=True)
        key = str(payload.get("submissionKey") or payload.get("submissionId") or "").strip()
        if not 16 <= len(key) <= 64 or not all(c.isascii() and (c.isalnum() or c in "_-") for c in key):
            _fail(400, "submissionKey must contain 16-64 identifier characters")
        delivery = str(payload.get("deliveryMethod", "FILE")).upper()
        intent = str(payload.get("publicationIntent", "")).upper()
        if payload.get("consent") is not True:
            _fail(400, "请确认分享权利并同意管理员整理发布")
        if delivery not in {"FILE", "NETDISK"} or intent not in {"FREE", "PAID", "CONTACT"}:
            _fail(400, "Invalid delivery method or publication intent")
        files = payload.get("files") or []
        if not isinstance(files, list) or len(files) > min(20, self.settings.batch_submission_max_files) or (delivery == "FILE" and not files):
            _fail(400, "A file batch requires 1-20 files")
        if delivery == "NETDISK" and files:
            _fail(400, "Netdisk batches cannot contain uploads")
        normalized = []
        for file in files:
            name = str(file.get("name", "")).strip()
            size = file.get("sizeBytes")
            content_type = str(file.get("contentType") or "application/octet-stream").strip().lower()
            if (not name or len(name) > 255 or any(c in name for c in "/\\\x00")
                    or any(ord(c) < 32 for c in name) or not isinstance(size, int) or isinstance(size, bool)
                    or size <= 0 or size > 50 * MIB or len(content_type) > 128
                    or Path(name).suffix.lower() not in self.settings.resolved_upload_allowed_material_extensions):
                _fail(400, "Invalid file descriptor; each file must be at most 50 MiB")
            normalized.append({"name": name, "sizeBytes": size, "contentType": content_type})
        if sum(i["sizeBytes"] for i in normalized) > min(100 * MIB, self.settings.batch_submission_max_bytes):
            _fail(400, "Batch exceeds 100 MiB")
        netdisk = str(payload.get("netdiskUrl") or "").strip() or None
        if delivery == "NETDISK":
            try:
                parsed = urlsplit(netdisk or "")
                valid = parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password
            except ValueError:
                valid = False
            if not valid or len(netdisk or "") > 2048:
                _fail(400, "Invalid netdisk URL")
        elif netdisk or payload.get("netdiskPassword"):
            _fail(400, "File batches cannot contain netdisk credentials")
        values = {"delivery_method": delivery, "publication_intent": intent, "netdisk_url": netdisk,
                  "netdisk_password": payload.get("netdiskPassword") or None,
                  "pricing_note": payload.get("pricingNote") or None, "note": payload.get("note") or None}
        if any(v is not None and (not isinstance(v, str) or len(v) > 3000) for v in values.values()):
            _fail(400, "Batch text is too long")
        digest = _digest({**values, "files": normalized})
        existing = session.scalar(select(Batch).where(Batch.uploader_id == user_id, Batch.submission_key == key))
        if existing:
            if existing.payload_digest != digest:
                _fail(409, "Submission key already used for different content")
            return self._serialize(session, existing, created=True)
        if len(values["netdisk_password"] or "") > 64:
            _fail(400, "Netdisk password too long")
        self.upload_authorization.reserve_batch(user_id=user_id, submission_id=key,
            files=[UploadFileDescriptorPayload(role="MATERIAL", **f) for f in normalized])
        batch = Batch(uploader_id=user_id, submission_key=key, payload_digest=digest, status="DRAFT", **values)
        session.add(batch)
        session.flush()
        for f in normalized:
            session.add(Item(batch_id=batch.id, name=f["name"], size_bytes=f["sizeBytes"],
                             content_type=f["contentType"], status="PENDING", scan_status="PENDING",
                             scan_attempts=0, cleanup_attempts=0))
        if delivery == "NETDISK":
            session.add(Item(batch_id=batch.id, name="Netdisk submission", size_bytes=0,
                             content_type="application/octet-stream", status="UPLOADED",
                             scan_status="NOT_APPLICABLE", scan_attempts=0, cleanup_attempts=0))
        self._audit(session, batch, user_id, "CREATE")
        session.commit()
        return self._serialize(session, batch, created=True)

    def list_batches(self, session: Session, *, user_id: int | None = None, offset=0, limit=20) -> dict:
        query = select(Batch)
        if user_id is not None:
            query = query.where(Batch.uploader_id == user_id)
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        rows = session.scalars(query.order_by(Batch.id.desc()).offset(max(0, offset)).limit(max(1, min(50, limit))))
        return {"items": [self._serialize(session, b, admin=user_id is None) for b in rows], "total": total}

    def detail(self, session: Session, batch_id: int, *, user_id: int | None = None) -> dict:
        return self._serialize(session, self._batch(session, batch_id, user_id=user_id), admin=user_id is None)

    def authorize_upload(self, session: Session, batch_id: int, item_id: int, *, user_id: int) -> dict:
        self._user(session, user_id, lock=True)
        batch = self._batch(session, batch_id, user_id=user_id, lock=True)
        item = self._item(session, batch_id, item_id)
        if batch.status != "DRAFT":
            _fail(409, "批次已提交，不能继续上传")
        if item.status == "UPLOADED":
            return {"alreadyUploaded": True}
        if item.status in {"UPLOADING", "RECEIVING"} and item.upload_claimed_at and item.upload_claimed_at.replace(tzinfo=UTC) < _now() - timedelta(minutes=15):
            item.status = "PENDING"
            item.upload_claimed_at = None
        if item.status != "PENDING" or item.upload_claimed_at:
            _fail(409, "Item cannot be authorized")
        ttl = max(60, int(self.settings.upload_authorization_ttl_seconds))
        token = secrets.token_urlsafe(32)
        item.upload_token_digest = hashlib.sha256(token.encode()).hexdigest()
        item.upload_token_expires_at = _now() + timedelta(seconds=ttl)
        session.commit()
        return {"uploadToken": token, "expiresInSeconds": ttl, "batchId": batch_id, "itemId": item_id}

    def begin_upload(self, session, batch_id, item_id, *, user_id, token):
        self._user(session, user_id, lock=True)
        batch = self._batch(session, batch_id, user_id=user_id, lock=True)
        item = self._item(session, batch_id, item_id)
        digest = hashlib.sha256(token.encode()).hexdigest()
        if not item.upload_token_digest or not secrets.compare_digest(digest, item.upload_token_digest):
            _fail(403, "上传授权无效，请重试")
        if item.status == "UPLOADED":
            return True
        if batch.status != "DRAFT" or item.status != "PENDING" or not item.upload_token_expires_at or item.upload_token_expires_at.replace(tzinfo=UTC) <= _now():
            _fail(409, "上传授权过期或文件正在上传，请稍后重试")
        active = session.scalar(select(func.count()).select_from(Item).join(Batch, Item.batch_id == Batch.id).where(
            Batch.uploader_id == user_id, Item.status.in_(["RECEIVING", "UPLOADING"])))
        if active >= min(2, self.settings.batch_submission_upload_concurrency):
            _fail(429, "同时最多上传两个文件，请稍后重试")
        item.status = "RECEIVING"
        item.upload_claimed_at = _now()
        session.commit()
        return False

    def release_receive(self, session, batch_id, item_id, *, token):
        session.rollback()
        item = self._item(session, batch_id, item_id)
        if item.status == "RECEIVING" and item.upload_token_digest == hashlib.sha256(token.encode()).hexdigest():
            item.status = "PENDING"
            item.upload_claimed_at = None
            item.upload_token_digest = None
            session.commit()

    def upload(self, session: Session, batch_id: int, item_id: int, *, user_id: int,
               token: str, upload: UploadFile) -> dict:
        self._user(session, user_id, lock=True)
        batch = self._batch(session, batch_id, user_id=user_id, lock=True)
        item = self._item(session, batch_id, item_id)
        digest = hashlib.sha256(token.encode()).hexdigest()
        if not item.upload_token_digest or not secrets.compare_digest(item.upload_token_digest, digest):
            _fail(403, "Upload token revoked")
        if item.status == "UPLOADED":
            return {"id": item.id, "status": item.status}
        if (batch.status != "DRAFT" or item.status != "RECEIVING"
                or not item.upload_token_expires_at
                or item.upload_token_expires_at.replace(tzinfo=UTC) <= _now()):
            _fail(409, "Upload already claimed or no longer available")
        if upload.filename != item.name or (upload.content_type or "application/octet-stream").lower() != item.content_type:
            _fail(400, "Upload descriptor mismatch")
        size = validate_material_upload(upload, max_size_bytes=item.size_bytes, missing_detail="Missing filename",
                                        invalid_type_detail="Invalid file content", too_large_detail="Upload too large")
        if size != item.size_bytes:
            _fail(400, "Upload size mismatch")
        item.status = "UPLOADING"
        item.upload_claimed_at = _now()
        session.commit()  # Durable single-use nonce before touching object storage.
        key = None
        try:
            upload.file.seek(0)
            key, saved = self.asset_store.storage_provider.save_upload(
                root=self.settings.resolved_material_asset_dir,
                relative_dir=Path("bulk") / str(batch_id) / str(item_id), upload=upload, fallback_name="file.bin")
            if saved != size:
                _fail(400, "Stored upload size mismatch")
            batch = self._batch(session, batch_id, user_id=user_id, lock=True)
            item = self._item(session, batch_id, item_id)
            if item.upload_token_digest != digest:
                self.asset_store.delete_key_strict(key)
                _fail(409, "上传已由新的重试接替，请刷新状态")
            item.object_key = key
            item.status = "UPLOADED" if batch.status == "DRAFT" else "REJECTED"
            self._audit(session, batch, user_id, "UPLOAD", [item_id])
            session.commit()
        except Exception:
            session.rollback()
            item = self._item(session, batch_id, item_id)
            if item.upload_token_digest != digest:
                raise
            item.object_key = key
            item.status = "REJECTED" if key else "PENDING"
            # A failed request may receive a new nonce, but never reuse this one.
            if not key:
                item.upload_token_digest = None
                item.upload_claimed_at = None
            session.commit()
            raise
        return {"id": item.id, "status": item.status}

    def submit(self, session: Session, batch_id: int, *, user_id: int) -> dict:
        self._user(session, user_id)
        batch = self._batch(session, batch_id, user_id=user_id, lock=True)
        if batch.status != "DRAFT":
            return self._serialize(session, batch)
        items = self._items(session, batch_id, lock=True)
        if batch.status != "DRAFT" or any(i.status != "UPLOADED" for i in items):
            _fail(409, "All files must be uploaded before submission")
        batch.status = "WAITING"
        self._audit(session, batch, user_id, "SUBMIT")
        session.commit()
        return self._serialize(session, batch)

    def amend(self, session, batch_id, *, user_id, payload):
        batch = self._batch(session, batch_id, user_id=user_id, lock=True)
        items = self._items(session, batch_id, lock=True)
        if not any(i.status == "RETURNED" for i in items):
            _fail(409, "只有退回补充的投稿可以修改")
        if any(i.status == "PUBLISHED" for i in items) and any(k != "note" for k in payload):
            _fail(409, "部分资料已发布，仅能补充备注")
        if batch.delivery_method == "FILE" and any(k in payload for k in ("netdiskUrl", "netdiskPassword")):
            _fail(400, "文件投稿不接受网盘链接")
        for field, attribute in {"note": "note", "pricingNote": "pricing_note", "publicationIntent": "publication_intent",
                                 "netdiskUrl": "netdisk_url", "netdiskPassword": "netdisk_password"}.items():
            if field in payload:
                setattr(batch, attribute, payload[field])
        for item in items:
            if item.status == "RETURNED":
                item.status = "UPLOADED"
        batch.status = "PARTIAL" if any(i.status == "PUBLISHED" for i in items) else "WAITING"
        self._audit(session, batch, user_id, "SUPPLEMENT")
        session.commit()
        return self._serialize(session, batch)

    def _subset(self, session, batch, ids):
        if not isinstance(ids, list) or not ids or any(type(i) is not int for i in ids) or len(set(ids)) != len(ids):
            _fail(400, "Select distinct item IDs")
        items = [i for i in self._items(session, batch.id, lock=True) if i.id in ids]
        if len(items) != len(ids):
            _fail(404, "Selected item not found in batch")
        return items

    def review(self, session: Session, batch_id: int, *, operator_id: int, payload: dict) -> dict:
        self._user(session, operator_id, admin=True)
        batch = self._batch(session, batch_id, lock=True)
        action = str(payload.get("action", "")).upper()
        reason = str(payload.get("reason") or "").strip()
        if action not in {"REVIEW", "RETURN", "REJECT"} or (action != "REVIEW" and not reason) or len(reason) > 1000:
            _fail(400, "Valid review action and reason required")
        if batch.status not in {"WAITING", "REVIEW", "RETURNED", "PARTIAL", "PUBLISHED"}:
            _fail(409, "Batch is not submitted")
        items = self._subset(session, batch, payload.get("itemIds"))
        if any(i.status in {"PUBLISHED", "REJECTED", "CLEANED", "PUBLISHING"} for i in items):
            _fail(409, "Published or rejected sources cannot be changed")
        for item in items:
            item.status = {"REVIEW": "REVIEW", "RETURN": "RETURNED", "REJECT": "REJECTED"}[action]
            item.reason = reason or None
            if action == "REVIEW" and item.scan_status == "ERROR":
                item.scan_status = "PENDING"
                item.scan_attempts = 0
                item.next_attempt_at = None
        batch.status = "PARTIAL" if any(i.status == "PUBLISHED" for i in self._items(session, batch.id)) else {
            "REVIEW": "REVIEW", "RETURN": "RETURNED", "REJECT": "REVIEW" if items else "REJECTED"}[action]
        self._audit(session, batch, operator_id, action, [i.id for i in items])
        session.commit()
        return self._serialize(session, batch, admin=True)

    def publish(self, session: Session, batch_id: int, *, operator_id: int, payload: dict) -> dict:
        self._user(session, operator_id, admin=True)
        batch = self._batch(session, batch_id, lock=True)
        key = str(payload.get("publicationId") or "").strip()
        if not 16 <= len(key) <= 64:
            _fail(400, "publicationKey must contain 16-64 characters")
        digest = _digest(payload)
        existing = session.scalar(select(Publication).where(Publication.publication_key == key).with_for_update())
        if existing:
            if existing.batch_id != batch.id or existing.payload_digest != digest:
                _fail(409, "Publication key already used for different content")
            if existing.status == "PUBLISHED":
                return {"id": existing.id, "materialId": existing.material_id, "status": existing.status}
            _fail(409, "Publication is already in progress")
        if batch.status not in {"WAITING", "REVIEW", "PARTIAL"}:
            _fail(409, "Batch is not ready for publication")
        items = self._subset(session, batch, payload.get("itemIds"))
        if batch.delivery_method == "NETDISK" and session.scalar(select(Publication.id).where(
                Publication.batch_id == batch.id, Publication.status == "PUBLISHED")):
            _fail(409, "Netdisk batch already published")
        if any(i.status not in {"UPLOADED", "REVIEW"} or (batch.delivery_method == "FILE"
               and (i.scan_status != "CLEAN" or not i.object_key)) for i in items):
            _fail(409, "Selected files must be clean, reviewed and unpublished")
        if sum(i.size_bytes for i in items) > 50 * MIB:
            _fail(400, "Publication subset exceeds 50 MiB; select fewer files")
        material_data = {k: v for k, v in payload.items() if k in MaterialCreatePayload.model_fields}
        price = material_data.get("price", 0)
        confirmation = str(payload.get("confirmationNote") or "").strip()
        if type(price) is not int or price < 0 or (batch.publication_intent == "FREE" and price != 0):
            _fail(400, "Price conflicts with uploader intent")
        if (batch.publication_intent != "FREE" or price > 0) and (payload.get("pricingConfirmed") is not True or not confirmation):
            _fail(400, "Explicit pricing confirmation required")
        if len(confirmation) > 1000:
            _fail(400, "Pricing confirmation too long")
        material_data.update(deliveryMethod=batch.delivery_method, netdiskUrl=batch.netdisk_url,
                             netdiskPassword=batch.netdisk_password, stagedUploadTokens=[],
                             submissionId="batchpub_" + hashlib.sha256(key.encode()).hexdigest()[:48])
        material_data["generalCourse"] = material_data.get("courseCategory") == "GENERAL"
        if material_data["generalCourse"]:
            material_data.update(college=None, major=None)
        material_payload = MaterialCreatePayload.model_validate(material_data)
        publication = Publication(batch_id=batch.id, publication_key=key, payload_digest=digest,
                                  item_ids_json=json.dumps(sorted(i.id for i in items)), operator_id=operator_id,
                                  pricing_confirmation=confirmation or None, status="PENDING")
        session.add(publication)
        session.flush()
        upload = self._publication_upload(items) if batch.delivery_method == "FILE" else None
        try:
            # MaterialsService commits internally. A separate identity map and
            # savepoint keep that commit inside this locked publication transaction.
            with Session(bind=session.connection(), join_transaction_mode="create_savepoint") as inner:
                material = self.materials_service.create_material(inner, material_payload,
                    uploader_id=batch.uploader_id, zip_file=upload, markdown_file=None,
                    previews=[], custom_previews=[])
            publication.material_id = int(material["id"])
            publication.status = "PUBLISHED"
            for item in items:
                item.status = "PUBLISHED"
            session.flush()
            batch.status = "PUBLISHED" if all(i.status in {"PUBLISHED", "CLEANED", "REJECTED"}
                for i in self._items(session, batch.id)) else "PARTIAL"
            self._audit(session, batch, operator_id, "PUBLISH", [i.id for i in items])
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            if upload:
                upload.file.close()
        return {"id": publication.id, "materialId": publication.material_id, "status": publication.status}

    def _publication_upload(self, items):
        stream = SpooledTemporaryFile(max_size=2 * MIB)
        try:
            if len(items) == 1:
                stream.write(self.asset_store.read_bytes(items[0].object_key, max_size_bytes=50 * MIB))
                name = items[0].name
                media_type = items[0].content_type
            else:
                with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
                    for item in items:
                        archive.writestr(f"{item.id}_{Path(item.name).name}",
                            self.asset_store.read_bytes(item.object_key, max_size_bytes=item.size_bytes))
                name, media_type = "batch.zip", "application/zip"
            size = stream.tell()
            if size > 50 * MIB:
                _fail(400, "Generated publication exceeds 50 MiB; select fewer files")
            stream.seek(0)
            return UploadFile(file=stream, filename=name, size=size, headers=Headers({"content-type": media_type}))
        except Exception:
            stream.close()
            raise

    def download_item(self, session: Session, batch_id: int, item_id: int):
        """Privileged route only: return a private object reference, never a URL."""
        self._batch(session, batch_id, lock=True)
        item = self._item(session, batch_id, item_id)
        if not item.object_key or item.status in {"CLEANED", "REJECTED"}:
            _fail(404, "File unavailable")
        return item

    def run_once(self, session: Session, limit=1, *, scanner=None) -> dict:
        """One sequential scan, then bounded cleanup; never creates a material."""
        if scanner is None:
            from app.services.material_security_service import MaterialSecurityService
            scanner = MaterialSecurityService(self.settings, None, self.asset_store)
        counts = {"processed": 0, "clean": 0, "infected": 0, "errors": 0, "cleaned": 0}
        now = _now().replace(microsecond=0)
        item = session.scalar(select(Item).join(Batch, Batch.id == Item.batch_id).where(
            Batch.delivery_method == "FILE", Batch.status.in_(["WAITING", "REVIEW", "PARTIAL", "RETURNED"]),
            Item.status.in_(["UPLOADED", "REVIEW", "RETURNED"]),
            or_(Item.scan_status == "PENDING", (Item.scan_status == "SCANNING") & (Item.claimed_at < now - timedelta(minutes=15))),
            or_(Item.next_attempt_at.is_(None), Item.next_attempt_at <= now))
            .order_by(Item.id).limit(1).with_for_update(skip_locked=True)) if self.settings.resolved_material_security_scan_enabled else None
        if item:
            item.scan_status = "SCANNING"
            item.claimed_at = now
            item.scan_attempts += 1
            item_id, key, claim = item.id, item.object_key, now
            session.commit()
            try:
                result = scanner._scan_object(key)
                outcome = result.status
            except Exception:
                outcome = "ERROR"
            item = session.scalar(select(Item).where(Item.id == item_id).with_for_update().execution_options(populate_existing=True))
            if (item.status in {"UPLOADED", "REVIEW", "RETURNED"} and item.scan_status == "SCANNING" and item.object_key == key and item.claimed_at
                    and item.claimed_at.replace(tzinfo=UTC) == claim):
                counts["processed"] += 1
                if outcome in {"CLEAN", "INFECTED"}:
                    item.scan_status = outcome
                    counts["clean" if outcome == "CLEAN" else "infected"] += 1
                    if outcome == "INFECTED":
                        item.status, item.reason = "REJECTED", "Security scan rejected file"
                else:
                    item.scan_status = "ERROR" if item.scan_attempts >= self.settings.material_security_scan_max_attempts else "PENDING"
                    item.next_attempt_at = _now() + timedelta(minutes=min(30, 2 * item.scan_attempts))
                    counts["errors"] += 1
                item.claimed_at = None
                batch = self._batch(session, item.batch_id)
                self._audit(session, batch, None, "SCAN_" + item.scan_status, [item.id])
                session.commit()
        stale = session.scalars(select(Batch).where(Batch.status == "DRAFT", Batch.created_at < now - timedelta(days=max(1, self.settings.batch_submission_draft_retention_days)))
                                .limit(20).with_for_update(skip_locked=True)).all()
        for batch in stale:
            batch.status = "EXPIRED"
            for item in self._items(session, batch.id, lock=True):
                if item.status not in {"PUBLISHED", "CLEANED"}:
                    item.status = "REJECTED"
            self._audit(session, batch, None, "EXPIRE")
        session.commit()
        cleanup_ids = session.scalars(select(Item.id).where(Item.status == "REJECTED")
                                     .order_by(Item.id).limit(20)).all()
        for item_id in cleanup_ids:
            batch_id = session.scalar(select(Item.batch_id).where(Item.id == item_id))
            # Match review/publication lock order: batch first, then its items.
            batch = self._batch(session, batch_id, lock=True)
            item = session.scalar(select(Item).where(Item.id == item_id).with_for_update().execution_options(populate_existing=True))
            if item.status != "REJECTED":
                continue
            # Association check is deliberately conservative, even after material deletion.
            publications = session.scalars(select(Publication).where(Publication.batch_id == item.batch_id)).all()
            if any(item.id in json.loads(p.item_ids_json or "[]") for p in publications):
                continue
            if item.object_key and session.scalar(select(MaterialRecord.id).where(MaterialRecord.file_storage_key == item.object_key).limit(1)):
                continue
            item.cleanup_attempts += 1
            try:
                if item.object_key:
                    self.asset_store.delete_key_strict(item.object_key)
            except Exception:
                session.commit()
                counts["errors"] += 1
                continue
            item.object_key = None
            item.status = "CLEANED"
            item.name = "已清理"
            item.content_type = "application/octet-stream"
            item.upload_token_digest = None
            item.upload_token_expires_at = None
            batch = self._batch(session, item.batch_id)
            self._audit(session, batch, None, "CLEANUP", [item.id])
            siblings = self._items(session, batch.id)
            if all(i.status == "CLEANED" for i in siblings):
                batch.status = "CLEANED"
                batch.note = batch.pricing_note = batch.netdisk_url = batch.netdisk_password = None
            elif all(i.status in {"PUBLISHED", "CLEANED"} for i in siblings):
                batch.status = "PUBLISHED"
            session.commit()
            counts["cleaned"] += 1
        return counts
