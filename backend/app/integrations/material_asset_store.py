from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status

from app.core.config import Settings
from app.core.security import JwtTokenCodec
from app.providers.storage import StorageProvider


class MaterialAssetStore:
    def __init__(self, settings: Settings, token_codec: JwtTokenCodec, storage_provider: StorageProvider) -> None:
        self.settings = settings
        self.token_codec = token_codec
        self.storage_provider = storage_provider

    @property
    def provider_name(self) -> str:
        return self.storage_provider.provider_name

    def save_upload(self, *, material_id: int, slot: str, upload: UploadFile) -> tuple[str, int]:
        return self.storage_provider.save_upload(
            root=self.settings.resolved_material_asset_dir,
            relative_dir=Path(str(material_id)) / slot,
            upload=upload,
            fallback_name="file.bin",
        )

    async def save_upload_async(self, *, material_id: int, slot: str, upload: UploadFile) -> tuple[str, int]:
        return await self.storage_provider.save_upload_async(
            root=self.settings.resolved_material_asset_dir,
            relative_dir=Path(str(material_id)) / slot,
            upload=upload,
            fallback_name="file.bin",
        )

    def save_staged_upload(
        self,
        *,
        user_id: int,
        submission_id: str,
        role: str,
        upload: UploadFile,
    ) -> tuple[str, int]:
        normalized_role = role.strip().lower().replace("_", "-")
        return self.storage_provider.save_upload(
            root=self.settings.resolved_material_asset_dir,
            relative_dir=Path("staged") / str(user_id) / submission_id / normalized_role,
            upload=upload,
            fallback_name="file.bin",
        )

    def issue_staged_upload_token(
        self,
        *,
        user_id: int,
        submission_id: str,
        assets: list[dict[str, Any]],
    ) -> str:
        return self.token_codec.encode(
            {
                "sub": f"material-staged-upload:{user_id}:{submission_id}",
                "kind": "material-staged-upload",
                "userId": user_id,
                "submissionId": submission_id,
                "assets": assets,
            },
            ttl_seconds=max(600, int(self.settings.staged_upload_token_ttl_seconds)),
        )

    def verify_staged_upload_tokens(
        self,
        *,
        tokens: list[str],
        user_id: int,
        submission_id: str,
    ) -> list[dict[str, Any]]:
        assets: list[dict[str, Any]] = []
        expected_prefix = f"staged/{user_id}/{submission_id}/"
        for token in tokens:
            try:
                claims = self.token_codec.decode(token)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="暂存文件凭证无效或已过期") from exc
            if (
                claims.get("kind") != "material-staged-upload"
                or int(claims.get("userId") or 0) != user_id
                or claims.get("submissionId") != submission_id
            ):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="暂存文件凭证不属于当前投稿")
            claimed_assets = claims.get("assets")
            if not isinstance(claimed_assets, list):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="暂存文件凭证格式非法")
            for asset in claimed_assets:
                if not isinstance(asset, dict):
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="暂存文件凭证格式非法")
                key = str(asset.get("key") or "")
                role = str(asset.get("role") or "")
                normalized_key = key.lstrip("/")
                belongs_to_submission = normalized_key.startswith(expected_prefix) or f"/{expected_prefix}" in f"/{normalized_key}"
                if not belongs_to_submission or role not in {"MATERIAL", "PREVIEW", "CUSTOM_PREVIEW"}:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="暂存文件凭证格式非法")
                assets.append(
                    {
                        "key": key,
                        "role": role,
                        "name": str(asset.get("name") or "")[:255],
                        "size": max(0, int(asset.get("size") or 0)),
                        "contentType": str(asset.get("contentType") or "")[:128],
                    }
                )
        if len(assets) > 16:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="暂存文件数量过多")
        return assets

    def delete_key(self, key: str | None) -> None:
        self.storage_provider.delete_key(root=self.settings.resolved_material_asset_dir, key=key)

    async def delete_key_async(self, key: str | None) -> None:
        await self.storage_provider.delete_key_async(root=self.settings.resolved_material_asset_dir, key=key)

    def cleanup_staged_uploads(self, *, protected_keys: set[str], older_than: datetime) -> int:
        return self.storage_provider.cleanup_staged_uploads(
            root=self.settings.resolved_material_asset_dir,
            protected_keys=protected_keys,
            older_than=older_than,
        )

    def build_download_url(self, *, material_id: int, key: str, filename: str | None) -> tuple[str, str | None]:
        direct_url = self.storage_provider.build_signed_download_url(
            root=self.settings.resolved_material_asset_dir,
            key=key,
            filename=filename,
            ttl_seconds=self.settings.material_signed_url_ttl_seconds,
            content_type=self.guess_media_type(filename or key),
        )
        if direct_url is not None:
            return direct_url
        token = self.token_codec.encode(
            {
                "sub": f"material-download:{material_id}",
                "materialId": material_id,
                "kind": "download",
                "key": key,
                "filename": filename,
            },
            ttl_seconds=self.settings.material_signed_url_ttl_seconds,
        )
        expires_at = self.token_codec.decode(token).get("exp")
        return f"/api/materials/{material_id}/download/file?token={token}", self._exp_to_iso(expires_at)

    async def build_download_url_async(self, *, material_id: int, key: str, filename: str | None) -> tuple[str, str | None]:
        direct_url = await self.storage_provider.build_signed_download_url_async(
            root=self.settings.resolved_material_asset_dir,
            key=key,
            filename=filename,
            ttl_seconds=self.settings.material_signed_url_ttl_seconds,
            content_type=self.guess_media_type(filename or key),
        )
        if direct_url is not None:
            return direct_url
        return await asyncio.to_thread(self.build_download_url, material_id=material_id, key=key, filename=filename)

    def build_preview_url(self, *, material_id: int, index: int, key: str | None, placeholder: bool) -> str:
        token = self.token_codec.encode(
            {
                "sub": f"material-preview:{material_id}:{index}",
                "materialId": material_id,
                "kind": "preview-placeholder" if placeholder else "preview-image",
                "key": key,
                "index": index,
            },
            ttl_seconds=self.settings.material_signed_url_ttl_seconds,
        )
        return f"/api/materials/{material_id}/preview/images/{index}?token={token}"

    async def build_preview_url_async(self, *, material_id: int, index: int, key: str | None, placeholder: bool) -> str:
        return await asyncio.to_thread(
            self.build_preview_url,
            material_id=material_id,
            index=index,
            key=key,
            placeholder=placeholder,
        )

    def verify_download_token(self, *, material_id: int, token: str) -> dict[str, Any]:
        return self._verify_token(material_id=material_id, token=token, allowed_kind={"download"})

    def verify_preview_token(self, *, material_id: int, token: str) -> dict[str, Any]:
        return self._verify_token(material_id=material_id, token=token, allowed_kind={"preview-image", "preview-placeholder"})

    def verify_custom_preview_token(self, *, material_id: int, token: str) -> dict[str, Any]:
        return self._verify_token(material_id=material_id, token=token, allowed_kind={"custom-preview"})

    def resolve_path(self, key: str) -> Path:
        return self.storage_provider.resolve_path(
            root=self.settings.resolved_material_asset_dir,
            key=key,
            invalid_detail="无效的文件路径",
        )

    def read_bytes(self, key: str, *, max_size_bytes: int) -> bytes:
        return self.storage_provider.read_bytes(
            root=self.settings.resolved_material_asset_dir,
            key=key,
            max_size_bytes=max_size_bytes,
        )

    async def read_bytes_async(self, key: str, *, max_size_bytes: int) -> bytes:
        return await self.storage_provider.read_bytes_async(
            root=self.settings.resolved_material_asset_dir,
            key=key,
            max_size_bytes=max_size_bytes,
        )

    def copy_to_path(self, key: str, destination: Path, *, max_size_bytes: int) -> int:
        return self.storage_provider.copy_to_path(
            root=self.settings.resolved_material_asset_dir,
            key=key,
            destination=destination,
            max_size_bytes=max_size_bytes,
        )

    def guess_media_type(self, key: str | None, default: str = "application/octet-stream") -> str:
        return self.storage_provider.guess_media_type(key, default=default)

    def build_public_custom_preview_url(self, *, material_id: int, index: int, key: str) -> str:
        direct_url = self.storage_provider.build_signed_object_url(
            root=self.settings.resolved_material_asset_dir,
            key=key,
            ttl_seconds=self.settings.material_signed_url_ttl_seconds,
        )
        if direct_url is not None:
            return direct_url
        token = self.token_codec.encode(
            {
                "sub": f"material-custom-preview:{material_id}:{index}",
                "materialId": material_id,
                "kind": "custom-preview",
                "key": key,
                "index": index,
            },
            ttl_seconds=self.settings.material_signed_url_ttl_seconds,
        )
        return f"/api/materials/{material_id}/assets/custom/{index}?token={token}"

    async def build_public_custom_preview_url_async(self, *, material_id: int, index: int, key: str) -> str:
        direct_url = await self.storage_provider.build_signed_object_url_async(
            root=self.settings.resolved_material_asset_dir,
            key=key,
            ttl_seconds=self.settings.material_signed_url_ttl_seconds,
        )
        if direct_url is not None:
            return direct_url
        return await asyncio.to_thread(
            self.build_public_custom_preview_url,
            material_id=material_id,
            index=index,
            key=key,
        )

    def _verify_token(self, *, material_id: int, token: str, allowed_kind: set[str]) -> dict[str, Any]:
        try:
            claims = dict(self.token_codec.decode(token))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="链接已失效") from exc
        if int(claims.get("materialId", 0) or 0) != material_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="链接已失效")
        if claims.get("kind") not in allowed_kind:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="链接已失效")
        return claims

    def _exp_to_iso(self, exp: Any) -> str | None:
        if exp is None:
            return None
        try:
            from datetime import UTC, datetime

            return datetime.fromtimestamp(int(exp), tz=UTC).isoformat()
        except Exception:  # noqa: BLE001
            return None
