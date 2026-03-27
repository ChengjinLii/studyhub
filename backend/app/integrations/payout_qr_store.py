from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import UploadFile

from app.core.config import Settings
from app.providers.storage import StorageProvider


class PayoutQrStore:
    """收款码只做本地私有文件托管，运行时不依赖旧仓库或外部 OSS。"""

    def __init__(self, settings: Settings, storage_provider: StorageProvider) -> None:
        self.settings = settings
        self.storage_provider = storage_provider

    @property
    def root(self) -> Path:
        return self.settings.resolved_payout_qr_asset_dir

    @property
    def provider_name(self) -> str:
        return self.storage_provider.provider_name

    def save_upload(self, *, user_id: int, upload: UploadFile) -> str:
        key, _ = self.storage_provider.save_upload(
            root=self.root,
            relative_dir=Path(str(user_id)),
            upload=upload,
            fallback_name="payout-qr.bin",
        )
        return key

    async def save_upload_async(self, *, user_id: int, upload: UploadFile) -> str:
        key, _ = await self.storage_provider.save_upload_async(
            root=self.root,
            relative_dir=Path(str(user_id)),
            upload=upload,
            fallback_name="payout-qr.bin",
        )
        return key

    def delete_key(self, key: str | None) -> None:
        self.storage_provider.delete_key(root=self.root, key=key)

    async def delete_key_async(self, key: str | None) -> None:
        await self.storage_provider.delete_key_async(root=self.root, key=key)

    def resolve_path(self, key: str) -> Path:
        return self.storage_provider.resolve_path(root=self.root, key=key, invalid_detail="无效的收款码路径")

    def guess_media_type(self, key: str | None, default: str = "application/octet-stream") -> str:
        return self.storage_provider.guess_media_type(key, default=default)

    def build_private_access_url(self, *, key: str) -> str | None:
        direct_url = self.storage_provider.build_signed_download_url(
            root=self.root,
            key=key,
            filename=Path(key).name,
            ttl_seconds=300,
            content_type=self.guess_media_type(key, default="image/png"),
        )
        if direct_url is None:
            return None
        return direct_url[0]

    async def build_private_access_url_async(self, *, key: str) -> str | None:
        direct_url = await self.storage_provider.build_signed_download_url_async(
            root=self.root,
            key=key,
            filename=Path(key).name,
            ttl_seconds=300,
            content_type=self.guess_media_type(key, default="image/png"),
        )
        if direct_url is None:
            return None
        return direct_url[0]
