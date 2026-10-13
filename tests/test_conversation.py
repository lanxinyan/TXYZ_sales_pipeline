from datetime import timedelta

from sales_pipeline.config import Settings
from sales_pipeline.conversation import analyze, forward_origin, fresh_text, invoice_status, parse_date
from sales_pipeline.models import EmailMessage, EmailThread

ME = "xinyan.zhang@creative-biostructure.com"
YANI = "yani.zhao@creative-biostructure.com"
CUST = "pat@lab.example"
S = Settings()

FORM = """---------- Forwarded message ---------
From: <admin@cd-sciences.info>
Date: Fri, Oct 9, 2026 at 2:16 PM
Subject: Liposome Formulation - Creative Biostructure (ID:
BS01-M-26100965765)
To: <inquiry@creative-biostructure.com>

Contact Information
First Name *robin*
Last Name *Smith*
Phone Number *6125550100 <(612)%20555-0100>*
Company/Institution *Example University*
Email *rs@uni.example <rs@uni.example>*
Extra Information
Topic *Liposome Formulation*"""

_n = [0]


def M(sender, to, body, date, cc=(), subject="Re: Quote", name=""):
    _n[0] += 1
    return EmailMessage(f"x{_n[0]}", sender, list(to), list(cc), subject, date, body,
                        message_id=f"<x{_n[0]}@m>", sender_name=name)


def day(d, h=12):
    return f"2026-09-{d:02d}T{h:02d}:00:00+00:00"


def test_website_inquiry_forward_needs_a_same_day_reply_and_sees_colleague_crm():
    t = EmailThread("t", "Fwd: Liposome Formulation - Creative Biostructure (ID: BS01-M-1)", [
        M("inquiry@creative-biostructure.com", [ME, YANI], FORM, day(9, 18)),
        M(YANI, ["usa@creative-biostructure.com"], "Extra Information\nTopic *Liposome Formulation*", day(9, 19)),
        M(YANI, [], "Inquiry-0012345 crm updated\n\nOn Fri, Oct 9 Yani wrote:\n> old", day(9, 20), cc=[ME],
          name="Yani Zhao")])
    c = analyze(t, S, ME)
    assert c.stage == "reply_needed" and not c.replied_ever and c.inquiry_forward
    assert c.customer_emails == ["rs@uni.example"]
    assert (c.customer_name, c.company, c.topic) == ("Robin Smith", "Example University", "Liposome Formulation")
    assert parse_date(c.due_at) - parse_date(day(9, 18)) == timedelta(hours=24)   # answer the first day
    assert c.crm_refs[0]["ref"] == "Inquiry-0012345" and c.crm_refs[0]["who"] == "Yani Zhao"
    assert c.last_inbound["cc"] == ["inquiry@creative-biostructure.com", YANI]     # reply-all to our people


def test_followups_count_colleagues_and_follow_the_1_2_7_30_cadence():
    msgs = [M(CUST, [ME], "Could you quote this?", day(1)),
            M(ME, [CUST], "Below is our quote CBSXY09012601.", day(2), cc=[YANI])]
    expected = [(1, 1), (2, 2), (3, 7), (4, 30)]
    senders = [ME, YANI, ME, YANI]
    for i, (n, gap) in enumerate(expected):
        c = analyze(EmailThread("t", "Re: Quote", list(msgs)), S, ME, now=parse_date(msgs[-1].date))
        assert (c.stage, c.followup_no, c.touches) == ("awaiting_customer", n, n)
        assert parse_date(c.due_at) - parse_date(msgs[-1].date) == timedelta(days=gap)
        msgs.append(M(senders[i], [CUST], f"follow-up {n}", day(3 + i), cc=[ME]))
    c = analyze(EmailThread("t", "Re: Quote", msgs), S, ME, now=parse_date(msgs[-1].date))
    assert c.stage == "exhausted" and c.touches == 5
    assert parse_date(c.due_at) - parse_date(msgs[-1].date) == timedelta(days=S.close_after_days)
    assert c.quote_sent and c.last_outbound["sender"] == YANI
    assert c.last_outbound["to"] == [CUST] and c.last_outbound["cc"] == [YANI]   # next follow-up copies Yani


