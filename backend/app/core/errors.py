"""统一错误响应（需求规格 5.6）。"""
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ClinicOSError(Exception):
    """业务错误。code 使用大写蛇形；retryable 供调用方判断是否可重试。"""

    def __init__(
        self,
        code: str,
        message: str,
        details: Any = None,
        retryable: bool = False,
        status_code: int = 400,
    ):
        self.code = code
        self.message = message
        self.details = details
        self.retryable = retryable
        self.status_code = status_code
        super().__init__(message)


def error_body(code: str, message: str, details: Any, retryable: bool, request: Request) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "retryable": retryable,
            "request_id": getattr(request.state, "request_id", None),
        }
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ClinicOSError)
    async def clinic_error_handler(request: Request, exc: ClinicOSError):
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.details, exc.retryable, request),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=error_body(
                "INVALID_ARGUMENT",
                "请求参数校验失败",
                exc.errors(),
                retryable=False,
                request=request,
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content=error_body(
                "INTERNAL_ERROR",
                "服务器内部错误",
                None,
                retryable=True,
                request=request,
            ),
        )