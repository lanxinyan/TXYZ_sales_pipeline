from datetime import datetime, timedelta, timezone

import pytest

from sales_pipeline.actions import Conflict, Executor
from sales_pipeline.conversation import parse_date
from sales_pipeline.demo import ME, YANI, seed
from sales_pipeline.models import EmailMessage
from sales_pipeline.store import Store
from sales_pipeline.tasks import action_label, level


@pytest.fixture
def demo(settings):
    store = Store(settings.db_path)
    gmail, zoho, pipe = seed(settings, store)
    ex = Executor(settings, store, gmail=gmail, zoho=zoho, pipeline=pipe)
    return store, gmail, zoho, pipe, ex


def lead(zoho, email):
    return next(r for (m, _), r in zoho.records.items() if r.get("Email") == email)


def tags(zoho, email):
    return [t["name"] for t in lead(zoho, email).get("Tag", [])]


def test_the_list_follows_the_rules(demo, settings):
    store = demo[0]
    get = store.get
    inquiry = get("demo-inquiry")
    assert (inquiry.status, level(inquiry.priority), action_label(inquiry.kind, inquiry.conv, settings)) == \
        ("ready", "high", "First reply")
    crm_step = inquiry.plan[0]
    assert crm_step["id"] == "crm_inquiry" and not crm_step["enabled"] and "Inquiry-0031002" in crm_step["detail"]
    fu2 = get("demo-fu2")
    assert action_label(fu2.kind, fu2.conv, settings) == "Follow-up 2/4"
    draft = fu2.plan[0]["draft"]
    assert draft["to"] == "p.nair@helio-thera.example" and YANI in draft["cc"] and draft["quote"]["body"]
    assert "had a chance to review the email below" in draft["body"]
    assert get("demo-fu4").plan[0]["id"] == "followup_4"
    assert get("demo-upcoming").status == "scheduled"
    assert get("demo-crm-closed").status == "done" and "不买了" in get("demo-crm-closed").issues[0]
    assert get("demo-vendor").status == "skipped" and get("demo-colleague").status == "skipped"
    acct = next(s for s in get("demo-order").plan if s["id"] == "accounting")
    assert not acct["enabled"] and "Yani Zhao sent it to accounting" in acct["evidence"][0]
    hold = next(s for s in get("demo-order-hold").plan if s["id"] == "accounting")
    assert not hold["enabled"] and "asked to wait" in hold["evidence"][0]


def test_sending_a_follow_up_records_it_in_zoho_and_schedules_the_next(demo):
    store, gmail, zoho, _, ex = demo
    rec = ex.approve("demo-fu2", send=True)
    assert any(line.startswith("SENT") for line in gmail.log)
    note = zoho.notes[-1]
    assert note["title"].startswith("Follow-up #2 (email)") and "had a chance to review" in note["content"]
    assert tags(zoho, "p.nair@helio-thera.example") == ["跟进中"]
    assert rec.status == "scheduled" and rec.conv.followup_no == 3
    due = parse_date(rec.due_at) - datetime.now(timezone.utc)
    assert timedelta(days=6, hours=23) < due <= timedelta(days=7)
    assert any("Recorded “Follow-up #2" in a["text"] for a in store.activity("demo-fu2"))


def test_a_colleague_following_up_first_stops_the_send(demo):
    store, gmail, _, _, ex = demo
    ex.approve("demo-race")
    with pytest.raises(Conflict) as c:
        ex.send("demo-race", "followup_1")
    assert "Yani Zhao already replied to the customer" in c.value.reasons[0]
    assert not any(line.startswith("SENT") for line in gmail.log)
    assert store.get("demo-race").status == "awaiting_send"          # kept as a draft
    rec = ex.send("demo-race", "followup_1", force=True)              # "Send anyway"
    assert rec.conv.touches == 3 and any(line.startswith("SENT") for line in gmail.log)


def test_first_reply_uses_the_template_and_copies_the_team(demo):
    store, gmail, zoho, _, ex = demo
    draft = store.get("demo-inquiry").plan[1]["draft"]
    assert draft["to"] == "rmoreau@northfield.example"
    assert "inquiry@creative-biostructure.com" in draft["cc"] and YANI in draft["cc"]
    assert draft["body"].startswith("Hi Robin,") and "Liposome Formulation" in draft["body"]
    assert "1-516-512-3133" in draft["body"]
    ex.approve("demo-inquiry", send=True)
    # Yani's existing CRM record is reused, not duplicated, and gets the note + stage tag
    assert sum(1 for r in zoho.records.values() if r.get("Email") == "rmoreau@northfield.example") == 1
    assert zoho.notes[-1]["title"].startswith("First reply (email)")
    assert tags(zoho, "rmoreau@northfield.example") == ["询价"]
    assert store.get("demo-inquiry").conv.followup_no == 1


def test_reply_placeholder_must_be_filled_before_sending(demo, settings):
    store, gmail, _, pipe, ex = demo
    t = gmail.threads["demo-upcoming"]
    t.messages.append(EmailMessage("q1", "c.moss@coastal-demo.example", [ME], [], "Re: TEM", (datetime.now(
        timezone.utc) - timedelta(minutes=1)).isoformat(), "Thanks! Can you also do cryo-EM?", message_id="<q1@m>"))
    pipe.refresh("demo-upcoming")
    rec = store.get("demo-upcoming")
    assert rec.status == "ready" and rec.plan[0]["draft"]["template"] == "reply"
    with pytest.raises(ValueError, match="Write your reply first"):
        ex.approve("demo-upcoming", send=True)
    rec = ex.approve("demo-upcoming", steps={"reply": {"draft": {"body": "Yes, we can. Quote to follow.\n\nTony"}}},
                     send=True)
    assert rec.status == "scheduled"


