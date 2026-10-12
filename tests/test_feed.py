import re
from datetime import datetime, timezone

import pytest

from sales_pipeline.actions import Executor
from sales_pipeline.demo import ME, seed
from sales_pipeline.feed import export, grade
from sales_pipeline.models import EmailMessage
from sales_pipeline.store import Store


@pytest.fixture
def demo(settings, tmp_path):
    settings.crm_feed_dir = str(tmp_path / "feed")
    store = Store(settings.db_path)
    gmail, zoho, pipe = seed(settings, store)
    return store, gmail, pipe


def section(text, who):
    part = next(p for p in text.split("\n## ") if who in p.split("\n", 1)[0])
    return part


def test_the_feed_speaks_the_rulebook(demo):
    store, gmail, pipe = demo
    res = export(pipe)
    text = open(res["path"], encoding="utf-8").read()
    fu2 = section(text, "Priya Nair")
    assert re.search(r"`\d{6}q: CBSXY10052611`", fu2)                       # quote sent
    assert re.search(r"`\d{6}f: follow-up 1` \(Yani Zhao\)", fu2)           # a colleague's follow-up
    assert "Team (from the quote/order number):** CBSXY" in fu2
    assert "add `No reply`: 4 follow-ups" in section(text, "m.ito@bluefin-bio.example")
    lee = section(text, "Harborline")
    assert re.search(r"`\d{6}: PO received`", lee) and "add `已下单`" in lee and "Key Customer:** YES" in lee
    usa = section(text, "Hanna Berg")
    assert "New record" in usa and "draft** for Tony to send, to internal people only: usa@" in usa
    # Not Tony's: the support@ thread he is only copied on, the GPU vendor, and an inquiry with nothing new.
    assert "s.kim@" not in text and "gpu-vendor" not in text and "Robin" not in text
    assert not re.search(r"[一-鿿]{2,}", usa)                       # no internal Chinese notes
    assert export(pipe)["path"] is None                                      # nothing is repeated


def test_new_activity_and_decisions_show_up_in_the_next_feed(demo):
    store, gmail, pipe = demo
    export(pipe)
    gmail.threads["demo-fu2"].messages.append(EmailMessage(
        "n1", "p.nair@helio-thera.example", [ME], [], "Re: Quote", datetime.now(timezone.utc).isoformat(),
        "Thanks Tony, is there any discount for 5 antibodies?", message_id="<n1@m>"))
    pipe.crm = None                                                          # Zoho not written directly
    ex = Executor(pipe.s, store, gmail=gmail, pipeline=pipe)
    ex.outcome("demo-fu4", "lost")
    text = open(export(pipe)["path"], encoding="utf-8").read()
    assert re.search(r"`\d{6}r: wants discount`: “Thanks Tony, is there any discount", text)
    assert "tag 不买了 (you chose this in Sales Desk" in text


def test_other_teams_are_left_out(demo):
    store, gmail, pipe = demo
    t = gmail.threads["demo-upcoming"]
    t.messages[-1].body = t.messages[-1].body.replace("CBSXY10102601", "CBSMA10102601")
    text = open(export(pipe)["path"], encoding="utf-8").read()
    assert "c.moss@" not in text.split("Left out", 1)[0]
    assert "c.moss@coastal-demo.example (CBSMA)" in text


def test_grades():
    assert grade("someone@gmail.com")[0] == "D"
    assert grade("pi@nih.gov")[0] == "A"
    assert grade("lab@stanford.edu")[0] == "B"
    assert grade("buyer@pharma.example")[0] == ""


def test_a_placeholder_feed_folder_gets_a_clear_message(demo):
    store, gmail, pipe = demo
    pipe.s.crm_feed_dir = r"C:\Users\<you>\OneDrive\Cowork"
    with pytest.raises(ValueError, match="copy the path"):
        export(pipe)


def test_a_promised_quote_is_not_a_quote_sent(settings):
    """Website inquiry -> internal notes -> Tony answers ("we will send a formal quote") -> customer
    replies -> Tony answers again. Nothing here is a quote."""
    from sales_pipeline.conversation import analyze
    from sales_pipeline.demo import INQ, USA, WEB_FORM, YANI
    from sales_pipeline.feed import read_thread
    from sales_pipeline.models import EmailThread

    settings.user_email = ME
    cust, s = "pat@univ-demo.edu", "Fwd: Pharmacosomes Production - Creative Biostructure (ID: BS01-M-1)"
    form = WEB_FORM.format(date="Fri, Oct 9, 2026", topic="Pharmacosomes Production", n="9", first="pat",
                           last="Lane", phone="555-0100", company="Univ Demo", email=cust, text="Hydrophobic drugs.")

    def m(i, sender, to, body, day, cc=()):
        return EmailMessage(f"r{i}", sender, to, list(cc), s, f"2026-10-{day}T12:{i:02d}:00+00:00", body,
                            message_id=f"<r{i}@m>")

    promise = "\n\nOnce we hear back, we will send a formal quote and turnaround time.\n\nBest regards,\nTony"
    t = EmailThread("rq", s, [
        m(1, INQ, [YANI, ME], form, "09"),
        m(2, YANI, [USA], "Extra Information", "09", cc=[ME]),
        m(3, YANI, [], "Inquiry-0026001 crm updated", "09", cc=[ME]),
        m(4, USA, [YANI], "具体药物分子是啥知道么\n5 ml /$381\n3周", "10", cc=[ME]),
        m(5, ME, [cust], "Dear Dr. Lane,\n\nYes, we can help with this. Are the drugs commercial?" + promise, "12",
          cc=[YANI, INQ]),
        m(6, cust, [ME], "They are commercially available inhibitors.", "12"),
        m(7, ME, [USA], "客户说 They are commercially available inhibitors.", "12", cc=[YANI]),
        m(8, ME, [cust], "Dear Pat,\n\nThank you, that helps. To prepare the quote, could you share the "
          "compounds?" + promise, "12", cc=[YANI]),
    ], "https://mail.google.com/")
    info = read_thread(t, None, settings)
    assert [(e.code, e.words) for e in info["entries"]] == [("f", "first reply"), ("r", "replied"), ("f", "answered")]
    assert info["quote_way"] is None and info["quotes"] == [] and info["inquiry"] == ["Inquiry-0026001"]
    assert not analyze(t, settings, ME).quote_sent          # follow-ups won't ask about "the quote"

    # Real quotes still count: a quote file, a new quote number, or "Below is our quote".
    t.messages.append(m(9, ME, [cust], "Dear Pat,\n\nPlease find attached our formal quotation.", "13"))
    t.messages[-1].attachment_names = ["Quotation_CBSXY10132601.pdf"]
    t.messages.append(m(10, ME, [cust], "Dear Pat,\n\nBelow is our quote: $4,200, 3 weeks.", "14"))
    info = read_thread(t, None, settings)
    assert [(e.code, e.words) for e in info["entries"][3:]] == [("q", "CBSXY10132601"), ("q", "quote sent")]
    assert analyze(t, settings, ME).quote_sent
