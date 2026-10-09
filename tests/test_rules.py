from sales_pipeline.extract_rules import extract, find_order_codes, parse_order_form
from tests.conftest import FORM_BODY

CODE = r"(?<![A-Za-z0-9])CBS[A-Z]{2}\d{8}[A-Z]?(?:-\d+)?(?![A-Za-z0-9])"
INTERNAL = ["creative-biostructure.com", "pr-abacebiology.com"]


def test_order_codes():
    text = "Order_CBSXY09012601 and quote CBSRX09242501B-2, update CBSRX12102502.zip"
    assert find_order_codes(text, CODE) == ["CBSXY09012601", "CBSRX09242501B-2", "CBSRX12102502"]


def test_parse_order_form():
    o = parse_order_form(FORM_BODY, CODE)
    assert o.order_code == "CBSRX09242501B-2"
    assert o.order_date == "2026-10-02"
    assert o.order_type == "service"
    assert o.items[0].product_name == "Custom PFAS Analysis in Serum Samples"
    assert o.items[0].quantity == 1
    assert o.items[0].unit_price == 12500.0
    assert o.total == 12500.0
    assert o.shipping is None
    assert o.po_number is None  # "无"
    assert o.sales_rep == "王小明"
    assert o.customer_status == "existing"
    assert "客户样品已到美国办" in o.notes


def test_non_form_body_is_ignored():
    assert parse_order_form("Hi, please see attached PO 4500123.", CODE) is None


def test_extract_finds_customer_in_forwarded_reply(order_thread):
    o = extract(order_thread, CODE, INTERNAL)
    assert o.is_sales_order
    assert o.customer.email == "jane.doe@acme-health.com"
    assert o.customer.contact_name == "Jane Doe"


def test_extract_customer_po(order_thread):
    from sales_pipeline.models import EmailMessage, EmailThread

    t = EmailThread("t2", "Re: Request for Quotation", [EmailMessage(
        "m", "buyer@university.edu", ["sales@creative-biostructure.com"], [], "Re: Request for Quotation",
        "2026-08-14T15:39:15Z", "We are generating PO number 4500987654 under quote number CBSXY07202601.")])
    o = extract(t, CODE, INTERNAL)
    assert o.order_code == "CBSXY07202601"
    assert o.po_number == "4500987654"
    assert o.customer.email == "buyer@university.edu"
    assert o.order_date == "2026-08-14"
