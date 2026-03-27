from __future__ import annotations

import shutil
import subprocess

from app.core.config import Settings


def gateway_url_for_env(alipay_env: str) -> str:
    if alipay_env.strip().lower() in {"prod", "production"}:
        return "https://openapi.alipay.com/gateway.do"
    return "https://openapi-sandbox.dl.alipaydev.com/gateway.do"


def build_alipay_client(settings: Settings):
    try:
        from alipay import AliPay  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Alipay provider 依赖缺失，请安装 python-alipay-sdk。") from exc
    return AliPay(
        appid=settings.alipay_app_id,
        app_notify_url=settings.alipay_notify_url,
        app_private_key_string=load_key_material(settings.alipay_app_private_key_path),
        alipay_public_key_string=load_public_key_material(
            public_key_path=settings.alipay_public_key_path,
            public_cert_path=settings.alipay_public_cert_path,
        ),
        sign_type=settings.alipay_sign_type,
        debug=settings.alipay_env.strip().lower() not in {"prod", "production"},
    )


def load_public_key_material(*, public_key_path: str | None, public_cert_path: str | None) -> str:
    if public_key_path:
        return load_key_material(public_key_path)
    if public_cert_path:
        return extract_public_key_from_cert(public_cert_path)
    raise RuntimeError("缺少支付宝公钥或公钥证书路径配置。")


def load_key_material(path: str | None) -> str:
    if not path:
        raise RuntimeError("缺少支付宝密钥文件路径配置。")
    content = open(path, "r", encoding="utf-8").read().strip()
    if "BEGIN" in content:
        return "".join(
            line.strip()
            for line in content.splitlines()
            if "BEGIN" not in line and "END" not in line
        )
    return "".join(content.split())


def extract_public_key_from_cert(path: str) -> str:
    openssl = shutil.which("openssl")
    if not openssl:
        raise RuntimeError("系统缺少 openssl，无法从支付宝证书提取公钥。")
    completed = subprocess.run(
        [openssl, "x509", "-pubkey", "-noout", "-in", path],
        check=True,
        capture_output=True,
        text=True,
    )
    return load_key_material_from_pem_text(completed.stdout)


def load_key_material_from_pem_text(content: str) -> str:
    stripped = content.strip()
    if "BEGIN" in stripped:
        return "".join(
            line.strip()
            for line in stripped.splitlines()
            if "BEGIN" not in line and "END" not in line
        )
    return "".join(stripped.split())
