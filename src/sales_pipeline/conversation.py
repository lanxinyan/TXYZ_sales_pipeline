"""Read an email thread as a customer conversation.

Answers: who wrote last, how many times our side has followed up since the
customer last wrote (counting colleagues' emails too), when the next follow-up
is due, and what colleagues have already done - replied to the customer,
forwarded to accounting, asked to hold the invoice, or logged it in the CRM.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .config import Settings
from .extract_rules import EMAIL, is_internal
from .models import Conversation, EmailMessage, EmailThread

# ---------- text helpers ----------

FWD_MARK = re.compile(r"-{2,}\s*Forwarded message\s*-{2,}|Begin forwarded message:", re.I)
FWD_FROM = re.compile(r"^\s*From:\s*(?P<name>[^<\n]*?)\s*<?(?P<email>[\w.+-]+@[\w-]+(?:\.[\w-]+)+)>?\s*$", re.M)
QUOTE_CUTS = [
    re.compile(r"^On [^\n]{0,200}(?:\n[^\n]{0,200})?wrote:\s*$", re.M),      # Gmail
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}", re.M | re.I),           # Outlook
    re.compile(r"^_{8,}\s*$", re.M),
    re.compile(r"^From:\s[^\n]*\n\s*(?:Sent|Date):\s", re.M),
    re.compile(r"^(?:发件人|寄件者)[:：]", re.M),                                # Chinese clients
    re.compile(r"^Original:\s*$", re.M),
]
FORM_FIELDS = {
    "first_name": "First Name", "last_name": "Last Name", "email": "Email",
    "company": "Company/Institution", "phone": "Phone Number", "topic": "Topic",
}

QUOTE_SENT = re.compile(
    r"\b(?:our|the attached|attached|formal)\s+(?:formal\s+)?quot(?:e|ation)\b|"
    r"\bquot(?:e|ation)\b[^.\n]{0,40}\b(?:below|attached)\b|^\s*QUOTATION\b|\bQuotation[_ ]Creative",
    re.I | re.M)
# "Once we hear back, we will send a formal quote" promises a quote; it doesn't send one.
QUOTE_PROMISE = re.compile(
    r"\b(?:will|would|shall|once|as soon as|going to|to prepare|prepare|preparing|upon|happy to|glad to|"
    r"can (?:send|provide|prepare)|could (?:send|provide|prepare)|after (?:we|you|receiving|getting))\b", re.I)
DECLINE = re.compile(
    r"not interested|no longer (?:need|interested|required|pursu)|decided (?:not|to go with|against)|"
    r"go(?:ing)? with (?:another|a different|other)|(?:another|other|different) (?:vendor|supplier|provider|company)|"
    r"core facility|work with (?:the )?core|(?:do|run) it locally|more expensive|too expensive|"
    r"(?:over|beyond|exceeds?) (?:our|the) budget|no budget|not (?:be )?(?:moving|going) forward|"
    r"won'?t be (?:moving|proceeding)|not (?:to )?proceed|cancel(?:led)? (?:the|this|our)|put (?:it|this|the project) on hold|"
    r"不需要|不做了|不买|太贵|找别家", re.I)
QUOTE_ASK = re.compile(   # a customer asking us for a price (not a vendor sending us one)
    r"\b(?:could|can|would|will) you (?:please )?(?:quote|provide (?:me |us )?(?:with )?(?:a )?quot|"
    r"send (?:me |us )?(?:a )?quot|give (?:me |us )?(?:a )?(?:quote|price))|\bplease (?:send (?:a |us a |me a )?)?quote\b|"
    r"\b(?:request(?:ing)?|need|like|want) (?:a |an )?(?:formal )?quot(?:e|ation)|\bhow much\b|"
    r"\b(?:what is|what's|send|share|provide) (?:the |your )?pric(?:e|es|ing)\b|报价|询价", re.I)
ORDER_INTENT = re.compile(
    r"\bPO\b|purchase order|place (?:an|the|our) order|(?:would like|like|ready|happy) to proceed|"
    r"go ahead|please (?:start|begin)|issue (?:a|the) PO|下单", re.I)
ACK_ONLY = re.compile(r"^\W*(?:great|perfect|ok(?:ay)?|got it|received|noted|sounds good|thanks?|thank you)\b", re.I)
HOLD = re.compile(
    r"(?:稍等|等待|暂缓|先不|先别|不要|别急|hold|wait|don'?t|do not)[^\n]{0,20}(?:invoice|发票|预付|开票)|"
    r"(?:invoice|发票|预付|开票)[^\n]{0,20}(?:稍等|暂缓|先不|on hold|hold off|later)", re.I)
CRM_REF = re.compile(r"\b(Inquiry-\d{5,})\b[^\n]{0,30}?\bcrm\b\s*(\w+(?:\s*&\s*\w+)?)?", re.I)
GREETING = re.compile(r"^\s*(Dear|Hi|Hello|Hey)\b[ ,]*([^,\n]{0,40}?)\s*[,，!]?\s*$", re.I)
NO_REPLY_LOCALPART = re.compile(r"^(?:no-?reply|do-?not-?reply|mailer-daemon|notifications?|postmaster)\b", re.I)


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            d = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def iso(d: datetime | None) -> str | None:
    return d.isoformat(timespec="seconds") if d else None


def fresh_text(body: str) -> str:
    """What the sender actually wrote: drops quoted history and forwarded parts."""
    text = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith(">"))
    cut = len(text)
    for rx in [*QUOTE_CUTS, FWD_MARK]:
        m = rx.search(text)
        if m:
            cut = min(cut, m.start())
    return text[:cut].strip()


def first_line(text: str, limit: int = 160) -> str:
    """The first line that says something (skips "Dear Priya," and blank lines)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for line in lines:
        if not GREETING.match(line):
            return line[:limit] + ("…" if len(line) > limit else "")
    return lines[0][:limit] if lines else ""


