"""Zero-dependency local web server (Python standard library only).

Binds to 127.0.0.1 by default, serves the single-page UI from ./web, and exposes a small JSON API.
No third-party packages, CDNs or outbound calls are used, so it runs inside air-gapped client networks.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from . import __version__
from .detect import LANG_NAMES
from .engine import analyze, explain, render_file
from .exporters import annotated_name, json_export, markdown_doc, project_zip, system_map
from .llm import LLMConfigError, LocalLLM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
SAMPLES = os.path.join(ROOT, "samples")
LOGS = os.path.join(ROOT, "logs")
MAX_BODY = 12 * 1024 * 1024
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")


def audit(action: str, **fields) -> None:
    """Append a metadata-only audit record. Source code is never logged, only a short hash."""
    if os.environ.get("LCC_AUDIT", "1") == "0":
        return
    os.makedirs(LOGS, exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "action": action, **fields}
    with open(os.path.join(LOGS, "audit.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


class Handler(BaseHTTPRequestHandler):
    server_version = "LegacyCodeCommenter/" + __version__

    def log_message(self, fmt, *args):  # keep the console quiet and free of request bodies
        if os.environ.get("LCC_VERBOSE"):
            super().log_message(fmt, *args)

    # ------------------------------------------------------------ helpers
    def _headers(self, status: int, ctype: str, length: int, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def _json(self, obj, status: int = 200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _error(self, status: int, msg: str):
        self._json({"error": msg}, status)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError(f"Request too large ({n // 1024} KB; limit {MAX_BODY // 1024 // 1024} MB)")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _same_origin(self) -> bool:
        # Block cross-site form/JS posts from other pages open in the browser.
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("Host", "")
        return urlparse(origin).netloc == host

    # ------------------------------------------------------------ GET
    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/api/config":
                return self._json(self._config())
            if path == "/api/samples":
                files = sorted(f for f in os.listdir(SAMPLES) if not f.startswith(".")) if os.path.isdir(SAMPLES) else []
                return self._json({"samples": files})
            if path.startswith("/api/samples/"):
                name = os.path.basename(path[len("/api/samples/"):])
                full = os.path.join(SAMPLES, name)
                if not os.path.isfile(full):
                    return self._error(404, "No such sample")
                with open(full, encoding="utf-8", newline="") as f:
                    return self._json({"filename": name, "content": f.read()})
            if path.startswith("/api/"):
                return self._error(404, "Unknown endpoint")
            return self._static(path)
        except Exception as e:  # pragma: no cover - defensive
            traceback.print_exc()
            return self._error(500, f"{type(e).__name__}: {e}")

    def _static(self, path: str):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.realpath(os.path.join(WEB, rel))
        if not full.startswith(os.path.realpath(WEB) + os.sep) or not os.path.isfile(full):
            return self._error(404, "Not found")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            data = f.read()
        self._headers(200, ctype, len(data))
        self.wfile.write(data)

    def _config(self) -> dict:
        try:
            llm = self.server.llm or LocalLLM()
            self.server.llm = llm
            status = llm.status()
        except LLMConfigError as e:
            status = {"available": False, "reason": str(e)}
        return {"version": __version__, "languages": LANG_NAMES, "llm": status,
                "max_upload_mb": MAX_BODY // 1024 // 1024, "audit": os.environ.get("LCC_AUDIT", "1") != "0",
                "bind": self.server.server_address[0]}

    # ------------------------------------------------------------ POST
    def do_POST(self):
        path = urlparse(self.path).path
        if not self._same_origin():
            return self._error(403, "Cross-origin request refused")
        try:
            data = self._body()
        except (ValueError, json.JSONDecodeError) as e:
            return self._error(400, str(e))
        try:
            if path == "/api/analyze":
                content = data.get("content", "")
                filename = os.path.basename(data.get("filename") or "upload.txt")
                res = analyze(content, filename, data.get("language") or None,
                              use_llm=bool(data.get("use_llm")), mask=data.get("mask", True) is not False,
                              llm=self.server.llm, library=data.get("library") or None)
                audit("analyze", sha=digest(content), language=res["language"], lines=res["line_count"],
                      annotations=len(res["annotations"]), llm=res["llm"].get("used", False))
                return self._json(res)
            if path == "/api/render":
                text, metrics = render_file(data["file"], data.get("tag") or "AI", data.get("ascii", True) is not False)
                return self._json({"text": text, "metrics": metrics})
            if path == "/api/export":
                f = data["file"]
                fmt = data.get("format", "annotated")
                if fmt == "annotated":
                    text, _ = render_file(f, data.get("tag") or "AI", data.get("ascii", True) is not False)
                    out = {"filename": annotated_name(f["filename"]), "content": text, "mime": "text/plain"}
                elif fmt == "markdown":
                    out = {"filename": os.path.splitext(f["filename"])[0] + ".md", "content": markdown_doc(f), "mime": "text/markdown"}
                elif fmt == "json":
                    out = {"filename": os.path.splitext(f["filename"])[0] + ".analysis.json", "content": json_export(f), "mime": "application/json"}
                else:
                    return self._error(400, f"Unknown format {fmt}")
                audit("export", sha=digest(f.get("content", "")), format=fmt)
                return self._json(out)
            if path == "/api/export-zip":
                files = data.get("files") or []
                blob = project_zip(files, data.get("tag") or "AI")
                audit("export-zip", files=len(files))
                self._headers(200, "application/zip", len(blob),
                              {"Content-Disposition": 'attachment; filename="legacy-docs.zip"'})
                self.wfile.write(blob)
                return
            if path == "/api/system-map":
                return self._json(system_map(data.get("files") or []))
            if path == "/api/explain":
                res = explain(data.get("content", ""), os.path.basename(data.get("filename") or "upload.txt"),
                              data.get("language"), int(data.get("start", 1)), int(data.get("end", 1)),
                              use_llm=bool(data.get("use_llm")), mask=data.get("mask", True) is not False,
                              llm=self.server.llm)
                audit("explain", sha=digest(data.get("content", "")), llm=res["source"] == "llm")
                return self._json(res)
            return self._error(404, "Unknown endpoint")
        except KeyError as e:
            return self._error(400, f"Missing field {e}")
        except Exception as e:
            traceback.print_exc()
            return self._error(500, f"{type(e).__name__}: {e}")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    llm: LocalLLM | None = None


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"WARNING: binding to {host} exposes uploaded source code to the network. "
              "Only do this inside an approved client environment.")
    httpd = Server((host, port), Handler)
    try:
        httpd.llm = LocalLLM()
    except LLMConfigError as e:
        print(f"LLM disabled: {e}")
    url = f"http://{'localhost' if host in ('127.0.0.1', '::1') else host}:{port}/"
    print(f"Legacy Code Commenter {__version__} running at {url}  (Ctrl+C to stop)")
    print("Offline mode: no data leaves this machine unless you enable a local LLM endpoint.")
    if open_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
