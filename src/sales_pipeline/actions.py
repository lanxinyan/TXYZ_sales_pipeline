"""Carry out a decision made in the dashboard.

approve -> routine steps run now (Zoho, labels); gated steps become Gmail drafts.
send    -> one gated draft is sent (after any last edits).
"""
from __future__ import annotations

import logging

from .config import Settings
from .models import Order
from .pipeline import Pipeline, _company_from_email, validate
from .store import Record, Store
from .tasks import build_plan

log = logging.getLogger(__name__)


class Executor:
    def __init__(self, settings: Settings, store: Store, gmail=None, zoho=None):
        self.s, self.store, self.gmail, self.zoho = settings, store, gmail, zoho

    # ---------- decisions ----------

    def approve(self, thread_id: str, order: dict | None = None, steps: dict | None = None) -> Record:
        rec = self._get(thread_id)
        o = Order.model_validate(order) if order else rec.order
        plan = [dict(st) for st in rec.plan]
        for st in plan:
            choice = (steps or {}).get(st["id"])
            if not choice:
                continue
            if "enabled" in choice:
                st["enabled"] = bool(choice["enabled"])
            if st.get("gated") and choice.get("draft") and choice["draft"] != st.get("draft"):
                st["draft"], st["draft_edited"] = choice["draft"], True
        plan = build_plan(rec.kind, o, rec.subject, self.s, plan)  # refresh text from edited order
        issues = validate(o) if rec.kind == "order" else rec.issues
        if rec.kind == "order" and any(s["id"] == "zoho_so" and s["enabled"] for s in plan) and not o.order_code:
            raise ValueError("add the order/quote number before creating the Sales Order")
        self.store.update(thread_id, order=o, plan=plan, issues=issues, status="approved")

        for st in plan:
            if st["state"] not in ("pending", "failed"):
                continue
            if not st["enabled"]:
                st["state"] = "skipped"
                continue
            try:
                if st.get("gated"):
                    st["draft_id"] = self._draft(thread_id, st["draft"])
                    st["state"] = "drafted"
                else:
                    st["result"] = self._routine(thread_id, rec.kind, o, st["id"])
                    st["state"] = "done"
            except Exception as e:
                log.exception("step %s failed", st["id"])
                st["state"], st["result"] = "failed", str(e)
            self.store.update(thread_id, plan=plan)
        return self._settle(thread_id, plan)

    def send(self, thread_id: str, step_id: str, draft: dict | None = None) -> Record:
        rec = self._get(thread_id)
        plan = rec.plan
        st = next(s for s in plan if s["id"] == step_id)
        if st.get("state") not in ("drafted", "failed"):
            raise ValueError(f"step {step_id} is {st.get('state')}, nothing to send")
        if draft and draft != st.get("draft"):
            # The text changed after the draft was made: replace the Gmail draft.
            if st.get("draft_id") and self.gmail:
                self.gmail.delete_draft(st["draft_id"])
            st["draft"], st["draft_edited"] = draft, True
            st["draft_id"] = self._draft(thread_id, draft)
        try:
            if not self.gmail:
                raise RuntimeError("Gmail is not connected")
            if not st.get("draft_id"):
                st["draft_id"] = self._draft(thread_id, st["draft"])
            self.gmail.send_draft(st["draft_id"])
            st["state"], st["result"] = "sent", f"sent to {st['draft']['to']}"
        except Exception as e:
            st["state"], st["result"] = "failed", str(e)
        return self._settle(thread_id, plan)

    def discard(self, thread_id: str, step_id: str) -> Record:
        rec = self._get(thread_id)
        st = next(s for s in rec.plan if s["id"] == step_id)
        if st.get("draft_id") and self.gmail:
            try:
                self.gmail.delete_draft(st["draft_id"])
            except Exception as e:
                log.warning("could not delete draft: %s", e)
        st["state"] = "skipped"
        return self._settle(thread_id, rec.plan)

    def skip(self, thread_id: str) -> Record:
        self._get(thread_id)
        self.store.update(thread_id, status="skipped")
        if self.gmail:
            from .gmail_source import LABEL_SKIPPED

            self.gmail.set_label(thread_id, LABEL_SKIPPED)
        return self._get(thread_id)

    # ---------- steps ----------

    def _routine(self, thread_id: str, kind: str, o: Order, step_id: str) -> str:
        if step_id == "zoho_so":
            if not self.zoho:
                raise RuntimeError("Zoho is not connected")
            res = Pipeline(self.s, self.store, gmail=self.gmail, zoho=self.zoho).push(thread_id, force=True)
            return f"Sales Order {res['zoho_id']} ({res['status']})"
        if step_id == "zoho_contact":
            if not self.zoho:
                raise RuntimeError("Zoho is not connected")
            acc = self.zoho.find_or_create_account(o.customer.company or _company_from_email(o.customer.email), o)
            con = self.zoho.find_or_create_contact(o, acc)
            return f"Account {acc}, Contact {con}"
        if step_id == "label":
            from .gmail_source import LABEL_QUOTE, LABEL_SYNCED

            label = LABEL_QUOTE if kind == "quote_request" else LABEL_SYNCED
            if self.gmail:
                self.gmail.set_label(thread_id, label)
            return label
        raise ValueError(f"unknown step {step_id}")

    def _draft(self, thread_id: str, draft: dict) -> str | None:
        if not self.gmail:
            raise RuntimeError("Gmail is not connected")
        if not draft.get("to"):
            raise ValueError("draft has no recipient")
        thread = self.gmail.get_thread(thread_id)
        reply_to = thread.messages[-1].message_id if thread.messages else ""
        return self.gmail.create_draft(thread_id, draft["to"], draft["subject"], draft["body"], reply_to)

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
