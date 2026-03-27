from __future__ import annotations


class StorageAdapter:
    """OSS/对象存储的统一入口，具体实现留到业务迁移步骤。"""

    def sign_url(self, key: str, expires_in_seconds: int) -> str:
        raise NotImplementedError("对象存储适配会在后续步骤实现。")
