from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.materials import MaterialRecord, MaterialSecurityScanRecord


class MaterialSecurityPolicyMixin:
    def _queue_material_security_scan(
        self,
        session: Session,
        material: MaterialRecord,
        *,
        release_status: str,
        release_review_status: str | None,
    ) -> None:
        if not self._material_security_scan_enabled() or not material.file_storage_key:
            return
        scan = self.material_repo.get_security_scan(session, int(material.id))
        if scan is None:
            scan = MaterialSecurityScanRecord(material_id=int(material.id), object_key=material.file_storage_key)
        scan.object_key = material.file_storage_key
        scan.status = "PENDING"
        scan.release_status = release_status
        scan.release_review_status = release_review_status
        scan.attempt_count = 0
        scan.next_attempt_at = None
        scan.claimed_at = None
        scan.scanned_at = None
        scan.scanner_version = None
        scan.finding = None
        scan.last_error = None
        material.status = "HIDDEN"
        material.review_status = "SECURITY_PENDING"
        self.material_repo.save_security_scan(session, scan)

    def _material_security_status(self, session: Session | None, material_id: int) -> str | None:
        if not self._material_security_scan_enabled() or session is None:
            return None
        scan = self.material_repo.get_security_scan(session, material_id)
        return scan.status if scan is not None else None

    def _assert_material_security_scan_complete(self, session: Session, material_id: int) -> None:
        if not self._material_security_scan_enabled():
            return
        scan = self.material_repo.get_security_scan(session, material_id)
        if scan is None or scan.status == "CLEAN":
            return
        if scan.status == "INFECTED":
            raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="文件未通过安全检查，暂不可下载")
        if scan.status == "ERROR":
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="文件安全检查暂未完成，请稍后再试")
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="文件正在进行安全检查，请稍后再试")

    def _material_security_scan_enabled(self) -> bool:
        return bool(getattr(self.settings, "resolved_material_security_scan_enabled", False))
