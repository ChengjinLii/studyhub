from __future__ import annotations

import base64
import importlib.util

import pytest

from app.core.config import Settings
from app.services.kyc_crypto_service import KycCryptoService


def test_local_dev_kyc_crypto_service_fallback_round_trip() -> None:
    service = KycCryptoService(Settings(environment="local-dev"))

    encrypted = service.encrypt("白山")

    assert encrypted is not None
    assert service.decrypt(encrypted) == "白山"
    assert service.hash_id("51010619990101123X")
    assert service.mask_account("chengjin@example.com") == "c***@example.com"
    assert service.mask_name("白山") == "白*"


@pytest.mark.skipif(importlib.util.find_spec("cryptography") is None, reason="cryptography not installed")
def test_configured_kyc_crypto_service_round_trip() -> None:
    service = KycCryptoService(
        Settings(
            environment="production",
            kyc_encryption_key=base64.b64encode(b"0123456789abcdef").decode("utf-8"),
            kyc_hash_salt=base64.b64encode(b"studyhub-hmac-salt").decode("utf-8"),
        )
    )

    encrypted = service.encrypt("51010619990101123X")

    assert encrypted is not None
    assert service.decrypt(encrypted) == "51010619990101123X"
    assert service.hash_id("51010619990101123X") != service.hash_id("110101199001010000")