def sentence_with(text: str, rx: re.Pattern, statements_only: bool = False) -> str:
    """The sentence around the first match (optionally skipping questions)."""
    for m in rx.finditer(text):
        start = max(text.rfind(".", 0, m.start()), text.rfind("\n", 0, m.start()),
                    text.rfind("?", 0, m.start()), text.rfind("!", 0, m.start())) + 1
        ends = [i for i in (text.find(c, m.end()) for c in ".?!\n") if i >= 0]
        end = min(ends) if ends else len(text)
        sentence = " ".join(text[start:end + 1].split())
        if statements_only and sentence.endswith("?"):
            continue
        return sentence[:240]
    return ""


def quote_statement(text: str) -> str:
    """The sentence saying a quote is attached/below/sent, or "" (promises don't count)."""
    for m in QUOTE_SENT.finditer(text):
        start = max(text.rfind(c, 0, m.start()) for c in ".?!\n") + 1
        ends = [i for i in (text.find(c, m.end()) for c in ".?!\n") if i >= 0]
        sentence = " ".join(text[start:min(ends) if ends else len(text)].split())
        if not QUOTE_PROMISE.search(sentence):
            return sentence
    return ""


def quote_sent_in(text: str, attachment_names: list[str], code_regex: str) -> bool:
    """Did this email of ours send a quote? A quote file, our quote number, or a sentence like
    "Below is our quote" / "Please find the attached quotation"."""
    return (any(re.search(r"quot", a, re.I) for a in attachment_names) or bool(re.search(code_regex, text))
            or bool(quote_statement(text)))


def form_fields(body: str) -> dict:
    """Website inquiry form ("First Name *robin*", "Email *x@y.edu*", ...)."""
    out = {}
    for key, label in FORM_FIELDS.items():
        m = re.search(rf"^\s*{re.escape(label)}\s*\*(.+?)\*\s*$", body, re.M)
        if m:
            value = m.group(1).strip()
            if key == "email":
                e = EMAIL.search(value)
                value = e.group(0).lower() if e else ""
            elif key == "phone":
                value = value.split("<")[0].strip()
            if value:
                out[key] = value
    return out


