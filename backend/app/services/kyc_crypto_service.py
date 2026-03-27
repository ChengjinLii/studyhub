from __future__ import annotations

from base64 import b64decode, b64encode
from dataclasses import dataclass
from hashlib import sha256
import hmac
from os import urandom

from app.core.config import Settings


@dataclass(slots=True)
class KycCryptoMaterial:
    encryption_key: bytes | None
    hash_salt: bytes | None


class KycCryptoService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.material = KycCryptoMaterial(
            encryption_key=self._decode_optional(settings.kyc_encryption_key),
            hash_salt=self._decode_optional(settings.kyc_hash_salt),
        )

    def encrypt(self, plain: str | None) -> str | None:
        if not plain:
            return None
        if self.material.encryption_key:
            iv = urandom(12)
            payload = self._aesgcm().encrypt(iv, plain.encode("utf-8"), None)
            return b64encode(iv + payload).decode("utf-8")
        if not self.settings.requires_private_env_file:
            return b64encode(plain.encode("utf-8")).decode("utf-8")
        raise RuntimeError("KYC encryption key missing")

    def decrypt(self, encoded: str | None) -> str | None:
        if not encoded:
            return None
        raw = b64decode(encoded)
        if self.material.encryption_key:
            iv = raw[:12]
            payload = raw[12:]
            return self._aesgcm().decrypt(iv, payload, None).decode("utf-8")
        if not self.settings.requires_private_env_file:
            return raw.decode("utf-8")
        raise RuntimeError("KYC encryption key missing")

    def hash_id(self, value: str | None) -> str | None:
        if not value:
            return None
        if self.material.hash_salt:
            return b64encode(hmac.digest(self.material.hash_salt, value.encode("utf-8"), "sha256")).decode("utf-8")
        if not self.settings.requires_private_env_file:
            return sha256(value.encode("utf-8")).hexdigest()
        raise RuntimeError("KYC hash salt missing")

    def last4(self, value: str | None) -> str | None:
        if not value:
            return None
        normalized = value.strip()
        return normalized if len(normalized) <= 4 else normalized[-4:]

    def mask_name(self, value: str | None) -> str | None:
        if not value:
            return None
        normalized = value.strip()
        if len(normalized) == 1:
            return normalized + "*"
        return normalized[0] + "*" * max(1, len(normalized) - 1)

    def mask_account(self, value: str | None) -> str | None:
        if not value:
            return None
        normalized = value.strip()
        at_index = normalized.find("@")
        if at_index > 1:
            return normalized[0] + "***" + normalized[at_index:]
        if len(normalized) <= 4:
            return "*" * len(normalized)
        return normalized[:2] + "***" + normalized[-2:]

    def _decode_optional(self, value: str | None) -> bytes | None:
        if not value:
            return None
        try:
            return b64decode(value.strip())
        except Exception:  # noqa: BLE001
            return value.strip().encode("utf-8")

    def _aesgcm(self):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("缺少 cryptography 依赖，无法启用生产 KYC 加密。") from exc
        return AESGCM(self.material.encryption_key)
