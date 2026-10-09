"""Command line:  sales-pipeline <command>

  scan                 read new order emails from Gmail and extract them
  list [--status S]    show what has been found
  show ID              full extracted order + issues for one thread
  edit ID FILE         replace the extracted order with a corrected JSON file
  approve ID           mark a reviewed order ready to push
  skip ID              mark a thread as not an order
  push ID|--ready      create the Sales Order(s) in Zoho (--dry-run to preview)
  run                  scan, then push everything ready if AUTO_PUSH=true
  gmail-auth           one-time Gmail sign-in (opens a browser)
  zoho-auth CODE       one-time: trade a Zoho self-client grant code for a refresh token
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import Settings
from .models import Order
from .pipeline import Pipeline, validate
from .store import Store


def _gmail(s: Settings):
    from .gmail_source import GmailSource

    return GmailSource(s.gmail_credentials_file, s.gmail_token_file)


def _zoho(s: Settings):
    from .zoho import ZohoCRM

    return ZohoCRM(s.zoho_accounts_url, s.zoho_api_domain, s.zoho_client_id,
                   s.zoho_client_secret, s.zoho_refresh_token)


def _llm(s: Settings):
    if not s.use_llm:
        return None
    from .extract_llm import ClaudeExtractor

    return ClaudeExtractor(s.claude_model, s.internal_domains, s.anthropic_api_key)


def _resolve(store: Store, ident: str) -> str:
    """Accept a Gmail thread id or an order code."""
    if store.get(ident):
        return ident
    hits = [r for r in store.list() if r.order_code == ident]
    if len(hits) == 1:
        return hits[0].thread_id
    sys.exit(f"no single record matches {ident!r}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="sales-pipeline", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("scan")
    sc.add_argument("--query", help="Gmail search (default: GMAIL_QUERY)")
    sc.add_argument("--limit", type=int, default=50)
    sc.add_argument("--rescan", action="store_true", help="re-extract threads already seen")
    sc.add_argument("--no-llm", action="store_true", help="rule-based extraction only")

    ls = sub.add_parser("list")
    ls.add_argument("--status", choices=["needs_review", "ready", "pushed", "failed", "skipped"])

    for name in ("show", "approve", "skip"):
        sub.add_parser(name).add_argument("id")
    ed = sub.add_parser("edit")
    ed.add_argument("id")
    ed.add_argument("file", help="JSON file (start from `show ID --json > file`)")
    sub.choices["show"].add_argument("--json", action="store_true")

    pu = sub.add_parser("push")
    pu.add_argument("id", nargs="?")
    pu.add_argument("--ready", action="store_true", help="push every order marked ready")
    pu.add_argument("--dry-run", action="store_true", help="print the Zoho payload, change nothing")
    pu.add_argument("--force", action="store_true", help="push even if not approved")

    sub.add_parser("run")
    sub.add_parser("gmail-auth")
    za = sub.add_parser("zoho-auth")
    za.add_argument("code", help="grant code from https://api-console.zoho.com (Self Client)")

    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING,
                        format="%(levelname)s %(message)s")
    s = Settings.from_env()

    if a.cmd == "gmail-auth":
        _gmail(s)
        print(f"Gmail authorized; token saved to {s.gmail_token_file}")
        return
    if a.cmd == "zoho-auth":
        import requests

        r = requests.post(f"{s.zoho_accounts_url}/oauth/v2/token", params={
            "grant_type": "authorization_code", "code": a.code,
            "client_id": s.zoho_client_id, "client_secret": s.zoho_client_secret}, timeout=30).json()
        if "refresh_token" not in r:
            sys.exit(f"Zoho did not return a refresh token: {r}")
        print(f"Add this to .env:\nZOHO_REFRESH_TOKEN={r['refresh_token']}")
        return

    store = Store(s.db_path)

    if a.cmd == "scan":
        if a.no_llm:
            s.use_llm = False
        pipe = Pipeline(s, store, gmail=_gmail(s), llm=_llm(s))
        counts = pipe.scan(a.query, a.limit, a.rescan)
        print("scan done:", ", ".join(f"{v} {k}" for k, v in counts.items()) or "nothing new")
    elif a.cmd == "list":
        for r in store.list(a.status):
            o = r.order
            who = (o.customer.company or o.customer.email or "?") if o else "?"
            total = f"${o.total:,.2f}" if o and o.total else "-"
            print(f"{r.thread_id}  {r.status:<12} {r.order_code or '-':<20} {total:>12}  {who[:30]:<30} {r.subject[:50]}")
            for i in r.issues if r.status in ("needs_review", "failed") else []:
                print(f"{'':20}! {i}")
            if r.error:
                print(f"{'':20}! {r.error}")
    elif a.cmd == "show":
        r = store.get(_resolve(store, a.id))
        if a.json:
            print(r.order.model_dump_json(indent=2) if r.order else "{}")
        else:
            print(f"{r.subject}\n{r.thread_url}\nstatus: {r.status}   zoho: {r.zoho_id or '-'}")
            for i in r.issues:
                print(f"  ! {i}")
            print(r.order.model_dump_json(indent=2) if r.order else "(no order)")
    elif a.cmd == "edit":
        tid = _resolve(store, a.id)
        with open(a.file, encoding="utf-8") as f:
            order = Order.model_validate(json.load(f))
        issues = validate(order)
        store.update(tid, order=order, issues=issues, status="ready" if not issues else "needs_review")
        print("saved;", "ready to push" if not issues else "still has issues: " + "; ".join(issues))
    elif a.cmd == "approve":
        tid = _resolve(store, a.id)
        store.update(tid, status="ready")
        print(f"{tid} approved")
    elif a.cmd == "skip":
        tid = _resolve(store, a.id)
        store.update(tid, status="skipped")
        print(f"{tid} skipped")
    elif a.cmd == "push":
        pipe = Pipeline(s, store, gmail=None if a.dry_run else _gmail(s),
                        zoho=None if a.dry_run else _zoho(s))
        if a.ready:
            for tid, res in pipe.push_ready(dry_run=a.dry_run):
                print(tid, json.dumps(res, indent=2, ensure_ascii=False) if isinstance(res, dict) else res)
        elif a.id:
            res = pipe.push(_resolve(store, a.id), dry_run=a.dry_run, force=a.force)
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            sys.exit("give a thread id / order code, or --ready")
    elif a.cmd == "run":
        pipe = Pipeline(s, store, gmail=_gmail(s), llm=_llm(s), zoho=_zoho(s) if s.auto_push else None)
        counts = pipe.scan()
        print("scan:", counts or "nothing new")
        if s.auto_push:
            for tid, res in pipe.push_ready():
                print(tid, res)
        else:
            print("AUTO_PUSH is off - review with `sales-pipeline list`, then `push`.")


if __name__ == "__main__":
    main()
