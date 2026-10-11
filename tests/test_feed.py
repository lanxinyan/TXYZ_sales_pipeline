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
