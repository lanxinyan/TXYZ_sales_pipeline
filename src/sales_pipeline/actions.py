"""Carry out a decision made in the dashboard.

approve -> routine steps run now (Zoho records, tags, labels); emails become Gmail drafts
           (or are sent straight away with approve-and-send).
send    -> one email is sent, after re-checking the thread and Zoho for anything a
           colleague (or the customer) did since the plan was made. Every email to a
           customer is then recorded as a follow-up note in Zoho.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from .config import Settings
from .conversation import (Who, display_name, first_line, forward_origin, fresh_text, invoice_status,
                           parse_date, short)
from .models import Order
from .pipeline import Pipeline, validate
from .store import Record, Store
from .tasks import build_plan
from .templates import PLACEHOLDER_REPLY

log = logging.getLogger(__name__)

STAGE_FOR_STEP = {"reply": "inquiry", "followup": "following_up", "followup_anyway": "following_up"}


class Conflict(Exception):
    """Something changed since the plan was made; the user must look before sending."""

    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


class Executor:
    def __init__(self, settings: Settings, store: Store, gmail=None, zoho=None, pipeline: Pipeline | None = None):
        self.s, self.store, self.gmail, self.zoho = settings, store, gmail, zoho
        self.pipeline = pipeline or Pipeline(settings, store, gmail=gmail, zoho=zoho)
        self.crm = self.pipeline.crm

    # ---------- decisions ----------

    def approve(self, thread_id: str, order: dict | None = None, steps: dict | None = None,
                send: bool = False, force: bool = False) -> Record:
        rec = self._get(thread_id)
        o = Order.model_validate(order) if order else rec.order
        plan = [dict(st) for st in rec.plan]
        for st in plan:
            choice = (steps or {}).get(st["id"])
            if not choice:
                continue
            if "enabled" in choice:
                st["enabled"] = bool(choice["enabled"])
            if st.get("gated") and choice.get("draft"):
                new = {**st["draft"], **{k: v for k, v in choice["draft"].items() if k in ("to", "cc", "subject", "body")}}
                if new != st["draft"]:
                    st["draft"], st["draft_edited"] = new, True
        if order and rec.kind == "order":
            # Re-word the drafts from the corrected order, keeping the user's choices.
            plan = build_plan(rec.kind, o, rec.conv, rec.subject, self.s,
                              self.pipeline._context(rec.kind, o, None), plan)
        issues = validate(o) if rec.kind == "order" else rec.issues
        if rec.kind == "order" and any(s["id"] == "zoho_so" and s["enabled"] for s in plan) and not o.order_code:
            raise ValueError("add the order/quote number before creating the Sales Order")
        if send:
            for st in plan:
                if st.get("gated") and st["enabled"] and st["state"] in ("pending", "failed"):
                    self._check_written(st)
        self.store.update(thread_id, order=o, plan=plan, issues=issues, status="approved")

        for st in plan:
            if st["state"] not in ("pending", "failed"):
                continue
            if not st["enabled"]:
                st["state"] = "skipped"
                continue
            try:
                if st.get("gated"):
                    st["draft_id"] = self._make_draft(self._get(thread_id), st)
                    st["state"] = "drafted"
                else:
                    st["result"] = self._routine(self._get(thread_id), o, st)
                    st["state"] = "done"
                    self.store.log(thread_id, f"{st['title']}: {st['result']}")
            except Exception as e:
                log.exception("step %s failed", st["id"])
                st["state"], st["result"] = "failed", str(e)
            self.store.update(thread_id, plan=plan)

        if rec.kind == "quote_request":
            closed = any(x["id"].startswith("tag_") and x["state"] == "done" for x in plan)
            emailed = any(x.get("gated") and x["state"] in ("drafted", "sent") for x in plan)
            if not closed and not emailed and not any(x["state"] == "failed" for x in plan):
                # Nothing went to the customer: keep the conversation alive, ask again tomorrow.
                self.store.update(thread_id, plan=plan)
                return self.snooze(thread_id, 1, why="no email was sent")
        rec = self._settle(thread_id, plan)
        if send:
            for sid in [x["id"] for x in plan if x["state"] == "drafted"]:
                current = self._get(thread_id)
                if any(x["id"] == sid and x["state"] == "drafted" for x in current.plan):
                    rec = self.send(thread_id, sid, force=force)
        return rec

    def send(self, thread_id: str, step_id: str, draft: dict | None = None, force: bool = False) -> Record:
        rec = self._get(thread_id)
        plan = rec.plan
        st = _step(plan, step_id)
        if st.get("state") not in ("drafted", "failed", "pending"):
            raise ValueError(f"“{st['title']}” is {st.get('state')}; nothing to send")
        if draft:
            new = {**st["draft"], **{k: v for k, v in draft.items() if k in ("to", "cc", "subject", "body")}}
            if new != st["draft"]:
                if st.get("draft_id") and self.gmail:
                    _quietly(self.gmail.delete_draft, st["draft_id"])
                st["draft"], st["draft_edited"], st["draft_id"] = new, True, None
        self._check_written(st)
        if not force:
            reasons = self.check(rec, st)
            if reasons:
                st["conflicts"] = reasons
                self.store.update(thread_id, plan=plan)
                raise Conflict(reasons)
        if not self.gmail:
            raise RuntimeError("Gmail is not connected")
        try:
            if not st.get("draft_id"):
                st["draft_id"] = self._make_draft(rec, st)
            sent_id = self.gmail.send_draft(st["draft_id"])
        except Exception as e:
            st["state"], st["result"] = "failed", f"not sent: {e}"
            return self._settle(thread_id, plan)
        to = st["draft"]["to"]
        st.pop("conflicts", None)
        st["state"], st["result"] = "sent", f"Sent to {to} on {short(_now())}"
        self.store.update(thread_id, plan=plan)
        self.store.log(thread_id, f"Sent “{st['title']}” to {to}" + (" (sent anyway)" if force else ""))
        if st.get("crm_log"):
            st["crm"] = self._record_in_crm(rec, st, sent_id)
            self.store.update(thread_id, plan=plan)
        if rec.kind == "quote_request" and self.gmail is not None and not any(
                x["state"] == "drafted" for x in plan if x is not st):
            # Re-read the thread: the next follow-up is now scheduled from this email.
            try:
                self.pipeline.refresh(thread_id)
                return self._get(thread_id)
            except Exception as e:
                log.warning("refresh after send failed: %s", e)
        return self._settle(thread_id, plan)

    def discard(self, thread_id: str, step_id: str) -> Record:
        rec = self._get(thread_id)
        st = _step(rec.plan, step_id)
        if st.get("draft_id") and self.gmail:
            _quietly(self.gmail.delete_draft, st["draft_id"])
        st["state"], st["draft_id"] = "skipped", None
        self.store.log(thread_id, f"Discarded “{st['title']}”")
        if rec.kind == "quote_request" and not any(x["state"] == "drafted" for x in rec.plan):
            self.store.update(thread_id, plan=rec.plan)
            return self.snooze(thread_id, 1, why="email discarded")
        return self._settle(thread_id, rec.plan)

    def skip(self, thread_id: str) -> Record:
        self._get(thread_id)
        self.store.update(thread_id, status="skipped")
        self.store.log(thread_id, "Skipped")
        if self.gmail:
            from .gmail_source import LABEL_SKIPPED

            _quietly(self.gmail.set_label, thread_id, LABEL_SKIPPED)
        return self._get(thread_id)

    def snooze(self, thread_id: str, days: float, why: str = "") -> Record:
        due = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")
        self.store.update(thread_id, status="scheduled", due_at=due)
        self.store.log(thread_id, f"Snoozed until {short(due)}" + (f" ({why})" if why else ""))
        return self._get(thread_id)

    def outcome(self, thread_id: str, outcome: str) -> Record:
        """已下单 / 不买了 / no response: tag the customer in Zoho and stop follow-ups."""
        rec = self._get(thread_id)
        if outcome not in ("ordered", "lost", "no_response"):
            raise ValueError(f"unknown outcome {outcome}")
        email = _customer_email(rec)
        if not email:
            raise ValueError("no customer email on this item")
        if self.crm is None:
            raise RuntimeError("Zoho is not connected, so the tag can't be set")
        tag = self.crm.set_stage(email, outcome, **_create_info(rec))
        if not tag:
            raise ValueError(f"no Zoho tag is mapped for '{outcome}' (run `sales-pipeline zoho-setup`)")
        self.crm.log_followup(email, f"Marked {tag} in Sales Desk", f"Marked {tag} by {self.s.sender_name}.\n{rec.thread_url}",
                              **_create_info(rec))
        for st in rec.plan:
            if st.get("state") == "drafted" and st.get("draft_id") and self.gmail:
                _quietly(self.gmail.delete_draft, st["draft_id"])
                st["state"] = "skipped"
        self.store.update(thread_id, status="done", plan=rec.plan, issues=[f"closed: {tag}"])
        self.store.log(thread_id, f"Tagged {tag} in Zoho; follow-ups stopped")
        if outcome == "ordered":
            self.pipeline.close_customer_threads(email, rec.order_code, f"customer ordered ({tag})")
        return self._get(thread_id)

    def ignore(self, thread_id: str) -> Record:
        """Not a customer (e.g. a vendor): never suggest follow-ups for this domain."""
        rec = self._get(thread_id)
        email = _customer_email(rec)
        if not email:
            raise ValueError("no external address on this item")
        domain = email.split("@")[1]
        self.store.ignore_domain(domain)
        self.store.update(thread_id, status="skipped", issues=[f"{domain} is not a customer"])
        self.store.log(thread_id, f"{domain} marked as not a customer")
        return self._get(thread_id)

    def retry_crm(self, thread_id: str, step_id: str) -> Record:
        rec = self._get(thread_id)
        st = _step(rec.plan, step_id)
        st["crm"] = self._record_in_crm(rec, st, st.get("sent_id") or "")
        self.store.update(thread_id, plan=rec.plan)
        return self._settle(thread_id, rec.plan)

    # ---------- checks right before sending ----------

    def check(self, rec: Record, st: dict) -> list[str]:
        """What a colleague (or the customer) did since this plan was made."""
        reasons: list[str] = []
        email = _customer_email(rec)
        if self.gmail is not None:
            fresh = self.gmail.get_thread(rec.thread_id, attachments=False)
            if st["id"] == "accounting":
                threads = [fresh]
                code = rec.order.order_code if rec.order else None
                if code:
                    for tid in self.gmail.search(f'"{code}" newer_than:180d', 10):
                        if tid != rec.thread_id:
                            threads.append(self.gmail.get_thread(tid, attachments=False))
                inv = invoice_status(threads, self.s, self.s.user_email)
                if inv["state"] == "done":
                    reasons.append("Accounting has already been contacted: " + inv["evidence"][-1])
                elif inv["state"] == "hold":
                    reasons.append("A colleague asked to hold the invoice: " + inv["evidence"][-1])
            elif rec.kind == "quote_request":
                reasons += self._new_activity(rec, fresh)
        if self.crm is not None and email and st["id"] != "accounting":
            try:
                closed = self.crm.closing_tag(email)
            except Exception as e:
                closed = None
                log.warning("Zoho tag check failed: %s", e)
            # Tags this same plan just set (e.g. 不买了 with a thank-you note) are not a colleague's doing.
            own = {self.crm.tags.get(x["id"][4:]) for x in rec.plan
                   if x["id"].startswith("tag_") and x.get("state") == "done"}
            if closed and closed not in own:
                reasons.append(f"The customer is already tagged {closed} in Zoho")
        return reasons

    def _new_activity(self, rec: Record, fresh) -> list[str]:
        known = rec.conv.newest_message_id if rec.conv else None
        msgs = sorted(fresh.messages, key=lambda m: parse_date(m.date) or datetime.min.replace(tzinfo=timezone.utc))
        ids = [m.id for m in msgs]
        new = msgs[ids.index(known) + 1:] if known in ids else []
        who = Who(self.s, self.s.user_email, self.store.ignored_domains())
        out = []
        for m in new:
            sender = m.sender.lower()
            text = first_line(fresh_text(m.body), 140)
            if who.customer(sender) or (who.system(sender)):
                out.append(f"The customer wrote on {short(m.date)}: “{text}”")
            elif who.internal(sender) and any(who.customer(r.lower()) for r in m.to + m.cc):
                if sender == self.s.user_email:
                    out.append(f"You already replied on {short(m.date)} (outside Sales Desk): “{text}”")
                else:
                    out.append(f"{display_name(m)} already replied to the customer on {short(m.date)}: “{text}”")
            elif who.internal(sender) and sender != self.s.user_email:
                origin = forward_origin(m.body)
                if origin and who.customer(origin.get("email", "")):
                    out.append(f"{display_name(m)} forwarded a new message from the customer on {short(m.date)}")
        return out

    # ---------- steps ----------

    def _routine(self, rec: Record, o: Order, st: dict) -> str:
        sid = st["id"]
        email = _customer_email(rec)
        if sid == "zoho_so":
            if not self.zoho:
                raise RuntimeError("Zoho is not connected")
            res = self.pipeline.push(rec.thread_id, force=True)
            self.pipeline.close_customer_threads(email, o.order_code, "order placed")
            return f"Sales Order {res['zoho_id']} ({res['status']})"
        if sid in ("tag_ordered", "tag_lost", "tag_no_response"):
            if self.crm is None:
                raise RuntimeError("Zoho is not connected")
            stage = sid[4:]
            tag = self.crm.set_stage(email, stage, **_create_info(rec))
            if stage == "ordered":
                self.pipeline.close_customer_threads(email, o.order_code, f"customer ordered ({tag})")
            return f"tagged {tag}" + (", follow-ups stopped" if stage != "ordered" else "")
        if sid == "crm_inquiry":
            if self.crm is None:
                raise RuntimeError("Zoho is not connected")
            module, rid = self.crm.ensure(email, **_create_info(rec))
            tag = self.crm.set_stage(email, "inquiry", **_create_info(rec))
            return f"{module} {rid}" + (f", tagged {tag}" if tag else "")
        if sid == "label":
            from .gmail_source import LABEL_QUOTE, LABEL_SYNCED

            label = LABEL_QUOTE if rec.kind == "quote_request" else LABEL_SYNCED
            if self.gmail:
                self.gmail.set_label(rec.thread_id, label)
            return label
        raise ValueError(f"unknown step {sid}")

    def _make_draft(self, rec: Record, st: dict) -> str:
        if not self.gmail:
            raise RuntimeError("Gmail is not connected")
        d = st["draft"]
        to = _split(d.get("to"))
        if not to:
            raise ValueError("the email has no recipient")
        thread_id = (st.get("target_thread") or rec.thread_id) if d.get("in_thread") else None
        return self.gmail.create_draft(thread_id, to, d["subject"], d["body"], d.get("in_reply_to", ""),
                                       _split(d.get("cc")), d.get("quote"))

    def _record_in_crm(self, rec: Record, st: dict, sent_id: str) -> str:
        """Every email to a customer becomes a follow-up note in Zoho (+ lifecycle tag)."""
        n = st.get("followup")
        title = {"reply": "Reply", "confirm": "Order confirmation"}.get(st["id"], "Follow-up")
        if st["id"] == "reply" and rec.conv and not rec.conv.replied_ever:
            title = "First reply"
        if n:
            title = f"Follow-up #{n}"
        title = f"{title} (email) {datetime.now(timezone.utc):%Y-%m-%d}"
        st["sent_id"] = sent_id
        if self.crm is None:
            return "Not recorded in Zoho (not connected); it will be recorded on the next scan once it is"
        email = _split(st["draft"]["to"])[0]
        try:
            content = f"{st['draft']['body']}\n\nTo: {st['draft']['to']}\nSubject: {st['draft']['subject']}\n{rec.thread_url}"
            self.crm.log_followup(email, title, content, **_create_info(rec))
            if sent_id:
                self.store.mark_crm_logged(sent_id, rec.thread_id, "")
            stage = STAGE_FOR_STEP.get("followup" if n else st["id"])
            if stage == "inquiry" and rec.conv and rec.conv.replied_ever:
                stage = None
            tag = self.crm.set_stage(email, stage, **_create_info(rec)) if stage else ""
            self.store.log(rec.thread_id, f"Recorded “{title}” in Zoho" + (f", tagged {tag}" if tag else ""))
            return f"Recorded in Zoho as “{title}”" + (f", tagged {tag}" if tag else "")
        except Exception as e:
            log.warning("Zoho follow-up note failed: %s", e)
            self.store.log(rec.thread_id, f"Zoho note failed ({e}); will retry on next scan")
            return f"Not recorded in Zoho yet ({e}); it will be retried on the next scan"

    @staticmethod
    def _check_written(st: dict) -> None:
        if st.get("gated") and PLACEHOLDER_REPLY in (st.get("draft") or {}).get("body", ""):
            raise ValueError("Write your reply first (replace “[write your reply here]”)")

    # ---------- helpers ----------

    def _get(self, thread_id: str) -> Record:
        rec = self.store.get(thread_id)
        if rec is None:
            raise KeyError(thread_id)
        return rec

    def _settle(self, thread_id: str, plan: list[dict]) -> Record:
        states = {s["state"] for s in plan}
        status = ("failed" if "failed" in states else
                  "awaiting_send" if "drafted" in states else "done")
        rec = self._get(thread_id)
        self.store.update(thread_id, plan=plan, status=status, zoho_id=rec.zoho_id)
        return self._get(thread_id)


def _step(plan: list[dict], step_id: str) -> dict:
    for st in plan:
        if st["id"] == step_id:
            return st
    raise KeyError(f"no step {step_id}")


def _split(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [v.strip() for v in value if v.strip()]
    return [v.strip() for v in value.replace(";", ",").split(",") if v.strip()]


def _customer_email(rec: Record) -> str:
    if rec.conv and rec.conv.customer_emails:
        return rec.conv.customer_emails[0]
    return (rec.order.customer.email if rec.order else "") or ""


def _create_info(rec: Record) -> dict:
    """Details used if the customer's Zoho record has to be created."""
    c = rec.conv
    o = rec.order
    return {"name": (c.customer_name if c else None) or (o.customer.contact_name if o else None),
            "company": (c.company if c else None) or (o.customer.company if o else None),
            "phone": (c.phone if c else None) or (o.customer.phone if o else None),
            "description": (c.topic if c else None)}


def _quietly(fn, *args):
    try:
        return fn(*args)
    except Exception as e:
        log.warning("%s failed: %s", getattr(fn, "__name__", fn), e)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
