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


def send_in_gmail(gmail, ex, tid):
    """You open the drafts in Gmail and press Send there; Sales Desk notices on its next look."""
    for st in ex.store.get(tid).plan:
        if st.get("state") == "drafted":
            gmail.send_draft(st["draft_id"])
    return ex.sync(tid)


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
    assert draft["to"] == "p.nair@helio-thera.example" and draft["cc"] == "" and draft["quote"]["body"]
    assert "had a chance to review the email below" in draft["body"]
    assert get("demo-fu4").plan[0]["id"] == "followup_4"
    assert get("demo-upcoming").status == "scheduled"
    assert get("demo-crm-closed").status == "done" and "不买了" in get("demo-crm-closed").issues[0]
    assert get("demo-vendor").status == "skipped" and get("demo-colleague").status == "skipped"
    acct = next(s for s in get("demo-order").plan if s["id"] == "accounting")
    assert not acct["enabled"] and "Yani Zhao sent it to accounting" in acct["evidence"][0]
    hold = next(s for s in get("demo-order-hold").plan if s["id"] == "accounting")
    assert not hold["enabled"] and "asked to wait" in hold["evidence"][0]


def test_a_follow_up_is_drafted_and_you_send_it_from_gmail(demo):
    store, gmail, zoho, _, ex = demo
    rec = ex.approve("demo-fu2")
    assert rec.status == "awaiting_send" and len(gmail.drafts) == 1
    assert not any(line.startswith("SENT") for line in gmail.log)       # Sales Desk never sends
    assert ex.sync("demo-fu2").status == "awaiting_send"                # not sent yet: stays in drafts
    rec = send_in_gmail(gmail, ex, "demo-fu2")
    note = zoho.notes[-1]
    assert note["title"].startswith("Follow-up #2 (email)") and "had a chance to review" in note["content"]
    assert tags(zoho, "p.nair@helio-thera.example") == ["跟进中"]
    assert rec.status == "scheduled" and rec.conv.followup_no == 3
    due = parse_date(rec.due_at) - datetime.now(timezone.utc)
    assert timedelta(days=6, hours=23) < due <= timedelta(days=7)
    assert any("Recorded “Follow-up #2" in a["text"] for a in store.activity("demo-fu2"))


def test_a_colleague_following_up_first_stops_the_draft(demo):
    store, gmail, _, _, ex = demo
    with pytest.raises(Conflict) as c:
        ex.approve("demo-race")
    assert "Yani Zhao already replied to the customer" in c.value.reasons[0]
    assert not gmail.drafts and store.get("demo-race").status == "ready"
    assert ex.approve("demo-race", force=True).status == "awaiting_send"     # "Draft anyway"
    rec = send_in_gmail(gmail, ex, "demo-race")
    assert rec.conv.touches == 3


def test_first_reply_uses_the_template_and_goes_to_the_customer_only(demo):
    store, gmail, zoho, _, ex = demo
    draft = store.get("demo-inquiry").plan[1]["draft"]
    assert draft["to"] == "rmoreau@northfield.example" and draft["cc"] == ""     # no inquiry@, no Yani
    assert YANI not in str(draft) and "inquiry@" not in str(draft)
    assert draft["subject"] == "Re: Liposome Formulation - Creative Biostructure (ID: BS01-M-261010001)"
    assert draft["body"].startswith("Hi Robin,") and "inquiry about liposome formulation" in draft["body"]
    assert "1-631-559-9269" in draft["body"]
    ex.approve("demo-inquiry")
    send_in_gmail(gmail, ex, "demo-inquiry")
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
        ex.approve("demo-upcoming")
    rec = ex.approve("demo-upcoming", steps={"reply": {"draft": {"body": "Yes, we can. Quote to follow.\n\nTony"}}})
    assert rec.status == "awaiting_send"
    assert send_in_gmail(gmail, ex, "demo-upcoming").status == "scheduled"


def test_customer_who_declines_is_thanked_and_tagged(demo):
    store, gmail, zoho, _, ex = demo
    rec = store.get("demo-declined")
    assert [s["id"] for s in rec.plan] == ["reply", "tag_lost"]
    assert "Thank you for letting us know" in rec.plan[0]["draft"]["body"]
    ex.approve("demo-declined")
    assert tags(zoho, "j.hale@riverton-med.example") == ["不买了"]
    assert send_in_gmail(gmail, ex, "demo-declined").status == "done"