def test_customer_reply_resets_the_follow_up_count():
    t = EmailThread("t", "Re: Quote", [
        M(ME, [CUST], "Our quote is attached.", day(1)),
        M(ME, [CUST], "Just checking in.", day(2)),
        M(CUST, [ME], "Can you do it in 4 weeks instead of 6?", day(3)),
        M(ME, [CUST], "Yes, 4 weeks works.", day(4))])
    c = analyze(t, S, ME, now=parse_date(day(4, 13)))
    assert (c.stage, c.followup_no) == ("awaiting_customer", 1)


def test_decline_only_after_we_replied_and_never_on_questions():
    first = EmailThread("t", "Inquiry", [M(CUST, [ME], "We cannot do this in-house. Is it more expensive than "
                                           "doing it locally?", day(1))])
    assert analyze(first, S, ME).signals == []
    t = EmailThread("t", "Re: Quote", [
        M(ME, [CUST], "Below is our quote CBSXY09052601.", day(1)),
        M(CUST, [ME], "It is way more expensive than we do it locally. Let me work with the core at our institute. Thanks!",
          day(2))])
    c = analyze(t, S, ME)
    assert c.stage == "reply_needed" and c.signals[0]["kind"] == "declined"
    t.messages.append(M(ME, [CUST], "Completely understand.", day(3)))
    assert analyze(t, S, ME).stage == "declined"


def test_a_thank_you_needs_no_answer_and_order_intent_is_noticed():
    t = EmailThread("t", "Re: update", [M(ME, [CUST], "Progress report attached.", day(1)),
                                        M(CUST, [ME], "Great! Thanks for the update.", day(2))])
    assert analyze(t, S, ME).stage == "none"
    t.messages[-1].body = "We would like to proceed. PO to follow."
    c = analyze(t, S, ME)
    assert c.stage == "reply_needed" and c.signals[0]["kind"] == "wants_to_order"


def test_quoted_history_and_forwards_in_quotes_are_ignored():
    body = ("Thanks, we will review.\n\nOn Tue, Sep 1, 2026 at 5:38 PM xinyan zhang <\n"
            "xinyan.zhang@creative-biostructure.com> wrote:\n> Our quote\n> ---------- Forwarded message ---------\n"
            "> From: Someone <someone@else.example>")
    assert fresh_text(body) == "Thanks, we will review."
    assert fresh_text("Hi Xinyan, no thanks.\nFrom: xinyan zhang <x@y.com>\nSent: Monday\nold") == "Hi Xinyan, no thanks."
    assert forward_origin(body) is None
    # my own internal message quoting the inquiry is not the customer writing again
    t = EmailThread("t", "Re: inquiry", [M(ME, ["usa@creative-biostructure.com"], "看一下哈\n\n" + body, day(1))])
    assert analyze(t, S, ME).customer_emails == []


def test_vendors_system_mailers_and_copies_are_handled():
    vendor = EmailThread("t", "Re: GPU", [M(ME, ["sam@vendor.example"], "Can you send a quote?", day(1))])
    assert analyze(vendor, S, ME, ignored={"vendor.example"}).customer_emails == []
    web = EmailThread("t", "Liposome - Creative Biostructure (ID: 1)",
                      [M("admin@cd-sciences.info", [ME], FORM.split("\n\n", 1)[1], day(1))])
    assert analyze(web, S, ME).customer_emails == ["rs@uni.example"]
    cc_only = EmailThread("t", "Re: project", [M(CUST, ["support@creative-biostructure.com"], "Question?", day(1),
                                                   cc=[ME])])
    c = analyze(cc_only, S, ME)
    assert c.stage == "reply_needed" and not c.last_inbound_to_me and not c.i_participated


