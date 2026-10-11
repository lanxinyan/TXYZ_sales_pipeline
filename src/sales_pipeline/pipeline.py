"""Scan Gmail -> extract -> validate -> (approve) -> push to Zoho CRM."""
from __future__ import annotations

import logging
import re
from contextlib import nullcontext
from datetime import datetime, timezone

from .config import Settings
from .extract_rules import extract as rules_extract
from .extract_rules import is_internal
from .models import EmailThread, Order
from .store import Store
from .zoho import ZohoCRM, ZohoError

log = logging.getLogger(__name__)


# ---------- extraction ----------

def merge(llm: Order | None, rules: Order, settings: Settings) -> tuple[Order, list[str]]:
    """Claude's reading wins; the rule-based parse fills gaps and flags disagreements."""
    notes: list[str] = []
    if llm is None:
        return rules, ["extracted by rules only (Claude unavailable or declined)"] if settings.use_llm else []
    o = llm.model_copy(deep=True)
    if rules.order_code and o.order_code and rules.order_code != o.order_code:
        notes.append(f"order code mismatch: email form says {rules.order_code}, Claude read {o.order_code}")
        o.order_code = rules.order_code
    if rules.total and o.total and abs(rules.total - o.total) > 0.01:
        notes.append(f"total mismatch: order form ${rules.total:,.2f} vs quote ${o.total:,.2f}")
    for f in ("order_code", "po_number", "order_date", "order_type", "total", "shipping",
              "sales_rep", "customer_status"):
        if getattr(o, f) in (None, "") and getattr(rules, f) not in (None, ""):
            setattr(o, f, getattr(rules, f))
    if not o.items and rules.items:
        o.items = rules.items
    if o.customer.email and is_internal(o.customer.email, settings.internal_domains):
        o.customer.email = None
    if not o.customer.email and rules.customer.email:
        o.customer.email = rules.customer.email
        o.customer.contact_name = o.customer.contact_name or rules.customer.contact_name
    if rules.notes and rules.notes not in (o.notes or ""):
        o.notes = "\n".join(x for x in (o.notes, rules.notes) if x)
    return o, notes


def validate(order: Order) -> list[str]:
    """Reasons a human must look before this goes into Zoho. Empty list = ready."""
    issues = []
    if not order.order_code:
        issues.append("no order/quote number found")
    if not order.customer.company:
        issues.append("customer company unknown (Zoho needs an Account)")
    if not order.customer.email:
        issues.append("customer contact email unknown")
    if not order.items:
        issues.append("no line items")
    for it in order.items:
        if it.unit_price is None:
            issues.append(f"no price for item {it.product_name!r}")
    if order.total is None:
        issues.append("order total unknown")
    elif order.items and all(it.unit_price is not None for it in order.items):
        computed = sum(it.quantity * it.unit_price - (it.discount or 0) for it in order.items)
        computed += (order.shipping or 0) - (order.discount or 0)
        if abs(computed - order.total) > max(1.0, 0.005 * order.total):
            issues.append(f"line items add up to ${computed:,.2f} but total is ${order.total:,.2f}")
    return issues


# ---------- Zoho payload ----------

def sales_order_payload(order: Order, *, account_id=None, contact_id=None, product_ids=None,
                        status="Created", thread_url="") -> dict:
    product_ids = product_ids or [None] * len(order.items)
    items = []
    for it, pid in zip(order.items, product_ids):
        row = {"Product_Name": {"id": pid} if pid else {"name": it.product_name},
               "Quantity": it.quantity, "List_Price": it.unit_price or 0}
        if it.discount:
            row["Discount"] = it.discount
        if it.catalog_number:
            row["Description"] = f"Cat# {it.catalog_number}"
        items.append(row)
    desc = [order.notes or ""]
    if order.payment_terms:
        desc.append(f"Payment terms: {order.payment_terms}")
    if order.sales_rep:
        desc.append(f"Sales rep: {order.sales_rep}")
    if thread_url:
        desc.append(f"Source email: {thread_url}")
    rec = {
        "Subject": order.order_code,
        "Status": status,
        "Ordered_Items": items,
        "Description": "\n".join(d for d in desc if d).strip(),
        "Account_Name": {"id": account_id} if account_id else {"name": order.customer.company},
    }
    if contact_id:
        rec["Contact_Name"] = {"id": contact_id}
    if order.po_number:
        rec["Purchase_Order"] = order.po_number
    if order.shipping:
        rec["Adjustment"] = order.shipping
    if order.discount:
        rec["Discount"] = order.discount
    if order.customer.billing_address:
        rec["Billing_Street"] = order.customer.billing_address
    if order.customer.shipping_address:
        rec["Shipping_Street"] = order.customer.shipping_address
    if order.currency and order.currency != "USD":
        rec["Currency"] = order.currency
    return rec


