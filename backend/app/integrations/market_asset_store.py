from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import UploadFile

from app.core.config import Settings
from app.providers.storage import StorageProvider


class MarketAssetStore:
    def __init__(self, settings: Settings, storage_provider: StorageProvider) -> None:
        self.settings = settings
        self.storage_provider = storage_provider

    @property
    def root(self) -> Path:
        return self.settings.resolved_market_asset_dir

    @property
    def provider_name(self) -> str:
        return self.storage_provider.provider_name

    def save_upload(self, *, item_id: int, upload: UploadFile) -> str:
        key, _ = self.storage_provider.save_upload(
            root=self.root,
            relative_dir=Path(str(item_id)),
            upload=upload,
            fallback_name="image.bin",
        )
        return key

    async def save_upload_async(self, *, item_id: int, upload: UploadFile) -> str:
        key, _ = await self.storage_provider.save_upload_async(
            root=self.root,
            relative_dir=Path(str(item_id)),
            upload=upload,
            fallback_name="image.bin",
        )
        return key

    def delete_key(self, key: str | None) -> None:
        self.storage_provider.delete_key(root=self.root, key=key)

    async def delete_key_async(self, key: str | None) -> None:
        await self.storage_provider.delete_key_async(root=self.root, key=key)

    def resolve_path(self, key: str) -> Path:
        return self.storage_provider.resolve_path(root=self.root, key=key, invalid_detail="无效的图片路径")

    def guess_media_type(self, key: str | None, default: str = "application/octet-stream") -> str:
        return self.storage_provider.guess_media_type(key, default=default)

    def build_public_url(self, *, item_id: int, index: int, key: str) -> str:
        direct_url = self.storage_provider.build_public_url(root=self.root, key=key)
        if direct_url is not None:
            return direct_url
        return f"/api/market/{item_id}/images/{index}"

    async def build_public_url_async(self, *, item_id: int, index: int, key: str) -> str:
        direct_url = await self.storage_provider.build_public_url_async(root=self.root, key=key)
        if direct_url is not None:
            return direct_url
        return await asyncio.to_thread(self.build_public_url, item_id=item_id, index=index, key=key)
