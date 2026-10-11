"""Local review dashboard:  sales-pipeline ui   ->  http://127.0.0.1:8765

One prioritized to-do list. Each item shows a plan: Approve checks the thread
again for anything a colleague or the customer did, runs the routine steps
(tags, labels) and puts the emails in your Gmail drafts. Sales Desk never
sends: you read each draft in Gmail and press Send there."""
from __future__ import annotations

import json
import logging
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources

from .actions import Conflict, Executor
from .safety import UnsafeEmail, problems
from .pipeline import Pipeline
from .store import Record, Store
from .tasks import action_label, level

log = logging.getLogger(__name__)

VIEWS = {
    "todo": ["needs_review", "ready", "failed", "approved"],
    "upcoming": ["scheduled"],
    "send": ["awaiting_send"],      # drafts waiting in Gmail for you to send
    "done": ["done", "pushed"],
    "skipped": ["skipped"],
}


def record_json(r: Record, s) -> dict:
    o, c = r.order, r.conv
    title = None
    if r.kind == "order" and o:
        title = o.customer.company or o.customer.contact_name or o.customer.email
    elif c:
        name = c.customer_name or (c.salutation or {}).get("name")
        title = " · ".join(x for x in (name, c.company) if x) or (c.customer_emails[0] if c.customer_emails else None)
    title = title or (o.customer.company or o.customer.email if o else None)
    plan = [dict(st, safety=problems(st["draft"], s)) if st.get("gated") and st.get("draft") else st
            for st in r.plan]
    return {
        "id": r.thread_id, "subject": r.subject, "url": r.thread_url, "status": r.status, "kind": r.kind,
        "priority": r.priority, "level": level(r.priority), "reasons": r.reasons, "issues": r.issues,
        "error": r.error, "zoho_id": r.zoho_id, "updated_at": r.updated_at, "due_at": r.due_at,
        "action": action_label(r.kind, c, s), "order": o.model_dump() if o else None, "plan": plan,
        "conv": c.model_dump(exclude={"last_inbound_text"}) if c else None, "title": title,
    }


