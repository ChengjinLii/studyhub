from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers


def create_publication_upload(asset_store, items, *, max_size_bytes: int) -> UploadFile:
    """Build one publication upload from already-authorized private objects."""
    stream = NamedTemporaryFile(mode="w+b", prefix="studyhub-batch-publication-", suffix=".tmp")
    try:
        if len(items) == 1:
            item = items[0]
            asset_store.copy_to_path(item.object_key, Path(stream.name), max_size_bytes=max_size_bytes)
            name = item.name
            media_type = item.content_type
        else:
            with TemporaryDirectory(prefix="studyhub-batch-sources-") as source_dir:
                with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
                    for item in items:
                        source_path = Path(source_dir) / str(item.id)
                        asset_store.copy_to_path(
                            item.object_key,
                            source_path,
                            max_size_bytes=item.size_bytes,
                        )
                        archive.write(source_path, arcname=f"{item.id}_{Path(item.name).name}")
            name, media_type = "batch.zip", "application/zip"
        stream.seek(0, 2)
        size = stream.tell()
        if size > max_size_bytes:
            raise HTTPException(status_code=400, detail="Generated publication exceeds 50 MiB; select fewer files")
        stream.seek(0)
        return UploadFile(
            file=stream,
            filename=name,
            size=size,
            headers=Headers({"content-type": media_type}),
        )
    except Exception:
        stream.close()
        raise
