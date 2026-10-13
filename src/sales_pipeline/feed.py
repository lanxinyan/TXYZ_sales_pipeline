"""The Gmail feed for Cowork.

Until Sales Desk may write to Zoho itself, Cowork updates the Inquiry records from
this file (and asks you before each change). It holds what happened in the customer
conversations you are involved in, already in the shape of the CRM rulebook:

* one running note per inquiry, each entry `MMDDYY` + code + `: ` + a few words,
  with f = we followed up, r = the customer replied, q = quote sent; other events are
  written as words (`101226: PO received`, `100726: teleconference`);
* the Inquiry number when Gmail has it ("Inquiry-0031002 crm created");
* tag facts (No reply after 4 unanswered follow-ups, 已下单, how a quote was sent) and,
  for a new inquiry, suggestions for the fields to fill in.

Each export only carries what earlier exports did not (unless asked for everything).
"""
from __future__ import annotations

import logging
import re
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .conversation import (ACK_ONLY, CRM_REF, DECLINE, ORDER_INTENT, QUOTE_ASK, REVISIT_MARK, Who, display_name,
                           first_line,
                           form_fields, forward_origin, fresh_text, owner_is_me, parse_date, quote_statement, short)
from .models import EmailMessage, EmailThread
from .store import Record

log = logging.getLogger(__name__)

FREE_MAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "hotmail.com", "outlook.com", "live.com", "msn.com",
    "aol.com", "icloud.com", "me.com", "mail.com", "gmx.com", "gmx.de", "proton.me", "protonmail.com", "qq.com",
    "163.com", "126.com", "yeah.net", "sina.com", "sohu.com", "foxmail.com", "naver.com", "yandex.ru",
}
INQUIRY_NO = re.compile(r"\bInquiry-\d{5,}\b", re.I)
PO = re.compile(r"\bPO\b|purchase order", re.I)
NDA = re.compile(r"\bNDA\b|non-?disclosure|confidentiality agreement", re.I)
SIGNED = re.compile(r"\bsign(?:ed)?\b|\bexecuted\b|countersign", re.I)
TELECON = re.compile(
    r"thank(?:s| you) for (?:the|your|joining|taking)[^.\n]{0,40}\b(?:call|meeting|teleconference|zoom|teams)\b|"
    r"\b(?:great|nice|good) (?:talking|speaking|meeting) (?:with|to) you|\bteleconference\b", re.I)
SAMPLES_IN = re.compile(r"\bsamples? (?:have |has |were |was )?(?:arrived|been received|received)\b|"
                        r"\breceived (?:the|your) samples?\b", re.I)
DISCOUNT = re.compile(r"\bdiscount|lower (?:the )?price|best price|\bbudget\b", re.I)
TIMELINE = re.compile(r"turnaround|timeline|how long|lead time", re.I)
SAMPLE = re.compile(r"\bsamples?\b", re.I)
OUR_TEAMS = ("CBSXY", "CBSRX")      # the rulebook's scope; CBSMA and the rest are never touched


@dataclass
class Entry:
    at: datetime
    code: str          # f / r / q, or "" for a word event
    words: str
    who: str
    excerpt: str
    key: str

    def line(self) -> str:
        return f"{self.at.astimezone():%m%d%y}{self.code}: {self.words}"


# ---------- reading one conversation ----------

def _pdfs(m: EmailMessage) -> list[str]:
    return [n for n in m.attachment_names if n.lower().endswith(".pdf")]


def _reply_words(text: str, m: EmailMessage) -> tuple[str, str]:
    """(code, words) for a customer's email."""
    names = " ".join(m.attachment_names)
    if PO.search(names) or (PO.search(text) and ORDER_INTENT.search(text) and (_pdfs(m) or "attached" in text.lower())):
        return "", "PO received"
    for rx, words in ((DECLINE, "not interested"), (ORDER_INTENT, "wants to order"), (DISCOUNT, "wants discount"),
                      (QUOTE_ASK, "asked for quote"), (TIMELINE, "asked timeline"), (SAMPLE, "asked about samples")):
        if rx.search(text):
            return "r", words
    if len(text) < 140 and ACK_ONLY.search(text) and "?" not in text:
        return "r", "thanks"
    return "r", "has questions" if "?" in text else "replied"


