from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.integrations.material_asset_store import MaterialAssetStore
from app.repos.material_repo import MaterialRepository


@dataclass(slots=True)
class MalwareScanResult:
    status: str
    version: str | None = None
    finding: str | None = None
    error: str | None = None


LIGHTWEIGHT_SCANNER_VERSION = "studyhub-structural/1"
LIGHTWEIGHT_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
PDF_ACTIVE_CONTENT_KEYS = {
    "/AA",
    "/EmbeddedFile",
    "/EmbeddedFiles",
    "/ImportData",
    "/JavaScript",
    "/JS",
    "/Launch",
    "/OpenAction",
    "/RichMedia",
    "/SubmitForm",
    "/XFA",
}
PDF_OBJECT_INSPECTION_LIMIT = 20_000
IMAGE_PIXEL_LIMIT = 100_000_000


class MaterialSecurityService:
    def __init__(self, settings: Settings, material_repo: MaterialRepository, asset_store: MaterialAssetStore) -> None:
        self.settings = settings
        self.material_repo = material_repo
        self.asset_store = asset_store

    def run_once(self, session: Session, *, limit: int = 2) -> dict[str, int]:
        now = datetime.now(UTC)
        scans = self.material_repo.list_ready_security_scans(
            session,
            now,
            stale_before=now - timedelta(minutes=10),
            limit=limit,
        )
        result_counts = {"processed": 0, "clean": 0, "infected": 0, "errors": 0}
        for scan in scans:
            object_key = scan.object_key
            scan.status = "SCANNING"
            scan.claimed_at = datetime.now(UTC)
            scan.attempt_count = int(scan.attempt_count or 0) + 1
            scan.last_error = None
            self.material_repo.save_security_scan(session, scan)
            session.commit()
            try:
                result = self._scan_object(object_key)
            except Exception as exc:  # noqa: BLE001
                result = MalwareScanResult(status="ERROR", error=str(exc)[:512])

            session.refresh(scan)
            if scan.object_key != object_key or scan.status != "SCANNING":
                continue
            result_counts["processed"] += 1
            scan.scanner_version = result.version
            scan.scanned_at = datetime.now(UTC)
            if result.status == "CLEAN":
                material = self.material_repo.get_material(session, scan.material_id)
                if material is None:
                    scan.status = "ERROR"
                    scan.last_error = "material not found"
                    result_counts["errors"] += 1
                else:
                    scan.status = "CLEAN"
                    scan.finding = None
                    scan.last_error = None
                    material.status = scan.release_status or "VISIBLE"
                    material.review_status = scan.release_review_status or "APPROVED"
                    self.material_repo.save_material(session, material)
                    result_counts["clean"] += 1
            elif result.status == "INFECTED":
                material = self.material_repo.get_material(session, scan.material_id)
                scan.status = "INFECTED"
                scan.finding = result.finding or "malware detected"
                scan.last_error = None
                if material is not None:
                    material.status = "HIDDEN"
                    material.review_status = "SECURITY_REJECTED"
                    self.material_repo.save_material(session, material)
                result_counts["infected"] += 1
            else:
                attempts = int(scan.attempt_count or 0)
                scan.status = "ERROR" if attempts >= self.settings.material_security_scan_max_attempts else "PENDING"
                scan.next_attempt_at = datetime.now(UTC) + timedelta(minutes=min(30, max(2, attempts * 2)))
                scan.last_error = result.error or "scanner failed"
                result_counts["errors"] += 1
            self.material_repo.save_security_scan(session, scan)
            session.commit()
        return result_counts

    def _scan_object(self, object_key: str) -> MalwareScanResult:
        quarantine_dir = self.settings.private_dir / "quarantine"
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(object_key).suffix[:16]
        with tempfile.NamedTemporaryFile(prefix="material-", suffix=suffix, dir=quarantine_dir, delete=False) as handle:
            temporary = Path(handle.name)
        try:
            self.asset_store.copy_to_path(
                object_key,
                temporary,
                max_size_bytes=self.settings.material_file_max_size_bytes,
            )
            lightweight_result = self._lightweight_scan(temporary)
            if lightweight_result is not None:
                return lightweight_result
            return self._clamav_scan(temporary)
        finally:
            temporary.unlink(missing_ok=True)

    def _lightweight_scan(self, path: Path) -> MalwareScanResult | None:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._lightweight_pdf_scan(path)
        if suffix in LIGHTWEIGHT_IMAGE_SUFFIXES:
            return self._lightweight_image_scan(path)
        return None

    def _lightweight_pdf_scan(self, path: Path) -> MalwareScanResult | None:
        try:
            with path.open("rb") as handle:
                if handle.read(8).lstrip()[:5] != b"%PDF-":
                    return None
            reader = PdfReader(str(path), strict=False)
            if reader.is_encrypted or len(reader.pages) < 1:
                return None
            if self._pdf_contains_active_content(reader):
                return None
        except Exception:  # noqa: BLE001
            return None
        return MalwareScanResult(status="CLEAN", version=LIGHTWEIGHT_SCANNER_VERSION)

    def _pdf_contains_active_content(self, reader: PdfReader) -> bool:
        stack: list[object] = [reader.trailer]
        seen_indirect: set[tuple[int, int]] = set()
        seen_containers: set[int] = set()
        inspected = 0
        while stack:
            current = stack.pop()
            if isinstance(current, IndirectObject):
                reference = (int(current.idnum), int(current.generation))
                if reference in seen_indirect:
                    continue
                seen_indirect.add(reference)
                current = current.get_object()
            if isinstance(current, (DictionaryObject, ArrayObject)):
                container_id = id(current)
                if container_id in seen_containers:
                    continue
                seen_containers.add(container_id)
            inspected += 1
            if inspected > PDF_OBJECT_INSPECTION_LIMIT:
                return True
            if isinstance(current, DictionaryObject):
                if PDF_ACTIVE_CONTENT_KEYS.intersection(str(key) for key in current.keys()):
                    return True
                stack.extend(current.values())
            elif isinstance(current, ArrayObject):
                stack.extend(current)
        return False

    def _lightweight_image_scan(self, path: Path) -> MalwareScanResult | None:
        try:
            with Image.open(path) as image:
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > IMAGE_PIXEL_LIMIT:
                    return None
                if (image.format or "").upper() not in {"PNG", "JPEG", "WEBP", "GIF", "BMP"}:
                    return None
                image.verify()
        except (Image.DecompressionBombError, UnidentifiedImageError, OSError, SyntaxError, ValueError):
            return None
        return MalwareScanResult(status="CLEAN", version=LIGHTWEIGHT_SCANNER_VERSION)

    def _clamav_scan(self, path: Path) -> MalwareScanResult:
        version = self._scanner_version()
        completed = subprocess.run(
            [self.settings.material_security_scanner_command, "--no-summary", "--stdout", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=max(30, self.settings.material_security_scan_timeout_seconds),
        )
        output = (completed.stdout or completed.stderr or "").strip()
        if completed.returncode == 0:
            return MalwareScanResult(status="CLEAN", version=version)
        if completed.returncode == 1:
            finding = output.rsplit(":", 1)[-1].replace("FOUND", "").strip()[:255]
            return MalwareScanResult(status="INFECTED", version=version, finding=finding or "malware detected")
        return MalwareScanResult(status="ERROR", version=version, error=output[-512:] or "scanner exited abnormally")

    def _scanner_version(self) -> str | None:
        try:
            completed = subprocess.run(
                [self.settings.material_security_scanner_command, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:  # noqa: BLE001
            return None
        return (completed.stdout or completed.stderr or "").strip()[:128] or None
