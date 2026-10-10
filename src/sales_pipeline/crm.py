"""The customer's record in Zoho: find it (whoever created it), keep its
lifecycle tag right (已下单, 不买了, No reply ...), and record every reply as a follow-up note."""
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
DEFAULT_TAGS = {"ordered": "已下单", "lost": "不买了", "no_response": "No reply"}
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


INQUIRY_LABEL = re.compile(r"inquir|enquir|询价", re.I)
COMPANY_LABEL = re.compile(r"company|institution|organi[sz]ation|公司|单位|机构", re.I)
# Field layout assumed when Zoho's field list can't be read (standard Leads/Contacts).
STANDARD_FIELDS = [{"api_name": "Email", "data_type": "email"}, {"api_name": "Last_Name", "data_type": "text"},
                   {"api_name": "First_Name", "data_type": "text"}, {"api_name": "Company", "data_type": "text"},
                   {"api_name": "Phone", "data_type": "phone"}, {"api_name": "Description", "data_type": "textarea"}]


def discover_customer_modules(modules: list[dict]) -> list[str]:
    """Which Zoho modules hold customers, best first: the one labelled
    Inquiries/询价 (whatever its internal name), then Leads, then Contacts."""
    usable = [m for m in modules if m.get("api_supported", True) and m.get("api_name")]

    def label(m):
        return " ".join(str(m.get(k) or "") for k in ("plural_label", "singular_label", "module_name", "api_name"))

    found = [m["api_name"] for m in usable if INQUIRY_LABEL.search(label(m))]
    found += [name for name in ("Leads", "Contacts") if any(m["api_name"] == name for m in usable)]
    return list(dict.fromkeys(found)) or ["Contacts"]


class CustomerCRM:
    def __init__(self, zoho, s: Settings, tag_map: dict[str, str] | None = None):
        self.zoho, self.s = zoho, s
        self.tags = tag_map if tag_map is not None else load_tag_map(s.zoho_tag_file)
        self._cache: dict[str, tuple[str, str] | None] = {}
        self._modules: list[str] | None = list(s.zoho_customer_modules) or None
        self._fields: dict[str, list[dict]] = {}

    # ---------- which modules and fields ----------

    def modules(self) -> list[str]:
        if self._modules is None:
            try:
                self._modules = discover_customer_modules(self.zoho.list_modules())
            except Exception as e:
                log.warning("could not list Zoho modules (%s); using Contacts", e)
                self._modules = ["Contacts"]
        return self._modules

    def fields(self, module: str) -> list[dict]:
        if module not in self._fields:
            try:
                self._fields[module] = self.zoho.module_fields(module) or STANDARD_FIELDS
            except Exception as e:
                log.warning("could not read fields of %s (%s); assuming the standard ones", module, e)
                self._fields[module] = STANDARD_FIELDS
        return self._fields[module]

    def email_fields(self, module: str) -> list[str]:
        return [f["api_name"] for f in self.fields(module) if f.get("data_type") == "email"] or ["Email"]

    # ---------- finding the record ----------

    def find(self, email: str) -> tuple[str, str] | None:
        """(module, id) of the customer's record, searching the customer modules in order."""
        email = (email or "").lower()
        if not email:
            return None
        if email not in self._cache:
            for module in self.modules():
                rows = self.zoho.find_by_email(module, email, self.email_fields(module))
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
        module = self.modules()[0]
        rec = self.new_record(module, email, name, company, phone, description)
        rid = self.zoho.create(module, rec)
        log.info("created %s %s for %s", module, rid, email)
        self._cache[email.lower()] = (module, rid)
        return module, rid

    def new_record(self, module: str, email: str, name: str | None, company: str | None,
                   phone: str | None, description: str | None) -> dict:
        """Fill only fields this module really has (custom modules differ from Leads)."""
        fields = {f["api_name"]: f for f in self.fields(module)}
        name = (name or email.split("@")[0]).strip()
        first, _, last = name.rpartition(" ")
        rec: dict = {self.email_fields(module)[0]: email}
        if "Last_Name" in fields:
            rec["Last_Name"] = last or name
            if first and "First_Name" in fields:
                rec["First_Name"] = first
        elif "Name" in fields and fields["Name"].get("data_type") != "autonumber":
            rec["Name"] = name          # e.g. "Inquiry-0012345" names are auto-numbered: left to Zoho
        company_field = "Company" if "Company" in fields else next(
            (f["api_name"] for f in fields.values()
             if f.get("data_type") == "text" and COMPANY_LABEL.search(f.get("field_label", ""))), None)
        if company_field and (company or module == "Leads"):
            rec[company_field] = company or email.split("@")[1]
        phone_field = "Phone" if "Phone" in fields else next(
            (f["api_name"] for f in fields.values() if f.get("data_type") == "phone"), None)
        if phone and phone_field:
            rec[phone_field] = phone
        if description and "Description" in fields:
            rec["Description"] = description[:2000]
        return rec

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
