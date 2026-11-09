"""本地 HTTP 服务：给浏览器界面提供只读注册表 API。

安全边界：
  * 默认只绑定 127.0.0.1，显式拒绝非本地 host / 非本地 Origin（防 DNS rebinding / CSRF）；
  * 每次 API 请求都要带一次性 token，token 只出现在启动时打印的 URL 里；
  * 后端不含任何注册表写入调用，导出与收藏只写普通文件。
"""

from __future__ import annotations

import hmac
import json
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from . import __version__
from .bookmarks import BookmarkStore
from .export import FORMATS, build_export
from .paths import PathError, normalize_path
from .registry import Registry, RegistryError
from .search import VALID_SCOPES, search

STATIC_DIR = Path(__file__).resolve().parent / "web"
MIME = {
    "/": "text/html; charset=utf-8",
    "/index.html": "text/html; charset=utf-8",
    "/app.js": "application/javascript; charset=utf-8",
    "/style.css": "text/css; charset=utf-8",
    "/favicon.svg": "image/svg+xml",
}
MAX_BODY = 64 * 1024
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; "
       "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
       "form-action 'none'; frame-ancestors 'none'")


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class RegviewHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, context):
        self.context = context
        super().__init__(address, handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "regview/" + __version__
    protocol_version = "HTTP/1.1"

    # ---------- 基础响应 ----------

    def _send(self, status: int, body: bytes, content_type: str,
              extra: Optional[Dict[str, str]] = None, binary: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _fail(self, message: str, status: int = 400) -> None:
        self._json({"error": {"message": message, "status": status}}, status)

    def log_message(self, fmt: str, *args: Any) -> None:
        if not self.server.context.quiet:  # type: ignore[attr-defined]
            sys.stderr.write("[regview] " + (fmt % args) + "\n")

    # ---------- 安全校验 ----------

    def _local_host(self, value: str) -> bool:
        if not value:
            return False
        parsed = urlparse(value if "://" in value else "//" + value)
        host = (parsed.hostname or "").lower()
        port = parsed.port or self.server.server_port  # type: ignore[attr-defined]
        return host in ("127.0.0.1", "localhost", "::1") and port == self.server.server_port  # type: ignore[attr-defined]

    def _guard(self, need_token: bool = True) -> None:
        if not self._local_host(self.headers.get("Host", "")):
            raise ServiceError("只允许从 127.0.0.1 访问", 403)
        origin = self.headers.get("Origin", "").strip()
        if origin and not self._local_host(origin):
            raise ServiceError("拒绝跨站请求", 403)
        if need_token:
            supplied = (self.headers.get("X-Regview-Token", "")
                        or self._query().get("token", [""])[0])
            expected = self.server.context.token  # type: ignore[attr-defined]
            if not supplied or not hmac.compare_digest(supplied, expected):
                raise ServiceError("缺少或无效的 token，请使用启动命令输出的完整地址打开", 403)

    def _query(self) -> Dict[str, list]:
        return parse_qs(urlparse(self.path).query, keep_blank_values=True)

    def _arg(self, name: str, default: str = "") -> str:
        return self._query().get(name, [default])[0]

    def _int_arg(self, name: str, default: int, low: int, high: int) -> int:
        raw = self._arg(name, str(default))
        try:
            return max(low, min(high, int(raw)))
        except ValueError:
            return default

    # ---------- 业务对象 ----------

    def _registry(self):
        ctx = self.server.context  # type: ignore[attr-defined]
        if ctx.injected is not None:
            return ctx.injected
        view = self._arg("view", "default")
        with ctx.lock:
            if view not in ctx.registries:
                try:
                    ctx.registries[view] = Registry(view)
                except RegistryError as exc:
                    raise ServiceError(exc.message, 503) from exc
        return ctx.registries[view]

    def _path(self) -> str:
        try:
            return normalize_path(self._arg("path", "HKEY_CURRENT_USER"))
        except PathError as exc:
            raise ServiceError(str(exc), 400) from exc

    def _body(self) -> Dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ServiceError("无效的 Content-Length", 400)
        if length <= 0 or length > MAX_BODY:
            raise ServiceError("请求体为空或过大", 400)
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ServiceError("请求体不是合法 JSON", 400) from exc
        if not isinstance(payload, dict):
            raise ServiceError("请求体必须是 JSON 对象", 400)
        return payload

    # ---------- 路由 ----------

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle()

    def do_GET(self) -> None:  # noqa: N802
        self._handle()

    def do_POST(self) -> None:  # noqa: N802
        self._handle()

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle()

    def _handle(self) -> None:
        path = urlparse(self.path).path
        try:
            if path in MIME and self.command in ("GET", "HEAD"):
                self._serve_static(path)
                return
            if not path.startswith("/api/"):
                raise ServiceError("未找到：%s" % path, 404)
            self._guard()
            self._api(path)
        except ServiceError as exc:
            self._fail(exc.message, exc.status)
        except RegistryError as exc:
            self._fail(exc.message, 404)
        except KeyError as exc:
            self._fail("未找到：%s" % exc.args[0], 404)
        except (ValueError, PathError) as exc:
            self._fail(str(exc), 400)
        except BrokenPipeError:
            pass
        except Exception as exc:  # 不把内部堆栈回显给浏览器
            sys.stderr.write("[regview] internal error: %r\n" % (exc,))
            self._fail("服务器内部错误：%s" % type(exc).__name__, 500)

    def _serve_static(self, path: str) -> None:
        # 静态资源不含注册表数据，但仍校验 host/origin，防 DNS rebinding
        self._guard(need_token=(path in ("/", "/index.html")))
        target = STATIC_DIR / ("index.html" if path in ("/", "/index.html") else path.lstrip("/"))
        try:
            body = target.read_bytes()
        except OSError as exc:
            raise ServiceError("静态资源缺失：%s" % exc, 404) from exc
        self._send(200, body, MIME.get(path, "application/octet-stream"))

    def _api(self, path: str) -> None:
        method = self.command
        ctx = self.server.context  # type: ignore[attr-defined]

        if path == "/api/health":
            self._json({
                "ok": True, "version": __version__, "readonly": True,
                "platform": sys.platform, "formats": list(FORMATS),
                "scopes": list(VALID_SCOPES),
            })
        elif path == "/api/roots":
            self._json({"roots": self._registry().roots(), "default": "HKEY_CURRENT_USER"})
        elif path == "/api/node":
            self._json(self._registry().node(self._path()))
        elif path == "/api/children":
            self._json(self._registry().children(self._path()))
        elif path == "/api/value":
            self._json(self._registry().value_detail(self._path(), self._arg("name")))
        elif path == "/api/search":
            query = self._arg("q").strip()
            if not query:
                raise ServiceError("搜索关键字不能为空", 400)
            scope = self._arg("scope", "both")
            if scope not in VALID_SCOPES:
                raise ServiceError("未知搜索范围 %r" % scope, 400)
            try:
                root = normalize_path(self._arg("root", "HKEY_CURRENT_USER"))
            except PathError as exc:
                raise ServiceError(str(exc), 400) from exc
            self._json(search(
                self._registry(), query, root, scope=scope,
                limit=self._int_arg("limit", 200, 1, 500),
                max_keys=self._int_arg("max_keys", 5000, 100, 20000),
                time_limit=float(self._int_arg("seconds", 6, 1, 20)),
            ))
        elif path == "/api/export":
            fmt = self._arg("format", "reg")
            if fmt not in FORMATS:
                raise ServiceError("未知导出格式 %r" % fmt, 400)
            result = build_export(
                self._registry(), self._path(), fmt,
                max_keys=self._int_arg("max_keys", 2000, 10, 10000),
            )
            body = result["text"].encode(result["encoding"])
            self._send(200, body, result["content_type"], {
                "Content-Disposition": 'attachment; filename="%s"' % result["filename"],
                "X-Regview-Stats": json.dumps(result["stats"], ensure_ascii=False),
            }, binary=True)
        elif path == "/api/bookmarks":
            if method == "GET":
                self._json({"bookmarks": ctx.bookmarks.list()})
            elif method == "POST":
                payload = self._body()
                try:
                    items = ctx.bookmarks.add(str(payload.get("path", "")))
                except PathError as exc:
                    raise ServiceError(str(exc), 400) from exc
                self._json({"bookmarks": items})
            elif method == "DELETE":
                payload = self._body()
                try:
                    items = ctx.bookmarks.remove(str(payload.get("path", "")))
                except PathError as exc:
                    raise ServiceError(str(exc), 400) from exc
                self._json({"bookmarks": items})
            else:
                raise ServiceError("不支持的方法", 405)
        else:
            raise ServiceError("未知 API：%s" % path, 404)


def create_server(
    host: str = "127.0.0.1",
    port: int = 0,
    token: str = "",
    registry=None,
    home=None,
    quiet: bool = False,
) -> RegviewHTTPServer:
    """创建（但不启动）本地服务。返回带 ``.url`` 与 ``.token`` 的 server 对象。"""
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("出于安全考虑只允许绑定本地回环地址")
    auth_token = token or secrets.token_urlsafe(24)
    context = SimpleNamespace(
        token=auth_token,
        injected=registry,
        registries={},
        lock=threading.Lock(),
        bookmarks=BookmarkStore(home),
        quiet=quiet,
    )
    server = RegviewHTTPServer((host, port), Handler, context)
    server.token = auth_token  # type: ignore[attr-defined]
    server.url = "http://%s:%d/?token=%s" % (host, server.server_port, auth_token)  # type: ignore[attr-defined]
    return server
