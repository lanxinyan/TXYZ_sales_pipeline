"""Scan Gmail -> extract -> validate -> (approve) -> push to Zoho CRM."""
from __future__ import annotations

import logging
import re

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

class Pipeline:
    def __init__(self, settings: Settings, store: Store, gmail=None, zoho: ZohoCRM | None = None,
                 llm=None):
        self.s, self.store, self.gmail, self.zoho, self.llm = settings, store, gmail, zoho, llm

    def process_thread(self, thread: EmailThread) -> str:
        rules = rules_extract(thread, self.s.order_code_regex, self.s.internal_domains)
        llm_order = None
        if self.llm is not None:
            try:
                llm_order = self.llm.extract(thread)
            except Exception as e:  # network / API errors - fall back to rules
                log.warning("Claude extraction failed for %s: %s", thread.id, e)
        order, notes = merge(llm_order, rules, self.s)

        if not order.is_sales_order:
            status, issues = "skipped", notes
        else:
            issues = notes + validate(order)
            status = "ready" if not issues else "needs_review"
        self.store.save(thread.id, subject=thread.subject, thread_url=thread.url,
                        message_count=len(thread.messages), status=status, order=order, issues=issues)
        if self.gmail is not None:
            from .gmail_source import LABEL_REVIEW, LABEL_SKIPPED

            self.gmail.set_label(thread.id, LABEL_SKIPPED if status == "skipped" else LABEL_REVIEW)
        return status

    def scan(self, query: str | None = None, limit: int = 50, rescan: bool = False) -> dict[str, int]:
        counts: dict[str, int] = {}
        for tid in self.gmail.search(query or self.s.gmail_query, limit):
            existing = self.store.get(tid)
            if existing and existing.status == "pushed":
                continue
            thread = self.gmail.get_thread(tid)
            # Only re-read a thread when new replies arrived (or when asked to).
            if existing and not rescan and existing.message_count == len(thread.messages):
                continue
            status = self.process_thread(thread)
            log.info("%s  %-12s %s", tid, status, thread.subject)
            counts[status] = counts.get(status, 0) + 1
        return counts

    def push(self, thread_id: str, dry_run: bool = False, force: bool = False) -> dict:
        rec = self.store.get(thread_id)
        if rec is None or rec.order is None:
            raise KeyError(f"unknown thread {thread_id}")
        if rec.status == "pushed" and not force:
            return {"status": "already pushed", "zoho_id": rec.zoho_id}
        if rec.status not in ("ready", "failed") and not force:
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
