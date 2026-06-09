from __future__ import annotations

from app.core.config import Settings
from app.models.finance import OrderRecord
from app.providers.payment import AlipayPagePaymentProvider


class FakeAlipayClient:
    def api_alipay_trade_page_pay(self, **kwargs):
        assert kwargs["out_trade_no"] == "SH202606090001"
        return "app_id=app123&method=alipay.trade.page.pay&biz_content=%7B%22subject%22%3A%22StudyHub%22%7D&sign=abc%2B123"


def test_alipay_page_checkout_form_expands_gateway_query_fields(monkeypatch) -> None:
    provider = AlipayPagePaymentProvider(
        Settings(
            alipay_env="production",
            alipay_app_id="app123",
            alipay_notify_url="https://study-hub.cn/api/alipay-payment-notifications",
            alipay_return_url="https://study-hub.cn/pay/result",
        )
    )
    monkeypatch.setattr(provider, "_client", lambda: FakeAlipayClient())
    order = OrderRecord(id=7, material_id=11, material_title="StudyHub", amount=1200, status="CREATED", channel="alipay_page")

    payload = provider.build_checkout_payload(out_trade_no="SH202606090001", order=order)

    form = str(payload["form"])
    assert payload["gatewayUrl"] == (
        "https://openapi.alipay.com/gateway.do?"
        "app_id=app123&method=alipay.trade.page.pay&biz_content=%7B%22subject%22%3A%22StudyHub%22%7D&sign=abc%2B123"
    )
    assert 'action="https://openapi.alipay.com/gateway.do"' in form
    assert 'name="query"' not in form
    assert 'name="app_id" value="app123"' in form
    assert 'name="biz_content" value="{&quot;subject&quot;:&quot;StudyHub&quot;}"' in form
    assert 'name="sign" value="abc+123"' in form