def test_customer_who_declines_is_thanked_and_tagged(demo):
    store, gmail, zoho, _, ex = demo
    rec = store.get("demo-declined")
    assert [s["id"] for s in rec.plan] == ["reply", "tag_lost"]
    assert "Thank you for letting us know" in rec.plan[0]["draft"]["body"]
    rec = ex.approve("demo-declined", send=True)
    assert tags(zoho, "j.hale@riverton-med.example") == ["不买了"]
    assert rec.status == "done"


def test_no_answer_after_four_follow_ups_closes_as_lost(demo):
    store, _, zoho, _, ex = demo
    assert store.get("demo-close").plan[0]["id"] == "tag_lost"
    assert ex.approve("demo-close").status == "done"
    assert tags(zoho, "m.ito@bluefin-bio.example") == ["不买了"]


def test_order_creates_the_sale_tags_it_and_stops_quote_follow_ups(demo):
    store, gmail, zoho, _, ex = demo
    assert store.get("demo-order-cust").status == "ready"           # follow-up 1 was due
    rec = ex.approve("demo-order", send=True)
    states = {s["id"]: s["state"] for s in rec.plan}
    assert states == {"zoho_so": "done", "tag_ordered": "done", "label": "done", "confirm": "sent",
                      "accounting": "skipped"}                       # Yani already did accounting
    assert tags(zoho, "dr.lee@harborline-bio.example") == ["已下单"]
    assert store.get("demo-order-cust").status == "done"             # no more follow-ups
    confirmation = gmail.threads["demo-order-cust"].messages[-1]     # replied in the customer's own thread
    assert confirmation.sender == ME and "Thank you for your order CBSRX10012601" in confirmation.body
    assert zoho.notes[-1]["title"].startswith("Order confirmation (email)")


def test_accounting_email_is_rechecked_right_before_sending(demo):
    store, gmail, _, _, ex = demo
    with pytest.raises(Conflict) as c:
        ex.approve("demo-order-hold", steps={"accounting": {"enabled": True}, "confirm": {"enabled": False}},
                   send=True)
    assert "asked to hold the invoice" in c.value.reasons[0]
    assert not any("SENT" in line for line in gmail.log)


def test_outcome_buttons_keep_one_lifecycle_tag(demo):
    store, _, zoho, _, ex = demo
    assert ex.outcome("demo-fu4", "lost").status == "done"
    assert tags(zoho, "d.okafor@kestrel-labs.example") == ["不买了"]
    ex.outcome("demo-fu4", "ordered")                               # changed their mind
    assert tags(zoho, "d.okafor@kestrel-labs.example") == ["已下单"]
    assert zoho.notes[-1]["title"] == "Marked 已下单 in Sales Desk"


def test_snooze_ignore_and_due_dates(demo):
    store, _, _, pipe, ex = demo
    assert ex.snooze("demo-fu4", 3).status == "scheduled"
    ex.snooze("demo-fu4", -0.01)
    pipe.promote_due()
    assert store.get("demo-fu4").status == "ready"
    rec = ex.ignore("demo-fu2")
    assert rec.status == "skipped" and "helio-thera.example" in store.ignored_domains()
    pipe.scan(rescan=True)
    assert store.get("demo-fu2").kind == "other"


def test_unticking_the_email_keeps_the_conversation_alive(demo):
    store, gmail, _, _, ex = demo
    rec = ex.approve("demo-fu2", steps={"followup_2": {"enabled": False}})
    assert rec.status == "scheduled" and not gmail.drafts
    assert "no email was sent" in store.activity("demo-fu2")[0]["text"]


def test_replies_sent_straight_from_gmail_are_recorded_once(demo):
    store, gmail, zoho, pipe, _ = demo
    t = gmail.threads["demo-fu4"]
    t.messages.append(EmailMessage("g1", ME, ["d.okafor@kestrel-labs.example"], [], "Re: Cryo-EM screening quote",
                                   datetime.now(timezone.utc).isoformat(), "Quick update from Gmail.",
                                   message_id="<g1@m>"))
    pipe.scan()
    pipe.scan(rescan=True)
    gmail_notes = [n for n in zoho.notes if n["title"].startswith("Email to customer")]
    assert len(gmail_notes) == 1 and "Quick update from Gmail." in gmail_notes[0]["content"]


def test_a_handled_order_does_not_come_back_when_colleagues_reply(demo):
    store, gmail, _, pipe, ex = demo
    ex.approve("demo-order-hold", steps={"confirm": {"enabled": False}})
    assert store.get("demo-order-hold").status == "done"
    gmail.threads["demo-order-hold"].messages.append(EmailMessage(
        "z1", "platform@pr-abacebiology.com", [ME], [], "Re:Order_CBSXY10032602",
        datetime.now(timezone.utc).isoformat(), "样品表格 见附件"))
    pipe.scan()
    assert store.get("demo-order-hold").status == "done"