def forward_origin(body: str) -> dict | None:
    """Who originally wrote a forwarded email (not counting quoted '>' lines)."""
    text = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith(">"))
    mark = FWD_MARK.search(text)
    if not mark:
        return None
    block = text[mark.end():].lstrip("\n")
    origin: dict = {}
    m = FWD_FROM.search(block[:600])
    if m:
        origin = {"email": m.group("email").lower(), "name": m.group("name").strip(' "\'') or None}
    form = form_fields(block)
    if form.get("email"):
        name = " ".join(x for x in (form.get("first_name", "").title(), form.get("last_name", "")) if x)
        origin = {"email": form["email"], "name": name or None, "company": form.get("company"),
                  "phone": form.get("phone"), "topic": form.get("topic")}
    if not origin:
        return None
    # A long subject may wrap onto a second line, but the next header ("To: ...") is not part of it.
    subj = re.search(r"^\s*Subject:\s*(.+(?:\n(?![\w-]+:\s)\S.*)?)$", block[:800], re.M)
    if subj and not origin.get("topic"):
        origin["topic"] = clean_topic(re.sub(r"\s+", " ", subj.group(1)))
    origin["text"] = fresh_text(block.split("\n\n", 1)[-1])
    return origin


def display_name(m: EmailMessage) -> str:
    if m.sender_name:
        return m.sender_name
    local = m.sender.split("@")[0]
    return " ".join(p.capitalize() for p in re.split(r"[._-]", local) if p)


def clean_topic(subject: str) -> str:
    s = re.sub(r"^\s*((re|fwd?|fw|回覆|答复|转发)\s*[:：]\s*)+", "", subject, flags=re.I)
    s = re.sub(r"\s*-\s*Creative Biostructure\s*\(ID:.*$", "", s)
    return s.strip()


# ---------- classification of single messages ----------

class Who:
    def __init__(self, s: Settings, me: str, ignored: set[str] | frozenset = frozenset()):
        self.s, self.me, self.ignored = s, me.lower(), {d.lower() for d in ignored}

    def internal(self, addr: str) -> bool:
        return is_internal(addr, self.s.internal_domains)

    def system(self, addr: str) -> bool:
        local, _, domain = addr.lower().partition("@")
        return (bool(NO_REPLY_LOCALPART.match(local)) or
                any(domain == d or domain.endswith("." + d) for d in self.s.system_domains))

    def customer(self, addr: str) -> bool:
        addr = addr.lower()
        domain = addr.rsplit("@", 1)[-1]
        return bool(addr) and not self.internal(addr) and not self.system(addr) and domain not in self.ignored


def _sorted(messages: list[EmailMessage]) -> list[EmailMessage]:
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(messages, key=lambda m: parse_date(m.date) or epoch)


