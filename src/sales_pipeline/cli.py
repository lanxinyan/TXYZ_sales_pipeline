"""Command line:  sales-pipeline <command>

  check                what is set up and what to do next (start here)
  scan                 read new order emails from Gmail and extract them
  list [--status S]    show what has been found
  show ID              full extracted order + issues for one thread
  edit ID FILE         replace the extracted order with a corrected JSON file
  approve ID           mark a reviewed order ready to push
  skip ID              mark a thread as not an order
  push ID|--ready      create the Sales Order(s) in Zoho (--dry-run to preview)
  run                  scan, then push everything ready if AUTO_PUSH=true
  ui [--demo]          open the review dashboard (http://127.0.0.1:8765)
  followups            what is due: replies, follow-ups 1-4, close-outs
  gmail-auth           one-time Gmail sign-in (opens a browser)
  zoho-auth CODE       one-time: trade a Zoho self-client grant code for a refresh token
  zoho-setup [--write] read your Zoho tags (已下单, 不买了 ...) and map them to the follow-up stages
"""
from __future__ import annotations

import argparse
import json
import os
import logging
import sys

from .config import Settings
from .models import Order
from .pipeline import Pipeline, validate
from .store import Store


def _gmail(s: Settings):
    from .gmail_source import GmailSource

    g = GmailSource(s.gmail_credentials_file, s.gmail_token_file)
    if not s.user_email:
        s.user_email = g.profile_email()
    return g


def _zoho(s: Settings):
    from .zoho import ZohoCRM

    return ZohoCRM(s.zoho_accounts_url, s.zoho_api_domain, s.zoho_client_id,
                   s.zoho_client_secret, s.zoho_refresh_token)


