from __future__ import annotations

from Cryptodome.PublicKey import RSA

from app.core.config import Settings
from app.models.finance import OrderRecord
from app.providers.alipay_support import load_key_material, load_key_material_from_pem_text
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


def test_alipay_private_key_loader_wraps_bare_base64_for_sdk(tmp_path) -> None:
    private_key = RSA.generate(1024)
    private_pem = private_key.export_key(format="PEM", pkcs=8).decode("ascii")
    bare_body = "".join(line for line in private_pem.splitlines() if "BEGIN" not in line and "END" not in line)
    key_path = tmp_path / "app_private_key.txt"
    key_path.write_text(bare_body, encoding="utf-8")

    loaded = load_key_material(str(key_path), pem_label="PRIVATE KEY")

    assert loaded.startswith("-----BEGIN PRIVATE KEY-----")
    assert RSA.import_key(loaded).has_private()


def test_alipay_public_key_loader_preserves_pem_for_sdk(tmp_path) -> None:
    public_pem = RSA.generate(1024).public_key().export_key(format="PEM").decode("ascii")
    key_path = tmp_path / "alipay_public_key.pem"
    key_path.write_text(public_pem, encoding="utf-8")

    loaded = load_key_material(str(key_path), pem_label="PUBLIC KEY")

    assert loaded == public_pem.strip() + "\n"
    assert not RSA.import_key(loaded).has_private()


def test_alipay_cert_public_key_loader_preserves_extracted_pem() -> None:
    public_pem = RSA.generate(1024).public_key().export_key(format="PEM").decode("ascii")

    loaded = load_key_material_from_pem_text(public_pem)

    assert loaded == public_pem.strip() + "\n"
    assert not RSA.import_key(loaded).has_private()