def quote_numbers(text: str, names: list[str], s) -> list[str]:
    found = re.findall(s.order_code_regex, text + "\n" + "\n".join(names))
    return list(dict.fromkeys(found))


def read_thread(thread: EmailThread, rec: Record, s, ignored=frozenset()) -> dict:
    """Everything the feed needs from one Gmail thread."""
    who = Who(s, s.user_email, ignored)
    me = who.me
    msgs = sorted(thread.messages, key=lambda m: parse_date(m.date) or datetime.min.replace(tzinfo=timezone.utc))
    out = {"entries": [], "inquiry": [], "quotes": [], "quote_way": None, "tony_replied": None,
           "channel": None, "internal_people": [], "last_customer": None}
    seen_inbound = False
    since_customer = 0
    customer_emails = 0     # how many times the customer has written (the inquiry included)
    for m in msgs:
        at = parse_date(m.date)
        if not at:
            continue
        sender = (m.sender or "").lower()
        recips = [r.lower() for r in m.to + m.cc]
        text = fresh_text(m.body)
        for found in INQUIRY_NO.findall(m.subject + "\n" + text):
            if found not in out["inquiry"]:
                out["inquiry"].append(found)
        excerpt = first_line(text, 180)

        def add(code, words, by):
            out["entries"].append(Entry(at, code, words, by, excerpt, f"{thread.id}:{m.id}:{code}:{words}"))

        customer_text = None
        if who.customer(sender):
            customer_text = text
            out["channel"] = out["channel"] or ("email to you" if me in recips else "email to " + ", ".join(
                r for r in recips if who.internal(r))[:80])
        elif who.system(sender) and form_fields(m.body).get("email"):
            customer_text = form_fields(m.body).get("topic") or ""
            out["channel"] = out["channel"] or "website form"
        elif who.internal(sender):
            ext = [r for r in recips if who.customer(r)]
            if not ext:
                origin = forward_origin(m.body)
                if origin and who.customer(origin.get("email", "")):
                    customer_text = origin.get("text") or ""
                    excerpt = first_line(customer_text, 180)
                    out["channel"] = out["channel"] or (
                        "website form, forwarded by " + display_name(m) if "Inquiry Information" in m.body
                        else "forwarded by " + display_name(m))
                for r in [sender, *recips]:
                    if who.internal(r) and r != me and r not in out["internal_people"]:
                        out["internal_people"].append(r)
                ref = CRM_REF.search(text)
                if ref and ref.group(1) not in out["inquiry"]:
                    out["inquiry"].append(ref.group(1))
            else:
                since_customer += 1
                by = "Tony" if sender == me else display_name(m)
                if sender == me:
                    out["tony_replied"] = out["tony_replied"] or at
                nums = quote_numbers(text, m.attachment_names, s)
                new_nums = [n for n in nums if n not in out["quotes"]]   # an old number mentioned again isn't a new quote
                statement = quote_statement(text)       # "Below is our quote", not "we will send a quote"
                quote_file = [a for a in m.attachment_names if re.search(r"quot", a, re.I)]
                if new_nums or statement or quote_file:
                    out["quotes"] += new_nums
                    pdf = [a for a in _pdfs(m) if re.search(r"quot", a, re.I) or any(n in a for n in nums)]
                    out["quote_way"] = {"date": at, "numbers": new_nums or nums, "pdf": pdf,
                                        "formal": bool(re.search(r"formal quot", statement, re.I))}
                    add("q", ", ".join(new_nums or nums) or "quote sent", by)
                elif REVISIT_MARK.search(text):
                    add("f", "revisit", by)
                elif since_customer == 1:
                    add("f", ("first reply" if customer_emails == 1 else "answered") if seen_inbound
                        else "first email", by)
                else:   # the 1st email after theirs is the answer; then follow-ups 1, 2, 3, 4
                    add("f", f"follow-up {since_customer - 1}", by)
                if TELECON.search(text):
                    add("", "teleconference", by)
                if SAMPLES_IN.search(text):
                    add("", "samples received", by)
                if NDA.search(text + " ".join(m.attachment_names)) and SIGNED.search(text):
                    add("", "NDA signed", by)

        if customer_text is not None:
            if seen_inbound:
                code, words = _reply_words(customer_text, m)
                add(code, words, "customer")
            if NDA.search(customer_text + " ".join(m.attachment_names)) and SIGNED.search(customer_text):
                add("", "NDA signed", "customer")
            if TELECON.search(customer_text):
                add("", "teleconference", "customer")
            seen_inbound = True
            since_customer = 0
            customer_emails += 1
            out["last_customer"] = at
    return out


