from __future__ import annotations

import asyncio
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

    def delete_key(self, key: str | None) -> None:
        self.storage_provider.delete_key(root=self.settings.resolved_material_asset_dir, key=key)

    async def delete_key_async(self, key: str | None) -> None:
        await self.storage_provider.delete_key_async(root=self.settings.resolved_material_asset_dir, key=key)

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
        if key and not placeholder:
            direct_url = self.storage_provider.build_signed_download_url(
                root=self.settings.resolved_material_asset_dir,
                key=key,
                filename=Path(key).name,
                ttl_seconds=self.settings.material_signed_url_ttl_seconds,
                content_type=self.guess_media_type(key, default="image/png"),
            )
            if direct_url is not None:
                return direct_url[0]
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
        if key and not placeholder:
            direct_url = await self.storage_provider.build_signed_download_url_async(
                root=self.settings.resolved_material_asset_dir,
                key=key,
                filename=Path(key).name,
                ttl_seconds=self.settings.material_signed_url_ttl_seconds,
                content_type=self.guess_media_type(key, default="image/png"),
            )
            if direct_url is not None:
                return direct_url[0]
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

    def resolve_path(self, key: str) -> Path:
        return self.storage_provider.resolve_path(
            root=self.settings.resolved_material_asset_dir,
            key=key,
            invalid_detail="无效的文件路径",
        )

    def guess_media_type(self, key: str | None, default: str = "application/octet-stream") -> str:
        return self.storage_provider.guess_media_type(key, default=default)

    def build_public_custom_preview_url(self, *, material_id: int, index: int, key: str) -> str:
        direct_url = self.storage_provider.build_public_url(root=self.settings.resolved_material_asset_dir, key=key)
        if direct_url is not None:
            return direct_url
        return f"/api/materials/{material_id}/assets/custom/{index}"

    async def build_public_custom_preview_url_async(self, *, material_id: int, index: int, key: str) -> str:
        direct_url = await self.storage_provider.build_public_url_async(root=self.settings.resolved_material_asset_dir, key=key)
        if direct_url is not None:
            return direct_url
        return f"/api/materials/{material_id}/assets/custom/{index}"

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