# ---------- the pipeline ----------

# Bump when the plan rules change: open items saved by an older version are planned again
# (e.g. version 2: customer emails go to the customer only, never to colleagues).
PLAN_VERSION = "2"

class Pipeline:
    def __init__(self, settings: Settings, store: Store, gmail=None, zoho: ZohoCRM | None = None,
                 llm=None, crm=None, templates=None):
        from .crm import CustomerCRM, load_tag_map
        from .templates import load as load_templates

        self.s, self.store, self.gmail, self.zoho, self.llm = settings, store, gmail, zoho, llm
        # Customer records/tags/notes are written by Cowork from the Gmail feed, unless
        # ZOHO_DIRECT_UPDATES is turned on (after API access and a final rulebook).
        self.crm = crm if crm is not None else (
            CustomerCRM(zoho, settings) if zoho is not None and settings.zoho_direct_updates else None)
        self.tags = self.crm.tags if self.crm else load_tag_map(settings.zoho_tag_file)
        self.templates = templates or load_templates(settings.templates_file)

    # ---------- reading one thread ----------

    def process_thread(self, thread: EmailThread, reuse_order: Order | None = None) -> str:
        from .conversation import analyze, owner_is_me

        s = self.s
        conv = analyze(thread, s, s.user_email, self.store.ignored_domains())
        rules = rules_extract(thread, s.order_code_regex, s.internal_domains)
        if reuse_order is not None:
            order, notes = reuse_order, []
        elif self.llm is not None and _may_be_order(thread, rules):
            llm_order = None
            try:
                full = self.gmail.get_thread(thread.id) if self.gmail is not None else thread
                llm_order = self.llm.extract(full)
            except Exception as e:  # network / API errors - fall back to rules
                log.warning("Claude extraction failed for %s: %s", thread.id, e)
            order, notes = merge(llm_order, rules, s)
        else:
            order, notes = merge(None, rules, s)
            notes = [n for n in notes if not n.startswith("extracted by rules only")]

        from .tasks import classify
        kind = classify(thread, order, conv, s)
        issues: list[str] = list(notes)
        due_at = None
        if kind == "order":
            issues += validate(order)
            status = "ready" if not issues else "needs_review"
        elif kind == "quote_request":
            status, due_at, extra = self._conversation_status(conv)
            issues += extra
        else:
            status = "skipped"
            if conv.customer_emails and not owner_is_me(conv):
                issues.append("handled by colleagues (you are only in copy)")

        self._save(thread, kind, order, conv, status, issues, due_at)
        if kind == "quote_request":
            self._log_manual_replies(thread, conv)
        if self.gmail is not None and kind == "order":
            from .gmail_source import LABEL_REVIEW
            self.gmail.set_label(thread.id, LABEL_REVIEW)
        return status

    def _conversation_status(self, conv) -> tuple[str, str | None, list[str]]:
        from .conversation import owner_is_me, parse_date

        if not owner_is_me(conv):
            return "skipped", None, ["handled by colleagues (you are only in copy)"]
        if conv.stage == "none":
            return "done", None, []
        if self.crm is not None and conv.customer_emails:
            try:
                closed = self.crm.closing_tag(conv.customer_emails[0])
            except Exception as e:
                log.warning("Zoho tag check failed: %s", e)
                closed = None
            if closed and conv.stage != "reply_needed":
                # Someone already closed this customer in Zoho: no more follow-ups.
                return "done", None, [f"closed in Zoho: {closed}"]
            if closed:
                return "ready", conv.due_at, [f"customer wrote again but is tagged {closed} in Zoho"]
        due = parse_date(conv.due_at)
        if conv.stage in ("awaiting_customer", "exhausted") and due and due > datetime.now(timezone.utc):
            return "scheduled", conv.due_at, []
        return "ready", conv.due_at, []

    def _save(self, thread: EmailThread, kind, order, conv, status, issues, due_at) -> None:
        from .tasks import build_plan, prioritize

        previous = self.store.get(thread.id)
        priority, reasons = prioritize(kind, order, issues, conv, s=self.s)
        plan = build_plan(kind, order, conv, thread.subject, self.s, self._context(kind, order, thread, conv),
                          previous.plan if previous else None)
        self.store.save(thread.id, subject=thread.subject, thread_url=thread.url,
                        message_count=len(thread.messages), status=status, order=order, issues=issues,
                        kind=kind, priority=priority, reasons=reasons, plan=plan,
                        waiting_since=conv.last_inbound_at if conv.stage == "reply_needed" else None,
                        conv=conv, due_at=due_at, zoho_id=previous.zoho_id if previous else None)

    def _context(self, kind: str, order: Order, thread: EmailThread | None, conv=None):
        from .conversation import invoice_status
        from .tasks import PlanContext

        ctx = PlanContext(templates=self.templates, tags=self.tags, crm=self.crm is not None)
        if kind == "quote_request":
            if self.crm is not None and conv is not None and conv.customer_emails and not conv.replied_ever:
                try:   # a colleague may already have created the inquiry in Zoho
                    ctx.crm_record = self.crm.find(conv.customer_emails[0])
                except Exception as e:
                    log.warning("Zoho lookup failed: %s", e)
            return ctx
        if kind != "order":
            return ctx
        threads = [thread] if thread is not None else []
        if order.order_code and self.gmail is not None:
            # Accounting emails often live in their own thread: look them up by order code.
            try:
                for tid in self.gmail.search(f'"{order.order_code}" newer_than:180d', 10):
                    if thread is None or tid != thread.id:
                        threads.append(self.gmail.get_thread(tid, attachments=False))
            except Exception as e:
                log.warning("related-thread search failed: %s", e)
        ctx.invoice = invoice_status(threads, self.s, self.s.user_email) if threads else None
        ctx.customer_thread = self._customer_thread(order)
        return ctx

    def _customer_thread(self, order: Order) -> dict | None:
        """The customer's own quote/inquiry thread, so a confirmation lands there."""
        email = (order.customer.email or "").lower()
        for r in self.store.list():
            if r.kind == "quote_request" and r.conv and (
                    (order.order_code and r.order_code == order.order_code) or email in r.conv.customer_emails):
                return {"thread_id": r.thread_id, "conv": r.conv}
        return None

    def _log_manual_replies(self, thread: EmailThread, conv) -> None:
        """Replies you sent straight from Gmail are recorded in Zoho too."""
        from .conversation import Who, fresh_text, parse_date

        if self.crm is None or not self.s.log_manual_replies or not conv.customer_emails:
            return
        started = parse_date(self.store.meta("started_at"))
        who = Who(self.s, self.s.user_email, self.store.ignored_domains())
        for m in thread.messages:
            at = parse_date(m.date)
            if (m.sender.lower() != self.s.user_email or not any(who.customer(r) for r in m.to + m.cc)
                    or (started and at and at < started) or self.store.crm_logged(m.id)):
                continue
            try:
                note = self.crm.log_followup(
                    conv.customer_emails[0], f"Email to customer: {m.subject}"[:120],
                    f"{fresh_text(m.body)}\n\n(sent from Gmail {m.date}; {thread.url})",
                    name=conv.customer_name, company=conv.company)
                self.store.mark_crm_logged(m.id, thread.id, note)
                self.store.log(thread.id, f"Recorded your Gmail reply of {m.date[:10]} in Zoho")
            except Exception as e:
                log.warning("could not log reply %s in Zoho: %s", m.id, e)

    # ---------- keeping the list current ----------

    def scan(self, query: str | None = None, limit: int = 50, rescan: bool = False, lock=None) -> dict[str, int]:
        """Re-read new/changed threads. `lock` (the dashboard's) is held one thread at a
        time, so your clicks are never kept waiting for the whole scan."""
        from .gmail_source import rate_limited

        lock = lock or nullcontext()
        counts: dict[str, int] = {}
        queries = [query] if query else [self.s.gmail_query, self.s.followup_query]
        seen: list[str] = []
        history = getattr(self.gmail, "history", {})
        # Who counts as "us" (INTERNAL_DOMAINS ...). When that changes, every thread is read again once.
        rules = ",".join(sorted(self.s.internal_domains + self.s.system_domains))
        try:
            for q in queries:
                with lock:
                    found = self.gmail.search(q, limit)
                seen += [tid for tid in found if tid not in seen]
            for tid in seen:
                with lock:
                    existing = self.store.get(tid)
                    if existing and (existing.status in ("pushed", "awaiting_send") or
                                     (existing.kind == "order" and existing.status == "done")):
                        continue   # handled orders stay handled; conversations reopen when the customer writes
                    # Nothing changed in the thread since last time: don't even download it.
                    h = history.get(tid) or ""
                    mark, prev = f"{h}|{rules}", self.store.seen_history(tid)
                    if existing and not rescan and h and prev == mark:
                        continue
                    same_rules = bool(prev) and prev.split("|", 1)[-1] == rules
                    thread = self.gmail.get_thread(tid, attachments=False)
                    # Only re-read a thread when new replies arrived (or when asked to).
                    if existing and not rescan and same_rules and existing.message_count == len(thread.messages):
                        self.store.set_seen_history(tid, mark)
                        continue
                    status = self.process_thread(thread)
                    self.store.set_seen_history(tid, mark)
                log.info("%s  %-12s %s", tid, status, thread.subject)
                counts[status] = counts.get(status, 0) + 1
        except Exception as e:
            if not rate_limited(e):
                raise
            # Google's per-minute Gmail limit: keep what was read, carry on at the next scan.
            log.warning("Gmail rate limit reached; the scan continues next time: %s", e)
            counts["paused: Gmail's per-minute limit, continues at the next scan"] = 1
        with lock:
            due = self.promote_due()
        counts.update({k: counts.get(k, 0) + v for k, v in due.items()})
        return counts

    def upgrade_plans(self) -> int:
        """Re-plan open items saved by an older version, so its rules don't linger."""
        from .tasks import build_plan

        if self.store.meta("plan_version") == PLAN_VERSION:
            return 0
        n = 0
        for rec in self.store.list(["ready", "needs_review", "scheduled", "failed"]):
            if not rec.order:
                continue
            try:
                plan = build_plan(rec.kind, rec.order, rec.conv, rec.subject, self.s,
                                  self._context(rec.kind, rec.order, None, rec.conv), rec.plan)
            except Exception as e:
                log.warning("could not re-plan %s: %s", rec.thread_id, e)
                continue
            self.store.update(rec.thread_id, plan=plan)
            n += 1
        self.store.set_meta("plan_version", PLAN_VERSION)
        return n

    def promote_due(self) -> dict[str, int]:
        """Follow-ups whose day has come move from Upcoming to To decide."""
        from .conversation import parse_date
        from .tasks import build_plan

        now = datetime.now(timezone.utc)
        moved = 0
        for rec in self.store.list("scheduled"):
            due = parse_date(rec.due_at)
            if due and due <= now and rec.order:
                plan = build_plan(rec.kind, rec.order, rec.conv, rec.subject, self.s,
                                  self._context(rec.kind, rec.order, None, rec.conv), rec.plan)
                self.store.update(rec.thread_id, status="ready", plan=plan)
                moved += 1
        return {"due now": moved} if moved else {}

    def refresh(self, thread_id: str) -> str:
        """Re-read one thread from Gmail (after sending, or to double-check)."""
        rec = self.store.get(thread_id)
        thread = self.gmail.get_thread(thread_id, attachments=False)
        return self.process_thread(thread, reuse_order=rec.order if rec else None)

    def close_customer_threads(self, email: str | None, order_code: str | None, why: str) -> int:
        """Stop follow-ups on the customer's other conversations (e.g. they ordered)."""
        n = 0
        email = (email or "").lower()
        for r in self.store.list(["ready", "scheduled", "needs_review"]):
            if r.kind == "quote_request" and r.conv and (
                    (email and email in r.conv.customer_emails) or (order_code and r.order_code == order_code)):
                self.store.update(r.thread_id, status="done", issues=[why])
                self.store.log(r.thread_id, f"Follow-ups stopped: {why}")
                n += 1
        return n

    def push(self, thread_id: str, dry_run: bool = False, force: bool = False) -> dict:
        rec = self.store.get(thread_id)
        if rec is None or rec.order is None:
            raise KeyError(f"unknown thread {thread_id}")
        if rec.status == "pushed" and not force:
            return {"status": "already pushed", "zoho_id": rec.zoho_id}
        if rec.status not in ("ready", "failed", "approved") and not force:
            raise ValueError(f"thread {thread_id} is '{rec.status}' - approve it first")
        o = rec.order
        if dry_run:
            return sales_order_payload(o, status=self.s.zoho_so_status, thread_url=rec.thread_url)

        z = self.zoho
        try:
            existing = z.find_sales_order(o.order_code)
            if existing:
                self.store.update(thread_id, status="pushed", zoho_id=existing, error=None)
                return {"status": "exists", "zoho_id": existing}
            company = o.customer.company or _company_from_email(o.customer.email)
            account_id = z.find_or_create_account(company, o)
            contact_id = z.find_or_create_contact(o, account_id)
            product_ids = [z.find_or_create_product(it.product_name, it.catalog_number, it.unit_price,
                                                    self.s.zoho_auto_create_products,
                                                    self.s.zoho_generic_product_id) for it in o.items]
            payload = sales_order_payload(o, account_id=account_id, contact_id=contact_id,
                                          product_ids=product_ids, status=self.s.zoho_so_status,
                                          thread_url=rec.thread_url)
            so_id = z.create("Sales_Orders", payload)
        except ZohoError as e:
            self.store.update(thread_id, status="failed", error=str(e))
            raise
        # Attach the quote / PO PDFs; failure here should not undo the order.
        if self.gmail is not None:
            try:
                for pdf in self.gmail.get_thread(thread_id).pdfs():
                    z.attach("Sales_Orders", so_id, pdf.filename, pdf.data)
            except Exception as e:
                log.warning("could not attach PDFs to %s: %s", so_id, e)
            from .gmail_source import LABEL_SYNCED

            self.gmail.set_label(thread_id, LABEL_SYNCED)
        self.store.update(thread_id, status="pushed", zoho_id=so_id, error=None)
        return {"status": "created", "zoho_id": so_id}

    def push_ready(self, dry_run: bool = False) -> list[tuple[str, dict | str]]:
        results = []
        for rec in self.store.list("ready"):
            if rec.kind != "order":
                continue
            try:
                results.append((rec.thread_id, self.push(rec.thread_id, dry_run=dry_run)))
            except Exception as e:
                results.append((rec.thread_id, f"error: {e}"))
        return results


def _company_from_email(email: str | None) -> str:
    if not email:
        raise ZohoError("cannot create an Account without a company name or email")
    domain = email.split("@")[1].split(".")
    return re.sub(r"[-_]", " ", domain[-2] if len(domain) >= 2 else domain[0]).title()


def _may_be_order(thread: EmailThread, rules: Order) -> bool:
    """Only spend a Claude call on threads that could be an order."""
    if rules.is_sales_order:
        return True
    text = thread.subject + " " + " ".join(m.subject for m in thread.messages[-3:])
    names = " ".join(n for m in thread.messages for n in m.attachment_names)
    return bool(re.search(r"\bOrder_|purchase order|\bPO\b", text, re.I) or re.search(r"\bPO\b|purchase", names, re.I))