def grade(email: str) -> tuple[str, str]:
    """Inquiry Level / Customer Type suggestion (the two are always the same)."""
    domain = email.rsplit("@", 1)[-1].lower()
    if domain in FREE_MAIL:
        return "D", "free-mail address"
    if re.search(r"\.gov(\.[a-z]{2})?$|\.mil$", domain):
        return "A", "government address"
    if re.search(r"\.edu(\.[a-z]{2})?$|\.ac\.[a-z]{2}$", domain) or re.search(r"univ|college|institut", domain):
        return "B", "academic address"
    return "", "company: A for giant pharma, B for small-to-medium pharma, C for a small or lesser-known company"


# ---------- the export ----------

def _customer(rec: Record) -> tuple[str, str, str, str, str]:
    c, o = rec.conv, rec.order
    email = (c.customer_emails[0] if c and c.customer_emails else None) or (o.customer.email if o else None) or ""
    name = (c.customer_name if c else None) or (o.customer.contact_name if o else None) or ""
    company = (c.company if c else None) or (o.customer.company if o else None) or ""
    phone = (c.phone if c else None) or (o.customer.phone if o else None) or ""
    topic = (c.topic if c else None) or ""
    return email.lower(), name, company, phone, topic


def _involved(rec: Record) -> str | None:
    """Why this conversation is Tony's, or None (then Cowork must leave it alone)."""
    c = rec.conv
    if rec.kind == "order" and rec.order and rec.order.customer.email:
        return "order sent to you"
    if rec.kind != "quote_request" or not c or not c.customer_emails or rec.status == "skipped":
        return None
    if c.i_participated:
        return "you wrote to the customer"
    if not c.replied_ever and owner_is_me(c):
        return "new inquiry sent to you, not answered yet"
    return None


def teams(codes: list[str]) -> list[str]:
    """CBSXY10052601 -> CBSXY: the team is in the quote/order number."""
    return list(dict.fromkeys(c[:5].upper() for c in codes if len(c) >= 5))


