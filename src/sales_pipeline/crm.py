"""The customer's record in Zoho: find it (whoever created it), keep its
lifecycle tag right (已下单, 不买了 ...), and record every reply as a follow-up note."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .config import Settings

log = logging.getLogger(__name__)

# Lifecycle stages, in order. Only stages mapped to a tag are used.
STAGES = {
    "inquiry": "new inquiry received",
    "quoted": "quote sent",
    "following_up": "following up, no answer yet",
    "ordered": "customer ordered",
    "lost": "customer is not buying",
    "no_response": "no answer after all follow-ups",
}
DEFAULT_TAGS = {"ordered": "已下单", "lost": "不买了"}
# How existing Zoho tag names are recognised when building the map.
SUGGEST = {
    "ordered": r"已下单|下单|已订|成交|ordered|won",
    "lost": r"不买|放弃|丢单|lost|not buying",
    "no_response": r"无回复|未回复|没回复|no.?response|no.?reply",
    "quoted": r"已报价|报价|quoted",
    "following_up": r"跟进|follow",
    "inquiry": r"询价|新询|inquiry",
}
CLOSING = ("ordered", "lost", "no_response")


def load_tag_map(path: str) -> dict[str, str]:
    p = Path(path)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return {k: v for k, v in data.items() if k in STAGES and v}
        except (ValueError, OSError) as e:
            log.warning("ignoring unreadable %s: %s", path, e)
    return dict(DEFAULT_TAGS)


def suggest_tag_map(tag_names: list[str]) -> dict[str, str]:
    """Match the tags that already exist in Zoho to lifecycle stages."""
    out = {}
    for stage, rx in SUGGEST.items():
        hit = next((t for t in tag_names if re.search(rx, t, re.I)), None)
        if hit and hit not in out.values():
            out[stage] = hit
    for stage, tag in DEFAULT_TAGS.items():
        out.setdefault(stage, tag)
    return out


class CustomerCRM:
    def __init__(self, zoho, s: Settings, tag_map: dict[str, str] | None = None):
        self.zoho, self.s = zoho, s
        self.tags = tag_map if tag_map is not None else load_tag_map(s.zoho_tag_file)
        self._cache: dict[str, tuple[str, str] | None] = {}

    # ---------- finding the record ----------

    def find(self, email: str) -> tuple[str, str] | None:
        """(module, id) of the customer's record, searching e.g. Leads then Contacts."""
        email = (email or "").lower()
        if not email:
            return None
        if email not in self._cache:
            for module in self.s.zoho_customer_modules:
                rows = self.zoho.find_by_email(module, email)
                if rows:
                    # Only hits are remembered: a record may be created elsewhere at any time.
                    self._cache[email] = (module, rows[0]["id"])
                    break
        return self._cache.get(email)

    def ensure(self, email: str, name: str | None = None, company: str | None = None,
               phone: str | None = None, description: str | None = None) -> tuple[str, str]:
        found = self.find(email)
        if found:
            return found
        module = self.s.zoho_customer_modules[0]
        name = (name or email.split("@")[0]).strip()
        first, _, last = name.rpartition(" ")
        rec = {"Last_Name": last or name, "Email": email}
        if first:
            rec["First_Name"] = first
        if company or module == "Leads":
            rec["Company"] = company or email.split("@")[1]
        if phone:
            rec["Phone"] = phone
        if description:
            rec["Description"] = description[:2000]
        rid = self.zoho.create(module, rec)
        log.info("created %s %s for %s", module, rid, email)
        self._cache[email.lower()] = (module, rid)
        return module, rid

    # ---------- tags ----------

    def current_tags(self, email: str) -> list[str]:
        found = self.find(email)
        return self.zoho.record_tags(*found) if found else []

    def closing_tag(self, email: str) -> str | None:
        """A colleague (or you) already closed this customer in Zoho?"""
        closing = {self.tags[s] for s in CLOSING if s in self.tags}
        return next((t for t in self.current_tags(email) if t in closing), None)

    def set_stage(self, email: str, stage: str, **create) -> str:
        """Tag the customer's record with this stage's tag and remove the other
        lifecycle tags, so a record never says 已下单 and 不买了 at once."""
        tag = self.tags.get(stage)
        if not tag:
            return ""
        module, rid = self.ensure(email, **create)
        present = self.zoho.record_tags(module, rid)
        others = [t for st, t in self.tags.items() if st != stage and t in present]
        self.zoho.remove_tags(module, rid, others)
        if tag not in present:
            self.zoho.add_tags(module, rid, [tag])
        return tag

    # ---------- follow-up log ----------

    def log_followup(self, email: str, title: str, content: str, **create) -> str:
        module, rid = self.ensure(email, **create)
        return self.zoho.add_note(module, rid, title, content)