def test_invoice_status_sees_colleagues_accounting_and_holds():
    acct = EmailThread("a", "Fwd: x", [M(YANI, ["accounting@creative-biomart.com"], "Order_CBSXY09012601 麻烦收预付 $2,000",
                                         day(11), cc=[ME], name="Yani Zhao")])
    hold = EmailThread("h", "Re:Order_X", [M("xiaoyu.zhu@pr-abacebiology.com", [ME],
                                             "先稍等发预付invoice，待确认最终订单金额", day(2), name="Xiaoyu Zhu")])
    reply = EmailThread("r", "Re: x", [M("accounting@creative-biomart.com", [CUST], "Attached is the upfront payment "
                                         "invoice.", day(14))])
    assert invoice_status([hold], S, ME)["state"] == "hold"
    assert "Xiaoyu Zhu asked to wait" in invoice_status([hold], S, ME)["evidence"][0]
    assert invoice_status([acct], S, ME)["state"] == "done"
    assert invoice_status([hold, acct], S, ME)["state"] == "done"     # the latest word wins
    assert invoice_status([reply], S, ME)["state"] == "done"
    assert invoice_status([EmailThread("n", "x", [M(ME, [CUST], "hi", day(1))])], S, ME)["state"] is None


def test_follow_ups_greet_the_customer_the_way_we_last_did():
    from sales_pipeline.tasks import values
    from sales_pipeline.models import Order

    t = EmailThread("t", "Re: Quote", [M(ME, [CUST], "Dear Dr. Okafor,\n\nPlease find our quotation attached.", day(1)),
                                       M(YANI, [CUST], "Dear Dr. Okafor, we have not heard from you.", day(3), cc=[ME])])
    c = analyze(t, S, ME)
    assert c.salutation == {"word": "Dear", "name": "Dr. Okafor"}
    assert values(S, Order(is_sales_order=False), c)["greeting"] == "Dear Dr. Okafor,"
    assert c.events[0]["text"] == "Please find our quotation attached."      # timeline skips the greeting
    t2 = EmailThread("t", "Re: Quote", [M(ME, [CUST], "Hi, Scott\n\nThat works for us.", day(1))])
    assert analyze(t2, S, ME).salutation == {"word": "Hi", "name": "Scott"}


def test_a_conversation_belongs_to_whoever_answers_the_customer():
    from sales_pipeline.conversation import owner_is_me

    fwd = M("inquiry@creative-biostructure.com", [ME, YANI], FORM, day(9, 18))
    t = EmailThread("t", "Fwd: inquiry", [fwd])
    assert owner_is_me(analyze(t, S, ME))                       # sent to you, nobody answered yet: yours
    t.messages.append(M(YANI, ["rs@uni.example"], "Dear Robin, thank you for your inquiry.", day(10), cc=[ME]))
    assert not owner_is_me(analyze(t, S, ME))                   # Yani answered: hers, left to her
    t.messages.append(M(ME, ["rs@uni.example"], "Adding a note on pricing.", day(11), cc=[YANI]))
    assert owner_is_me(analyze(t, S, ME))                       # you wrote to the customer too: yours again


def test_a_customer_asking_us_for_a_price_is_an_inquiry_but_a_vendor_quote_is_not():
    from sales_pipeline.models import Order
    from sales_pipeline.tasks import classify

    ask = EmailThread("t", "TEM negative-stain", [M(CUST, [ME], "Hi, could you quote negative-stain TEM for 6 "
                                                  "samples?", day(1))])
    c = analyze(ask, S, ME)
    assert c.asked_for_quote and classify(ask, Order(is_sales_order=False), c, S) == "quote_request"
    vendor = EmailThread("t", "Your quotation", [M("rep@vendor.example", [ME], "Please find attached the quotation "
                                                   "you requested. Let me know if you have questions.", day(1))])
    cv = analyze(vendor, S, ME)
    assert not cv.asked_for_quote and classify(vendor, Order(is_sales_order=False), cv, S) == "other"