def analyze(thread: EmailThread, s: Settings, me: str, ignored=frozenset(),
            now: datetime | None = None) -> Conversation:
    who = Who(s, me, ignored)
    me = who.me
    conv = Conversation(topic=clean_topic(thread.subject) or None)
    topic_from_subject = True
    customers: dict[str, str | None] = {}
    last_in: datetime | None = None
    last_out: datetime | None = None
    touches = 0
    messages = _sorted(thread.messages)
    if messages:
        conv.newest_message_id = messages[-1].id

    for m in messages:
        at = parse_date(m.date)
        sender = (m.sender or "").lower()
        recips = [r.lower() for r in m.to + m.cc]
        to_me = me in [r.lower() for r in m.to]
        text = fresh_text(m.body)
        name = "You" if sender == me else display_name(m)
        event = {"at": iso(at), "who": name, "email": sender, "kind": "note", "text": first_line(text)}
        inbound = None  # {email, name, company, phone, topic}

        if sender and who.customer(sender):
            inbound = {"email": sender, "name": m.sender_name or None}
            event["kind"] = "customer"
        elif sender and who.system(sender):
            form = form_fields(m.body)
            if form.get("email") and who.customer(form["email"]):
                inbound = {"email": form["email"], "company": form.get("company"), "phone": form.get("phone"),
                           "topic": form.get("topic"),
                           "name": " ".join(x for x in (form.get("first_name", "").title(),
                                                        form.get("last_name", "")) if x) or None}
                event["kind"] = "customer"
        elif sender and who.internal(sender):
            ext = [r for r in recips if who.customer(r)]
            origin = forward_origin(m.body) if sender != me and not ext else None
            if ext:
                # Our side wrote to the customer: a reply or a follow-up.
                event["kind"] = "you_replied" if sender == me else "colleague_replied"
                for r in ext:
                    customers.setdefault(r, None)
                touches += 1
                last_out = at or last_out
                cc = [r for r in recips if who.internal(r) and r != me]
                if sender != me:
                    cc.append(sender)
                conv.last_outbound_at, conv.last_outbound_by = iso(at), sender
                conv.last_outbound = {
                    "gmail_id": m.id, "rfc_id": m.message_id, "sender": sender, "sender_name": display_name(m),
                    "to": [r for r in (x.lower() for x in m.to) if who.customer(r)] or ext,
                    "cc": list(dict.fromkeys(cc)), "customer_cc": [r for r in (x.lower() for x in m.cc)
                                                                   if who.customer(r)],
                    "subject": m.subject, "date": iso(at), "body": text[:4000]}
                conv.replied_ever = True
                conv.i_participated = conv.i_participated or sender == me
                g = GREETING.match(next((ln for ln in text.splitlines() if ln.strip()), ""))
                if g and g.group(2).strip():
                    conv.salutation = {"word": g.group(1).capitalize(), "name": g.group(2).strip()}
                if quote_sent_in(text, m.attachment_names, s.order_code_regex):
                    conv.quote_sent = True
            elif origin and origin.get("email") and who.customer(origin["email"]):
                # A colleague or the inquiry@ mailbox forwarded what the customer wrote.
                inbound = origin
                conv.inquiry_forward = True
                event["kind"] = "forwarded_inquiry"
                event["text"] = f"via {sender}: " + first_line(origin.get("text") or "")
                text = origin.get("text") or text
            else:
                acct = (s.accounting_email or "").lower()
                if acct and (sender == acct or acct in recips):
                    event["kind"] = "accounting"
                elif sender != me and HOLD.search(text):
                    event["kind"] = "hold"
                    event["text"] = sentence_with(text, HOLD) or event["text"]
                ref = CRM_REF.search(text)
                if ref:
                    event["kind"] = "crm"
                    conv.crm_refs.append({"ref": ref.group(1), "action": (ref.group(2) or "").lower(),
                                          "who": name, "at": iso(at)})

        if inbound:
            if event["kind"] == "customer":
                event["who"] = inbound.get("name") or inbound["email"]
                if QUOTE_ASK.search(text):
                    conv.asked_for_quote = True
            email = inbound["email"]
            customers[email] = inbound.get("name") or customers.get(email)
            conv.customer_name = conv.customer_name or inbound.get("name")
            conv.company = conv.company or inbound.get("company")
            conv.phone = conv.phone or inbound.get("phone")
            if inbound.get("topic") and topic_from_subject:
                conv.topic, topic_from_subject = inbound["topic"], False
            conv.first_inbound_at = conv.first_inbound_at or iso(at)
            conv.last_inbound_at = iso(at)
            conv.last_inbound_text = text[:2000]
            conv.last_inbound_to_me = to_me
            ours = [r for r in [sender, *recips] if who.internal(r) and r != me]
            conv.last_inbound = {"gmail_id": m.id, "rfc_id": m.message_id, "sender": sender,
                                 "subject": m.subject, "date": iso(at), "cc": list(dict.fromkeys(ours)),
                                 # their colleagues they copied (ours are never copied on customer emails)
                                 "customer_cc": [r for r in recips if who.customer(r) and r != email]}
            last_in = at or last_in
            touches = 0
        conv.events.append(event)

    conv.customer_emails = list(customers)
    conv.customer_name = conv.customer_name or next((n for n in customers.values() if n), None)
    conv.touches = touches
    conv.events = conv.events[-15:]

    # ---- what the customer last said (only once we have answered them before) ----
    said = conv.last_inbound_text or ""
    if said and conv.replied_ever:
        declined = sentence_with(said, DECLINE, statements_only=True)
        intent = sentence_with(said, ORDER_INTENT, statements_only=True)
        if declined:
            conv.signals.append({"kind": "declined", "text": declined})
        elif intent:
            conv.signals.append({"kind": "wants_to_order", "text": intent})
        elif len(said) < 140 and ACK_ONLY.search(said) and "?" not in said:
            conv.signals.append({"kind": "acknowledged", "text": said.strip()})

    # ---- where we stand, and when the next step is due ----
    kinds = {x["kind"] for x in conv.signals}
    if not conv.customer_emails:
        conv.stage = "none"
    elif last_in and (last_out is None or last_out < last_in):
        if "acknowledged" in kinds:
            conv.stage = "none"          # "Great, thanks!" needs no answer
        else:
            conv.stage = "reply_needed"
            conv.due_at = iso(last_in + timedelta(hours=s.first_reply_hours))
    elif last_out:
        n = max(1, touches)
        if "declined" in kinds:
            conv.stage, conv.due_at = "declined", iso(last_out)
        elif n <= len(s.followup_days):
            conv.stage = "awaiting_customer"
            conv.due_at = iso(last_out + timedelta(days=s.followup_days[n - 1]))
            conv.followup_no = catch_up(n, last_out, s.followup_days, now or datetime.now(timezone.utc))
        else:
            conv.stage = "exhausted"
            conv.due_at = iso(last_out + timedelta(days=s.close_after_days))
    return conv


