from __future__ import annotations

from app.core.config import Settings
from app.core.exceptions import BizException
from app.services.captcha_service import CaptchaService


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, dict[str, str]] = {}
        self.ttls: dict[str, int] = {}

    def pipeline(self, transaction: bool = True):
        del transaction
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback

    def hset(self, key: str, mapping: dict[str, object]) -> int:
        self.store[key] = {name: str(value) for name, value in mapping.items()}
        return len(mapping)

    def expire(self, key: str, ttl: int) -> bool:
        self.ttls[key] = ttl
        return True

    def execute(self) -> list[object]:
        return [True, True]

    def eval(self, script: str, numkeys: int, key: str, submitted_digest: str) -> int:
        del script, numkeys
        entry = self.store.get(key)
        if entry is None:
            return -1
        attempts = int(entry["attempts"])
        max_attempts = int(entry["max_attempts"])
        if entry["code_digest"] != submitted_digest:
            attempts += 1
            entry["attempts"] = str(attempts)
            if attempts >= max_attempts:
                self.store.pop(key, None)
                return -2
            return 0
        self.store.pop(key, None)
        return 1

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
                self.ttls.pop(key, None)
        return deleted


def test_captcha_service_uses_redis_backend_once(monkeypatch) -> None:
    service = CaptchaService(Settings(captcha_backend="redis", redis_url="redis://cache", captcha_ttl_seconds=60))
    fake_redis = FakeRedis()
    monkeypatch.setattr(service, "_client", lambda: fake_redis)

    payload = service.generate()
    code = service.peek_code_for_testing(payload.captchaId)

    assert code is not None
    key = next(key for key in fake_redis.store if key.startswith("studyhub-fastapi:captcha:"))
    assert fake_redis.ttls[key] == 60
    assert "code" not in fake_redis.store[key]
    assert code not in fake_redis.store[key].values()
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


def test_captcha_local_fallback_is_bounded() -> None:
    service = CaptchaService(Settings(environment="test", captcha_backend="local", captcha_local_max_entries=1))
    first = service.generate()
    second = service.generate()

    assert service.peek_code_for_testing(first.captchaId) is None
    assert service.peek_code_for_testing(second.captchaId) is not None
