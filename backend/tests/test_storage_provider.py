from pathlib import Path

from app.core.config import Settings
from app.providers.storage import AliyunOssStorageProvider, LocalFileStorageProvider


def test_local_delete_key_removes_file_and_empty_parent(tmp_path):
    root = tmp_path / "assets"
    target = root / "materials" / "demo.txt"
    target.parent.mkdir(parents=True)
    target.write_text("demo", encoding="utf-8")

    LocalFileStorageProvider().delete_key(root=root, key="materials/demo.txt")

    assert not target.exists()
    assert not target.parent.exists()
    assert root.exists()


def test_local_delete_key_ignores_paths_outside_root(tmp_path):
    root = tmp_path / "assets"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")

    provider = LocalFileStorageProvider()
    provider.delete_key(root=root, key="../outside.txt")
    provider.delete_key(root=root, key=str(outside))

    assert outside.read_text(encoding="utf-8") == "keep"


def test_oss_signed_download_url_does_not_override_content_type(monkeypatch):
    captured: dict[str, object] = {}

    class FakeBucket:
        def sign_url(self, method, key, ttl, *, slash_safe, headers, params):
            captured.update(
                {
                    "method": method,
                    "key": key,
                    "ttl": ttl,
                    "slash_safe": slash_safe,
                    "headers": headers,
                    "params": params,
                }
            )
            return "https://studyhub-prod.oss-cn-chengdu.aliyuncs.com/materials/demo.pdf?signature=demo"

    provider = AliyunOssStorageProvider(
        Settings(
            oss_endpoint="https://oss-cn-chengdu.aliyuncs.com",
            oss_bucket="studyhub-prod",
            oss_access_key_id="id",
            oss_access_key_secret="secret",
        )
    )
    monkeypatch.setattr(provider, "_bucket", lambda: FakeBucket())

    url, expires_at = provider.build_signed_download_url(
        root=Path("materials"),
        key="materials/demo.pdf",
        filename="概率论.pdf",
        ttl_seconds=900,
        content_type="application/pdf",
    )

    assert url.startswith("https://studyhub-prod.oss-cn-chengdu.aliyuncs.com/")
    assert expires_at
    assert "response-content-disposition" in captured["params"]
    assert "response-content-type" not in captured["params"]
