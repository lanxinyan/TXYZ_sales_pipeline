# TXYZ Sales Pipeline: Gmail → Zoho CRM Sales Orders

Turns sales-order emails in Gmail (`xinyan.zhang@creative-biostructure.com`) into
**Sales Orders in Zoho CRM**. It creates the Account, Contact and Products if they don't exist yet.
A person approves each order before it is written to Zoho.

```
 Gmail ──scan──▶ extract ──▶ validate ──▶ review queue ──approve──▶ push ──▶ Zoho CRM
 (search query)  rules +     arithmetic,   (SQLite +                 Account / Contact /
                 Claude      missing data  Gmail labels)             Products / Sales_Order
                 (reads PDF                                          + quote PDF attached
                  quotes/POs)
```

## What it understands

| Email type | Example | How it's read |
|---|---|---|
| Internal order form | subject `Order_CBSRX09242501B-2`, body = pasted spreadsheet row (年月日 报价号 … 产品名称 Qty PO 产品报价 …) | Rule-based parser takes the date, quote number, service/product type, product name, qty, price, total, sales rep and new/existing customer status |
| Customer PO / acceptance | "We are generating the PO … under quote number CBSXY07202601" | Quote number and PO number found by pattern; customer = first outside address |
| Attached formal quotation / PO PDF | `Quotation_Creative Biostructure_<code>.pdf` | Claude reads the PDF for the customer company, address, line items and prices |
| Noise | vendor invoices, marketing, our own purchases | Claude marks `is_sales_order=false` → labelled *Zoho/Not an order* |

Claude's reading is cross-checked against the rule-based parse. If the order number or total
disagree, or a line-item sum doesn't match the total, the order goes to **Needs review**.
It is never pushed silently.

## Setup (one time)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env        # then fill it in
```

1. **Gmail**: In Google Cloud Console, enable the Gmail API and create an *OAuth client ID → Desktop app*.
   Save it as `credentials.json`, then run `sales-pipeline gmail-auth` and sign in as
   xinyan.zhang@creative-biostructure.com. The scope is `gmail.modify` (read, label, drafts). Mail is
   sent only when you press **Send now** on a draft in the dashboard.
2. **Claude**: Put your key in `ANTHROPIC_API_KEY`. Set `USE_LLM=false` to run on the rule-based parser alone.
3. **Zoho CRM**: At <https://api-console.zoho.com>, create a *Self Client* and generate a code with scope
   `ZohoCRM.modules.ALL,ZohoCRM.settings.READ`. Put the client id and secret in `.env`, then run
   `sales-pipeline zoho-auth <code>` and paste the printed `ZOHO_REFRESH_TOKEN` into `.env`.
   If your Zoho account isn't on the US data center (`crm.zoho.com`), change `ZOHO_ACCOUNTS_URL` and `ZOHO_API_DOMAIN`.

## Daily use: the dashboard

```bash
sales-pipeline ui --demo     # try it first with fictional data (nothing leaves your computer)
sales-pipeline ui            # live: http://127.0.0.1:8765
```

One list, sorted by priority. Each item has a ready-made plan:

| Section | What happens when you press **Approve plan** (`A`) |
|---|---|
| **Runs automatically** | Zoho Sales Order (or Account + Contact for a quote request), Gmail label. Untick anything you don't want. |
| **Customer-facing: waits for your Send** | Order confirmation / quote acknowledgement / optional invoice request to accounting. These are saved as **Gmail drafts** and move to *Waiting to send*. Nothing goes out until you press **Send now** (you can still edit the text first) or **Discard**. |

Priority (High / Medium / Low) adds up: order value, how long the customer has been waiting on
a reply, new customer, prepayment, and anything the checks flagged. Edit any field (company, PO,
total, items) right in the page before approving; the plan and draft text update to match.
Keys: `J`/`K` move, `A` approve, `S` skip. **Scan Gmail** pulls in new threads.

Tabs: **To decide** → **Waiting to send** → **Done** (and **Skipped**). A failed step stays in
*To decide* with the error shown; approving again retries only what failed.

The page only listens on your own computer (127.0.0.1).

## Command line (same actions, no browser)

```bash
sales-pipeline scan                      # read new/updated order threads
sales-pipeline list                      # what was found; "!" lines say what needs fixing
sales-pipeline show CBSRX09242501B-2     # full extracted order (by order code or thread id)

# fix anything wrong:
sales-pipeline show CBSRX09242501B-2 --json > fix.json   # edit fix.json
sales-pipeline edit CBSRX09242501B-2 fix.json
sales-pipeline approve CBSRX09242501B-2  # or: skip <id>

sales-pipeline push CBSRX09242501B-2 --dry-run   # preview the Zoho record
sales-pipeline push CBSRX09242501B-2             # create it
sales-pipeline push --ready                      # push every approved order
```

`sales-pipeline run` = scan, then push everything in *ready* if `AUTO_PUSH=true`.
You can schedule it with cron, e.g. every 30 min: `*/30 * * * * cd /path && .venv/bin/sales-pipeline run`.

Statuses: `needs_review` → (edit/approve) → `ready` → `pushed`, or `failed` (the Zoho error is shown in `list`) or `skipped`.
Gmail labels mirror these: **Zoho/Needs review**, **Zoho/Synced**, **Zoho/Not an order**.

## Safety

- Pushing is idempotent. Before creating anything it searches Zoho for a Sales Order whose **Subject** is
  the order code, and links to the existing one if found.
- A thread is re-read only when new replies arrive (`scan --rescan` forces it).
- Secrets (`.env`, `credentials.json`, `token.json`) and the local database are git-ignored.

## Zoho field mapping

| Zoho Sales_Orders field | From |
|---|---|
| Subject | order / quote number (e.g. `CBSRX09242501B-2`) |
| Account_Name | customer company (found or created) |
| Contact_Name | customer email (found or created) |
| Ordered_Items | line items: Product_Name (found by Product_Code, then name, or created), Quantity, List_Price, Discount |
| Purchase_Order | customer PO number |
| Adjustment / Discount | shipping + dry ice + fees / order discount |
| Billing_Street / Shipping_Street | addresses from the quote/PO |
| Status | `ZOHO_SO_STATUS` (default `Created`) |
| Description | notes (Chinese translated), payment terms, sales rep, link to the Gmail thread |

To fill custom fields (e.g. sales rep picklist, prepayment flag), extend `sales_order_payload()` in
`src/sales_pipeline/pipeline.py`.

## Code map

| File | Role |
|---|---|
| `gmail_source.py` | Gmail API: search, fetch threads + PDF attachments, labels |
| `extract_rules.py` | deterministic parser for the order-form email, order codes, PO numbers, customer email |
| `extract_llm.py` | Claude structured extraction over the thread + PDFs |
| `pipeline.py` | merge + validate, review states, Zoho payload, push |
| `zoho.py` | Zoho CRM v8 REST client (OAuth refresh, search, create, attach) |
| `store.py` | SQLite review queue |
| `tasks.py` | kind (order / quote request), priority, and the plan of routine vs. gated steps |
| `actions.py` | carries out a decision: routine steps, Gmail drafts, send / discard |
| `web.py`, `ui.html` | the dashboard (standard library web server, no extra installs) |
| `demo.py` | fictional inbox + in-memory Gmail/Zoho for `ui --demo` |
| `cli.py` | `sales-pipeline` command |

Run tests with `pytest`.
