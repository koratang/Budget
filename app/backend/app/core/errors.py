"""统一错误格式：HTTP 4xx + {"code": 英文代码, "message": 中文提示, "details": {...}}。"""
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    status_code = 400
    code = "bad_request"
    message = "请求不合法"

    def __init__(self, message: str | None = None, *, code: str | None = None,
                 details: dict[str, Any] | None = None, status_code: int | None = None):
        self.message = message or self.message
        self.code = code or self.code
        self.details = details or {}
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.message)

    def body(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class Unauthenticated(AppError):
    status_code = 401
    code = "unauthenticated"
    message = "请先登录"


class Forbidden(AppError):
    """越权：message 固定「无权限」，不带任何记录字段（AC-F01-11、NFR-003）。"""
    status_code = 403
    code = "forbidden"
    message = "无权限"

    def __init__(self) -> None:
        super().__init__()

    def body(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


class NotFound(AppError):
    status_code = 404
    code = "not_found"
    message = "记录不存在"


class Conflict(AppError):
    status_code = 409
    code = "conflict"
    message = "数据冲突"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_error"
    message = "提交的数据不合法"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(exc.body(), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        errors = [
            {"loc": [str(x) for x in e.get("loc", ())], "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return JSONResponse(
            {"code": "validation_error", "message": "提交的数据不合法", "details": {"errors": errors}},
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        mapping = {404: ("not_found", "接口不存在"), 405: ("method_not_allowed", "请求方法不支持"),
                   401: ("unauthenticated", "请先登录"), 403: ("forbidden", "无权限")}
        code, message = mapping.get(exc.status_code, ("http_error", str(exc.detail)))
        return JSONResponse({"code": code, "message": message, "details": {}}, status_code=exc.status_code)
