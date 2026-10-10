"""Turn a thread into a to-do item: what kind it is, how urgent, and the plan
of steps that run once you approve.

Steps are either *routine* (Zoho records, tags, Gmail labels - run when you
approve) or *gated* (anything a customer or accounting will read - prepared as
a Gmail draft and sent only when you approve sending it). Every gated email
to a customer is recorded as a follow-up in Zoho after it is sent."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import Settings
from .conversation import fresh_text, parse_date, short
from .models import Conversation, EmailThread, Order
from .templates import Template, followup_variants, render

INQUIRY_SUBJECT = re.compile(
    r"Creative Biostructure \(ID:|request for quot|\bRFQ\b|quote request|\binquiry\b|\benquiry\b|询价", re.I)
STAGE_LABEL = {1: "gentle", 2: "friendly nudge", 3: "firm", 4: "final"}


@dataclass
class PlanContext:
    templates: dict[str, Template]
    tags: dict[str, str] = field(default_factory=dict)
    invoice: dict | None = None          # conversation.invoice_status() for orders
    customer_thread: dict | None = None  # the customer's own thread for an order: {thread_id, conv}
    crm_record: tuple | None = None      # (module, id) when the customer is already in Zoho


# ---------- what is it ----------

def classify(thread: EmailThread, order: Order, conv: Conversation | None, s: Settings) -> str:
    """'order', 'quote_request' (a customer sales conversation) or 'other'."""
    if order.is_sales_order:
        return "order"
    if not conv or not conv.customer_emails:
        return "other"
    ours = re.search(s.order_code_regex, thread.subject + "\n" + "\n".join(fresh_text(m.body) for m in thread.messages))
    if (conv.quote_sent or conv.inquiry_forward or conv.asked_for_quote or ours
            or INQUIRY_SUBJECT.search(thread.subject)):
        return "quote_request"
    return "other"


# ---------- how urgent ----------

def prioritize(kind: str, order: Order, issues: list[str], conv: Conversation | None = None,
               now: datetime | None = None, s: Settings | None = None) -> tuple[int, list[str]]:
    now = now or datetime.now(timezone.utc)
    total_followups = len(s.followup_days) if s else 4
    score, why = 0, []
    signals = {x["kind"] for x in (conv.signals if conv else [])}
    if kind == "order":
        score = 50
        if order.total:
            score += min(30, int(order.total / 1000))
            if order.total >= 10000:
                why.append(f"large order ${order.total:,.0f}")
        if conv and conv.stage == "reply_needed" and conv.last_inbound_at:
            hours = _hours(now, conv.last_inbound_at)
            score += min(30, int(hours / 2))
            why.append(f"customer waiting {_age(hours)}")
        if order.customer_status == "new":
            score += 10
            why.append("new customer")
        if order.payment_terms and "prepay" in order.payment_terms.lower():
            why.append("prepayment")
        if issues:
            score += 5
            why.append(f"{len(issues)} thing(s) to check")
    elif kind == "quote_request" and conv:
        late = _hours(now, conv.due_at) if conv.due_at else 0
        if conv.stage == "reply_needed":
            hours = _hours(now, conv.last_inbound_at)
            if not conv.replied_ever:
                score = 70   # a customer's first email is answered the same day
                why.append("first reply: answer today")
            else:
                score = 55
                why.append("customer replied")
            score += min(30, int(hours / 2))
            why.append(f"waiting {_age(hours)}" + (" (overdue)" if late > 0 else ""))
            if "wants_to_order" in signals:
                score += 15
                why.append("wants to order")
            if "declined" in signals:
                why.append("seems to decline")
        elif conv.stage == "awaiting_customer":
            score = 40 + 3 * conv.followup_no
            why.append(f"follow-up {conv.followup_no} of {total_followups}")
            if late >= 24:
                score += min(20, int(late / 24) * 2)
                why.append(f"{_age(late)} overdue")
        elif conv.stage == "declined":
            score = 35
            why.append("customer seems to decline")
        elif conv.stage == "exhausted":
            score = 25
            why.append(f"no answer after {total_followups} follow-ups")
        if order.total:
            score += min(15, int(order.total / 2000))
    return score, why


def level(score: int) -> str:
    return "high" if score >= 70 else "medium" if score >= 45 else "low"


def action_label(kind: str, conv: Conversation | None, s: Settings) -> str:
    if kind == "order":
        return "New order"
    if kind != "quote_request" or not conv:
        return ""
    if conv.stage == "reply_needed":
        return "First reply" if not conv.replied_ever else "Reply needed"
    if conv.stage == "awaiting_customer":
        return f"Follow-up {conv.followup_no}/{len(s.followup_days)}"
    if conv.stage == "declined":
        return "Customer declined?"
    if conv.stage == "exhausted":
        return "No answer: close?"
    return ""


def _hours(now: datetime, when: str | None) -> float:
    d = parse_date(when)
    return (now - d).total_seconds() / 3600 if d else 0.0


def _age(hours: float) -> str:
    return f"{hours:.0f}h" if hours < 48 else f"{hours / 24:.0f}d"


# ---------- the plan ----------

def values(s: Settings, order: Order, conv: Conversation | None) -> dict:
    name = (conv.customer_name if conv else None) or order.customer.contact_name or ""
    first = name.split()[0].strip(",").title() if name.strip() else ""
    topic = (conv.topic if conv else None) or ""
    total = f"${order.total:,.2f}" if order.total else ""
    items = "; ".join(f"{i.product_name} x{i.quantity:g}" for i in order.items) or topic or "your order"
    email = order.customer.email or (conv.customer_emails[0] if conv and conv.customer_emails else "")
    company = order.customer.company or (conv.company if conv else None) or ""
    prepay = bool(order.payment_terms and "prepay" in order.payment_terms.lower())
    sal = conv.salutation if conv else None
    if sal:   # greet them the way we (you or a colleague) last did: "Dear Dr. Okafor,"
        greeting = f"{sal['word']} {sal['name']},"
    else:
        greeting = f"Hi {first}," if first else "Hello,"
    return dict(
        greeting=greeting, first_name=first,
        sender_name=s.sender_name, sender_phone=s.sender_phone, signature=s.signature(),
        topic=topic, about_topic=f" about {topic}" if topic else "",
        order_code=order.order_code or "", total=total or "as quoted", items=items,
        company=company, customer_email=email,
        customer_line=" ".join(x for x in (company, f"<{email}>" if email else "") if x),
        prepay_line=("As this is a custom service, we will begin once the upfront payment is received; "
                     "our accounting team will send the invoice shortly.\n\n" if prepay else ""),
        invoice_cn="收预付" if prepay else "开发票",
        invoice_kind="the upfront payment (prepayment) invoice" if prepay else "the invoice",
        po_line=f"PO: {order.po_number}\n" if order.po_number else "",
        terms_line=f"Terms: {order.payment_terms}\n" if order.payment_terms else "",
    )


def _re(subject: str) -> str:
    return subject if re.match(r"^\s*re\s*:", subject or "", re.I) else f"Re: {subject}"


def _draft(t: Template, vals: dict, to: list[str], cc: list[str], subject: str, *,
           thread: bool = True, in_reply_to: str = "", quote: dict | None = None,
           variants: list[Template] | None = None) -> dict:
    return {"to": ", ".join(to), "cc": ", ".join(cc), "subject": subject, "body": render(t, **vals),
            "template": t.key, "in_thread": thread, "in_reply_to": in_reply_to,
            "quote": quote, "variants": [{"key": v.key, "label": v.label, "body": render(v, **vals)}
                                         for v in (variants or [t])]}


def _quote(prev: dict | None) -> dict | None:
    if not prev:
        return None
    d = parse_date(prev.get("date"))
    if d:
        d = d.astimezone()   # the computer's local time, like Gmail shows it
    label = f"{d:%a}, {d:%b} {d.day}, {d:%Y} at {d.strftime('%I:%M %p').lstrip('0')}" if d else ""
    return {"sender": f"{prev.get('sender_name', '')} <{prev.get('sender', '')}>".strip(),
            "date": prev.get("date"), "date_label": label, "body": prev.get("body", "")}


def build_plan(kind: str, order: Order, conv: Conversation | None, subject: str, s: Settings,
               ctx: PlanContext, previous: list[dict] | None = None) -> list[dict]:
    T = ctx.templates
    vals = values(s, order, conv)
    steps: list[dict] = []
    who = vals["company"] or vals["customer_email"] or "customer"
    tag = ctx.tags

    if kind == "order":
        total = vals["total"]
        steps.append(dict(id="zoho_so", gated=False, enabled=True,
                          title=f"Create Sales Order {order.order_code or '?'} in Zoho",
                          detail=f"{who} · {len(order.items)} item(s) · {total} · "
                                 "Account/Contact/Products found or created, quote PDF attached"))
        if tag.get("ordered") and vals["customer_email"]:
            steps.append(dict(id="tag_ordered", gated=False, enabled=True,
                              title=f"Tag the customer {tag['ordered']} in Zoho and stop their follow-ups",
                              detail="Other lifecycle tags (e.g. " + ", ".join(
                                  v for k, v in tag.items() if k != "ordered") + ") are removed"))
        steps.append(dict(id="label", gated=False, enabled=True, title="Label email Zoho/Synced", detail=""))
        if vals["customer_email"]:
            ct = ctx.customer_thread or {}
            ct_conv: Conversation | None = ct.get("conv")
            prev = (ct_conv.last_outbound or ct_conv.last_inbound) if ct_conv else None
            steps.append(dict(
                id="confirm", gated=True, enabled=True, crm_log=True,
                title="Order confirmation to the customer",
                detail=("Sent as a reply in your conversation with the customer" if prev
                        else "Sent as a new email (no earlier conversation found)"),
                target_thread=ct.get("thread_id"),
                draft=_draft(T["order_confirmation"], vals, [vals["customer_email"]],
                             [c for c in (prev or {}).get("cc", []) if c],
                             _re(prev["subject"]) if prev else f"Order confirmation: {order.order_code or ''}".strip(),
                             thread=bool(prev), in_reply_to=(prev or {}).get("rfc_id", ""))))
        if s.accounting_email:
            inv = ctx.invoice or {"state": None, "evidence": []}
            st = dict(id="accounting", gated=True, enabled=inv["state"] is None, crm_log=False,
                      title="Ask accounting for the invoice", evidence=inv["evidence"],
                      draft=_draft(T["accounting_invoice"], vals, [s.accounting_email], [],
                                   f"Order_{order.order_code or ''} {vals['invoice_cn']}", thread=False))
            if inv["state"] == "done":
                st["detail"] = "Already handled by a colleague. Left unticked; nothing to send."
                st["colleague"] = True
            elif inv["state"] == "hold":
                st["detail"] = "A colleague asked to wait. Left unticked until they confirm."
                st["colleague"] = True
            else:
                st["detail"] = "Checked: nobody has sent this to accounting yet. Checked again right before sending."
            steps.append(st)

    elif kind == "quote_request" and conv:
        signals = {x["kind"]: x["text"] for x in conv.signals}
        email = conv.customer_emails[0] if conv.customer_emails else ""
        inbound = conv.last_inbound or {}
        out = conv.last_outbound or {}
        n_total = len(s.followup_days)
        if conv.stage == "reply_needed":
            if not conv.replied_ever:
                ref = conv.crm_refs[-1] if conv.crm_refs else None
                crm_step = dict(id="crm_inquiry", gated=False, enabled=ref is None and ctx.crm_record is None,
                                title="Add the inquiry to Zoho" + (f" and tag {tag['inquiry']}" if tag.get("inquiry") else ""),
                                detail=f"{conv.customer_name or email} · {conv.company or ''} · {conv.topic or ''}")
                if ref:
                    crm_step["detail"] = f"Already in Zoho: {ref['ref']} (by {ref['who']}, {short(ref['at'])}). Nothing to do."
                    crm_step["colleague"] = True
                elif ctx.crm_record:
                    crm_step["detail"] = (f"Already in Zoho ({ctx.crm_record[0]} record {ctx.crm_record[1]}); "
                                          "your emails will be recorded there. Nothing to do.")
                    crm_step["colleague"] = True
                steps.append(crm_step)
                t = T["first_reply"]
            elif "declined" in signals:
                t = T["decline_reply"]
            else:
                t = T["reply"]
            steps.append(dict(
                id="reply", gated=True, enabled=True, crm_log=True,
                title="First reply to the customer (same day)" if not conv.replied_ever else "Reply to the customer",
                detail=("Fill in your answer before sending." if t.key == "reply" else
                        f"Template: {t.label}"),
                draft=_draft(t, vals, [email], inbound.get("cc", []), _re(inbound.get("subject") or subject),
                             in_reply_to=inbound.get("rfc_id", ""))))
            if "declined" in signals and tag.get("lost"):
                steps.append(dict(id="tag_lost", gated=False, enabled=True,
                                  title=f"Tag {tag['lost']} in Zoho and stop follow-ups",
                                  detail=f"Customer: “{signals['declined']}”"))
        elif conv.stage == "awaiting_customer":
            n = conv.followup_no
            variants = followup_variants(T, n, conv.quote_sent)
            last_by = "your" if out.get("sender") == s.user_email else f"{out.get('sender_name')}'s"
            steps.append(dict(
                id=f"followup_{n}", gated=True, enabled=True, crm_log=True, followup=n,
                title=f"Follow-up {n} of {n_total} ({STAGE_LABEL.get(n, 'firmer')})",
                detail=f"No answer since {last_by} email of {short(out.get('date'))}. "
                       "Your previous email is quoted underneath.",
                draft=_draft(variants[0], vals, out.get("to") or [email], out.get("cc", []),
                             _re(out.get("subject") or subject), in_reply_to=out.get("rfc_id", ""),
                             quote=_quote(out), variants=variants)))
        elif conv.stage in ("declined", "exhausted"):
            stage = "lost"
            if conv.stage == "exhausted" and tag.get("no_response"):
                stage = "no_response"
            if tag.get(stage):
                steps.append(dict(id=f"tag_{stage}", gated=False, enabled=True,
                                  title=f"Tag {tag[stage]} in Zoho and stop follow-ups",
                                  detail=(f"Customer: “{signals.get('declined', '')}”" if conv.stage == "declined"
                                          else f"No answer after {n_total} follow-ups")))
            if conv.stage == "declined":
                variants = followup_variants(T, min(max(conv.touches, 1), n_total), conv.quote_sent)
                steps.append(dict(
                    id="followup_anyway", gated=True, enabled=False, crm_log=True,
                    title="Or: follow up anyway", detail="Tick this instead if the customer is still in play.",
                    draft=_draft(variants[0], vals, out.get("to") or [email], out.get("cc", []),
                                 _re(out.get("subject") or subject), in_reply_to=out.get("rfc_id", ""),
                                 quote=_quote(out), variants=variants)))

    fp = (conv.newest_message_id if conv else None) or order.order_code or ""
    prev = {p["id"]: p for p in previous or [] if p.get("fp") == fp}
    for st in steps:
        st["fp"], st["state"] = fp, "pending"
        p = prev.get(st["id"])
        if p:
            st["enabled"] = p.get("enabled", st["enabled"])
            if p.get("draft") and p.get("draft_edited"):
                st["draft"] = {**st["draft"], **{k: p["draft"][k] for k in ("to", "cc", "subject", "body")
                                                 if k in p["draft"]}}
                st["draft_edited"] = True
            for k in ("state", "result", "draft_id", "crm"):
                if k in p:
                    st[k] = p[k]
    return steps
