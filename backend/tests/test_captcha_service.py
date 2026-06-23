from __future__ import annotations

from app.core.config import Settings
from app.core.exceptions import BizException
from app.services.captcha_service import CaptchaService


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        del ex
        self.store[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def eval(self, script: str, numkeys: int, key: str) -> str | None:
        del script, numkeys
        return self.store.pop(key, None)

    def scan_iter(self, match: str, count: int = 0):
        del count
        prefix = match.rstrip("*")
        for key in list(self.store):
            if key.startswith(prefix):
                yield key

    def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self.store:
                deleted += 1
                self.store.pop(key, None)
        return deleted


def test_captcha_service_uses_redis_backend_once(monkeypatch) -> None:
    service = CaptchaService(Settings(captcha_backend="redis", redis_url="redis://cache", captcha_ttl_seconds=60))
    fake_redis = FakeRedis()
    monkeypatch.setattr(service, "_client", lambda: fake_redis)

    payload = service.generate()
    code = service.peek_code_for_testing(payload.captchaId)

    assert code is not None
    assert any(key.startswith("studyhub-fastapi:captcha:") for key in fake_redis.store)
    service.validate(payload.captchaId, code)

    try:
        service.validate(payload.captchaId, code)
    except BizException as exc:
        assert exc.code == "CAPTCHA_EXPIRED"
    else:
        raise AssertionError("captcha should be single-use")


def test_captcha_service_falls_back_to_local_when_redis_unavailable(monkeypatch) -> None:
    service = CaptchaService(Settings(captcha_backend="redis", redis_url="redis://cache", captcha_ttl_seconds=60))

    def raise_redis_error():
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(service, "_client", raise_redis_error)

    payload = service.generate()
    code = service.peek_code_for_testing(payload.captchaId)

    assert code is not None
    service.validate(payload.captchaId, code)


def test_captcha_service_reset_clears_redis_keys(monkeypatch) -> None:
    service = CaptchaService(Settings(captcha_backend="redis", redis_url="redis://cache", captcha_ttl_seconds=60))
    fake_redis = FakeRedis()
    monkeypatch.setattr(service, "_client", lambda: fake_redis)
    payload = service.generate()

    service.reset()

    assert service.peek_code_for_testing(payload.captchaId) is None
    assert fake_redis.store == {}
