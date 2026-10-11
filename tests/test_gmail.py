import base64
import email

from sales_pipeline.gmail_source import GmailSource


class _Exec:
    def __init__(self, value):
        self.value = value

    def execute(self, num_retries=0):
        return self.value


class FakeService:
    def __init__(self, thread):
        self.thread, self.created = thread, []

    def users(self):
        return self

    def threads(self):
        return self

    def drafts(self):
        return self

    def get(self, **kw):
        return _Exec(self.thread)

    def create(self, userId, body):
        self.created.append(body)
        return _Exec({"id": "d1"})


def _part(text):
    return {"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()}}


def _msg(mid, sender, labels, text):
    return {"id": mid, "labelIds": labels, "internalDate": "1791580442000",
            "payload": {"headers": [{"name": "From", "value": sender}, {"name": "To", "value": "c@x.example"},
                                    {"name": "Subject", "value": "Re: Quote"},
                                    {"name": "Message-ID", "value": f"<{mid}@m>"}], **_part(text)}}


def gmail_with(thread):
    g = GmailSource.__new__(GmailSource)       # skip OAuth
    g.svc, g._label_ids = FakeService(thread), {}
    return g


def test_unsent_drafts_are_not_part_of_the_conversation():
    g = gmail_with({"messages": [_msg("a", "Tony <t@creative-biostructure.com>", ["SENT"], "Our quote."),
                                 _msg("b", "t@creative-biostructure.com", ["DRAFT"], "draft follow-up")]})
    t = g.get_thread("T1", attachments=False)
    assert [m.id for m in t.messages] == ["a"]
    m = t.messages[0]
    assert (m.sender, m.sender_name, m.message_id) == ("t@creative-biostructure.com", "Tony", "<a@m>")
    assert m.date.startswith("2026-10-09T")     # from Gmail's internal timestamp


def test_follow_up_draft_is_a_threaded_reply_with_cc_and_quote():
    g = gmail_with({})
    g.create_draft("T1", ["c@x.example"], "Re: Quote", "Hi Pat,\n\nAny news?", "<a@m>", ["yani@creative-biostructure.com"],
                   {"sender": "Tony <t@x.com>", "date_label": "Thu, Oct 8", "body": "Our quote."})
    body = g.svc.created[0]
    assert body["message"]["threadId"] == "T1"
    msg = email.message_from_bytes(base64.urlsafe_b64decode(body["message"]["raw"]))
    assert msg["To"] == "c@x.example" and msg["Cc"] == "yani@creative-biostructure.com"
    assert msg["In-Reply-To"] == "<a@m>"
    text = msg.get_payload(decode=True).decode()
    assert text.startswith("Hi Pat,\n\nAny news?") and "On Thu, Oct 8, Tony <t@x.com> wrote:\n> Our quote." in text
    g.create_draft(None, "acct@x.example", "Order_X", "body")       # accounting email: a new thread
    assert "threadId" not in g.svc.created[1]["message"]
