"""Minimal Zoho CRM v8 REST client for Accounts, Contacts, Products and Sales_Orders."""
from __future__ import annotations

import logging
import time

import requests

from .models import Order

log = logging.getLogger(__name__)


class ZohoError(RuntimeError):
    pass


NO_API_ACCESS = (
    "Your Zoho user isn't allowed to use the Zoho CRM API yet (Zoho: NO_PERMISSION, Crm_Implied_Api_Access). "
    "A Zoho administrator needs to turn on API access for your profile: Setup > Users and Control > "
    "Security Control > Profiles > your profile > enable 'Zoho CRM API' (API Access). Then run this again; "
    "you don't need to reconnect.")


class ZohoCRM:
    def __init__(self, accounts_url: str, api_domain: str, client_id: str, client_secret: str,
                 refresh_token: str, session: requests.Session | None = None):
        self.accounts_url = accounts_url.rstrip("/")
        self.base = api_domain.rstrip("/") + "/crm/v8"
        self.client_id, self.client_secret, self.refresh_token = client_id, client_secret, refresh_token
        self.http = session or requests.Session()
        self._token: str | None = None
        self._token_expiry = 0.0

    # ---------- auth ----------

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        if not (self.client_id and self.client_secret and self.refresh_token):
            raise ZohoError("Zoho credentials missing - set ZOHO_CLIENT_ID/SECRET/REFRESH_TOKEN")
        r = self.http.post(f"{self.accounts_url}/oauth/v2/token", params={
            "grant_type": "refresh_token", "refresh_token": self.refresh_token,
            "client_id": self.client_id, "client_secret": self.client_secret}, timeout=30)
        data = r.json()
        if "access_token" not in data:
            raise ZohoError(f"Zoho token refresh failed: {data}")
        self._token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 3600))
        return self._token

    def _request(self, method: str, path: str, **kw) -> dict:
        headers = {"Authorization": f"Zoho-oauthtoken {self._access_token()}"}
        r = self.http.request(method, f"{self.base}/{path.lstrip('/')}", headers=headers, timeout=60, **kw)
        if r.status_code == 204:  # search with no results
            return {}
        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text}
        if r.status_code >= 400:
            if isinstance(data, dict) and data.get("code") == "NO_PERMISSION" and \
                    "Crm_Implied_Api_Access" in str(data.get("details")):
                raise ZohoError(NO_API_ACCESS)
            raise ZohoError(f"{method} {path} -> {r.status_code}: {data}")
        return data

    # ---------- generic ----------

    def search(self, module: str, criteria: str) -> list[dict]:
        return self._request("GET", f"{module}/search", params={"criteria": criteria}).get("data", [])

    def create(self, module: str, record: dict, trigger: bool = True) -> str:
        body = {"data": [record]}
        if trigger:
            body["trigger"] = ["workflow"]
        data = self._request("POST", module, json=body)
        result = data["data"][0]
        if result.get("status") != "success":
            raise ZohoError(f"create {module} failed: {result}")
        return result["details"]["id"]

    def attach(self, module: str, record_id: str, filename: str, content: bytes) -> None:
        self._request("POST", f"{module}/{record_id}/Attachments",
                      files={"file": (filename, content, "application/pdf")})

    @staticmethod
    def _esc(value: str) -> str:
        # Zoho criteria need ( ) , escaped
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace(",", "\\,")

    def get(self, module: str, record_id: str) -> dict:
        rows = self._request("GET", f"{module}/{record_id}").get("data", [])
        return rows[0] if rows else {}

    def find_by_email(self, module: str, email: str, fields: list[str] | None = None) -> list[dict]:
        parts = [f"({f}:equals:{self._esc(email)})" for f in (fields or ["Email"])]
        return self.search(module, parts[0] if len(parts) == 1 else "(" + "or".join(parts) + ")")

    def module_fields(self, module: str) -> list[dict]:
        return self._request("GET", "settings/fields", params={"module": module}).get("fields", [])

    # ---------- tags, notes, modules (v8: /{module}/{id}/actions/add_tags etc.) ----------

    def list_tags(self, module: str) -> list[dict]:
        return self._request("GET", "settings/tags", params={"module": module}).get("tags", [])

    def record_tags(self, module: str, record_id: str) -> list[str]:
        return [t.get("name", "") for t in (self.get(module, record_id).get("Tag") or [])]

    def add_tags(self, module: str, record_id: str, names: list[str]) -> None:
        if names:
            self._request("POST", f"{module}/{record_id}/actions/add_tags",
                          json={"tags": [{"name": n} for n in names], "over_write": False})

    def remove_tags(self, module: str, record_id: str, names: list[str]) -> None:
        if names:
            self._request("POST", f"{module}/{record_id}/actions/remove_tags",
                          json={"tags": [{"name": n} for n in names]})

    def add_note(self, module: str, record_id: str, title: str, content: str) -> str:
        note = {"Note_Title": title[:120], "Note_Content": content,
                "Parent_Id": {"module": {"api_name": module}, "id": record_id}}
        return self.create("Notes", note, trigger=False)

    def list_modules(self) -> list[dict]:
        return self._request("GET", "settings/modules").get("modules", [])

    # ---------- lookups / creates ----------

    def find_sales_order(self, subject: str) -> str | None:
        rows = self.search("Sales_Orders", f"(Subject:equals:{self._esc(subject)})")
        return rows[0]["id"] if rows else None

    def find_or_create_account(self, name: str, order: Order) -> str:
        rows = self.search("Accounts", f"(Account_Name:equals:{self._esc(name)})")
        if rows:
            return rows[0]["id"]
        rec = {"Account_Name": name}
        if order.customer.phone:
            rec["Phone"] = order.customer.phone
        if order.customer.billing_address:
            rec["Billing_Street"] = order.customer.billing_address
        log.info("creating Account %s", name)
        return self.create("Accounts", rec)

    def find_or_create_contact(self, order: Order, account_id: str | None) -> str | None:
        c = order.customer
        if not c.email:
            return None
        rows = self.search("Contacts", f"(Email:equals:{self._esc(c.email)})")
        if rows:
            return rows[0]["id"]
        name = (c.contact_name or c.email.split("@")[0]).strip()
        first, _, last = name.rpartition(" ")
        rec = {"Last_Name": last or name, "Email": c.email}
        if first:
            rec["First_Name"] = first
        if c.phone:
            rec["Phone"] = c.phone
        if account_id:
            rec["Account_Name"] = {"id": account_id}
        log.info("creating Contact %s", c.email)
        return self.create("Contacts", rec)

    def find_or_create_product(self, name: str, code: str | None, price: float | None,
                               auto_create: bool, generic_id: str) -> str:
        if code:
            rows = self.search("Products", f"(Product_Code:equals:{self._esc(code)})")
            if rows:
                return rows[0]["id"]
        rows = self.search("Products", f"(Product_Name:equals:{self._esc(name[:120])})")
        if rows:
            return rows[0]["id"]
        if not auto_create:
            if generic_id:
                return generic_id
            raise ZohoError(f"product not found in Zoho: {name!r} (enable ZOHO_AUTO_CREATE_PRODUCTS "
                            "or set ZOHO_GENERIC_PRODUCT_ID)")
        rec = {"Product_Name": name[:120], "Product_Active": True}
        if code:
            rec["Product_Code"] = code
        if price is not None:
            rec["Unit_Price"] = price
        log.info("creating Product %s", name)
        return self.create("Products", rec)
