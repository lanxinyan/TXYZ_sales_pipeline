import pytest

from sales_pipeline.demo import seed
from sales_pipeline.store import Store
from sales_pipeline.tasks import PlanContext, build_plan
from sales_pipeline.templates import load
from sales_pipeline.web import App
from sales_pipeline.models import Customer, Order


@pytest.fixture
def app(settings):
    store = Store(settings.db_path)
    gmail, zoho, pipe = seed(settings, store)
    return App(settings, store, pipe, demo=True)


def test_views_are_sorted_and_counted(app):
    code, j = app.handle("GET", "/api/tasks?view=todo", {})
    assert code == 200 and j["demo"] and j["tags"]["lost"] == "不买了"
    assert [t["level"] for t in j["tasks"][:2]] == ["high", "high"]
    assert [t["priority"] for t in j["tasks"]] == sorted((t["priority"] for t in j["tasks"]), reverse=True)
    _, up = app.handle("GET", "/api/tasks?view=upcoming", {})
    assert [t["id"] for t in up["tasks"]] == ["demo-upcoming"] and up["tasks"][0]["action"] == "Follow-up 1/4"


def test_send_check_returns_409_then_send_anyway(app):
    code, j = app.handle("POST", "/api/tasks/demo-race/approve", {"send": True})
    assert code == 409 and "already replied to the customer" in j["conflict"][0]
    assert j["counts"]["send"] == 1
    code, j = app.handle("POST", "/api/tasks/demo-race/send", {"step": "followup_1", "force": True})
    assert code == 200 and j["task"]["status"] == "scheduled"
    _, act = app.handle("GET", "/api/activity", {})
    assert any("(sent anyway)" in a["text"] for a in act["activity"])


def test_outcome_snooze_ignore_and_errors(app):
    assert app.handle("POST", "/api/tasks/demo-fu4/outcome", {"outcome": "lost"})[1]["task"]["status"] == "done"
    assert app.handle("POST", "/api/tasks/demo-close/snooze", {"days": 3})[1]["task"]["status"] == "scheduled"
    assert app.handle("POST", "/api/tasks/demo-fu2/ignore", {})[1]["task"]["status"] == "skipped"
    assert app.handle("POST", "/api/scan", {})[0] == 400                # demo has no Gmail
    assert app.handle("POST", "/api/tasks/demo-fu2/frobnicate", {})[0] == 404


def test_plan_keeps_user_edits_for_the_same_message(settings):
    ctx = PlanContext(templates=load(), tags={"ordered": "已下单"})
    o = Order(is_sales_order=True, order_code="X1", total=10,
              customer=Customer(company="Acme", email="a@acme.example", contact_name="ann lee"))
    plan = build_plan("order", o, None, "Order_X1", settings, ctx)
    assert [s["id"] for s in plan] == ["zoho_so", "tag_ordered", "label", "confirm", "accounting"]
    confirm = plan[3]
    assert confirm["gated"] and confirm["draft"]["body"].startswith("Hi Ann,")
    confirm["draft"] = dict(confirm["draft"], body="custom text")
    confirm["draft_edited"] = True
    plan[2]["enabled"] = False
    again = build_plan("order", o, None, "Order_X1", settings, ctx, plan)
    assert again[3]["draft"]["body"] == "custom text" and again[2]["enabled"] is False


def test_the_page_answers_while_a_slow_scan_runs(settings):
    import threading
    import time

    store = Store(settings.db_path)
    _, _, pipe = seed(settings, store)
    gate = threading.Event()

    def slow_scanner(lock=None):
        with lock:              # e.g. a slow Gmail call for one thread
            gate.wait(5)
        return {}

    app = App(settings, store, pipe, scanner=slow_scanner)
    t = threading.Thread(target=app.scan)
    t.start()
    time.sleep(0.05)
    started = time.time()
    code, j = app.handle("GET", "/api/tasks?view=todo", {})
    assert code == 200 and j["scanning"] and time.time() - started < 1
    assert app.scan() == {"already scanning": 1}
    gate.set()
    t.join()
    assert app.handle("GET", "/api/tasks", {})[1]["scanning"] is False


def test_connecting_zoho_saves_values_into_env(tmp_path, monkeypatch):
    import os

    from sales_pipeline.cli import _set_env

    monkeypatch.setattr(os, "environ", dict(os.environ))     # keep the test process clean

    env = tmp_path / ".env"
    env.write_text("ZOHO_CLIENT_ID=\nSENDER_NAME=Tony\n", encoding="utf-8")
    _set_env("ZOHO_CLIENT_ID", "1000.ABC", str(env))
    _set_env("ZOHO_REFRESH_TOKEN", "1000.r3fr35h", str(env))
    assert env.read_text(encoding="utf-8") == ("ZOHO_CLIENT_ID=1000.ABC\nSENDER_NAME=Tony\n"
                                               "ZOHO_REFRESH_TOKEN=1000.r3fr35h\n")
