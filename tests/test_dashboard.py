from datetime import datetime, timedelta, timezone

import pytest

from sales_pipeline.actions import Executor
from sales_pipeline.demo import DemoGmail, DemoZoho, seed
from sales_pipeline.models import Customer, Order
from sales_pipeline.store import Store
from sales_pipeline.tasks import build_plan, level, prioritize
from sales_pipeline.web import App


@pytest.fixture
def demo(settings):
    store = Store(settings.db_path)
    gmail, zoho = seed(settings, store)
    return store, gmail, zoho


def test_priorities_and_kinds(demo):
    store, _, _ = demo
    todo = store.list(["needs_review", "ready"])
    assert [r.kind for r in todo][:2] == ["order", "quote_request"]
    assert level(todo[0].priority) == "high"           # big, new, prepay, customer waiting
    assert level(todo[1].priority) == "high"           # quote request unanswered for 3 days
    assert store.list("skipped")[0].subject.startswith("Your September invoice")


def test_waiting_customer_raises_priority():
    o = Order(is_sales_order=True, total=2000)
    now = datetime.now(timezone.utc)
    base, _ = prioritize("order", o, [], None, now)
    waited, why = prioritize("order", o, [], (now - timedelta(days=2)).isoformat(), now)
    assert waited > base and any("waiting" in w for w in why)


def test_plan_keeps_user_edits(settings):
    o = Order(is_sales_order=True, order_code="X1", total=10,
              customer=Customer(company="Acme", email="a@acme.example", contact_name="Ann Lee"))
    plan = build_plan("order", o, "Order_X1", settings)
    assert [s["id"] for s in plan] == ["zoho_so", "label", "confirm"]
    confirm = plan[2]
    assert confirm["gated"] and confirm["draft"]["body"].startswith("Hi Ann,")
    confirm["draft"] = dict(confirm["draft"], body="custom text")
    confirm["draft_edited"] = True
    plan[1]["enabled"] = False
    again = build_plan("order", o, "Order_X1", settings, plan)
    assert again[2]["draft"]["body"] == "custom text" and again[1]["enabled"] is False


def test_approve_runs_routine_and_drafts_but_never_sends(demo, settings):
    store, gmail, zoho = demo
    ex = Executor(settings, store, gmail=gmail, zoho=zoho)
    top = store.list(["needs_review", "ready"])[0]
    rec = ex.approve(top.thread_id)
    states = {s["id"]: s["state"] for s in rec.plan}
    assert states == {"zoho_so": "done", "label": "done", "confirm": "drafted"}
    assert rec.status == "awaiting_send"
    assert any("Sales_Orders" in l for l in zoho.log)
    assert not any(l.startswith("SENT") for l in gmail.log)

    rec = ex.send(top.thread_id, "confirm",
                  dict(rec.plan[2]["draft"], body="Edited before sending"))
    assert rec.status == "done"
    assert gmail.log[-1].startswith("SENT")
    assert any(l.startswith("deleted") for l in gmail.log)   # old draft replaced by edited one


def test_approve_applies_order_edits_and_unchecked_steps(demo, settings):
    store, gmail, zoho = demo
    ex = Executor(settings, store, gmail=gmail, zoho=zoho)
    rec = next(r for r in store.list() if r.order_code == "CBSXY10032602")  # company missing
    order = rec.order.model_dump()
    order["customer"]["company"] = "Lakeside University"
    rec = ex.approve(rec.thread_id, order, {"confirm": {"enabled": False}})
    assert rec.order.customer.company == "Lakeside University"
    assert rec.issues == []
    assert {s["id"]: s["state"] for s in rec.plan}["confirm"] == "skipped"
    assert rec.status == "done"


def test_failures_are_reported_not_hidden(demo, settings):
    store, gmail, _ = demo
    ex = Executor(settings, store, gmail=gmail, zoho=None)   # Zoho not connected
    top = store.list(["needs_review", "ready"])[0]
    rec = ex.approve(top.thread_id)
    so = next(s for s in rec.plan if s["id"] == "zoho_so")
    assert so["state"] == "failed" and "Zoho is not connected" in so["result"]
    assert rec.status == "failed"


def test_api(demo, settings):
    store, gmail, zoho = demo
    app = App(settings, store, gmail=gmail, zoho=zoho, demo=True)
    code, j = app.handle("GET", "/api/tasks?view=todo", {})
    assert code == 200 and j["counts"]["todo"] == 4 and j["tasks"][0]["level"] == "high"
    tid = j["tasks"][0]["id"]
    code, j = app.handle("POST", f"/api/tasks/{tid}/approve", {})
    assert code == 200 and j["counts"]["send"] == 1
    code, j = app.handle("POST", f"/api/tasks/{tid}/skip", {})
    assert j["task"]["status"] == "skipped"
    assert app.handle("POST", "/api/scan", {})[0] == 400   # no Gmail scanner in demo