def collect(pipeline, everything: bool = False, days: int = 30, lock=None, left_out: list | None = None) -> list[dict]:
    s, store = pipeline.s, pipeline.store
    lock = lock or nullcontext()
    since = datetime.now(timezone.utc) - timedelta(days=days)
    orders = [r for r in store.list() if r.kind == "order" and r.order and r.order.customer.email]
    items_by_thread: dict[str, list[dict]] = {}
    for it in store.feed_items(pending_only=not everything):
        items_by_thread.setdefault(it["thread_id"], []).append(it)
    sections = []
    for rec in store.list():
        why = _involved(rec)
        if not why:
            continue
        email, name, company, phone, topic = _customer(rec)
        try:
            with lock:
                thread = pipeline.gmail.get_thread(rec.thread_id, attachments=False) if pipeline.gmail else None
        except Exception as e:
            log.warning("feed: could not read %s: %s", rec.thread_id, e)
            if left_out is not None:     # not marked as sent, so it comes in the next feed
                left_out.append(f"{email or rec.subject} (Gmail couldn't be read just now; in the next feed)")
            continue
        if thread is None:
            continue
        info = read_thread(thread, rec, s, store.ignored_domains())
        codes = info["quotes"] + ([rec.order.order_code] if rec.kind == "order" and rec.order and
                                  rec.order.order_code else [])
        team = teams(codes)
        if any(t not in OUR_TEAMS for t in team):
            if left_out is not None:
                left_out.append(f"{email or rec.subject} ({', '.join(team)})")
            continue
        entries = [e for e in info["entries"] if e.at >= since and (everything or not store.feed_seen(e.key))]
        if rec.kind == "order" and rec.order:
            o = rec.order
            first = parse_date(thread.messages[0].date) if thread.messages else None
            if first and first >= since:
                k = f"{rec.thread_id}:order:{o.order_code}"
                if everything or not store.feed_seen(k):
                    entries.append(Entry(first, "", "PO received", "order form",
                                         f"Order {o.order_code or ''} {f'${o.total:,.0f}' if o.total else ''}".strip(), k))
        tags, keys = [], []
        n_total = len(s.followup_days)
        c = rec.conv
        if rec.kind == "quote_request" and c and c.touches > n_total and c.stage in ("awaiting_customer", "exhausted"):
            k = f"{rec.thread_id}:tag:No reply:{c.last_outbound_at}"
            if everything or not store.feed_seen(k):
                tags.append(f"add `No reply`: {c.touches - 1} follow-ups without an answer "
                            f"(last one {short(c.last_outbound_at)})")
                keys.append(k)
        if rec.kind == "order":
            k = f"{rec.thread_id}:tag:ordered"
            if everything or not store.feed_seen(k):
                tags.append(f"add `{pipeline.tags.get('ordered', '已下单')}`: order "
                            f"{rec.order.order_code or ''} placed")
                keys.append(k)
        items = items_by_thread.get(rec.thread_id, [])
        for it in items:
            tags.append(f"{it['text']} (you chose this in Sales Desk on {short(it['ts'])})")
        new_inquiry = not info["inquiry"] and rec.kind == "quote_request"
        create_key = f"{rec.thread_id}:create"
        ask_create = new_inquiry and (everything or not store.feed_seen(create_key))
        if not (entries or tags or ask_create):
            continue
        if ask_create:
            keys.append(create_key)
        mine = [o for o in orders if o.order.customer.email.lower() == email]
        big = [o for o in mine if (o.order.total or 0) > 20000]
        # An order that came from this very quote doesn't make them a returning customer.
        earlier = [o for o in mine if o.thread_id != rec.thread_id and o.order.order_code not in codes]
        sections.append({
            "rec": rec, "why": why, "email": email, "name": name, "company": company, "phone": phone,
            "topic": topic, "info": info, "entries": sorted(entries, key=lambda e: e.at), "tags": tags,
            "keys": keys + [e.key for e in entries], "item_ids": [it["id"] for it in items],
            "create": ask_create, "key_customer": big, "returned": bool(earlier), "team": team,
        })
    sections.sort(key=lambda x: (not x["create"], -(x["entries"][-1].at.timestamp() if x["entries"] else 0)))
    return sections


