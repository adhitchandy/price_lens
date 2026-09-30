"""A small local web server for the app (Python standard library only).

Serves the pages in ``static/`` and the JSON API in ``api.py``. It listens on 127.0.0.1 only.
Requests that change something must carry the ``X-PI-App`` header, which other websites
cannot add, and the Host header must be localhost (no DNS-rebinding tricks).
"""
from __future__ import annotations

import json
import mimetypes
import re
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlparse

from . import api

STATIC = Path(__file__).with_name("static")
MAX_BODY = 25 * 1024 * 1024
Route = tuple[str, re.Pattern, Callable[..., Any]]

ROUTES: list[Route] = []


def route(method: str, pattern: str):
    def register(func):
        ROUTES.append((method, re.compile(f"^{pattern}$"), func))
        return func
    return register


RUN = r"(?P<name>[A-Za-z0-9_\-]+)"
DRAFT = r"(?P<draft_id>[A-Za-z0-9_\-]+)"

route("GET", "/api/meta")(lambda q, b: api.meta())
route("GET", "/api/settings")(lambda q, b: api.settings())
route("PUT", "/api/settings")(lambda q, b: api.save_settings(b))
route("GET", "/api/researches")(lambda q, b: api.research_list())
route("GET", "/api/storefronts")(lambda q, b: api.storefront_health())
route("GET", "/api/cleanup")(lambda q, b: api.cleanup_candidates())
route("POST", "/api/cleanup")(lambda q, b: api.cleanup())
route("GET", "/api/fx")(lambda q, b: api.exchange_rates(q.get("refresh") == "1"))
route("PUT", r"/api/fx/(?P<code>[A-Za-z]{3})")(lambda q, b, code: api.set_exchange_rate(code, b))
route("DELETE", r"/api/fx/(?P<code>[A-Za-z]{3})")(lambda q, b, code: api.remove_exchange_rate(code))

route("GET", "/api/drafts")(lambda q, b: {"drafts": api.list_drafts()})
route("POST", "/api/drafts")(lambda q, b: api.create_draft(b))
route("GET", f"/api/drafts/{DRAFT}")(lambda q, b, draft_id: api.get_draft(draft_id))
route("PUT", f"/api/drafts/{DRAFT}")(lambda q, b, draft_id: api.save_draft(draft_id, b))
route("DELETE", f"/api/drafts/{DRAFT}")(lambda q, b, draft_id: api.delete_draft(draft_id))

route("POST", "/api/plan/validate")(lambda q, b: api.validate_plan(b.get("plan") or {}))
route("POST", "/api/plan/quick-setup")(lambda q, b: api.apply_quick_setup(b))
route("POST", "/api/plan/suggest-excludes")(lambda q, b: api.suggest_excludes(b))
route("POST", "/api/plan/prompt")(lambda q, b: api.planning_prompt(b))
route("POST", "/api/plan/import")(lambda q, b: api.import_plan(b))
route("POST", "/api/start")(lambda q, b: api.start(b))

route("GET", f"/api/runs/{RUN}")(lambda q, b, name: api.run_detail(name))
route("DELETE", f"/api/runs/{RUN}")(lambda q, b, name: api.delete_run(name))
route("GET", f"/api/runs/{RUN}/products")(lambda q, b, name: api.products(name, q.get("source")))
route("POST", f"/api/runs/{RUN}/export")(lambda q, b, name: api.export(name, b))
route("GET", f"/api/runs/{RUN}/files")(lambda q, b, name: api.raw_file(name, q.get("file", "")))
route("GET", f"/api/runs/{RUN}/live")(lambda q, b, name: api.live(name))
route("POST", f"/api/runs/{RUN}/cancel")(lambda q, b, name: api.cancel(name))
route("POST", f"/api/runs/{RUN}/force-stop")(lambda q, b, name: api.force_stop(name))
route("POST", f"/api/runs/{RUN}/pause")(lambda q, b, name: api.pause(name))
route("POST", f"/api/runs/{RUN}/resume")(lambda q, b, name: api.resume(name))
route("POST", f"/api/runs/{RUN}/retry")(lambda q, b, name: api.start_retry(name, b))
route("GET", f"/api/runs/{RUN}/fx")(lambda q, b, name: api.run_rates(name))
route("POST", f"/api/runs/{RUN}/fx")(lambda q, b, name: api.reprice_run(name, b))

