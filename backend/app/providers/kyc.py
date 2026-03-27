from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
import hashlib
import json
import re

from app.core.config import Settings


@dataclass(slots=True)
class KycDecision:
    passed: bool
    retryable: bool
    provider_name: str
    request_id: str | None
    biz_code: str
    biz_message: str
    raw_message: str | None = None


class KycProvider(Protocol):
    provider_name: str

    def verify_id2_meta(self, *, real_name: str, id_card_no: str) -> KycDecision: ...

    def probe(self, *, deep: bool = False) -> dict[str, Any]: ...


class LocalMockKycProvider:
    provider_name = "mock_local"

    def verify_id2_meta(self, *, real_name: str, id_card_no: str) -> KycDecision:
        request_id = f"KYC{hashlib.md5(f'{real_name}:{id_card_no}'.encode('utf-8')).hexdigest()[:12].upper()}"  # noqa: S324
        if not re.fullmatch(r"\d{15}|\d{17}[\dX]", id_card_no):
            return KycDecision(
                passed=False,
                retryable=False,
                provider_name=self.provider_name,
                request_id=request_id,
                biz_code="INVALID_ID",
                biz_message="身份证号格式不正确",
            )
        if id_card_no.endswith("0000"):
            return KycDecision(
                passed=False,
                retryable=True,
                provider_name=self.provider_name,
                request_id=request_id,
                biz_code="PENDING",
                biz_message="实名核验排队中，请稍后重试",
            )
        return KycDecision(
            passed=True,
            retryable=False,
            provider_name=self.provider_name,
            request_id=request_id,
            biz_code="SUCCESS",
            biz_message="实名认证通过",
        )

    def probe(self, *, deep: bool = False) -> dict[str, Any]:
        del deep
        return {
            "status": "ok",
            "provider": self.provider_name,
            "mode": "local-simulated",
        }


class AliyunCloudAuthKycProvider:
    provider_name = "aliyun_cloud_auth"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def verify_id2_meta(self, *, real_name: str, id_card_no: str) -> KycDecision:
        if not self.settings.kyc_enabled:
            return KycDecision(
                passed=False,
                retryable=False,
                provider_name=self.provider_name,
                request_id=None,
                biz_code="KYC_DISABLED",
                biz_message="KYC 未开启",
            )
        if not self.settings.alibaba_cloud_access_key_id or not self.settings.alibaba_cloud_access_key_secret:
            return KycDecision(
                passed=False,
                retryable=False,
                provider_name=self.provider_name,
                request_id=None,
                biz_code="KYC_NOT_CONFIG",
                biz_message="KYC 凭证未配置",
            )
        try:
            client, request = self._build_request(real_name=real_name, id_card_no=id_card_no)
            response_bytes = client.do_action_with_exception(request)
            return self._parse_response(response_bytes)
        except Exception as exc:  # noqa: BLE001
            return KycDecision(
                passed=False,
                retryable=True,
                provider_name=self.provider_name,
                request_id=None,
                biz_code="KYC_EXCEPTION",
                biz_message="KYC 调用失败",
                raw_message=str(exc),
            )

    def probe(self, *, deep: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": "ok",
            "provider": self.provider_name,
            "endpoint": self.settings.kyc_endpoint,
            "region": self.settings.kyc_region_id,
            "enabled": self.settings.kyc_enabled,
        }
        if deep:
            client, request = self._build_request(real_name="张三", id_card_no="110101199001010000")
            payload["clientReady"] = client is not None and request is not None
        return payload

    def _build_request(self, *, real_name: str, id_card_no: str):
        try:
            from aliyunsdkcore.client import AcsClient  # type: ignore[import-not-found]
            from aliyunsdkcore.request import CommonRequest  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("Aliyun KYC provider 依赖缺失，请安装 aliyun-python-sdk-core。") from exc

        client = AcsClient(
            self.settings.alibaba_cloud_access_key_id,
            self.settings.alibaba_cloud_access_key_secret,
            self.settings.kyc_region_id,
        )
        request = CommonRequest()
        request.set_accept_format("json")
        request.set_domain(self.settings.kyc_endpoint)
        request.set_method("POST")
        request.set_version(self.settings.kyc_api_version)
        request.set_action_name("Id2MetaVerify")
        request.add_query_param("IdentifyNum", id_card_no)
        request.add_query_param("UserName", real_name)
        return client, request

    def _parse_response(self, response_bytes: bytes) -> KycDecision:
        payload = json.loads(response_bytes.decode("utf-8"))
        request_id = payload.get("RequestId")
        http_code = str(payload.get("Code") or "")
        result = payload.get("ResultObject") or payload.get("Result") or {}
        biz_code = str(result.get("BizCode") or "KYC_EMPTY")
        biz_message = str(result.get("BizMessage") or payload.get("Message") or "KYC 返回为空")
        return KycDecision(
            passed=biz_code == "1",
            retryable=http_code != "200",
            provider_name=self.provider_name,
            request_id=request_id,
            biz_code=biz_code,
            biz_message=biz_message,
            raw_message=str(payload.get("Message") or "") or None,
        )