def catch_up(n: int, last_out: datetime, days: list[int], now: datetime) -> int:
    """Follow-up n is due days[n-1] after our last email. If even the next one's
    time has passed (e.g. a quote that went quiet weeks ago), skip ahead to the
    follow-up that fits the time elapsed rather than a gentle "did you receive it?"."""
    elapsed = (now - last_out).total_seconds() / 86400
    k, waited = n, days[n - 1]
    while k < len(days) and elapsed >= waited + days[k]:
        waited += days[k]
        k += 1
    return k


def owner_is_me(conv: Conversation) -> bool:
    """Whoever answers the customer owns the conversation. It is yours when you have
    written to this customer, or nobody has answered yet and it was sent/forwarded to
    you directly (not just copied). Once a colleague is answering, it is theirs."""
    if conv.i_participated:
        return True
    if conv.replied_ever:
        return False
    return conv.last_inbound_to_me


def colleague_activity_since(conv_now: Conversation, since_iso: str | None, me: str) -> list[dict]:
    """Emails from anyone but you that arrived after `since` (the time a plan was made)."""
    since = parse_date(since_iso) if since_iso else None
    out = []
    for e in conv_now.events:
        at = parse_date(e.get("at"))
        if since and at and at <= since:
            continue
        if e["kind"] in ("customer", "forwarded_inquiry"):
            out.append({**e, "why": f"{e['who']} wrote on {short(e['at'])}: “{e['text']}”"})
        elif e["kind"] == "colleague_replied":
            out.append({**e, "why": f"{e['who']} already replied to the customer on {short(e['at'])}: “{e['text']}”"})
        elif e["kind"] == "you_replied":
            out.append({**e, "why": f"You already replied on {short(e['at'])} (outside Sales Desk)"})
    return out


def invoice_status(threads: list[EmailThread], s: Settings, me: str) -> dict:
    """Has someone already asked accounting for the invoice, or asked to hold it?"""
    me = me.lower()
    acct = (s.accounting_email or "").lower()
    found = []
    seen = set()
    for t in threads:
        for m in t.messages:
            if m.id in seen:
                continue
            seen.add(m.id)
            sender = (m.sender or "").lower()
            recips = [r.lower() for r in m.to + m.cc]
            text = fresh_text(m.body)
            who = "You" if sender == me else display_name(m)
            if acct and sender == acct:
                found.append(("done", m, f"Accounting wrote on {short(m.date)}: “{first_line(text, 120)}”"))
            elif acct and acct in recips and is_internal(sender, s.internal_domains):
                found.append(("done", m, f"{who} sent it to accounting on {short(m.date)}: “{first_line(text, 120)}”"))
            elif is_internal(sender, s.internal_domains) and sender != me and HOLD.search(text):
                found.append(("hold", m, f"{who} asked to wait on {short(m.date)}: “{sentence_with(text, HOLD)}”"))
    if not found:
        return {"state": None, "evidence": []}
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    found.sort(key=lambda x: parse_date(x[1].date) or epoch)
    return {"state": found[-1][0], "evidence": [f[2] for f in found]}


def short(value: str | None) -> str:
    d = parse_date(value) if isinstance(value, str) else value
    return f"{d:%b} {d.day}" if d else "?"
