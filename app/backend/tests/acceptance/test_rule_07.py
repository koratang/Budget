"""RULE-07 开发身份模拟在生产不可用（REQ-F01-01、NFR-003；DEC-002、DEC-013）。期望值逐字取自 TDD验收契约.md：

生产配置下 /api/dev/login-as 返回 404、/api/auth/config 的开发开关为 false、登录页无身份切换区；开关为真或缺凭据时进程拒绝
启动并输出明确错误、退出码非 0；dev 来源会话被拒绝并在启动时清除；生产构建产物中不含「开发模式身份切换」文字与组件。

全部用真实启动命令：`uvicorn app.main:app`（产品入口，库 budget_acc4，端口 8014）；生产前端以 `npm run build` 构建到临时目录，
由同一产品入口托管（仅把 app.main.STATIC_DIR 指向该目录，不改动共享的 app/static）。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.config import load_settings
from app.main import create_app
from app.models import User, UserSession

BACKEND = Path(__file__).resolve().parents[2]
# 使用 E4 专用应用库 budget_acc4 与端口 8014：只在 E4 环境显式运行（E4_LIVE=1），避免其他执行者的全量 pytest 改动
pytestmark = pytest.mark.skipif(os.environ.get("E4_LIVE") != "1", reason="E4 专用：设置 E4_LIVE=1 运行")
FRONTEND = BACKEND.parent / "frontend"
UVICORN = str(BACKEND / ".venv" / "bin" / "uvicorn")
ACC4_URL = "postgresql+psycopg://budget:budget@127.0.0.1:5432/budget_acc4"
PORT = 8014
BASE = f"http://127.0.0.1:{PORT}"
CREDS = {"DINGTALK_APP_KEY": "prod-key", "DINGTALK_APP_SECRET": "prod-secret", "DINGTALK_AGENT_ID": "10001",
         "DINGTALK_CORP_ID": "ding-prod-corp"}
LAUNCH = ("import os, uvicorn; from pathlib import Path; import app.main as m; "
          "m.STATIC_DIR = Path(os.environ['E4_STATIC_DIR']); "
          f"uvicorn.run(m.app, host='127.0.0.1', port={PORT}, log_level='warning')")


def _env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DINGTALK_", "APP_ENV", "DEV_IDENTITY"))}
    env.update(DATABASE_URL=ACC4_URL, SCHEDULER_ENABLED="false", DINGTALK_BASE_URL="http://127.0.0.1:8024")
    env.update(extra)
    return env


def _port_free() -> bool:
    try:
        httpx.get(f"{BASE}/api/health", timeout=1)
        return False
    except httpx.TransportError:
        return True


@pytest.fixture(scope="module")
def prod_static(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("static-prod")
    r = subprocess.run(["npm", "run", "build", "--", "--outDir", str(out), "--emptyOutDir"], cwd=FRONTEND,
                       capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    return out


def test_rule_07_prod_build_has_no_dev_switch(prod_static, tmp_path):
    files = [p for p in prod_static.rglob("*") if p.is_file()]
    assert files and (prod_static / "index.html").exists()
    hits = [str(p) for p in files if re.search("开发模式身份切换|DevIdentitySwitch|dev-users|data-dev-switch",
                                               p.read_text(encoding="utf-8", errors="ignore"))]
    assert hits == []
    # 对照：开发构建产物含该文字与组件（证明检索有效）
    dev = tmp_path / "static-dev"
    r = subprocess.run(["npm", "run", "build:dev", "--", "--outDir", str(dev), "--emptyOutDir"], cwd=FRONTEND,
                       capture_output=True, text=True, timeout=900)
    assert r.returncode == 0
    assert any("开发模式身份切换" in p.read_text(encoding="utf-8", errors="ignore") for p in dev.rglob("*.js"))


@pytest.mark.parametrize("label,extra,message", [
    ("开关为真", {**CREDS, "APP_ENV": "prod", "DEV_IDENTITY_SWITCH": "true"},
     "生产配置（APP_ENV=prod）禁止开启 DEV_IDENTITY_SWITCH，拒绝启动"),
    *[(f"缺 {k}", {**{c: v for c, v in CREDS.items() if c != k}, "APP_ENV": "prod"},
       f"生产配置缺少钉钉凭据：{k}，拒绝启动") for k in CREDS],
])
def test_rule_07_prod_refuses_to_start(label, extra, message):
    assert _port_free(), f"端口 {PORT} 被占用，先停止开发配置后端"
    r = subprocess.run([UVICORN, "app.main:app", "--port", str(PORT)], cwd=BACKEND, env=_env(**extra),
                       capture_output=True, text=True, timeout=60)
    print(f"\nRULE-07 {label}: exit_code={r.returncode}; stderr 末行：{r.stderr.strip().splitlines()[-1]}")
    assert r.returncode != 0
    assert message in r.stderr
    assert _port_free()


def test_rule_07_prod_start_404_config_false_purges_dev_sessions(prod_static, dingtalk):
    assert _port_free(), f"端口 {PORT} 被占用，先停止开发配置后端"
    from tests.acceptance.e4_env import reset
    reset(url=ACC4_URL)
    # 开发库：以开发配置登录，产生 auth_source=dev 会话
    dev_app = create_app(load_settings(DATABASE_URL=ACC4_URL, APP_ENV="dev", DEV_IDENTITY_SWITCH=True,
                                       SCHEDULER_ENABLED=False, DINGTALK_BASE_URL="http://dingtalk-stub.local",
                                       **CREDS), dingtalk=dingtalk)
    eng = create_engine(ACC4_URL)
    with Session(eng) as s:
        lin = s.scalar(select(User.id).where(User.dingtalk_userid == "linxiao"))
    dev = TestClient(dev_app, base_url="http://127.0.0.1")
    assert dev.post("/api/dev/login-as", json={"user_id": lin}).status_code == 200
    cookie = dev.cookies.get("budget_session")
    assert cookie and dev.get("/api/me").status_code == 200

    def dev_sessions():
        with Session(eng) as s:
            return s.scalar(select(func.count()).select_from(UserSession).where(UserSession.auth_source == "dev"))
    assert dev_sessions() == 1

    # 同一库切换到生产配置真实启动
    proc = subprocess.Popen([sys.executable, "-c", LAUNCH], cwd=BACKEND,
                            env=_env(**CREDS, APP_ENV="prod", E4_STATIC_DIR=str(prod_static)),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(100):
            if not _port_free():
                break
            assert proc.poll() is None, proc.stderr.read()
            time.sleep(0.2)
        assert dev_sessions() == 0  # 启动时清除
        with httpx.Client(base_url=BASE) as c:
            assert c.post("/api/dev/login-as", json={"user_id": lin}).status_code == 404
            assert c.post("/api/auth/dev-login", json={"user_id": lin}).status_code == 404
            assert c.get("/api/auth/dev-users").status_code == 404
            cfg = c.get("/api/auth/config").json()
            assert cfg["dev_switch"] is False
            r = c.get("/api/me", cookies={"budget_session": cookie})
            assert r.status_code == 401
        # 登录页（生产构建）无身份切换区
        node = subprocess.run(["node", "e2e/rule_07.spec.mjs"], cwd=FRONTEND, env={**os.environ, "E4_BASE": BASE},
                              capture_output=True, text=True, timeout=120)
        print("\n" + node.stdout)
        assert node.returncode == 0, node.stdout + node.stderr
    finally:
        proc.terminate()
        proc.wait(timeout=30)
    eng.dispose()