def test_no_answer_after_four_follow_ups_is_tagged_no_reply(demo):
    store, _, zoho, _, ex = demo
    assert store.get("demo-close").plan[0]["id"] == "tag_no_response"
    assert ex.approve("demo-close").status == "done"
    assert tags(zoho, "m.ito@bluefin-bio.example") == ["No reply"]


def test_order_creates_the_sale_tags_it_and_stops_quote_follow_ups(demo):
    store, gmail, zoho, _, ex = demo
    assert store.get("demo-order-cust").status == "ready"           # follow-up 1 was due
    assert ex.approve("demo-order").status == "awaiting_send"
    rec = send_in_gmail(gmail, ex, "demo-order")
    states = {s["id"]: s["state"] for s in rec.plan}
    assert states == {"zoho_so": "done", "tag_ordered": "done", "label": "done", "confirm": "sent",
                      "accounting": "skipped"}                       # Yani already did accounting
    assert tags(zoho, "dr.lee@harborline-bio.example") == ["已下单"]
    assert store.get("demo-order-cust").status == "done"             # no more follow-ups
    confirmation = gmail.threads["demo-order-cust"].messages[-1]     # replied in the customer's own thread
    assert confirmation.sender == ME and "Thank you for your order CBSRX10012601" in confirmation.body
    assert zoho.notes[-1]["title"].startswith("Order confirmation (email)")


def test_accounting_email_is_rechecked_before_it_is_drafted(demo):
    store, gmail, _, _, ex = demo
    with pytest.raises(Conflict) as c:
        ex.approve("demo-order-hold", steps={"accounting": {"enabled": True}, "confirm": {"enabled": False}})
    assert "asked to hold the invoice" in c.value.reasons[0]
    assert not gmail.drafts


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
    assert "no email was drafted" in store.activity("demo-fu2")[0]["text"]


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


def test_first_reply_sees_a_zoho_record_even_without_a_crm_email(demo, settings):
    store, gmail, zoho, pipe, _ = demo
    zoho._add("Leads", {"Last_Name": "Moss", "Email": "c.moss@coastal-demo.example"})
    t = gmail.threads["demo-upcoming"]
    t.messages[:] = t.messages[:1]                               # only the customer's inquiry so far
    pipe.refresh("demo-upcoming")
    step = store.get("demo-upcoming").plan[0]
    assert step["id"] == "crm_inquiry" and not step["enabled"] and "Already in Zoho" in step["detail"]


def test_a_draft_deleted_in_gmail_comes_back_to_decide(demo):
    store, gmail, _, _, ex = demo
    rec = ex.approve("demo-fu2")
    gmail.delete_draft(rec.plan[0]["draft_id"])                    # you deleted it in Gmail
    rec = ex.sync("demo-fu2")
    assert rec.status == "ready" and rec.plan[0]["state"] == "pending" and "deleted" in rec.plan[0]["result"]


def test_customer_emails_never_reach_colleagues_or_carry_chinese(demo):
    from sales_pipeline.demo import USA
    from sales_pipeline.safety import UnsafeEmail

    store, gmail, _, _, ex = demo
    rec = store.get("demo-usa")                    # the US office forwarded it with a note in Chinese
    reply = next(s for s in rec.plan if s["id"] == "reply")
    d = reply["draft"]
    assert d["to"] == "h.berg@fjord-bio.example" and d["cc"] == "" and USA not in str(d)
    assert d["subject"] == "Re: Negative stain EM question" and not d.get("quote")
    assert "请" not in d["body"]
    with pytest.raises(UnsafeEmail, match="usa@creative-biostructure.com"):
        ex.approve("demo-usa", steps={"reply": {"draft": {"cc": USA}}})
    with pytest.raises(UnsafeEmail, match="Chinese"):
        ex.approve("demo-usa", steps={"reply": {"draft": {"cc": "", "body": d["body"] + "\n请看下"}}})
    assert not gmail.drafts
    ex.approve("demo-usa", steps={"reply": {"draft": {"body": d["body"]}}})
    (made,) = gmail.drafts.values()
    assert made["to"] == ["h.berg@fjord-bio.example"] and made["cc"] == []


def test_the_chinese_accounting_brief_is_only_for_accounting(settings):
    from sales_pipeline.safety import problems

    brief = {"to": "accounting@creative-biomart.com", "subject": "Order_X 开发票", "body": "Order_X: 麻烦开发票 $1,000"}
    assert problems(brief, settings) == []
    assert problems(dict(brief, cc="dr.lee@harborline-bio.example"), settings)
    to_customer = {"to": "dr.lee@harborline-bio.example", "subject": "Re: Quote", "body": "Hi Dana,"}
    assert problems(to_customer, settings) == []
    assert problems(dict(to_customer, body="Hi Dana, ask usa@creative-biostructure.com"), settings)


