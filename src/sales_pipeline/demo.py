"""Fictional inbox + in-memory Gmail/Zoho so the dashboard can be tried with no accounts.
All people, companies and addresses here are made up."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .config import Settings
from .crm import CustomerCRM
from .models import Attachment, Customer, EmailMessage, EmailThread, LineItem, Order
from .pipeline import Pipeline
from .store import Store

ME = "you@creative-biostructure.com"
YANI = "yani.zhao@creative-biostructure.com"
INQ = "inquiry@creative-biostructure.com"
USA = "usa@creative-biostructure.com"
DEMO_TAGS = {"inquiry": "询价", "quoted": "已报价", "following_up": "跟进中", "ordered": "已下单", "lost": "不买了",
             "no_response": "No reply"}

FORM = ("年月日 报价号 包裹类型 备注 产品/定制/服务 目录号 业务类别 产品名称 Qty PO 产品报价 S H Dry Ice "
        "5%信用卡手续费 sales 销售人员 新客户/老客户/分销商 {date} {code} 服务 {product} 1*1 无 ${price} $0.00 "
        "$0.00 $0.00 $0.00 ${price} 王小明 {status} N/A {note}")
WEB_FORM = """---------- Forwarded message ---------
From: <admin@cd-sciences.info>
Date: {date}
Subject: {topic} - Creative Biostructure (ID: BS01-M-2610{n})
To: <inquiry@creative-biostructure.com>