def render(sections: list[dict], s, now: datetime | None = None, left_out: list | None = None) -> str:
    now = (now or datetime.now(timezone.utc)).astimezone()
    n_entries = sum(len(x["entries"]) for x in sections)
    n_new = sum(1 for x in sections if x["create"])
    L = [f"# Gmail feed for Cowork: {now:%Y-%m-%d %H:%M}", "",
         "Made by Sales Desk from Tony's Gmail. Follow `inquiry-rulebook-decisions.md` (it wins over everything else):",
         "only CBSXY or CBSRX records, never CBSMA or any other team; one running note per inquiry, new entries "
         "appended at the end; confirm every change with Tony before saving. Skip a note line that is already "
         "in the note. The words after each code are a suggestion: improve them from the excerpt, in Tony's "
         "short style.", "",
         f"{len(sections)} conversation(s) · {n_entries} note entr{'y' if n_entries == 1 else 'ies'} · "
         f"{n_new} without an Inquiry number in Gmail", ""]
    if left_out:
        L += [f"Left out (another team's quote/order number, never touched; or Gmail busy): "
              f"{'; '.join(left_out)}", ""]
    if not sections:
        L += ["Nothing new since the last feed."]
    for i, x in enumerate(sections, 1):
        rec, info = x["rec"], x["info"]
        title = " · ".join(v for v in (x["name"], x["company"]) if v) or x["email"]
        L += ["---", "", f"## {i}. {title}", ""]
        if info["inquiry"]:
            L.append(f"- **Inquiry:** {', '.join(info['inquiry'])} (from Gmail)")
        else:
            L.append("- **Inquiry:** no Inquiry number in Gmail. Search Zoho by the email below; "
                     "if there is no record, it may need creating (see *New record* below)")
        L.append(f"- **Customer:** {x['email']}" + (f" · {x['phone']}" if x["phone"] else "")
                 + (f" · topic: {x['topic']}" if x["topic"] else ""))
        if x["team"]:
            L.append(f"- **Team (from the quote/order number):** {', '.join(x['team'])}")
        L.append(f"- **Gmail:** {rec.thread_url}")
        L.append(f"- **Why it's Tony's:** {x['why']}"
                 + (f" (first wrote to the customer {short(info['tony_replied'].isoformat())})"
                    if info["tony_replied"] else ""))
        if x["entries"]:
            L.append("- **Append to the running note:**")
            for e in x["entries"]:
                by = "" if e.who in ("Tony", "customer") else f" ({e.who})"
                quote = e.excerpt.replace("`", "'")
                L.append(f"  - `{e.line()}`{by}" + (f": “{quote}”" if quote else ""))
        if x["tags"]:
            L.append("- **Tags:** " + "; ".join(x["tags"]))
        q = info["quote_way"]
        if q:
            how = (f"as a PDF attachment ({', '.join(q['pdf'])})" if q["pdf"] else
                   "as a formal quote" if q["formal"] else "with the price in the email body (no PDF)")
            L.append(f"- **Quote:** {', '.join(q['numbers']) or 'no number in the email'} sent "
                     f"{short(q['date'].isoformat())} {how}. Tony decides Draft Quote / PDF Quote / formal quote"
                     + (f"; Quote Number from Gmail: {q['numbers'][-1]}" if q["numbers"] else ""))
        if x["key_customer"]:
            o = x["key_customer"][0].order
            L.append(f"- **Key Customer:** YES: order {o.order_code} ${o.total:,.0f} (over $20,000)")
        if x["create"]:
            g, why = grade(x["email"])
            L.append("- **New record** (only if Zoho has none; Tony confirms first):")
            L.append(f"  - Inquiry Method: how it came in: {info['channel'] or 'email'}")
            L.append(f"  - Inquiry Level and Customer Type (same value): {g + ' (' + why + ')' if g else why}")
            L.append(f"  - Key Customer: {'YES' if x['key_customer'] else 'NO (no order over $20,000 in Gmail)'}")
            L.append(f"  - New or Returned Customer: {'Returned (earlier order in Gmail)' if x['returned'] else 'check Zoho'}")
            L.append(f"  - Team: {x['team'][0] if x['team'] else 'CBSXY'} (one team only)")
            if x["topic"]:
                L.append(f"  - Services and Products of Interested: {x['topic']}")
            if info["internal_people"]:
                L.append(f"  - Then post `Inquiry-00NNNNN crm created` in the internal thread above, as a Gmail "
                         f"**draft** for Tony to send, to internal people only: {', '.join(info['internal_people'])}")
        L.append("")
    return "\n".join(L).rstrip() + "\n"


def export(pipeline, everything: bool = False, days: int = 30, out_dir: str | None = None, lock=None) -> dict:
    """Write the feed file; what it contains is not repeated in the next one."""
    s, store = pipeline.s, pipeline.store
    left_out: list[str] = []
    sections = collect(pipeline, everything, days, lock, left_out)
    if not sections:
        return {"path": None, "conversations": 0, "entries": 0, "new_inquiries": 0}
    now = datetime.now(timezone.utc)
    raw = out_dir or s.crm_feed_dir
    fix = (f"CRM_FEED_DIR in .env isn't a folder Windows can use ({raw}). Open the Cowork folder in File "
           "Explorer, click the address bar, copy the path, paste it after CRM_FEED_DIR=, save .env and "
           "restart Sales Desk.")
    if re.search(r'[<>"|?*]', raw):
        raise ValueError(fix)
    folder = Path(raw).expanduser()
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ValueError(f"{fix} ({e.strerror or e})") from e
    path = folder / f"gmail-feed-{now.astimezone():%Y-%m-%d-%H%M%S}.md"
    path.write_text(render(sections, s, now, left_out), encoding="utf-8")
    store.mark_feed([k for x in sections for k in x["keys"]])
    store.mark_items_exported([i for x in sections for i in x["item_ids"]])
    store.set_meta("last_feed", now.isoformat(timespec="seconds"))
    entries = sum(len(x["entries"]) for x in sections)
    store.log("", f"Gmail feed for Cowork: {len(sections)} conversation(s), {entries} note entries -> {path}")
    return {"path": str(path.resolve()), "conversations": len(sections), "entries": entries,
            "new_inquiries": sum(1 for x in sections if x["create"])}
