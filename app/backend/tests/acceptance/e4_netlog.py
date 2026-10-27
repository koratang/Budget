"""RULE-04 出站网络记录器：pytest 插件（-p tests.acceptance.e4_netlog）或在服务进程启动前导入。

记录两层，写入 E4_NETLOG 指定的 JSON Lines 文件：
- 套接字层：sys.addaudithook 捕获本进程每一次 socket.connect / socket.getaddrinfo（任何库、任何主机）；
- 应用出站 HTTP：钉钉网关 AllowlistTransport.handle_request 收到的每个请求（含被白名单拒绝的），
  工作通知请求记录完整正文。
"""
import json
import os
import sys
import threading

_PATH = os.environ.get("E4_NETLOG")
_lock = threading.Lock()


def _write(rec: dict) -> None:
    if not _PATH:
        return
    with _lock, open(_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")


def _hook(event: str, args) -> None:
    if event == "socket.connect":
        addr = args[1]
        _write({"layer": "socket", "event": "connect", "address": list(addr) if isinstance(addr, tuple) else addr})
    elif event == "socket.getaddrinfo":
        _write({"layer": "socket", "event": "getaddrinfo", "host": args[0], "port": args[1]})


def install() -> None:
    sys.addaudithook(_hook)
    from app.dingtalk import gateway

    orig = gateway.AllowlistTransport.handle_request

    def handle_request(self, request):
        body = request.content.decode("utf-8", "replace") if request.content else ""
        _write({"layer": "http", "method": request.method, "host": request.url.host, "url": str(request.url),
                "body": body if "asyncsend" in str(request.url) else ""})
        return orig(self, request)

    gateway.AllowlistTransport.handle_request = handle_request


def pytest_configure(config):  # pytest 插件入口
    install()