class App:
    def __init__(self, settings, store: Store, pipeline: Pipeline, scanner=None, demo: bool = False):
        self.s, self.store, self.pipeline, self.demo = settings, store, pipeline, demo
        self.exec = Executor(settings, store, gmail=pipeline.gmail, zoho=pipeline.zoho, pipeline=pipeline)
        self.scanner = scanner
        self.lock = threading.RLock()            # one Gmail/Zoho action at a time
        self._scan_guard = threading.Lock()      # one scan at a time
        self.scanning = False
        self.last_scan: str | None = None
        try:
            pipeline.upgrade_plans()
        except Exception:
            log.exception("re-planning older items failed")

    def counts(self) -> dict:
        return {v: len(self.store.list(st)) for v, st in VIEWS.items()}

    def scan(self) -> dict:
        if not self._scan_guard.acquire(blocking=False):
            return {"already scanning": 1}
        self.scanning = True
        try:
            if self.scanner:
                result = self.scanner(lock=self.lock)
            else:
                with self.lock:
                    result = self.pipeline.promote_due()
            # Drafts you sent (or deleted) in Gmail since the last look.
            for k, v in self.exec.sync_all(lock=self.lock).items():
                result[k] = result.get(k, 0) + v
            self.last_scan = datetime.now(timezone.utc).isoformat(timespec="seconds")
            return result
        finally:
            self.scanning = False
            self._scan_guard.release()

    def _list(self, view: str) -> list[dict]:
        if view in ("todo", "upcoming") and self.lock.acquire(blocking=False):
            try:   # move follow-ups whose day has come into To decide (skipped while busy)
                self.pipeline.promote_due()
            finally:
                self.lock.release()
        recs = self.store.list(VIEWS.get(view, VIEWS["todo"]))
        if view == "upcoming":
            recs.sort(key=lambda r: r.due_at or "")
        return [record_json(r, self.s) for r in recs]

    def info(self) -> dict:
        return {"demo": self.demo, "zoho": self.pipeline.zoho is not None, "crm": self.pipeline.crm is not None,
                "gmail": self.pipeline.gmail is not None, "feed_dir": self.s.crm_feed_dir,
                "tags": self.pipeline.tags, "last_scan": self.last_scan, "scanning": self.scanning,
                "me": self.s.user_email, "followup_days": self.s.followup_days}

    def handle(self, method: str, path: str, body: dict) -> tuple[int, dict]:
        parts = [p for p in path.split("?")[0].split("/") if p][1:]  # drop "api"
        query = dict(q.split("=", 1) for q in path.split("?", 1)[1].split("&") if "=" in q) if "?" in path else {}
        # Reading never waits for a scan; actions take turns with it, one thread at a time.
        if method == "GET" and parts == ["tasks"]:
            return 200, {"tasks": self._list(query.get("view", "todo")), "counts": self.counts(), **self.info()}
        if method == "GET" and parts == ["activity"]:
            return 200, {"activity": self.store.activity(limit=200), "counts": self.counts(), **self.info()}
        if method == "POST" and parts == ["crm-feed"]:
            from .feed import export

            res = export(self.pipeline, everything=bool(body.get("all")), lock=self.lock)
            return 200, {"feed": res, "counts": self.counts()}
        if method == "POST" and parts == ["scan"]:
            if not self.scanner:
                return 400, {"error": "Gmail is not connected" if not self.demo else
                             "The demo has no Gmail to scan"}
            return 200, {"result": self.scan(), "counts": self.counts()}
        with self.lock:
            if len(parts) == 3 and parts[0] == "tasks" and method == "POST":
                tid, action = parts[1], parts[2]
                ex = self.exec
                try:
                    if action == "approve":
                        rec = ex.approve(tid, body.get("order"), body.get("steps"), force=bool(body.get("force")))
                    elif action == "check":
                        rec = ex.sync(tid)
                    elif action == "demo_send" and self.demo:
                        # Demo only: stands in for you pressing Send in Gmail.
                        for st in self.store.get(tid).plan:
                            if st.get("state") == "drafted" and st.get("draft_id") in self.pipeline.gmail.drafts:
                                self.pipeline.gmail.send_draft(st["draft_id"])
                        rec = ex.sync(tid)
                    elif action == "discard":
                        rec = ex.discard(tid, body["step"])
                    elif action == "skip":
                        rec = ex.skip(tid)
                    elif action == "snooze":
                        rec = ex.snooze(tid, float(body.get("days", 1)), why="snoozed by you")
                    elif action == "outcome":
                        rec = ex.outcome(tid, body["outcome"])
                    elif action == "ignore":
                        rec = ex.ignore(tid)
                    elif action == "retry":
                        rec = ex.retry_crm(tid, body["step"])
                    else:
                        return 404, {"error": f"unknown action {action}"}
                except UnsafeEmail as e:
                    return 400, {"error": str(e)}
                except Conflict as c:
                    return 409, {"conflict": c.reasons, "task": record_json(self.store.get(tid), self.s),
                                 "counts": self.counts()}
                return 200, {"task": record_json(rec, self.s), "counts": self.counts()}
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
            except (KeyError, ValueError) as e:
                code, payload = 400, {"error": str(e).strip("'") or type(e).__name__}
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


def serve(app: App, port: int = 8765, scan_every_min: int = 0, open_browser: bool = True) -> None:
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    except OSError:
        raise SystemExit(f"Something is already running at http://127.0.0.1:{port} (probably another Sales Desk "
                         "window, e.g. the demo). Close that black window first, or add --port 8770.")
    url = f"http://127.0.0.1:{port}"
    if app.scanner:
        def loop():   # first scan right away, then every few minutes while the page is open
            while True:
                try:
                    app.scan()
                except Exception:
                    log.exception("background scan failed")
                if not scan_every_min:
                    return
                time.sleep(scan_every_min * 60)
        threading.Thread(target=loop, daemon=True).start()
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    print(f"Sales Desk is running at {url}  ({'DEMO data' if app.demo else 'live'})")
    print("Keep this window open while you use it; close it (or press Ctrl+C) to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
