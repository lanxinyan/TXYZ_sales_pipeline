import pytest

from sales_pipeline.models import Customer, LineItem, Order
from sales_pipeline.pipeline import Pipeline, merge, sales_order_payload, validate
from sales_pipeline.store import Store


class FakeGmail:
    def __init__(self, threads):
        self.threads = {t.id: t for t in threads}
        self.labels = {}

    def search(self, q, limit):
        return list(self.threads)

    def get_thread(self, tid, attachments=True):
        return self.threads[tid]

    def set_label(self, tid, name):
        self.labels[tid] = name


class FakeLLM:
    def __init__(self, order):
        self.order = order

    def extract(self, thread):
        return self.order


class FakeZoho:
    def __init__(self):
        self.created, self.attached = [], []
        self.existing = {}

    def find_sales_order(self, subject):
        return self.existing.get(subject)

    def find_or_create_account(self, name, order):
        self.created.append(("Accounts", name))
        return "acc1"

    def find_or_create_contact(self, order, account_id):
        return "con1"

    def find_or_create_product(self, name, code, price, auto, generic):
        return "prod1"

    def create(self, module, rec):
        self.created.append((module, rec))
        return "so1"

    def attach(self, module, rid, fn, data):
        self.attached.append(fn)


def claude_order():
    return Order(
        is_sales_order=True, order_code="CBSRX09242501B-2", total=12500.0,
        customer=Customer(company="Acme Health", contact_name="Jane Doe", email="jane.doe@acme-health.com"),
        items=[LineItem(product_name="Custom PFAS Analysis in Serum Samples", quantity=1, unit_price=12500.0)],
        payment_terms="Prepayment",
    )


def test_rules_only_needs_review_without_company(settings, order_thread):
    gm = FakeGmail([order_thread])
    pipe = Pipeline(settings, Store(settings.db_path), gmail=gm)
    assert pipe.scan() == {"needs_review": 1}
    rec = pipe.store.get("t1")
    assert any("company" in i for i in rec.issues)
    assert gm.labels["t1"] == "Zoho/Needs review"
    # unchanged thread is not processed twice
    assert pipe.scan() == {}


def test_full_flow_with_claude_and_push(settings, order_thread):
    settings.use_llm = True
    gm, z = FakeGmail([order_thread]), FakeZoho()
    pipe = Pipeline(settings, Store(settings.db_path), gmail=gm, zoho=z, llm=FakeLLM(claude_order()))
    assert pipe.scan() == {"ready": 1}

    preview = pipe.push("t1", dry_run=True)
    assert preview["Subject"] == "CBSRX09242501B-2"
    assert z.created == []

    res = pipe.push("t1")
    assert res == {"status": "created", "zoho_id": "so1"}
    module, so = z.created[-1]
    assert module == "Sales_Orders"
    assert so["Account_Name"] == {"id": "acc1"} and so["Contact_Name"] == {"id": "con1"}
    assert so["Ordered_Items"][0] == {"Product_Name": {"id": "prod1"}, "Quantity": 1, "List_Price": 12500.0}
    assert "Payment terms: Prepayment" in so["Description"]
    assert z.attached == ["Quotation_CBSRX09242501B-2.pdf"]
    assert gm.labels["t1"] == "Zoho/Synced"
    assert pipe.push("t1")["status"] == "already pushed"


def test_push_is_idempotent_when_order_exists_in_zoho(settings, order_thread):
    z = FakeZoho()
    z.existing["CBSRX09242501B-2"] = "so-old"
    pipe = Pipeline(settings, Store(settings.db_path), gmail=FakeGmail([order_thread]), zoho=z,
                    llm=FakeLLM(claude_order()))
    pipe.scan()
    assert pipe.push("t1") == {"status": "exists", "zoho_id": "so-old"}
    assert not any(m == "Sales_Orders" for m, _ in z.created)


def test_unapproved_order_is_not_pushed(settings, order_thread):
    pipe = Pipeline(settings, Store(settings.db_path), gmail=FakeGmail([order_thread]), zoho=FakeZoho())
    pipe.scan()
    with pytest.raises(ValueError):
        pipe.push("t1")


def test_not_an_order_is_skipped(settings, order_thread):
    pipe = Pipeline(settings, Store(settings.db_path), gmail=FakeGmail([order_thread]),
                    llm=FakeLLM(Order(is_sales_order=False)))
    assert pipe.scan() == {"skipped": 1}


def test_merge_prefers_form_code_and_flags_total_mismatch(settings):
    rules = Order(is_sales_order=True, order_code="CBSRX09242501B-2", total=12500.0)
    llm = claude_order()
    llm.order_code, llm.total = "CBSRX09242501B", 11250.0
    o, notes = merge(llm, rules, settings)
    assert o.order_code == "CBSRX09242501B-2"
    assert any("total mismatch" in n for n in notes)


def test_merge_drops_internal_email(settings):
    llm = claude_order()
    llm.customer.email = "sales@creative-biostructure.com"
    rules = Order(is_sales_order=True, customer=Customer(email="jane.doe@acme-health.com"))
    o, _ = merge(llm, rules, settings)
    assert o.customer.email == "jane.doe@acme-health.com"


def test_validate_checks_arithmetic():
    o = claude_order()
    assert validate(o) == []
    o.items.append(LineItem(product_name="Extra", quantity=2, unit_price=100))
    assert any("add up to" in i for i in validate(o))
    o.shipping, o.total = 50.0, 12750.0
    assert validate(o) == []


def test_payload_without_ids_uses_names():
    p = sales_order_payload(claude_order())
    assert p["Account_Name"] == {"name": "Acme Health"}
    assert p["Ordered_Items"][0]["Product_Name"] == {"name": "Custom PFAS Analysis in Serum Samples"}
