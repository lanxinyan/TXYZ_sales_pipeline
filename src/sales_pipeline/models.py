"""Data shapes shared by every stage of the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------- what we read out of Gmail ----------

@dataclass
class Attachment:
    filename: str
    mime_type: str
    data: bytes


@dataclass
class EmailMessage:
    id: str
    sender: str
    to: list[str]
    cc: list[str]
    subject: str
    date: str
    body: str
    attachments: list[Attachment] = field(default_factory=list)
    message_id: str = ""  # RFC 822 Message-ID header, used to thread replies
    sender_name: str = ""
    attachment_names: list[str] = field(default_factory=list)


@dataclass
class EmailThread:
    id: str
    subject: str
    messages: list[EmailMessage]
    url: str = ""

    def text(self) -> str:
        """The whole conversation as plain text, oldest message first."""
        parts = []
        for m in self.messages:
            parts.append(
                f"--- From: {m.sender} | Date: {m.date} | Subject: {m.subject}\n"
                f"To: {', '.join(m.to)}" + (f" | Cc: {', '.join(m.cc)}" if m.cc else "") + f"\n\n{m.body.strip()}"
            )
        return "\n\n".join(parts)

    def pdfs(self) -> list[Attachment]:
        seen, out = set(), []
        for m in self.messages:
            for a in m.attachments:
                if a.mime_type == "application/pdf" and a.filename not in seen:
                    seen.add(a.filename)
                    out.append(a)
        return out


# ---------- the structured order (also the Claude output schema) ----------

class LineItem(BaseModel):
    product_name: str = Field(description="Product or service name as quoted")
    catalog_number: Optional[str] = Field(None, description="Catalog / SKU number if any")
    quantity: float = Field(1, description="Quantity ordered")
    unit_price: Optional[float] = Field(None, description="Price per unit before discount, in order currency")
    discount: Optional[float] = Field(None, description="Discount amount for this line (money, not percent)")


class Customer(BaseModel):
    company: Optional[str] = Field(None, description="Customer organization / institution name")
    contact_name: Optional[str] = Field(None, description="Customer contact person full name")
    email: Optional[str] = Field(None, description="Customer contact email (never an internal company address)")
    phone: Optional[str] = None
    billing_address: Optional[str] = None
    shipping_address: Optional[str] = None


class Order(BaseModel):
    is_sales_order: bool = Field(
        description="True only if this thread confirms a customer is buying from us "
        "(order form, customer PO, order confirmation). False for quotes not yet accepted, "
        "our own purchases from vendors, invoices we received, marketing."
    )
    order_code: Optional[str] = Field(None, description="Internal order / quote number, e.g. CBSRX09242501B-2")
    po_number: Optional[str] = Field(None, description="Customer purchase-order number, if given")
    order_date: Optional[str] = Field(None, description="Order date as YYYY-MM-DD")
    order_type: Optional[Literal["product", "service", "custom"]] = None
    currency: str = "USD"
    customer: Customer = Field(default_factory=Customer)
    items: list[LineItem] = Field(default_factory=list)
    shipping: Optional[float] = Field(None, description="Shipping / handling / dry-ice charges")
    discount: Optional[float] = Field(None, description="Order-level discount amount (money)")
    total: Optional[float] = Field(None, description="Final order total")
    payment_terms: Optional[str] = Field(None, description="e.g. prepayment required, Net 30, credit card")
    sales_rep: Optional[str] = None
    customer_status: Optional[Literal["new", "existing", "distributor"]] = None
    notes: Optional[str] = Field(None, description="Anything the order processor must know")


# ---------- a customer conversation (inquiry -> reply -> follow-ups) ----------

class Conversation(BaseModel):
    """What the email thread says about where we stand with the customer."""
    customer_emails: list[str] = Field(default_factory=list)
    customer_name: Optional[str] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    topic: Optional[str] = None
    first_inbound_at: Optional[str] = None
    last_inbound_at: Optional[str] = None
    last_inbound_text: Optional[str] = None
    last_inbound_to_me: bool = False
    # the customer's last email: gmail_id, rfc_id, sender, subject, date, cc (our people on it)
    last_inbound: Optional[dict] = None
    inquiry_forward: bool = False   # started as a forwarded website/email inquiry
    asked_for_quote: bool = False   # the customer asked us for a quote / price
    salutation: Optional[dict] = None   # how we last greeted them: {"word": "Dear", "name": "Dr. Okafor"}
    last_outbound_at: Optional[str] = None
    last_outbound_by: Optional[str] = None
    # the email being followed up: gmail_id, rfc_id, sender, to, cc, subject, date, body
    last_outbound: Optional[dict] = None
    touches: int = 0              # our emails to the customer since they last wrote
    replied_ever: bool = False
    i_participated: bool = False
    quote_sent: bool = False
    # reply_needed | awaiting_customer | declined | exhausted | none
    stage: str = "none"
    followup_no: int = 0          # the follow-up that is next (1-4)
    due_at: Optional[str] = None
    signals: list[dict] = Field(default_factory=list)   # {kind, text}
    events: list[dict] = Field(default_factory=list)    # timeline {at, who, kind, text}
    crm_refs: list[dict] = Field(default_factory=list)  # {ref, who, at}
    newest_message_id: Optional[str] = None


ReviewStatus = Literal["needs_review", "ready", "pushed", "failed", "skipped"]
