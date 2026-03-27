from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


OrderChannel = Literal["simulated", "wechat_jsapi", "wechat_native", "alipay_page"]
PayoutContactType = Literal["QQ", "WECHAT", "PHONE", "OTHER"]
PayoutReviewStatus = Literal["APPROVED", "REJECTED"]


class OrderCreatePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    materialId: int = Field(..., ge=1)
    channel: OrderChannel = "simulated"


class AlipayCreatePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    orderId: int | None = Field(default=None, ge=1)
    materialId: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_target(self) -> "AlipayCreatePayload":
        if self.orderId is None and self.materialId is None:
            raise ValueError("订单或资料信息不能为空")
        return self


class PayoutApplicationCreatePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    alipayAccount: str
    alipayName: str
    realName: str
    idCardNo: str
    contactType: PayoutContactType
    contactValue: str
    notes: str | None = None

    @field_validator("alipayAccount")
    @classmethod
    def validate_alipay_account(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("支付宝账号不能为空")
        if len(normalized) > 128:
            raise ValueError("支付宝账号长度过长")
        return normalized

    @field_validator("alipayName", "realName")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("姓名不能为空")
        if len(normalized) > 64:
            raise ValueError("姓名长度过长")
        return normalized

    @field_validator("idCardNo")
    @classmethod
    def validate_id_card(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("身份证号不能为空")
        if len(normalized) > 32:
            raise ValueError("身份证号长度过长")
        return normalized

    @field_validator("contactValue")
    @classmethod
    def validate_contact_value(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("联系方式不能为空")
        if len(normalized) > 128:
            raise ValueError("联系方式长度过长")
        return normalized

    @field_validator("notes")
    @classmethod
    def validate_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) > 500:
            raise ValueError("备注长度过长")
        return normalized or None


class PayoutApplicationReviewPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: PayoutReviewStatus
    reviewNotes: str | None = None

    @field_validator("reviewNotes")
    @classmethod
    def validate_review_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) > 500:
            raise ValueError("审核备注长度过长")
        return normalized or None


class PayoutScheduleUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    launchDate: date
    nextPayoutDate: date | None = None


class AdminMonthlyPayoutMarkPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    monthKey: str
    uploaderId: int = Field(..., ge=1)
    markPaid: bool = True

    @field_validator("monthKey")
    @classmethod
    def validate_month_key(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) != 7 or normalized[4] != "-":
            raise ValueError("month 参数格式错误，应为 YYYY-MM")
        return normalized