def _llm(s: Settings):
    # Claude is optional: without a key, order emails are read by the built-in parser.
    if not s.use_llm or not (s.anthropic_api_key or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return None
    from .extract_llm import ClaudeExtractor

    return ClaudeExtractor(s.claude_model, s.internal_domains, s.anthropic_api_key)


def _set_env(key: str, value: str, path: str = ".env") -> None:
    """Write KEY=value into .env (replacing an existing line)."""
    lines = open(path, encoding="utf-8").read().splitlines() if os.path.exists(path) else []
    for i, ln in enumerate(lines):
        if ln.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.environ[key] = value


def _check(s: Settings) -> None:
    """Walk through the setup and say what is missing, in order."""
    import sys as _sys

    def line(ok, what, fix=""):
        print(f"  [{'x' if ok else ' '}] {what}" + ("" if ok or not fix else f"\n        -> {fix}"))
        return ok

    print("Sales Desk setup:")
    line(_sys.version_info >= (3, 10), f"Python {_sys.version.split()[0]}", "install Python 3.10 or newer")
    line(os.path.exists(".env"), "settings file .env", "copy .env.example to .env (setup does this for you)")
    has_creds = os.path.exists(s.gmail_credentials_file)
    has_token = os.path.exists(s.gmail_token_file)
    line(has_creds or has_token, f"Google sign-in file {s.gmail_credentials_file}",
         "download it from Google Cloud Console (README, step 3) and put it in this folder")
    gmail_ok = False
    if has_token:
        try:
            _gmail(s)
            gmail_ok = line(True, f"Gmail connected as {s.user_email}")
        except Exception as e:
            line(False, "Gmail sign-in", f"run `sales-pipeline gmail-auth` again ({e})")
    else:
        line(False, "Gmail signed in", "run `sales-pipeline gmail-auth` (opens a browser to sign in)")
    zoho_ok = False
    if s.zoho_refresh_token:
        try:
            from .crm import CustomerCRM

            from .zoho import NO_API_ACCESS

            z = _zoho(s)
            z.list_modules()          # a real call, so permission problems show up here
            crm = CustomerCRM(z, s)
            zoho_ok = line(True, f"Zoho connected; customers are looked up in {', '.join(crm.modules())}")
        except Exception as e:
            fix = str(e) if str(e) == NO_API_ACCESS else f"check ZOHO_CLIENT_ID/SECRET/REFRESH_TOKEN in .env ({e})"
            line(False, "Zoho connection", fix)
    else:
        line(False, "Zoho connected", "README, step 4: create a Self Client, then `sales-pipeline zoho-auth <code>`")
    if zoho_ok:
        line(os.path.exists(s.zoho_tag_file), f"tag map {s.zoho_tag_file}",
             "run `sales-pipeline zoho-setup --write` (until then only 已下单 and 不买了 are used)")
    line(True, "Claude: " + ("on" if _llm(s) else "off (optional; order emails are read by the built-in parser)"))
    print()
    if gmail_ok:
        print("Ready: start it with  sales-pipeline ui" + ("" if zoho_ok else "   (CRM steps wait until Zoho is connected)"))
    else:
        print("Next: connect Gmail. Meanwhile try it with made-up data:  sales-pipeline ui --demo")


def _pipeline(s: Settings, store: Store) -> Pipeline:
    zoho = _zoho(s) if s.zoho_refresh_token else None
    return Pipeline(s, store, gmail=_gmail(s), zoho=zoho, llm=_llm(s))


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
    sub.add_parser("followups")
    zs = sub.add_parser("zoho-setup")
    zs.add_argument("--write", action="store_true", help="save the suggested map to ZOHO_TAG_FILE")
    ui = sub.add_parser("ui")
    ui.add_argument("--demo", action="store_true", help="fictional data, nothing leaves your computer")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--no-browser", action="store_true", help="don't open the browser automatically")
    sub.add_parser("check")
    sub.add_parser("gmail-auth")
    za = sub.add_parser("zoho-auth")
    za.add_argument("code", nargs="?", help="grant code from https://api-console.zoho.com (asked for when left out)")

    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING,
                        format="%(levelname)s %(message)s")
    s = Settings.from_env()

    if a.cmd == "gmail-auth":
        if not os.path.exists(s.gmail_credentials_file):
            sys.exit(f"First put the Google sign-in file in this folder as {s.gmail_credentials_file} "
                     "(README, step 3).")
        _gmail(s)
        print(f"Gmail connected as {s.user_email}; sign-in saved to {s.gmail_token_file}")
        return
    if a.cmd == "zoho-auth":
        import requests

        print("Connect Zoho CRM (README, step 4). Values are saved to .env.")
        if not s.zoho_client_id:
            s.zoho_client_id = input("Client ID (from api-console.zoho.com, Self Client): ").strip()
            _set_env("ZOHO_CLIENT_ID", s.zoho_client_id)
        if not s.zoho_client_secret:
            s.zoho_client_secret = input("Client Secret: ").strip()
            _set_env("ZOHO_CLIENT_SECRET", s.zoho_client_secret)
        code = a.code or input("Code from 'Generate Code' (scope ZohoCRM.modules.ALL,ZohoCRM.settings.READ): ").strip()
        r = requests.post(f"{s.zoho_accounts_url}/oauth/v2/token", params={
            "grant_type": "authorization_code", "code": code,
            "client_id": s.zoho_client_id, "client_secret": s.zoho_client_secret}, timeout=30).json()
        if "refresh_token" not in r:
            sys.exit(f"Zoho did not accept it: {r}\nA code is only valid for a few minutes; generate a new "
                     "one and run this again. If the Client ID/Secret were wrong, fix them in .env.")
        _set_env("ZOHO_REFRESH_TOKEN", r["refresh_token"])
        print("Zoho connected; saved to .env.")
        return

    if a.cmd == "zoho-setup":
        from .crm import STAGES, CustomerCRM, load_tag_map, suggest_tag_map

        from .zoho import ZohoError

        z = _zoho(s)
        crm = CustomerCRM(z, s)
        try:
            modules = z.list_modules()
        except ZohoError as e:
            sys.exit(str(e))
        chosen = crm.modules()
        print("Your Zoho modules (name shown in Zoho -> internal API name):")
        for m in modules:
            if not m.get("api_supported", True):
                continue
            mark = f"   <- customers, searched #{chosen.index(m['api_name']) + 1}" if m["api_name"] in chosen else ""
            print(f"  {str(m.get('plural_label') or m.get('module_name') or ''):28} {m['api_name']}{mark}")
        how = "from ZOHO_CUSTOMER_MODULES" if s.zoho_customer_modules else "found automatically"
        print(f"\nCustomers are looked up in: {', '.join(chosen)} ({how}); new inquiries go into {chosen[0]}.")
        for module in chosen:
            print(f"  {module}: email field(s) {', '.join(crm.email_fields(module))}")
        print("To change it, set ZOHO_CUSTOMER_MODULES in .env (comma-separated API names).\n")
        names: list[str] = []
        for module in chosen:
            try:
                tags = [t["name"] for t in z.list_tags(module)]
            except Exception as e:
                print(f"{module}: could not read tags ({e})")
                continue
            print(f"{module} tags: {', '.join(tags) or '(none)'}")
            names += [t for t in tags if t not in names]
        current, suggested = load_tag_map(s.zoho_tag_file), suggest_tag_map(names)
        print("\nStage -> tag (current / suggested):")
        for stage, what in STAGES.items():
            print(f"  {stage:13} {what:32} {current.get(stage, '-'):10} {suggested.get(stage, '-')}")
        if a.write:
            with open(s.zoho_tag_file, "w", encoding="utf-8") as f:
                json.dump(suggested, f, ensure_ascii=False, indent=2)
            print(f"\nSaved to {s.zoho_tag_file}. Edit it to change a mapping; delete a line to stop using a stage.")
        else:
            print(f"\nRun with --write to save the suggestion to {s.zoho_tag_file}.")
        return

    if a.cmd == "ui":
        from .web import App, serve

        if a.demo:
            from .demo import seed

            s.db_path = "demo.db"
            store = Store(s.db_path)
            _, _, pipe = seed(s, store)
            serve(App(s, store, pipe, demo=True), a.port, open_browser=not a.no_browser)
            return
        if not (os.path.exists(s.gmail_token_file) or os.path.exists(s.gmail_credentials_file)):
            sys.exit("Gmail isn't connected yet, so there is nothing to show.\n"
                     f"  1. Put the Google sign-in file in this folder as {s.gmail_credentials_file} (README, step 3)\n"
                     "  2. Run:  sales-pipeline gmail-auth\n"
                     "Meanwhile you can try it with made-up data:  sales-pipeline ui --demo\n"
                     "Run `sales-pipeline check` to see everything that is left to set up.")
        store = Store(s.db_path)
        try:
            pipe = _pipeline(s, store)
        except Exception as e:
            sys.exit(f"Couldn't connect to Gmail: {e}\n"
                     "Run `sales-pipeline check` to see what is missing (README, step 3).")
        if pipe.zoho is None:
            print("Note: Zoho isn't connected yet; CRM steps will wait until it is (README, step 4).")
        if pipe.llm is None:
            print("Note: Claude is off (no ANTHROPIC_API_KEY); order emails are read by the built-in parser.")
        serve(App(s, store, pipe, scanner=pipe.scan), a.port, s.scan_interval_min, open_browser=not a.no_browser)
        return

    if a.cmd == "check":
        _check(s)
        return

    store = Store(s.db_path)

    if a.cmd == "scan":
        if a.no_llm:
            s.use_llm = False
        pipe = _pipeline(s, store)
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
        pipe = _pipeline(s, store)
        counts = pipe.scan()
        print("scan:", counts or "nothing new")
        if s.auto_push and pipe.zoho is not None:
            for tid, res in pipe.push_ready():
                print(tid, res)
        else:
            print("Review in the dashboard (`sales-pipeline ui`) or `sales-pipeline followups`.")
    elif a.cmd == "followups":
        from .tasks import action_label, level

        Pipeline(s, store).promote_due()
        for title, statuses in (("TO DO NOW", ["ready", "needs_review", "failed"]), ("UPCOMING", ["scheduled"])):
            recs = [r for r in store.list(statuses) if r.kind == "quote_request"]
            if title == "UPCOMING":
                recs.sort(key=lambda r: r.due_at or "")
            print(f"\n{title} ({len(recs)})")
            for r in recs:
                who = (r.conv.customer_name or (r.conv.customer_emails or ["?"])[0]) if r.conv else "?"
                due = (r.due_at or "")[:10]
                print(f"  {level(r.priority):6} {action_label(r.kind, r.conv, s):20} due {due:10}  {who[:28]:28} {r.subject[:50]}")


if __name__ == "__main__":
    main()