def test_a_quote_that_went_quiet_long_ago_skips_ahead_to_a_firmer_follow_up():
    from datetime import datetime, timezone

    from sales_pipeline.conversation import catch_up

    sent = datetime(2026, 8, 1, tzinfo=timezone.utc)
    days = [1, 2, 7, 30]
    at = lambda d: sent + timedelta(days=d)          # noqa: E731
    assert [catch_up(1, sent, days, at(d)) for d in (1, 2.9, 3, 9, 10, 39, 40, 400)] == [1, 1, 2, 2, 3, 3, 4, 4]
    assert catch_up(3, sent, days, at(10)) == 3      # after FU2: FU3 is due at +7, FU4 not before +37
    t = EmailThread("t", "Re: Quote", [M(ME, [CUST], "Below is our quote CBSXY08012601.", "2026-08-01T12:00:00+00:00")])
    c = analyze(t, S, ME, now=at(25))
    assert (c.stage, c.touches, c.followup_no) == ("awaiting_customer", 1, 3)
    c = analyze(t, S, ME, now=at(49))                # a month or more: an "it's been a while" check-in instead
    assert (c.stage, c.quiet_days) == ("revisit", 48)     # the quote went out at noon


def test_quiet_for_a_month_to_three_months_gets_a_check_in():
    from datetime import datetime, timezone

    sent = datetime(2026, 7, 1, tzinfo=timezone.utc)
    at = lambda d: (sent + timedelta(days=d)).isoformat()          # noqa: E731
    quote = [M(CUST, [ME], "Could you quote this?", at(-1)), M(ME, [CUST], "Below is our quote CBSXY07012601.", at(0))]
    no_quote = [M(CUST, [ME], "Do you do TEM?", at(-1)), M(ME, [CUST], "Yes, we can help. How many samples?", at(0))]
    for msgs, quoted in ((quote, True), (no_quote, False)):
        c = analyze(EmailThread("t", "Re: Quote", list(msgs)), S, ME, now=parse_date(at(45)))
        assert (c.stage, c.quote_sent) == ("revisit", quoted)
    assert analyze(EmailThread("t", "Re", quote), S, ME, now=parse_date(at(95))).stage == "none"   # > 3 months

    # Natural cadence: follow-up 4 comes a month after follow-up 3 and keeps its own wording.
    fu = quote + [M(ME, [CUST], f"follow-up {i}", at(d)) for i, d in ((1, 1), (2, 3), (3, 10))]
    c = analyze(EmailThread("t", "Re", fu), S, ME, now=parse_date(at(41)))
    assert (c.stage, c.followup_no) == ("awaiting_customer", 4)

    # After the check-in: one last follow-up a week later, then close.
    checked = quote + [M(ME, [CUST], "Hi Pat,\n\nIt's been a while since we last talked.", at(45))]
    c = analyze(EmailThread("t", "Re", checked), S, ME, now=parse_date(at(46)))
    assert (c.stage, c.followup_no) == ("awaiting_customer", 4)
    assert parse_date(c.due_at) == parse_date(at(52))
    closed = checked + [M(ME, [CUST], "follow-up", at(52))]
    assert analyze(EmailThread("t", "Re", closed), S, ME, now=parse_date(at(53))).stage == "exhausted"
    # The customer answering starts things over.
    c = analyze(EmailThread("t", "Re", checked + [M(CUST, [ME], "Still interested!", at(47))]), S, ME,
                now=parse_date(at(47)))
    assert c.stage == "reply_needed"


def test_a_customer_we_answered_is_a_sales_conversation_without_a_quote_but_a_vendor_is_not():
    from sales_pipeline.models import Order
    from sales_pipeline.tasks import classify

    asked = EmailThread("t", "Cryo-EM", [M(CUST, [ME], "Do you do cryo-EM on membrane proteins?", day(1)),
                                         M(ME, [CUST], "Yes. How many constructs?", day(2))])
    assert classify(asked, Order(is_sales_order=False), analyze(asked, S, ME), S) == "quote_request"
    vendor = EmailThread("t", "Your quotation", [
        M("rep@vendor.example", [ME], "Please find attached the quotation you requested.", day(1)),
        M(ME, ["rep@vendor.example"], "Thanks, we will review it.", day(2))])
    assert classify(vendor, Order(is_sales_order=False), analyze(vendor, S, ME), S) == "other"
