"""Read candidate order threads from Gmail and label them as they are processed."""
from __future__ import annotations

import base64
import html
import os
import re
from datetime import datetime, timezone
from email.utils import getaddresses, parseaddr

from .models import Attachment, EmailMessage, EmailThread

# Read, label and create drafts. Sales Desk never sends: you open the draft in
# Gmail, read it over and press Send there yourself.
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

LABEL_REVIEW = "Zoho/Needs review"
LABEL_SYNCED = "Zoho/Synced"
LABEL_SKIPPED = "Zoho/Not an order"
LABEL_QUOTE = "Zoho/Quote request"
ALL_LABELS = (LABEL_REVIEW, LABEL_SYNCED, LABEL_SKIPPED, LABEL_QUOTE)


def _b64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _html_to_text(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", s)
    s = re.sub(r"(?i)</td>|</th>", " ", s)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"[ \t]+", " ", html.unescape(s))


class GmailSource:
    def __init__(self, credentials_file: str, token_file: str):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds = None
        if os.path.exists(token_file):
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_file, "w") as f:
                f.write(creds.to_json())
        self.svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        self._label_ids: dict[str, str] = {}

    # ---------- reading ----------

    def search(self, query: str, limit: int = 50) -> list[str]:
        ids, token = [], None
        while len(ids) < limit:
            resp = self.svc.users().threads().list(
                userId="me", q=query, maxResults=min(100, limit - len(ids)), pageToken=token).execute()
            ids += [t["id"] for t in resp.get("threads", [])]
            token = resp.get("nextPageToken")
            if not token:
                break
        return ids

    def profile_email(self) -> str:
        return self.svc.users().getProfile(userId="me").execute()["emailAddress"].lower()

    def get_thread(self, thread_id: str, attachments: bool = True) -> EmailThread:
        raw = self.svc.users().threads().get(userId="me", id=thread_id, format="full").execute()
        # Unsent drafts (including ones Sales Desk prepared) are not part of the conversation.
        messages = [self._message(m, attachments) for m in raw.get("messages", [])
                    if "DRAFT" not in m.get("labelIds", [])]
        return EmailThread(
            id=thread_id,
            subject=messages[0].subject if messages else "",
            messages=messages,
            url=f"https://mail.google.com/mail/u/0/#all/{thread_id}",
        )

    def _message(self, m: dict, attachments: bool = True) -> EmailMessage:
        headers = {h["name"].lower(): h["value"] for h in m["payload"].get("headers", [])}
        plain, htmls, atts, names = [], [], [], []
        self._walk(m["id"], m["payload"], plain, htmls, atts, names, attachments)
        body = "\n".join(plain) if plain else _html_to_text("\n".join(htmls))
        sender_name, sender = parseaddr(headers.get("from", ""))
        date = headers.get("date", "")
        if m.get("internalDate"):
            date = datetime.fromtimestamp(int(m["internalDate"]) / 1000, tz=timezone.utc).isoformat()
        return EmailMessage(
            id=m["id"],
            sender=sender.lower(),
            sender_name=sender_name.strip('" '),
            attachment_names=names,
            to=[a.lower() for _, a in getaddresses([headers.get("to", "")]) if a],
            cc=[a.lower() for _, a in getaddresses([headers.get("cc", "")]) if a],
            subject=headers.get("subject", ""),
            date=date,
            body=body,
            attachments=atts,
            message_id=headers.get("message-id", ""),
        )

    def _walk(self, msg_id, part, plain, htmls, atts, names, download=True):
        mime = part.get("mimeType", "")
        body = part.get("body", {})
        if part.get("filename"):
            names.append(part["filename"])
            if download and (mime == "application/pdf" or part["filename"].lower().endswith(".pdf")):
                data = body.get("data")
                if not data and body.get("attachmentId"):
                    data = self.svc.users().messages().attachments().get(
                        userId="me", messageId=msg_id, id=body["attachmentId"]).execute()["data"]
                if data:
                    atts.append(Attachment(part["filename"], "application/pdf", _b64(data)))
        elif mime == "text/plain" and body.get("data"):
            plain.append(_b64(body["data"]).decode("utf-8", "replace"))
        elif mime == "text/html" and body.get("data"):
            htmls.append(_b64(body["data"]).decode("utf-8", "replace"))
        for sub in part.get("parts", []) or []:
            self._walk(msg_id, sub, plain, htmls, atts, names, download)

    # ---------- labelling ----------

    def _label_id(self, name: str) -> str:
        if not self._label_ids:
            for lab in self.svc.users().labels().list(userId="me").execute().get("labels", []):
                self._label_ids[lab["name"]] = lab["id"]
        if name not in self._label_ids:
            lab = self.svc.users().labels().create(
                userId="me", body={"name": name, "labelListVisibility": "labelShow",
                                   "messageListVisibility": "show"}).execute()
            self._label_ids[name] = lab["id"]
        return self._label_ids[name]

    def set_label(self, thread_id: str, name: str) -> None:
        """Apply one pipeline label and remove the others."""
        add = [self._label_id(name)]
        remove = [self._label_id(n) for n in ALL_LABELS if n != name]
        self.svc.users().threads().modify(
            userId="me", id=thread_id, body={"addLabelIds": add, "removeLabelIds": remove}).execute()

    # ---------- drafts (you send them from Gmail) ----------

    def create_draft(self, thread_id: str | None, to: list[str] | str, subject: str, body: str,
                     in_reply_to: str = "", cc: list[str] | str = "", quote: dict | None = None) -> dict:
        """Returns {"id": draft id, "thread_id": the Gmail thread the draft (and later the sent email) is in}."""
        from email.mime.text import MIMEText

        from .templates import quote_block

        msg = MIMEText(body.rstrip() + "\n" + quote_block(quote), "plain", "utf-8")
        msg["To"] = to if isinstance(to, str) else ", ".join(to)
        cc = cc if isinstance(cc, str) else ", ".join(cc)
        if cc:
            msg["Cc"] = cc
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = msg["References"] = in_reply_to
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        message = {"raw": raw}
        if thread_id:
            message["threadId"] = thread_id
        d = self.svc.users().drafts().create(userId="me", body={"message": message}).execute()
        return {"id": d["id"], "thread_id": d.get("message", {}).get("threadId") or thread_id}

    def draft_exists(self, draft_id: str) -> bool:
        from googleapiclient.errors import HttpError

        try:
            self.svc.users().drafts().get(userId="me", id=draft_id, format="minimal").execute()
            return True
        except HttpError as e:
            if getattr(e, "resp", None) is not None and e.resp.status == 404:
                return False
            raise

    def delete_draft(self, draft_id: str) -> None:
        self.svc.users().drafts().delete(userId="me", id=draft_id).execute()
