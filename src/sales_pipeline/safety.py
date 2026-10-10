"""Hard rules for every email Sales Desk prepares, checked again right before a
Gmail draft is made (so edits in the dashboard are covered too):

1. An email to a customer goes to customers only. No colleague (e.g. Emma Flores,
   usa@creative-biostructure.com) and no internal mailbox is put in To or Cc, or named
   in the text (your own address in a signature is fine).
2. Nothing in Chinese reaches a customer: internal briefs (the accounting note,
   colleagues' comments) stay internal, and the quoted earlier email must be clean too.
"""
from __future__ import annotations

import re

from .extract_rules import is_internal

CJK = re.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


class UnsafeEmail(ValueError):
    pass


def addresses(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [v.strip().lower() for v in value if v and v.strip()]
    return [v.strip().lower() for v in str(value).replace(";", ",").split(",") if v.strip()]


def internal(addr: str, s) -> bool:
    return is_internal(addr, s.internal_domains)


def customers_only(addrs, s) -> list[str]:
    """Drop colleagues, internal mailboxes and system senders (website form mailer)."""
    out = []
    for a in addresses(addrs):
        domain = a.rsplit("@", 1)[-1]
        if internal(a, s) or any(domain == d or domain.endswith("." + d) for d in s.system_domains):
            continue
        out.append(a)
    return list(dict.fromkeys(out))


def has_chinese(text: str | None) -> bool:
    return bool(text and CJK.search(text))


def problems(draft: dict, s) -> list[str]:
    """Why this draft must not be made, or [] when it is fine."""
    rcpts = addresses(draft.get("to")) + addresses(draft.get("cc"))
    if not any(not internal(r, s) for r in rcpts):
        return []          # internal-only email (e.g. accounting): Chinese is fine there
    out = []
    ours = [r for r in rcpts if internal(r, s)]
    if ours:
        out.append("This email goes to a customer, so colleagues and internal mailboxes can't be on it: remove "
                   + ", ".join(ours))
    written = [a.lower() for a in EMAIL.findall((draft.get("subject") or "") + "\n" + (draft.get("body") or ""))]
    named = [a for a in dict.fromkeys(written) if internal(a, s) and a != (s.user_email or "").lower()]
    if named:
        out.append("This email goes to a customer but names internal addresses in the text: " + ", ".join(named))
    if has_chinese(draft.get("subject")) or has_chinese(draft.get("body")):
        out.append("This email goes to a customer but contains Chinese text (internal notes must not reach the "
                   "customer)")
    q = draft.get("quote") or {}
    if has_chinese(q.get("body")):
        out.append("The earlier email quoted underneath contains Chinese text")
    return out


def check(draft: dict, s) -> None:
    found = problems(draft, s)
    if found:
        raise UnsafeEmail("; ".join(found))
