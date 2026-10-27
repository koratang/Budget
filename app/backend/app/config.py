"""应用配置（pydantic-settings，读取环境变量与 .env）。

DEC-013：APP_ENV=prod 时开启 DEV_IDENTITY_SWITCH、或钉钉四项凭据缺失，进程拒绝启动。
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent

OFFICIAL_DINGTALK_API = "https://api.dingtalk.com"
OFFICIAL_DINGTALK_OAPI = "https://oapi.dingtalk.com"
OFFICIAL_DINGTALK_LOGIN = "https://login.dingtalk.com"


class ConfigError(RuntimeError):
    """配置不合法，进程应拒绝启动。"""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    APP_ENV: Literal["dev", "test", "prod"] = "dev"
    DATABASE_URL: str = "postgresql+psycopg://budget:budget@127.0.0.1:5432/budget"
    DEV_IDENTITY_SWITCH: bool = False
    DATA_DIR: Path = BACKEND_DIR / "data"
    # 系统对外链接（钉钉通知中的系统链接、扫码回调地址）
    APP_BASE_URL: str = "http://localhost:8000"

    SESSION_IDLE_HOURS: int = 8
    COOKIE_SECURE: bool = False
    SCHEDULER_ENABLED: bool = True
    BOOTSTRAP_FINANCE_HEAD_USERID: str | None = None

    # 钉钉：基地址默认官方域名；本地替身时设为 http://127.0.0.1:8090（三者均可只设 DINGTALK_BASE_URL）
    DINGTALK_BASE_URL: str = OFFICIAL_DINGTALK_API
    DINGTALK_OAPI_BASE_URL: str | None = None
    DINGTALK_LOGIN_BASE_URL: str | None = None
    DINGTALK_APP_KEY: str | None = None
    DINGTALK_APP_SECRET: str | None = None
    DINGTALK_AGENT_ID: str | None = None
    DINGTALK_CORP_ID: str | None = None

    @model_validator(mode="after")
    def _check_prod(self) -> "Settings":
        if self.APP_ENV == "prod":
            if self.DEV_IDENTITY_SWITCH:
                raise ValueError("生产配置（APP_ENV=prod）禁止开启 DEV_IDENTITY_SWITCH，拒绝启动")
            missing = [
                k for k in ("DINGTALK_APP_KEY", "DINGTALK_APP_SECRET", "DINGTALK_AGENT_ID", "DINGTALK_CORP_ID")
                if not getattr(self, k)
            ]
            if missing:
                raise ValueError(f"生产配置缺少钉钉凭据：{', '.join(missing)}，拒绝启动")
        return self

    @property
    def dev_identity_enabled(self) -> bool:
        return self.APP_ENV == "dev" and self.DEV_IDENTITY_SWITCH

    @property
    def _is_official_api(self) -> bool:
        return self.DINGTALK_BASE_URL.rstrip("/") == OFFICIAL_DINGTALK_API

    @property
    def dingtalk_api_url(self) -> str:
        return self.DINGTALK_BASE_URL.rstrip("/")

    @property
    def dingtalk_oapi_url(self) -> str:
        if self.DINGTALK_OAPI_BASE_URL:
            return self.DINGTALK_OAPI_BASE_URL.rstrip("/")
        return OFFICIAL_DINGTALK_OAPI if self._is_official_api else self.dingtalk_api_url

    @property
    def dingtalk_login_url(self) -> str:
        if self.DINGTALK_LOGIN_BASE_URL:
            return self.DINGTALK_LOGIN_BASE_URL.rstrip("/")
        return OFFICIAL_DINGTALK_LOGIN if self._is_official_api else self.dingtalk_api_url

    @property
    def dingtalk_allowed_hosts(self) -> frozenset[str]:
        """出站 HTTP 白名单：只允许配置的钉钉服务端地址（NFR-005）。"""
        return frozenset(urlsplit(u).netloc for u in (self.dingtalk_api_url, self.dingtalk_oapi_url))


def load_settings(**overrides) -> Settings:
    """构造配置；不合法时抛 ConfigError（启动失败）。"""
    try:
        return Settings(**overrides)
    except ValueError as e:  # pydantic ValidationError 是 ValueError 子类
        raise ConfigError(str(e)) from e


@lru_cache
def get_settings() -> Settings:
    return load_settings()
