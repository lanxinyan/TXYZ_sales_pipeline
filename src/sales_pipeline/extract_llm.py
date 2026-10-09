"""Claude-based extraction: reads the whole thread plus attached PDFs
(formal quotes, customer POs) and returns a validated `Order`."""
from __future__ import annotations

import base64
import logging

import anthropic

from .models import EmailThread, Order

log = logging.getLogger(__name__)

SYSTEM = """You extract sales orders for Creative Biostructure, a life-science \
products and contract-research company. Staff email each other order forms \
(often in Chinese, subject "Order_<quote number>"), forward customer purchase \
orders, and attach formal quotations as PDFs.

Rules:
- The customer is the outside organization buying from us. Staff addresses on \
these domains are never the customer: {internal}.
- Our own purchases from vendors, invoices we receive, marketing, and quotes \
the customer has not accepted are not sales orders (is_sales_order=false).
- Prefer the attached formal quotation/PO for line items, prices, addresses \
and the customer company; use the email text for anything else.
- Translate Chinese notes into English in `notes`. Keep product names as written.
- Report money as plain numbers. Leave a field null rather than guessing."""

MAX_PDF_BYTES = 20 * 1024 * 1024


class ClaudeExtractor:
    def __init__(self, model: str, internal_domains: list[str], api_key: str | None = None):
        self.client = anthropic.Anthropic(api_key=api_key or None)
        self.model = model
        self.system = SYSTEM.format(internal=", ".join(internal_domains))

    def extract(self, thread: EmailThread) -> Order | None:
        content: list[dict] = []
        for pdf in thread.pdfs():
            if len(pdf.data) > MAX_PDF_BYTES:
                log.warning("skipping large PDF %s (%d bytes)", pdf.filename, len(pdf.data))
                continue
            content.append({
                "type": "document",
                "title": pdf.filename,
                "source": {"type": "base64", "media_type": "application/pdf",
                           "data": base64.standard_b64encode(pdf.data).decode()},
            })
        content.append({"type": "text", "text": f"Email thread:\n\n{thread.text()}\n\n"
                                                 "Extract the sales order."})

        response = self.client.beta.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=self.system,
            messages=[{"role": "user", "content": content}],
            output_format=Order,
            output_config={"effort": "medium"},
            # If a safety classifier declines, the API retries on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            log.warning("Claude declined thread %s: %s", thread.id, response.stop_details)
            return None
        if response.stop_reason == "max_tokens":
            log.warning("Claude output truncated for thread %s", thread.id)
            return None
        return response.parsed_output
