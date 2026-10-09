"""Local review dashboard:  sales-pipeline ui   ->  http://127.0.0.1:8765

One prioritized list. Each item shows a plan; Approve runs the routine steps and
turns customer-facing replies into Gmail drafts that wait for your Send."""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources

from .actions import Executor
from .store import Record, Store
from .tasks import level

log = logging.getLogger(__name__)

VIEWS = {
    "todo": ["needs_review", "ready", "failed", "approved"],
    "send": ["awaiting_send"],
    "done": ["done", "pushed"],
    "skipped": ["skipped"],
}


def record_json(r: Record) -> dict:
    o = r.order
    return {
        "id": r.thread_id, "subject": r.subject, "url": r.thread_url, "status": r.status, "kind": r.kind,
        "priority": r.priority, "level": level(r.priority), "reasons": r.reasons, "issues": r.issues,
        "error": r.error, "zoho_id": r.zoho_id, "waiting_since": r.waiting_since, "updated_at": r.updated_at,
        "order": o.model_dump() if o else None, "plan": r.plan,
        "title": (o.customer.company or o.customer.contact_name or o.customer.email) if o else None,
    }


class App:
    def __init__(self, settings, store: Store, gmail=None, zoho=None, scanner=None, demo=False):
        self.s, self.store, self.demo = settings, store, demo
        self.exec = Executor(settings, store, gmail=gmail, zoho=zoho)
        self.scanner = scanner
        self.lock = threading.Lock()

    def counts(self) -> dict:
        return {v: len(self.store.list(st)) for v, st in VIEWS.items()}

    def handle(self, method: str, path: str, body: dict) -> tuple[int, dict]:
        parts = [p for p in path.split("?")[0].split("/") if p][1:]  # drop "api"
        query = dict(q.split("=", 1) for q in path.split("?", 1)[1].split("&")) if "?" in path else {}
        with self.lock:
            if method == "GET" and parts == ["tasks"]:
                view = query.get("view", "todo")
                return 200, {"tasks": [record_json(r) for r in self.store.list(VIEWS.get(view, VIEWS["todo"]))],
                             "counts": self.counts(), "demo": self.demo}
            if method == "POST" and parts == ["scan"]:
                if not self.scanner:
                    return 400, {"error": "Gmail is not connected"}
                return 200, {"result": self.scanner(), "counts": self.counts()}
            if len(parts) == 3 and parts[0] == "tasks" and method == "POST":
                tid, action = parts[1], parts[2]
                if action == "approve":
                    rec = self.exec.approve(tid, body.get("order"), body.get("steps"))
                elif action == "send":
                    rec = self.exec.send(tid, body["step"], body.get("draft"))
                elif action == "discard":
                    rec = self.exec.discard(tid, body["step"])
                elif action == "skip":
                    rec = self.exec.skip(tid)
                else:
                    return 404, {"error": f"unknown action {action}"}
                return 200, {"task": record_json(rec), "counts": self.counts()}
        return 404, {"error": "not found"}


def make_handler(app: App):
    page = resources.files(__package__).joinpath("ui.html").read_text(encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            log.info(fmt, *args)

        def _send(self, code, payload, ctype="application/json"):
            data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _route(self, method):
            if not self.path.startswith("/api/"):
                return self._send(200, page.encode(), "text/html")
            body = {}
            if method == "POST":
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
            try:
                code, payload = app.handle(method, self.path, body)
            except (KeyError, ValueError, StopIteration) as e:
                code, payload = 400, {"error": str(e) or type(e).__name__}
            except Exception as e:  # surface, don't crash the server
                log.exception("request failed")
                code, payload = 500, {"error": str(e)}
            self._send(code, payload)

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            # Same-origin only: refuse requests from other websites.
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{self.headers.get('Host')}":
                return self._send(403, {"error": "cross-origin request refused"})
            self._route("POST")

    return Handler


def serve(app: App, port: int = 8765) -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    print(f"Dashboard: http://127.0.0.1:{port}  ({'DEMO data' if app.demo else 'live'}; Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
