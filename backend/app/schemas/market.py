from __future__ import annotations

import json
from typing import TypeVar

from fastapi import HTTPException, status
from pydantic import BaseModel, Field


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class MarketCreatePayload(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=32)
    description: str | None = None
    price: float = Field(gt=0)
    contactType: str = Field(min_length=1, max_length=32)
    contactValue: str = Field(min_length=1, max_length=255)
    school: str | None = Field(default=None, max_length=120)


class MarketStatusPayload(BaseModel):
    status: str = Field(min_length=1, max_length=16)


class AdminMarketBatchUpdatePayload(BaseModel):
    itemIds: list[int] = Field(min_length=1)
    status: str | None = Field(default=None, max_length=16)
    category: str | None = Field(default=None, max_length=32)
    school: str | None = Field(default=None, max_length=120)
    contactType: str | None = Field(default=None, max_length=32)
    contactValue: str | None = Field(default=None, max_length=255)


class AdminMarketBatchDeletePayload(BaseModel):
    itemIds: list[int] = Field(min_length=1)


def parse_payload_json(raw_payload: object, schema: type[SchemaT]) -> SchemaT:
    if raw_payload is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少 payload")
    if hasattr(raw_payload, "read"):
        payload_bytes = raw_payload.file.read()
        raw_payload.file.seek(0)
        payload_text = payload_bytes.decode("utf-8")
    else:
        payload_text = str(raw_payload)
    try:
        data = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="payload 不是有效 JSON") from exc
    return schema.model_validate(data)
