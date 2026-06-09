from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.core.response import api_fail


logger = logging.getLogger(__name__)


class BizException(Exception):
    """用于承载与 Java 侧相同的业务错误语义。"""

    def __init__(self, code: str, message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def translate_reason(code: str, reason: str | None) -> str:
    translations = {
        "USERNAME_EXISTS": "用户名已存在",
        "EMAIL_EXISTS": "邮箱已被绑定",
        "CAPTCHA_EXPIRED": "验证码已失效，请重新获取",
        "CAPTCHA_MISMATCH": "验证码错误",
        "CAPTCHA_GENERATE_FAILED": "验证码生成失败，请稍后再试",
        "CAPTCHA_REQUIRED": "请先完成验证码验证",
        "DOWNLOAD_QUOTA_EXHAUSTED": "下载次数已用完，如需继续下载请联系管理员重置额度",
    }
    return translations.get(code, reason or "请求处理失败")


def _validation_error_message(error: dict[str, Any]) -> str:
    loc = tuple(str(part) for part in error.get("loc", ()))
    error_type = str(error.get("type", ""))
    field = loc[-1] if loc else ""
    if field == "username":
        if error_type == "string_pattern_mismatch":
            return "用户名仅支持中文、英文、数字、下划线或短横线"
        return "用户名长度需为 3-32 个字符"
    if field in {"captchaCode", "captchaId"}:
        return "图形验证码不合法，请重新输入"
    if field == "code":
        return "邮箱验证码不合法，请检查后重新输入"
    if field == "email":
        return "邮箱格式不正确"
    if field in {"password", "newPassword"}:
        return "密码长度需为 6-64 个字符"
    return str(error.get("msg", "请求参数不合法"))


def _extract_http_error(ex: HTTPException) -> tuple[str, str]:
    if isinstance(ex.detail, str):
        code = ex.detail
        return code, translate_reason(code, ex.detail)
    if isinstance(ex.detail, dict):
        code = str(ex.detail.get("code", ex.status_code))
        message = str(ex.detail.get("message", translate_reason(code, None)))
        return code, message
    code = str(ex.status_code)
    return code, translate_reason(code, None)


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(_: Request, ex: RequestValidationError) -> JSONResponse:
        first_error = ex.errors()[0] if ex.errors() else {}
        message = _validation_error_message(first_error)
        logger.info("Validation failed: %s", message)
        return JSONResponse(status_code=400, content=api_fail("VALIDATION_ERROR", message))

    @app.exception_handler(ValidationError)
    async def handle_model_validation(_: Request, ex: ValidationError) -> JSONResponse:
        logger.info("Validation failed: %s", ex)
        return JSONResponse(status_code=400, content=api_fail("VALIDATION_ERROR", "请求参数不合法"))

    @app.exception_handler(BizException)
    async def handle_biz(_: Request, ex: BizException) -> JSONResponse:
        logger.info("Business constraint [%s]: %s", ex.code, ex.message)
        return JSONResponse(status_code=ex.status_code, content=api_fail(ex.code, ex.message))

    @app.exception_handler(HTTPException)
    async def handle_http(_: Request, ex: HTTPException) -> JSONResponse:
        code, message = _extract_http_error(ex)
        if ex.status_code >= 500:
            logger.exception("HTTP exception [%s]", code)
        else:
            logger.info("HTTP exception [%s]: %s", code, message)
        return JSONResponse(status_code=ex.status_code, content=api_fail(code, message))

    @app.exception_handler(Exception)
    async def handle_exception(_: Request, ex: Exception) -> JSONResponse:
        logger.exception("Unexpected error", exc_info=ex)
        return JSONResponse(
            status_code=500,
            content=api_fail("SERVER_ERROR", "系统繁忙，请稍后再试"),
        )
