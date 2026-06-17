from __future__ import annotations

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.api.routes import (
    admin,
    ai,
    auth,
    comments,
    community,
    free_download,
    market,
    materials,
    notifications,
    orders,
    payments,
    payouts,
    profile,
    requests,
    session,
)


ROUTE_MODULES = (
    admin,
    ai,
    auth,
    comments,
    community,
    free_download,
    market,
    materials,
    notifications,
    orders,
    payments,
    payouts,
    profile,
    requests,
    session,
)


def _registered_routes() -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for module in ROUTE_MODULES
        for route in module.router.routes
        if isinstance(route, APIRoute)
        for method in (route.methods or set())
        if method not in {"HEAD", "OPTIONS"}
    }


def test_restful_alias_routes_are_registered() -> None:
    wanted = {
        ("POST", "/api/session"),
        ("POST", "/api/dev-session"),
        ("DELETE", "/api/session"),
        ("GET", "/api/captchas"),
        ("POST", "/api/registration-verifications"),
        ("POST", "/api/registrations"),
        ("POST", "/api/password-resets"),
        ("PATCH", "/api/me/password"),
        ("PUT", "/api/me/email"),
        ("GET", "/api/notifications"),
        ("PATCH", "/api/notifications"),
        ("POST", "/api/materials/{id}/views"),
        ("POST", "/api/materials/{id}/reviews"),
        ("PUT", "/api/materials/{id}/favorite"),
        ("PUT", "/api/materials/{id}/like"),
        ("POST", "/api/materials/{id}/downloads"),
        ("POST", "/api/material-downloads"),
        ("PATCH", "/api/admin/materials"),
        ("DELETE", "/api/admin/materials"),
        ("PUT", "/api/admin/materials/{id}/restoration"),
        ("POST", "/api/admin/material-restorations"),
        ("PATCH", "/api/admin/market"),
        ("DELETE", "/api/admin/market"),
        ("POST", "/api/requests/{id}/contributions"),
        ("POST", "/api/requests/{id}/responses"),
        ("PUT", "/api/requests/{id}/accepted-response"),
        ("POST", "/api/requests/{id}/preview-views"),
        ("POST", "/api/requests/{id}/disputes"),
        ("PATCH", "/api/requests/arbitrations/{id}"),
        ("DELETE", "/api/requests/contributions/{id}"),
        ("PATCH", "/api/requests/contributions/{id}"),
        ("PUT", "/api/orders/{id}/confirmation"),
        ("POST", "/api/alipay-payments"),
        ("POST", "/api/alipay-payment-notifications"),
        ("POST", "/api/alipay-gateway-notifications"),
        ("GET", "/api/orders/status"),
        ("GET", "/api/alipay-payments/{out_trade_no}"),
        ("GET", "/api/me/creator-payout-application"),
        ("GET", "/api/admin/creator-payout-applications/{id}/settlements"),
        ("PUT", "/api/admin/monthly-payout-marks"),
        ("GET", "/api/admin/users/{uploaderId}/payout-qr"),
        ("PATCH", "/api/admin/feedbacks/{id}"),
        ("PATCH", "/api/admin/volunteers/{id}"),
        ("PUT", "/api/comments/{id}/like"),
        ("POST", "/api/comments/{id}/reports"),
        ("PUT", "/api/users/{id}/follow"),
        ("POST", "/api/ai-chats"),
        ("POST", "/api/ai-recommendations"),
        ("POST", "/api/ai/feedback"),
        ("GET", "/api/ai/memory"),
        ("PUT", "/api/ai/memory-preferences"),
        ("GET", "/api/free-download"),
    }
    registered = _registered_routes()

    assert wanted <= registered, f"Missing RESTful aliases: {sorted(wanted - registered)}"


def test_restful_collection_routes_are_not_shadowed_by_id_routes(client: TestClient) -> None:
    order_status = client.get("/api/orders/status", params={"orderNo": "SMOKE"})
    request_contribution_status = client.get("/api/requests/contributions/status", params={"orderNo": "SMOKE"})

    assert order_status.status_code == 401
    assert request_contribution_status.status_code == 401
