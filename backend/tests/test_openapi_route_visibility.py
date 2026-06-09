from __future__ import annotations

from fastapi.testclient import TestClient


def test_openapi_exposes_first_stable_user_alias_batch(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]

    exposed_paths = {
        "/api/auth/captcha",
        "/api/captcha",
        "/api/auth/register",
        "/api/auth/verify",
        "/api/auth/login",
        "/api/auth/reset-password",
        "/api/auth/password",
        "/api/auth/bind-email",
        "/api/logout",
        "/api/ai/chat",
        "/api/ai/recommend",
        "/api/materials/{id}/view",
        "/api/materials/{id}/review",
        "/api/materials/{id}/favorite",
        "/api/materials/{id}/like",
        "/api/materials/{id}/download",
        "/api/materials/downloads/batch",
        "/api/comments/{id}/like",
        "/api/comments/{id}/report",
        "/api/users/{id}/follow",
        "/api/requests/{id}/follow",
        "/api/requests/{id}/respond",
        "/api/requests/{id}/accept",
        "/api/requests/{id}/preview-view",
        "/api/requests/{id}/dispute",
        "/api/requests/contributions/{id}/cancel",
        "/api/requests/contributions/{id}/deadline",
        "/api/orders/{id}/confirm",
        "/api/market/{id}/want",
        "/api/notifications/list",
        "/api/notifications/read",
        "/api/free-download/status",
        "/api/creator-payout-applications/me",
    }

    assert exposed_paths <= set(paths)


def test_openapi_keeps_sensitive_internal_routes_hidden(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]

    hidden_operations = {
        ("get", "/.well-known/oauth-protected-resource"),
        ("post", "/api/auth/dev-login"),
        ("post", "/api/pay/alipay/notify"),
        ("post", "/api/pay/alipay/gateway"),
        ("post", "/api/pay/alipay/create"),
        ("post", "/api/admin/materials/batch-delete"),
        ("post", "/api/admin/market/batch-delete"),
        ("patch", "/api/admin/creator-payout-applications"),
        ("post", "/api/notifications/admin"),
        ("post", "/api/requests/arbitrations/{id}/decision"),
    }

    for method, path in hidden_operations:
        assert method not in paths.get(path, {})


def test_openapi_operation_ids_are_unique(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    operation_ids: list[str] = []
    for path_item in schema["paths"].values():
        for operation in path_item.values():
            if isinstance(operation, dict) and "operationId" in operation:
                operation_ids.append(operation["operationId"])

    assert len(operation_ids) == len(set(operation_ids))
