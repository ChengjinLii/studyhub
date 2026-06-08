from __future__ import annotations

from types import SimpleNamespace

from app.integrations.material_asset_store import MaterialAssetStore


class _TokenCodec:
    def encode(self, payload, ttl_seconds: int) -> str:
        assert payload["kind"] == "preview-image"
        assert payload["key"] == "materials/41/preview/p001.jpg"
        assert ttl_seconds == 900
        return "preview-token"

    def decode(self, token: str):
        assert token == "preview-token"
        return {"exp": 1}


class _StorageProvider:
    provider_name = "fake"

    def build_signed_download_url(self, **kwargs):
        raise AssertionError("preview images must use the backend proxy route")


def test_preview_url_uses_backend_proxy_for_real_preview_images() -> None:
    settings = SimpleNamespace(resolved_material_asset_dir="/tmp/materials", material_signed_url_ttl_seconds=900)
    store = MaterialAssetStore(settings, _TokenCodec(), _StorageProvider())

    url = store.build_preview_url(
        material_id=41,
        index=1,
        key="materials/41/preview/p001.jpg",
        placeholder=False,
    )

    assert url == "/api/materials/41/preview/images/1?token=preview-token"
