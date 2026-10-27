"""RULE-04 财务数据不外发（NFR-005、AC-F11-04、AC-F03-01、REQ-F11-02；DEC-011）。期望值逐字取自 TDD验收契约.md：

出站目标只有 api.dingtalk.com 与 oapi.dingtalk.com（本机为其替身）；全部已发送通知正文不含金额、千分位数字或「¥」；
构造器收到金额参数时抛错；请求其他主机直接抛错；代码与依赖中不存在对外部大模型服务的调用。

出站抓取：以子进程运行 SMOKE-03、FLOW-09、FLOW-18、FLOW-29、FLOW-30 的验收测试（真实路由 + PostgreSQL，钉钉为本地替身），
由 tests/acceptance/e4_netlog.py 在套接字层与钉钉网关层全程记录。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from decimal import Decimal
from importlib import metadata
from pathlib import Path

import httpx
import pytest

from app.config import load_settings
from app.dingtalk.gateway import DingTalkClient, HostNotAllowed
from app.dingtalk.outbox import NoticeContentError, build_notice

# 使用 E4 专用应用库 budget_acc4（真实提交 / 子进程重建库）：只在 E4 环境显式运行，避免其他执行者的全量 pytest 改动该库
E4_LIVE = pytest.mark.skipif(os.environ.get("E4_LIVE") != "1", reason="E4 专用：设置 E4_LIVE=1 运行")
BACKEND = Path(__file__).resolve().parents[2]
FRONTEND = BACKEND.parent / "frontend"
ACC4_TEST_URL = "postgresql+psycopg://budget:budget@127.0.0.1:5432/budget_acc4"
STUB_HOST = "dingtalk-stub.local"   # tests/conftest.py 中钉钉替身的主机名（api / oapi 均指向它）

AMOUNT_IN_TEXT = [re.compile(r"[¥￥$€£]"), re.compile(r"\d{1,3}(,\d{3})+"), re.compile(r"\d+\.\d+"),
                  re.compile(r"(?<![\d-])\d{5,}(?![\d-])"), re.compile(r"\d\s*元")]


# ---------------------------------------------------------------------------
# 构造器与出站客户端
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("field,value", [
    ("name", Decimal("128000.00")), ("object_name", Decimal("0.334")), ("period", 554400),
    ("name", 1.5), ("object_name", "收入 ¥ 554,400.00"), ("name", "毛利 196853.76"), ("period", "预算 12000 元"),
])
def test_rule_04_notice_builder_rejects_amounts(field, value):
    kw = dict(title="【预警】", name="收入达成率低于 70%", object_name="TikTok-US-01", period="2027-04",
              link="http://127.0.0.1:8014/alerts")
    kw[field] = value
    with pytest.raises(NoticeContentError):
        build_notice(**kw)


def test_rule_04_outbound_client_only_dingtalk_hosts():
    official = load_settings(APP_ENV="dev", DINGTALK_APP_KEY="k", DINGTALK_APP_SECRET="s", DINGTALK_AGENT_ID="1",
                             DINGTALK_CORP_ID="c")
    assert official.dingtalk_allowed_hosts == frozenset({"api.dingtalk.com", "oapi.dingtalk.com"})
    called = []

    def handler(request):  # 白名单之后的内层传输：记录真正放行的请求
        called.append(request.url.host)
        return httpx.Response(200, json={"errcode": 0})

    client = DingTalkClient(official, transport=httpx.MockTransport(handler))
    for url in ("https://api.openai.com/v1/chat/completions", "https://example.com/upload",
                "https://dingtalk.com.evil.cn/x", "http://127.0.0.1:9000/"):
        with pytest.raises(HostNotAllowed):
            client._http.post(url, json={"revenue": "554400.00"})
    assert called == []
    client._http.get("https://oapi.dingtalk.com/gettoken")
    client._http.get("https://api.dingtalk.com/v1.0/oauth2/accessToken")
    assert called == ["oapi.dingtalk.com", "api.dingtalk.com"]
    client.close()


LLM = re.compile(r"openai|anthropic|claude|dashscope|qianfan|zhipu|moonshot|deepseek|ernie|baichuan|hunyuan|"
                 r"spark-api|langchain|llama|gemini|generativelanguage|chatgpt|tongyi|wenxin", re.I)


def test_rule_04_no_llm_service_in_code_or_dependencies():
    code = [p for p in (BACKEND / "app").rglob("*.py")] + [p for p in (FRONTEND / "src").rglob("*") if p.is_file()]
    hits = [str(p) for p in code if LLM.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert hits == []
    assert not LLM.search((BACKEND / "requirements.txt").read_text(encoding="utf-8"))
    installed = sorted(d.metadata["Name"] for d in metadata.distributions())
    assert [n for n in installed if LLM.search(n)] == []
    pkg = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    lock = json.loads((FRONTEND / "package-lock.json").read_text(encoding="utf-8"))
    all_pkgs = list(deps) + [k.split("node_modules/")[-1] for k in lock.get("packages", {})]
    assert [n for n in all_pkgs if LLM.search(n)] == []


# ---------------------------------------------------------------------------
# 全程出站抓取
# ---------------------------------------------------------------------------
def _flow_files() -> list[str]:
    out = []
    for name, fallback in (("test_smoke_03.py", "tests/g2/test_smoke_03.py"),
                           ("test_flow_09.py", "tests/g2/test_flow_09.py"),
                           ("test_flow_18.py", "tests/g2/test_flow_18.py"),
                           ("test_flow_29.py", "tests/g3/test_flow_29.py"),
                           ("test_flow_30.py", "tests/g3/test_flow_30.py")):
        acc = BACKEND / "tests" / "acceptance" / name
        out.append(str(acc.relative_to(BACKEND)) if acc.exists() else fallback)
    return out


@E4_LIVE
def test_rule_04_flows_outbound_only_dingtalk_and_no_amounts(tmp_path):
    log, trace = tmp_path / "netlog.jsonl", tmp_path / "strace.txt"
    files = _flow_files()
    env = {**os.environ, "E4_NETLOG": str(log), "TEST_DATABASE_URL": ACC4_TEST_URL}
    # 系统调用层：strace 记录子进程（含 libpq 等 C 扩展）的每一次 connect()
    proc = subprocess.run(["strace", "-f", "-qq", "-e", "trace=connect", "-o", str(trace),
                           sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p",
                           "tests.acceptance.e4_netlog", *files], cwd=BACKEND, env=env, capture_output=True,
                          text=True, timeout=1800)
    summary = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else proc.stderr[-500:]
    print(f"\nRULE-04 子进程：{' '.join(files)} → exit={proc.returncode}; {summary}")
    assert proc.returncode == 0, proc.stdout[-3000:]
    recs = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    http = [r for r in recs if r["layer"] == "http"]
    sock = [r for r in recs if r["layer"] == "socket"]

    # 出站 HTTP 目标只有钉钉（本机替身）
    hosts = sorted({r["host"] for r in http})
    assert hosts == [STUB_HOST], hosts
    # 套接字层：除本机 PostgreSQL 外没有任何连接
    targets = sorted({tuple(r["address"]) if isinstance(r["address"], list) else (r["address"],)
                      for r in sock if r["event"] == "connect"})
    assert all(t[0] in ("127.0.0.1", "::1") and t[1] == 5432 or str(t[0]).startswith("/") for t in targets), targets
    lookups = sorted({r["host"] for r in sock if r["event"] == "getaddrinfo"})
    assert set(lookups) <= {"127.0.0.1", "localhost"}, lookups

    # 系统调用层：全部 IPv4 / IPv6 connect() 目标只有本机 PostgreSQL（钉钉替身在进程内，无外部连接）
    inet = sorted(set(re.findall(r"sin6?_port=htons\((\d+)\), (?:sin_addr=inet_addr|inet_pton\(AF_INET6, )"
                                 r"\(?\"([^\"]+)\"", trace.read_text(encoding="utf-8"))))
    assert inet and all(addr in ("127.0.0.1", "::1") and port == "5432" for port, addr in inet), inet

    # 全部已发送通知正文不含金额、千分位数字或「¥」
    notices = [json.loads(r["body"]) for r in http if "asyncsend" in r["url"]]
    assert len(notices) >= 5
    bad = []
    for n in notices:
        link = n["msg"]["link"]
        for part in (link["title"], link["text"]):
            if any(p.search(part) for p in AMOUNT_IN_TEXT):
                bad.append(part)
    assert bad == [], bad
    print(f"RULE-04 观测：HTTP 请求 {len(http)} 次，目标主机 {hosts}；套接字连接目标 {targets}；"
          f"系统调用 connect 目标 {inet}；工作通知 {len(notices)} 条，含金额 0 条")
