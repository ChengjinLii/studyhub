from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, status

from bots.qq_studyhub_bot.config import BotSettings
from bots.qq_studyhub_bot.onebot import OneBotStudyHubBot


settings = BotSettings.from_env()
bot = OneBotStudyHubBot(settings=settings)
app = FastAPI(title="StudyHub QQ Bot", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "studyhub-qq-bot",
        "onebotApiConfigured": bool(settings.onebot_api_base_url),
        "allowedGroupCount": len(settings.allowed_group_ids),
    }


@app.post("/onebot/events")
async def onebot_events(
    request: Request,
    x_studyhub_qq_bot_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    if settings.webhook_secret and x_studyhub_qq_bot_secret != settings.webhook_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid webhook secret")
    event = await request.json()
    if not isinstance(event, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid OneBot event")
    reply = bot.handle_event(event)
    if reply is None:
        return {"ok": True, "handled": False}
    bot.send_group_message(reply)
    return {"ok": True, "handled": True, "reply": reply.message if not settings.onebot_api_base_url else None}