route("GET", f"/api/runs/{RUN}/review")(lambda q, b, name: api.review_state(name))
route("POST", f"/api/runs/{RUN}/review/prepare")(lambda q, b, name: api.review_prepare(name, b))
route("GET", f"/api/runs/{RUN}/review/prompt")(lambda q, b, name: api.review_prompt(name, q.get("batch")))
route("POST", f"/api/runs/{RUN}/review/answer")(lambda q, b, name: api.review_answer(name, b))
route("POST", f"/api/runs/{RUN}/review/claude")(lambda q, b, name: api.review_with_claude(name))
route("POST", f"/api/runs/{RUN}/review/apply")(lambda q, b, name: api.review_apply(name))
route("POST", f"/api/runs/{RUN}/review/reset")(lambda q, b, name: api.review_reset(name))
route("POST", f"/api/runs/{RUN}/review/extend")(lambda q, b, name: api.review_extend(name))
route("GET", f"/api/runs/{RUN}/review/decisions")(lambda q, b, name: api.review_decisions(name))
route("POST", f"/api/runs/{RUN}/review/override")(lambda q, b, name: api.review_override(name, b))


class Handler(BaseHTTPRequestHandler):
    server_version = "ProductIntelligence"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # keep the console quiet
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    # ---- helpers -----------------------------------------------------------------------
    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False, default=str, allow_nan=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0].strip("[]").lower()
        return host in {"127.0.0.1", "localhost", "::1"}

    # ---- dispatch ----------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        if not self._host_ok():
            self._json(HTTPStatus.FORBIDDEN, {"error": "Open the app at http://127.0.0.1"})
            return
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            if method != "GET":
                self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Not allowed"})
            else:
                self._static(url.path)
            return
        if method != "GET" and self.headers.get("X-PI-App") != "1":
            self._json(HTTPStatus.FORBIDDEN, {"error": "Missing app header"})
            return
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        body: Any = {}
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "Request too large"})
            return
        if length:
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON"})
                return
        if not isinstance(body, dict):
            body = {}
        for route_method, pattern, func in ROUTES:
            match = pattern.match(url.path)
            if match and route_method == method:
                self._call(func, query, body, match.groupdict())
                return
        self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def _call(self, func, query: dict, body: dict, params: dict) -> None:
        try:
            result = func(query, body, **params)
        except api.ApiError as exc:
            self._json(exc.status, {"error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - never kill the server; show the error
            traceback.print_exc()
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{exc.__class__.__name__}: {exc}"})
            return
        if isinstance(result, api.FileResult):
            self._send(HTTPStatus.OK, result.data, result.mime, {
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(result.name)}"})
        else:
            self._json(HTTPStatus.OK, result)

    def _static(self, path: str) -> None:
        if path in {"", "/"} or not Path(path).suffix:
            path = "/index.html"  # the app routes with #/…, but serve the page for any path
        target = (STATIC / path.lstrip("/")).resolve()
        if STATIC.resolve() not in target.parents or not target.is_file():
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        # explicit types: the Windows registry sometimes maps .js/.css to text/plain
        mime = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml",
                ".json": "application/json"}.get(target.suffix) or mimetypes.guess_type(target.name)[0] \
            or "application/octet-stream"
        extra = {}
        if target.name == "index.html":
            extra["Content-Security-Policy"] = (
                "default-src 'self'; style-src 'self' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self._send(HTTPStatus.OK, target.read_bytes(), f"{mime}; charset=utf-8"
                   if mime.startswith("text/") else mime, extra)


def make_server(port: int = 8765, verbose: bool = False) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.verbose = verbose  # type: ignore[attr-defined]
    return server
