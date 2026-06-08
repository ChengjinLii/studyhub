from app.providers.storage import LocalFileStorageProvider


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
