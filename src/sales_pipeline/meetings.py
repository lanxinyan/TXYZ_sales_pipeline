"""Coming meetings: customer meetings in your Google Calendar, next to their conversation.

Read-only access to the calendar, with its own sign-in (`sales-pipeline calendar-auth`), so
the Gmail sign-in isn't touched. A meeting counts when someone outside the company is invited
(colleagues, internal mailboxes and declined meetings are left out). After a meeting with a
known customer, `MMDDYY: teleconference` goes into the Cowork feed (the rulebook's TC note)."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from .conversation import Who, parse_date

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


class CalendarSource:
    def __init__(self, credentials_file: str, token_file: str):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(token_file, SCOPES) if os.path.exists(token_file) else None
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                creds = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES).run_local_server(port=0)
            with open(token_file, "w") as f:
                f.write(creds.to_json())
        self.svc = build("calendar", "v3", credentials=creds, cache_discovery=False)

    def events(self, start: datetime, end: datetime) -> list[dict]:
        out, token = [], None
        while True:
            resp = self.svc.events().list(
                calendarId="primary", timeMin=start.isoformat(), timeMax=end.isoformat(), singleEvents=True,
                orderBy="startTime", maxResults=250, pageToken=token).execute(num_retries=3)
            out += resp.get("items", [])
            token = resp.get("nextPageToken")
            if not token:
                return out


def _when(ev: dict, key: str) -> datetime | None:
    t = ev.get(key) or {}
    return parse_date(t.get("dateTime") or t.get("date"))


def customer_meetings(calendar, s, store, days_ahead: int = 14, days_back: int = 0) -> list[dict]:
    """Meetings with someone from outside the company, with the matching conversation (if any)."""
    now = datetime.now(timezone.utc)
    who = Who(s, s.user_email, store.ignored_domains())
    recs = [r for r in store.list() if r.conv and r.conv.customer_emails]
    out = []
    for ev in calendar.events(now - timedelta(days=days_back), now + timedelta(days=days_ahead)):
        if ev.get("status") == "cancelled":
            continue
        people = ev.get("attendees") or []
        mine = next((p for p in people if p.get("self") or (p.get("email") or "").lower() == s.user_email), None)
        if mine and mine.get("responseStatus") == "declined":
            continue
        customers = [(p.get("email") or "").lower() for p in people if who.customer((p.get("email") or "").lower())]
        if not customers:
            continue
        linked = sorted((r for r in recs if set(customers) & set(r.conv.customer_emails)),
                        key=lambda r: r.conv.last_inbound_at or r.conv.last_outbound_at or "", reverse=True)
        link = ""
        for ep in (ev.get("conferenceData") or {}).get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                link = ep.get("uri", "")
        out.append({
            "id": ev.get("id"), "title": ev.get("summary") or "(no title)", "start": _when(ev, "start"),
            "end": _when(ev, "end"), "customers": customers, "url": ev.get("htmlLink", ""),
            "join": link or ev.get("hangoutLink") or ev.get("location") or "",
            "description": (ev.get("description") or "")[:1500],
            "threads": [r.thread_id for r in linked],
        })
    return out


def meetings_json(items: list[dict], store, s) -> list[dict]:
    from .web import record_json

    out = []
    for m in items:
        recs = [store.get(t) for t in m["threads"][:3]]
        out.append({**m, "start": m["start"].isoformat() if m["start"] else None,
                    "end": m["end"].isoformat() if m["end"] else None,
                    "conversations": [record_json(r, s) for r in recs if r]})
    return out


def note_past_meetings(calendar, s, store) -> int:
    """After a meeting with a known customer: `MMDDYY: teleconference` for Cowork, once."""
    n = 0
    now = datetime.now(timezone.utc)
    for m in customer_meetings(calendar, s, store, days_ahead=0, days_back=3):
        end = m["end"] or m["start"]
        if not m["threads"] or not end or end > now or store.meta(f"meeting:{m['id']}"):
            continue
        start = (m["start"] or end).astimezone()
        store.add_feed_item(m["threads"][0], f"note: {start:%m%d%y}: teleconference")
        store.log(m["threads"][0], f"Teleconference {start:%b %d} recorded for Cowork ({m['title']})")
        store.set_meta(f"meeting:{m['id']}", "noted")
        n += 1
    return n