def test_unchanged_threads_are_not_downloaded_again(demo):
    store, gmail, _, pipe, _ = demo
    gmail.history = {tid: "h1" for tid in gmail.threads}      # Gmail's change marker, from the search
    calls = []
    real = gmail.get_thread
    gmail.get_thread = lambda tid, attachments=True: calls.append(tid) or real(tid, attachments)
    pipe.scan()
    calls.clear()
    pipe.scan()
    assert calls == []                                          # nothing changed: nothing downloaded
    gmail.history["demo-fu2"] = "h2"
    pipe.scan()
    assert calls == ["demo-fu2"]


def test_gmail_rate_limit_pauses_the_scan_instead_of_failing(demo):
    store, gmail, _, pipe, _ = demo

    def busy(tid, attachments=True):
        raise RuntimeError("<HttpError 403 ... 'Quota exceeded for quota metric', 'reason': 'rateLimitExceeded'>")

    gmail.get_thread = busy
    counts = pipe.scan(rescan=True)
    assert any(k.startswith("paused: Gmail's per-minute limit") for k in counts)


def test_items_planned_by_an_older_version_are_planned_again(demo):
    store, gmail, _, pipe, _ = demo
    rec = store.get("demo-fu2")
    old = [dict(rec.plan[0], draft=dict(rec.plan[0]["draft"], cc=YANI))]   # how the old version planned it
    store.update("demo-fu2", plan=old)
    store.set_meta("plan_version", "1")
    assert pipe.upgrade_plans() >= 1
    assert store.get("demo-fu2").plan[0]["draft"]["cc"] == ""
    assert pipe.upgrade_plans() == 0                                       # only once


def test_a_new_internal_domain_takes_effect_on_the_next_scan(demo, settings):
    store, gmail, _, pipe, _ = demo
    pipe.scan()
    assert store.get("demo-usa").kind == "quote_request"
    settings.internal_domains.append("fjord-bio.example")      # e.g. a sister company added in .env
    pipe.scan()                                                 # no rescan asked for
    assert store.get("demo-usa").kind == "other" and store.get("demo-usa").status == "skipped"


def test_quiet_conversations_wait_in_revisit_with_a_check_in(demo):
    store, gmail, _, pipe, ex = demo
    rec = store.get("demo-revisit")                       # quote sent 50 days ago, nobody followed up
    assert rec.status == "revisit" and [s["id"] for s in rec.plan] == ["revisit"]
    d = rec.plan[0]["draft"]
    assert d["template"] == "revisit_quote" and d["body"].startswith("Dear Dr. Nguyen,")
    assert "It's been a while" in d["body"] and "update the quote" in d["body"] and d["quote"]["body"]
    assert d["to"] == "l.nguyen@sparrow-demo.example" and d["cc"] == ""
    assert store.get("demo-revisit-noquote").plan[0]["draft"]["template"] == "revisit_service"
    assert store.get("demo-fu4").plan[0]["id"] == "followup_4"     # the natural 4th follow-up is unchanged
    ex.approve("demo-revisit")
    rec = send_in_gmail(gmail, ex, "demo-revisit")
    assert rec.status == "scheduled" and rec.conv.revisited_at and rec.conv.followup_no == 4   # last try in a week


def test_your_decisions_survive_reading_the_threads_again(demo):
    store, gmail, _, pipe, ex = demo
    pipe.crm = ex.crm = None
    ex.outcome("demo-fu4", "lost")
    ex.skip("demo-fu2")
    ex.snooze("demo-revisit", 3)
    pipe.scan(rescan=True)                                # e.g. after an update re-reads everything
    assert store.get("demo-fu4").status == "done" and store.get("demo-fu2").status == "skipped"
    assert store.get("demo-revisit").status == "scheduled"
    gmail.threads["demo-fu4"].messages.append(EmailMessage(
        "w1", "d.okafor@kestrel-labs.example", [ME], [], "Re: Cryo-EM screening quote",
        datetime.now(timezone.utc).isoformat(), "Sorry for the delay, we are still interested.", message_id="<w1@m>"))
    pipe.scan()
    assert store.get("demo-fu4").status == "ready"         # a new email from the customer reopens it