Inquiry Information
Contact Information
First Name *{first}*
Last Name *{last}*
Phone Number *{phone}*
Company/Institution *{company}*
Email *{email} <{email}>*
Extra Information
Topic *{topic}*
Description *{text}*"""


def _ago(**kw) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat(timespec="seconds")


class _Msgs:
    def __init__(self):
        self.n = 0

    def __call__(self, sender, to, body, when, subject, cc=(), name="", pdf=None):
        self.n += 1
        atts = [Attachment(pdf, "application/pdf", b"%PDF-1.4 demo")] if pdf else []
        return EmailMessage(f"m{self.n}", sender, list(to), list(cc), subject, when, body, atts,
                            message_id=f"<demo-{self.n}@mail>", sender_name=name,
                            attachment_names=[pdf] if pdf else [])


def demo_threads() -> tuple[list[EmailThread], dict[str, Order], dict[str, list[EmailMessage]]]:
    M = _Msgs()
    T: list[EmailThread] = []
    answers: dict[str, Order] = {}
    late: dict[str, list[EmailMessage]] = {}
    url = "https://mail.google.com/"

    # 1. Website inquiry forwarded by inquiry@ this morning; Yani already created it in the CRM.
    s = "Fwd: Liposome Formulation - Creative Biostructure (ID: BS01-M-261010001)"
    T.append(EmailThread("demo-inquiry", s, [
        M(INQ, [ME, YANI], WEB_FORM.format(date="Sat, Oct 10, 2026", topic="Liposome Formulation", n="001",
                                            first="robin", last="Moreau", phone="555-0142",
                                            company="Northfield University", email="rmoreau@northfield.example",
                                            text="Need a liposome formulation for a hydrophobic drug, ~5 batches."),
          _ago(hours=6), s, name="Creative Biostructure"),
        M(YANI, [], "Inquiry-0031002 crm created\n\nOn Sat, Oct 10 Creative Biostructure wrote:\n> ...",
          _ago(hours=5), "Re: " + s[5:], cc=[ME], name="Yani Zhao")], url))

    # 2. Quote sent 4 days ago, Yani followed up once, still no answer -> follow-up 2 due.
    s = "Re: Request for Quotation - HDX-MS epitope mapping"
    T.append(EmailThread("demo-fu2", s, [
        M("p.nair@helio-thera.example", ["info@creative-biostructure.com", ME],
          "Hello, could you quote HDX-MS epitope mapping for 3 antibodies? Priya Nair", _ago(days=5),
          "Request for Quotation - HDX-MS epitope mapping", name="Priya Nair"),
        M(ME, ["p.nair@helio-thera.example"], "Dear Priya,\n\nBelow is our quote CBSXY10052611 for HDX-MS epitope "
          "mapping of 3 antibodies: $14,400 total, 6-7 weeks.\n\nBest regards,\nTony", _ago(days=4), s,
          cc=[YANI], name="Tony"),
        M(YANI, ["p.nair@helio-thera.example"], "Dear Priya, hope my email finds you great! I was writing to check "
          "if you have got a chance to review the quotation.", _ago(days=3), s, cc=[ME], name="Yani Zhao")], url))

    # 3. Three follow-ups already, last one 35 days ago -> the final follow-up (4) is due.
    s = "Re: Cryo-EM screening quote"
    T.append(EmailThread("demo-fu4", s, [
        M(ME, ["d.okafor@kestrel-labs.example"], "Dear Dr. Okafor,\n\nPlease find our quotation CBSRX08262604 "
          "attached.\n\nBest regards,\nTony", _ago(days=45), s, cc=[YANI], name="Tony", pdf="Quotation_CBSRX08262604.pdf"),
        M(ME, ["d.okafor@kestrel-labs.example"], "This is Tony. I am writing to check whether you have received "
          "our previous email below.", _ago(days=44), s, cc=[YANI], name="Tony"),
        M(ME, ["d.okafor@kestrel-labs.example"], "Hope you are doing well! I am writing to check if you have had "
          "a chance to review the email below.", _ago(days=42), s, cc=[YANI], name="Tony"),
        M(YANI, ["d.okafor@kestrel-labs.example"], "Dear Dr. Okafor, we have not heard from you since the quote was "
          "delivered. Has a decision been made?", _ago(days=35), s, cc=[ME], name="Yani Zhao")], url))

    # 4. All four follow-ups sent, nothing back for 20 days -> suggest closing as No reply.
    s = "Re: SPR binding kinetics proposal"
    T.append(EmailThread("demo-close", s, [
        M(ME, ["m.ito@bluefin-bio.example"], "Dear Dr. Ito,\n\nBelow is our quote CBSXY07152602 for SPR kinetics."
          "\n\nBest regards,\nTony", _ago(days=60), s, name="Tony"),
        *[M(ME, ["m.ito@bluefin-bio.example"], f"Follow-up {i}.", _ago(days=d), s, name="Tony")
          for i, d in ((1, 59), (2, 57), (3, 50), (4, 20))]], url))

    # 5. The customer says they will use their core facility -> thank them and tag 不买了.
    s = "RE: Cryo-EM structure inquiry"
    T.append(EmailThread("demo-declined", s, [
        M(ME, ["j.hale@riverton-med.example"], "Dear Dr. Hale,\n\nBelow is our quotation CBSXY10052602 for the "
          "cryo-EM structure.\n\nBest regards,\nTony", _ago(days=3), s, cc=[YANI], name="Tony"),
        M("j.hale@riverton-med.example", [ME], "Hi Tony, it is way more expensive than we can do it locally. "
          "Let me work with the core facility at our institute. I will contact you if it doesn't work out. "
          "Thanks! Jordan", _ago(hours=20), s, name="Jordan Hale")], url))

    # 6. Big new order; the customer's quote thread is being followed up; Yani already sent it to accounting.
    s = "Re: Quote for cryo-EM structure determination"
    T.append(EmailThread("demo-order-cust", s, [
        M(ME, ["dr.lee@harborline-bio.example"], "Dear Dr. Lee,\n\nBelow is our quote CBSRX10012601 for cryo-EM "
          "structure determination: $38,500.\n\nBest regards,\nTony", _ago(days=6), s, name="Tony"),
        M("dr.lee@harborline-bio.example", [ME], "Thanks, we will review internally.", _ago(days=5), s, name="Dana Lee"),
        M(ME, ["dr.lee@harborline-bio.example"], "Thank you, Dana. Happy to answer any questions.", _ago(days=5), s,
          name="Tony")], url))
    s = "Order_CBSRX10012601"
    T.append(EmailThread("demo-order", s, [
        M("sales.rep@pr-abacebiology.com", [ME], FORM.format(
            date="2026/10/8", code="CBSRX10012601", product="Custom Cryo-EM Structure Determination",
            price="38,500.00", status="新客户", note="客户要求预付款后开始。"), _ago(days=2), s,
          name="Xiao Ming", pdf="Quotation_CBSRX10012601.pdf")], url))
    answers["demo-order"] = Order(
        is_sales_order=True, order_code="CBSRX10012601", order_type="service", total=38500, po_number="NB-55120",
        customer=Customer(company="Harborline Biosciences", contact_name="Dana Lee",
                          email="dr.lee@harborline-bio.example", billing_address="12 Harbor Way, Boston MA"),
        items=[LineItem(product_name="Custom Cryo-EM Structure Determination", quantity=1, unit_price=38500)],
        payment_terms="Prepayment required", customer_status="new",
        notes="Customer asked to start after prepayment.")
    s = "Fwd: Quote for cryo-EM structure determination"
    T.append(EmailThread("demo-accounting", s, [
        M(YANI, ["accounting@creative-biomart.com"], "Order_CBSRX10012601 麻烦收预付 $38,500", _ago(hours=3), s,
          cc=[ME], name="Yani Zhao")], url))

    # 7. Order where the China team asked to hold the invoice.
    s = "Order_CBSXY10032602"
    T.append(EmailThread("demo-order-hold", s, [
        M("sales.rep@pr-abacebiology.com", [ME], FORM.format(
            date="2026/10/9", code="CBSXY10032602", product="Membrane Protein Expression Screening",
            price="6,200.00", status="老客户", note=""), _ago(hours=30), s, name="Xiao Ming"),
        M("xiaoyu.zhu@pr-abacebiology.com", [ME], "先稍等发预付invoice，待确认最终订单金额\nformal quote 见附件",
          _ago(hours=29), "Re:" + s, name="Xiaoyu Zhu")], url))
    answers["demo-order-hold"] = Order(
        is_sales_order=True, order_code="CBSXY10032602", total=6200,
        customer=Customer(company="Lakeside University", contact_name="Sam Ortiz", email="sortiz@lakeside-univ.example"),
        items=[LineItem(product_name="Membrane Protein Expression Screening", quantity=1, unit_price=6200)],
        payment_terms="Prepayment", customer_status="existing")

    # 8. Quote sent this morning -> follow-up 1 is scheduled for tomorrow (Upcoming tab).
    s = "Re: TEM negative-stain quote"
    T.append(EmailThread("demo-upcoming", s, [
        M("c.moss@coastal-demo.example", [ME], "Could you quote negative-stain TEM for 6 samples?", _ago(days=1), s,
          name="Claire Moss"),
        M(ME, ["c.moss@coastal-demo.example"], "Dear Claire,\n\nBelow is our quote CBSXY10102601: $1,800 for 6 "
          "samples.\n\nBest regards,\nTony", _ago(hours=2), s, cc=[YANI], name="Tony")], url))

    # 9. Quote sent 2 days ago, follow-up 1 due. In the demo Yani follows up at the same moment you do,
    #    so pressing Send shows the "a colleague already did this" check.
    s = "Re: Protein crystallization quote"
    T.append(EmailThread("demo-race", s, [
        M(ME, ["a.brandt@vellum-tx.example"], "Dear Alex,\n\nBelow is our quote CBSXY10082603 for crystallization "
          "screening: $9,900.\n\nBest regards,\nTony", _ago(days=2), s, cc=[YANI], name="Tony")], url))
    late["demo-race"] = [M(YANI, ["a.brandt@vellum-tx.example"], "Dear Alex, I was writing to check if you have "
                           "got a chance to review the quotation.", _ago(minutes=1), s, cc=[ME], name="Yani Zhao")]

    # 10. A colleague already tagged this customer 不买了 in Zoho -> no follow-up is suggested.
    s = "Re: Mass photometry quote"
    T.append(EmailThread("demo-crm-closed", s, [
        M(ME, ["t.hart@ridgeway-demo.example"], "Dear Tom,\n\nBelow is our quote CBSXY09152604.\n\nBest,\nTony",
          _ago(days=12), s, name="Tony")], url))

    # 11. Not a customer: we are buying a GPU from a vendor.
    s = "Re: new GPU A6000"
    T.append(EmailThread("demo-vendor", s, [
        M(ME, ["sales@gpu-vendor.example"], "Hi Sam, following up on the second GPU. Can you send a quote?",
          _ago(days=2), s, name="Tony")], url))

    # 12. Project thread run by support@; you are only in copy.
    s = "Re: Mass Spectrometry Imaging Service - Creative Biostructure (ID: M-URE-250929172447)"
    T.append(EmailThread("demo-colleague", s, [
        M("support@creative-biostructure.com", ["s.kim@hillside-demo.example"], "Hi Scott, attached is the "
          "updated data.", _ago(days=3), s, cc=[ME], name="Charles Leong"),
        M("s.kim@hillside-demo.example", ["support@creative-biostructure.com"], "Thanks Charles, a question on "
          "peak 3?", _ago(days=1), s, cc=[ME], name="Scott Kim")], url))

    # 13. The US office forwards a customer's question with a note in Chinese. The reply must go to
    #     the customer only (not back to usa@) and carry none of the internal note.
    s = "Fwd: Negative stain EM question"
    T.append(EmailThread("demo-usa", s, [
        M(USA, [ME], "请看下这个问题，谢谢\n\n---------- Forwarded message ---------\nFrom: Hanna Berg "
          "<h.berg@fjord-bio.example>\nDate: Fri, Oct 9, 2026\nSubject: Negative stain EM question\n"
          "To: <usa@creative-biostructure.com>\n\nHello, could you quote negative-stain EM for 4 protein samples? "
          "Thanks, Hanna", _ago(hours=8), s, name="US Office")], url))

    # 14. A quote that went quiet 50 days ago (nobody followed up) -> Revisit: "it's been a while".
    s = "Re: Exosome isolation quote"
    T.append(EmailThread("demo-revisit", s, [
        M("l.nguyen@sparrow-demo.example", [ME], "Could you quote exosome isolation from 12 plasma samples?",
          _ago(days=52), "Exosome isolation quote", name="Linh Nguyen"),
        M(ME, ["l.nguyen@sparrow-demo.example"], "Dear Dr. Nguyen,\n\nBelow is our quote CBSXY08232601 for "
          "exosome isolation from 12 plasma samples: $4,800, 3-4 weeks.\n\nBest regards,\nTony",
          _ago(days=50), s, name="Tony")], url))

    # 15. Answered 40 days ago, no quote yet, then silence -> Revisit (asks for the details again).
    s = "Re: Cryo-EM for a membrane protein"
    T.append(EmailThread("demo-revisit-noquote", s, [
        M("a.okoro@meadow-demo.example", [ME], "Do you do cryo-EM on membrane proteins in nanodiscs?",
          _ago(days=41), "Cryo-EM for a membrane protein", name="Ada Okoro"),
        M(ME, ["a.okoro@meadow-demo.example"], "Dear Ada,\n\nYes, we do. Could you share the protein size "
          "and how many constructs?\n\nBest regards,\nTony", _ago(days=40), s, name="Tony")], url))
    return T, answers, late


class DemoGmail:
    def __init__(self, threads, late=None):
        self.threads = {t.id: t for t in threads}
        self.late = late or {}
        self.armed = False   # late messages appear only after the first scan
        self.log: list[str] = []
        self.drafts: dict[str, dict] = {}
        self._n = 0

    def search(self, q, limit):
        m = re.search(r'"([^"]+)"', q)
        if m:
            code = m.group(1)
            return [t.id for t in self.threads.values()
                    if code in t.subject or any(code in x.body for x in t.messages)][:limit]
        return [t for t in self.threads if not t.startswith("new-")][:limit]

    def get_thread(self, tid, attachments=True):
        if self.armed and tid in self.late:
            self.threads[tid].messages.extend(self.late.pop(tid))
        return self.threads[tid]

    def set_label(self, tid, name):
        self.log.append(f"label {tid} -> {name}")

    def create_draft(self, tid, to, subject, body, in_reply_to="", cc="", quote=None):
        self._n += 1
        did = f"d{self._n}"
        if not tid:   # a new email starts its own thread
            tid = f"new-{did}"
            self.threads[tid] = EmailThread(tid, subject, [], "https://mail.google.com/")
        self.drafts[did] = {"thread": tid, "to": to, "cc": cc, "subject": subject, "body": body, "quote": quote}
        self.log.append(f"draft {did} to {to}: {subject}")
        return {"id": did, "thread_id": tid}

    def draft_exists(self, draft_id):
        return draft_id in self.drafts

    def send_draft(self, draft_id):
        """Stands in for you pressing Send in Gmail (Sales Desk itself never sends)."""
        d = self.drafts.pop(draft_id)
        self._n += 1
        mid = f"sent{self._n}"
        to = d["to"] if isinstance(d["to"], list) else [d["to"]]
        cc = d["cc"] if isinstance(d["cc"], list) else [c for c in [d["cc"]] if c]
        msg = EmailMessage(mid, ME, to, cc, d["subject"], datetime.now(timezone.utc).isoformat(),
                           d["body"], message_id=f"<{mid}@mail>", sender_name="Tony")
        if d["thread"] and d["thread"] in self.threads:
            self.threads[d["thread"]].messages.append(msg)
        self.log.append(f"SENT {draft_id} to {', '.join(to)}")
        return mid

    def delete_draft(self, draft_id):
        self.drafts.pop(draft_id, None)
        self.log.append(f"deleted {draft_id}")


class DemoZoho:
    """Just enough of Zoho CRM for the demo: records, tags, notes."""

    def __init__(self):
        self.n = 0
        self.log: list[str] = []
        self.records: dict[tuple[str, str], dict] = {}
        self.notes: list[dict] = []
        self._add("Leads", {"Last_Name": "Moreau", "First_Name": "Robin", "Email": "rmoreau@northfield.example",
                            "Company": "Northfield University", "Tag": [{"name": "询价"}]})
        self._add("Leads", {"Last_Name": "Hart", "First_Name": "Tom", "Email": "t.hart@ridgeway-demo.example",
                            "Company": "Ridgeway Labs", "Tag": [{"name": "不买了"}]})

    def _add(self, module, rec):
        self.n += 1
        rid = f"{module.lower()}-{self.n}"
        self.records[(module, rid)] = {"id": rid, "Tag": [], **rec}
        return rid

    def find_by_email(self, module, email, fields=None):
        return [r for (m, _), r in self.records.items() if m == module and r.get("Email", "").lower() == email]

    def module_fields(self, module):
        from .crm import STANDARD_FIELDS

        return STANDARD_FIELDS

    def create(self, module, record, trigger=True):
        rid = self._add(module, dict(record))
        self.log.append(f"created {module} {rid}")
        return rid

    def get(self, module, rid):
        return self.records.get((module, rid), {})

    def record_tags(self, module, rid):
        return [t["name"] for t in self.records[(module, rid)].get("Tag", [])]

    def add_tags(self, module, rid, names):
        tags = self.records[(module, rid)].setdefault("Tag", [])
        tags += [{"name": n} for n in names if n not in [t["name"] for t in tags]]
        self.log.append(f"tag {rid} + {names}")

    def remove_tags(self, module, rid, names):
        if names:
            rec = self.records[(module, rid)]
            rec["Tag"] = [t for t in rec.get("Tag", []) if t["name"] not in names]
            self.log.append(f"tag {rid} - {names}")

    def add_note(self, module, rid, title, content):
        self.notes.append({"module": module, "id": rid, "title": title, "content": content})
        self.log.append(f"note on {rid}: {title}")
        return f"note-{len(self.notes)}"

    def list_tags(self, module):
        return [{"name": n} for n in ("询价", "已报价", "跟进中", "已下单", "不买了", "No reply", "VIP")]

    def list_modules(self):
        return [{"api_name": "Leads", "plural_label": "Inquiries"}, {"api_name": "Contacts", "plural_label": "Contacts"},
                {"api_name": "Sales_Orders", "plural_label": "Sales Orders"}]

    # Sales Order bits used by the order flow
    def find_sales_order(self, subject):
        return None

    def find_or_create_account(self, name, order):
        return self.create("Accounts", {"Account_Name": name})

    def find_or_create_contact(self, order, account_id):
        return self.create("Contacts", {"Email": order.customer.email, "Last_Name": order.customer.contact_name})

    def find_or_create_product(self, *a):
        return self.create("Products", {})

    def attach(self, *a):
        self.log.append("attached PDF")


class _Answers:
    def __init__(self, answers):
        self.answers = answers

    def extract(self, thread):
        a = self.answers.get(thread.id)
        return a.model_copy(deep=True) if a else None


def seed(settings: Settings, store: Store) -> tuple[DemoGmail, DemoZoho, Pipeline]:
    settings.user_email = settings.user_email or ME
    settings.accounting_email = settings.accounting_email or "accounting@creative-biomart.com"
    threads, answers, late = demo_threads()
    gmail, zoho = DemoGmail(threads, late), DemoZoho()
    crm = CustomerCRM(zoho, settings, tag_map=dict(DEMO_TAGS))
    pipe = Pipeline(settings, store, gmail=gmail, zoho=zoho, llm=_Answers(answers), crm=crm)
    if not store.list():
        pipe.scan(rescan=True)
    gmail.armed = True
    return gmail, zoho, pipe
