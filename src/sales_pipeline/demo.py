"""Fictional inbox + in-memory Gmail/Zoho so the dashboard can be tried with no accounts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .config import Settings
from .models import Attachment, Customer, EmailMessage, EmailThread, LineItem, Order
from .pipeline import Pipeline
from .store import Store

FORM = ("年月日 报价号 包裹类型 备注 产品/定制/服务 目录号 业务类别 产品名称 Qty PO 产品报价 S H Dry Ice "
        "5%信用卡手续费 sales 销售人员 新客户/老客户/分销商 {date} {code} 服务 {product} 1*1 无 ${price} $0.00 "
        "$0.00 $0.00 $0.00 ${price} 王小明 {status} N/A {note}")


def _ago(**kw) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat(timespec="seconds")


def _msg(i, sender, body, date, subject, pdf=None):
    atts = [Attachment(pdf, "application/pdf", b"%PDF-1.4 demo")] if pdf else []
    return EmailMessage(f"m{i}", sender, ["xinyan.zhang@creative-biostructure.com"], [], subject, date, body,
                        atts, message_id=f"<demo-{i}@mail>")


def demo_threads() -> tuple[list[EmailThread], dict[str, Order]]:
    t, answers = [], {}

    s = "Order_CBSRX10012601"
    t.append(EmailThread("demo-1", s, [
        _msg(1, "sales.rep@pr-abacebiology.com", FORM.format(
            date="2026/10/7", code="CBSRX10012601", product="Custom Cryo-EM Structure Determination",
            price="38,500.00", status="新客户", note="客户要求预付款后开始。"), _ago(days=2), s,
            "Quotation_CBSRX10012601.pdf"),
        _msg(2, "dr.lee@northfield-bio.example", "Hi, we have issued the PO. When can you start?\nDana Lee",
             _ago(hours=20), "Re: " + s)], "https://mail.google.com/"))
    answers["demo-1"] = Order(
        is_sales_order=True, order_code="CBSRX10012601", order_type="service", total=38500, po_number="NB-55120",
        customer=Customer(company="Northfield Biosciences", contact_name="Dana Lee",
                          email="dr.lee@northfield-bio.example", billing_address="12 Harbor Way, Boston MA"),
        items=[LineItem(product_name="Custom Cryo-EM Structure Determination", quantity=1, unit_price=38500)],
        payment_terms="Prepayment required", customer_status="new",
        notes="Customer asked to start after prepayment.")

    s = "Order_CBSXY10032602"
    t.append(EmailThread("demo-2", s, [
        _msg(3, "sales.rep@pr-abacebiology.com", FORM.format(
            date="2026/10/8", code="CBSXY10032602", product="Membrane Protein Expression Screening",
            price="6,200.00", status="老客户", note=""), _ago(hours=30), s)], "https://mail.google.com/"))
    answers["demo-2"] = Order(
        is_sales_order=True, order_code="CBSXY10032602", total=6200,
        customer=Customer(contact_name="Sam Ortiz", email="sortiz@lakeside-univ.example"),
        items=[LineItem(product_name="Membrane Protein Expression Screening", quantity=1, unit_price=6200)],
        customer_status="existing")

    s = "Request for quotation - HDX-MS on 3 antibodies"
    t.append(EmailThread("demo-3", s, [
        _msg(4, "procurement@helio-thera.example",
             "Hello, could you send a quote for HDX-MS epitope mapping on 3 antibodies? Timeline ~6 weeks.\n"
             "Priya Nair\nHelio Therapeutics", _ago(days=3), s)], "https://mail.google.com/"))
    answers["demo-3"] = Order(is_sales_order=False, customer=Customer(
        company="Helio Therapeutics", contact_name="Priya Nair", email="procurement@helio-thera.example"))

    s = "Order_CBSRX10052603"
    t.append(EmailThread("demo-4", s, [
        _msg(5, "sales.rep@pr-abacebiology.com", FORM.format(
            date="2026/10/9", code="CBSRX10052603", product="SPR Binding Kinetics", price="2,400.00",
            status="老客户", note=""), _ago(hours=5), s)], "https://mail.google.com/"))
    answers["demo-4"] = Order(
        is_sales_order=True, order_code="CBSRX10052603", total=2400,
        customer=Customer(company="Crescent Labs", contact_name="Wei Chen", email="wchen@crescent-labs.example"),
        items=[LineItem(product_name="SPR Binding Kinetics", quantity=1, unit_price=2400)],
        customer_status="existing")

    s = "Your September invoice from a lab supplier"
    t.append(EmailThread("demo-5", s, [_msg(6, "billing@supplier.example", "Invoice attached.", _ago(days=1), s)],
                         "https://mail.google.com/"))
    answers["demo-5"] = Order(is_sales_order=False)
    return t, answers


class DemoGmail:
    def __init__(self, threads):
        self.threads = {t.id: t for t in threads}
        self.log: list[str] = []
        self._n = 0

    def search(self, q, limit):
        return list(self.threads)[:limit]

    def get_thread(self, tid):
        return self.threads[tid]

    def set_label(self, tid, name):
        self.log.append(f"label {tid} -> {name}")

    def create_draft(self, tid, to, subject, body, in_reply_to=""):
        self._n += 1
        self.log.append(f"draft d{self._n} to {to}: {subject}")
        return f"d{self._n}"

    def send_draft(self, draft_id):
        self.log.append(f"SENT {draft_id}")
        return draft_id

    def delete_draft(self, draft_id):
        self.log.append(f"deleted {draft_id}")


class DemoZoho:
    def __init__(self):
        self.n = 0
        self.log: list[str] = []

    def _id(self, what):
        self.n += 1
        self.log.append(f"created {what}")
        return f"{what.lower()}-{self.n}"

    def find_sales_order(self, subject):
        return None

    def find_or_create_account(self, name, order):
        return self._id("Account")

    def find_or_create_contact(self, order, account_id):
        return self._id("Contact")

    def find_or_create_product(self, *a):
        return self._id("Product")

    def create(self, module, record):
        return self._id(module)

    def attach(self, *a):
        self.log.append("attached PDF")


class _Answers:
    def __init__(self, answers):
        self.answers = answers

    def extract(self, thread):
        return self.answers[thread.id].model_copy(deep=True)


def seed(settings: Settings, store: Store) -> tuple[DemoGmail, DemoZoho]:
    threads, answers = demo_threads()
    gmail, zoho = DemoGmail(threads), DemoZoho()
    if not store.list():
        Pipeline(settings, store, gmail=gmail, llm=_Answers(answers)).scan(rescan=True)
    return gmail, zoho
