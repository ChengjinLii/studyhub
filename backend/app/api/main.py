from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    account,
    admin,
    ai,
    community,
    auth,
    comments,
    creator,
    free_download,
    health,
    leaderboard,
    market,
    materials,
    notifications,
    orders,
    payments,
    profile,
    payouts,
    reports,
    requests,
    session,
)


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(session.router)
api_router.include_router(ai.router)
api_router.include_router(account.router)
api_router.include_router(profile.router)
api_router.include_router(free_download.router)
api_router.include_router(creator.router)
api_router.include_router(materials.router)
api_router.include_router(orders.router)
api_router.include_router(payments.router)
api_router.include_router(payouts.router)
api_router.include_router(leaderboard.router)
api_router.include_router(market.router)
api_router.include_router(comments.router)
api_router.include_router(community.router)
api_router.include_router(notifications.router)
api_router.include_router(reports.router)
api_router.include_router(admin.router)
api_router.include_router(requests.router)
