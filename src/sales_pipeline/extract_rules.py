"""Deterministic extraction - no API calls.

Handles the internal order-form email ("Order_<code>", the spreadsheet row pasted
into the body with headers like 年月日 报价号 ... 产品名称 Qty PO 产品报价 ...) and
picks out order codes, PO numbers, money amounts and customer emails from any
other email. It is also the safety net that cross-checks Claude's answer.
"""
from __future__ import annotations

import re
from datetime import datetime

from .models import Customer, EmailThread, LineItem, Order

MONEY = re.compile(r"\$\s?([\d,]+(?:\.\d{1,2})?)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
DATE = re.compile(r"\b(20\d{2})[/-](\d{1,2})[/-](\d{1,2})\b")
QTY = re.compile(r"^\d+(?:\*\d+)?$")
PO = re.compile(r"\b(?:P\.?O\.?|purchase order)\s*(?:#|no\.?|number)?\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{3,})", re.I)

# Header cells of the internal order form, in order.
FORM_MARKERS = ("报价号", "产品名称", "Qty")
ORDER_TYPES = {"服务": "service", "产品": "product", "定制": "custom"}
CUSTOMER_STATUS = {"新客户": "new", "老客户": "existing", "分销商": "distributor"}
EMPTY = {"无", "N/A", "-", ""}


def _money(s: str) -> float:
    return float(s.replace(",", ""))


def is_internal(email: str, internal_domains: list[str]) -> bool:
    domain = email.lower().rsplit("@", 1)[-1]
    return any(domain == d or domain.endswith("." + d) for d in internal_domains)


def find_order_codes(text: str, pattern: str) -> list[str]:
    return list(dict.fromkeys(re.findall(pattern, text)))


def parse_order_form(body: str, code_pattern: str) -> Order | None:
    """Parse the flattened order-form row. Empty cells vanish when Gmail turns the
    table into text, so we anchor on recognisable values instead of column positions."""
    if not all(m in body for m in FORM_MARKERS):
        return None
    first_line = body.strip().splitlines()[0]
    tokens = first_line.split()
    # The value row starts at the first date after the header cells.
    start = next((i for i, t in enumerate(tokens) if DATE.fullmatch(t)), None)
    if start is None:
        return None
    vals = tokens[start:]
    y, m, d = DATE.fullmatch(vals[0]).groups()
    order = Order(is_sales_order=True, order_date=f"{int(y):04d}-{int(m):02d}-{int(d):02d}")

    i = 1
    if i < len(vals) and re.fullmatch(code_pattern, vals[i]):
        order.order_code = vals[i]
        i += 1
    if i < len(vals) and vals[i] in ORDER_TYPES:
        order.order_type = ORDER_TYPES[vals[i]]
        i += 1
    # Optional catalog number, then the product name, up to the quantity token.
    name_tokens: list[str] = []
    qty = 1.0
    while i < len(vals):
        if QTY.match(vals[i]):
            a, _, b = vals[i].partition("*")
            qty = float(a) * (float(b) if b else 1)
            i += 1
            break
        name_tokens.append(vals[i])
        i += 1
    catalog = None
    if len(name_tokens) > 1 and re.fullmatch(r"[A-Z0-9][A-Z0-9-]*\d[A-Z0-9-]*", name_tokens[0]):
        catalog = name_tokens.pop(0)
    # PO cell (may be "无" = none)
    if i < len(vals) and not vals[i].startswith("$"):
        if vals[i] not in EMPTY:
            order.po_number = vals[i]
        i += 1
    amounts = []
    while i < len(vals) and MONEY.fullmatch(vals[i]):
        amounts.append(_money(MONEY.fullmatch(vals[i]).group(1)))
        i += 1
    rest = vals[i:]

    unit_price = amounts[0] / qty if amounts and qty else None
    if name_tokens:
        order.items = [LineItem(product_name=" ".join(name_tokens), catalog_number=catalog,
                                quantity=qty, unit_price=unit_price)]
    if amounts:
        order.total = amounts[-1]
        # columns after the product price: S&H, dry ice, card fee ...
        extras = sum(amounts[1:-1])
        if extras:
            order.shipping = extras
    if rest and rest[0] not in EMPTY:
        order.sales_rep = rest[0]
    for t in rest:
        if t in CUSTOMER_STATUS:
            order.customer_status = CUSTOMER_STATUS[t]
            break
    notes = "\n".join(body.strip().splitlines()[1:]).strip()
    tail = first_line.split("N/A")[-1].strip() if "N/A" in first_line else ""
    order.notes = "\n".join(x for x in (tail, notes) if x) or None
    return order


def guess_customer(thread: EmailThread, internal_domains: list[str]) -> Customer:
    """First external person in the conversation: a sender, a recipient, or an
    address pasted into the body (staff often forward the customer's contact)."""
    for m in thread.messages:
        for addr in [m.sender, *m.to, *m.cc]:
            if addr and not is_internal(addr, internal_domains):
                return Customer(email=addr.lower())
    for m in thread.messages:
        lines = m.body.splitlines()
        for idx, line in enumerate(lines):
            for addr in EMAIL.findall(line):
                if is_internal(addr, internal_domains):
                    continue
                name = None
                before = line.split(addr)[0].strip(" <:")
                if before:
                    name = before
                elif idx > 0 and lines[idx - 1].strip() and not EMAIL.search(lines[idx - 1]):
                    name = lines[idx - 1].strip()
                return Customer(email=addr.lower(), contact_name=name)
    return Customer()


def extract(thread: EmailThread, code_pattern: str, internal_domains: list[str]) -> Order:
    order = None
    for m in thread.messages:
        order = parse_order_form(m.body, code_pattern)
        if order:
            break
    full = f"{thread.subject}\n{thread.text()}"
    codes = find_order_codes(full, code_pattern)
    if order is None:
        order = Order(is_sales_order=bool(codes) and "order" in thread.subject.lower())
        if thread.messages:
            try:
                order.order_date = datetime.fromisoformat(
                    thread.messages[0].date.replace("Z", "+00:00")).date().isoformat()
            except ValueError:
                pass
    if not order.order_code and codes:
        order.order_code = codes[0]
    if not order.po_number:
        mo = PO.search(full)
        if mo and not re.fullmatch(code_pattern, mo.group(1)):
            order.po_number = mo.group(1)
    order.customer = guess_customer(thread, internal_domains)
    return order
