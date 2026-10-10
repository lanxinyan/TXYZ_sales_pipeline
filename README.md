# TXYZ Sales Pipeline: Sales Desk for Gmail + Zoho CRM

One prioritized to-do list for the sales mailbox (`xinyan.zhang@creative-biostructure.com`).
It covers new inquiries, follow-ups on quotes, and new orders. Each item comes with a ready-made
plan. You approve it, and the routine work happens in **Zoho CRM**: records, tags, follow-up
notes and Sales Orders. Anything a customer or accounting will read is sent only with your OK, and only
after re-checking that a colleague hasn't already done it.

```
 Gmail ──scan──▶ read the thread ──▶ what's due? ──▶ To-do list ──approve──▶ Zoho: records, tags, notes, Sales Order
 (inquiries,     (who wrote last,     (reply today,   (priority +            Gmail: drafts → re-check → send
  quotes,         colleagues,          follow-up n,    plan)                        → recorded as a follow-up in Zoho
  orders, sent)   order forms, PDFs)   close, order)
```

## The rules it follows

**Answering and following up.** The follow-up count includes emails from anyone on your side,
so Yani's follow-ups count too.

| Situation | Becomes | When |
|---|---|---|
| A customer's first email (direct, inquiry@ forward, website form) | **First reply** (High) | due the same day |
| Customer wrote back | **Reply needed** | within a day |
| No answer after your reply | **Follow-up 1**: *did you receive our email?* | next day |
| Still no answer | **Follow-up 2**: *had a chance to review?* | 2 days later |
| Still no answer | **Follow-up 3**: *has a decision been made on the quote?* (or *still interested?* if no quote went out) | a week later |
| Still no answer | **Follow-up 4**: *if you went with another vendor, a courtesy reply please* | a month later |
| Still no answer | **Close**: tag 不买了 | 14 days later |
| Customer says they're going elsewhere ("more expensive… our core facility") | **Thank-you reply + tag 不买了**, no more follow-ups | right away |
| "Great, thanks!" | nothing to do | |

Each follow-up is firmer than the one before. Each is sent as a reply in the same thread, with your
previous email quoted underneath and the same colleagues copied. Follow-ups that aren't due yet wait in
**Upcoming** and move to **To decide** on their day.

**Checking what colleagues did.** Before a plan is shown, and again right before anything is sent:

- If the customer wrote, or a colleague (Yani, Charles…) already replied or followed up, the send stops and
  you see what happened. You choose **Send anyway** or keep it as a draft.
- If someone already sent the order to accounting (e.g. "麻烦收预付"), or accounting already sent the
  invoice, the invoice request is left unticked and the evidence is shown. The same applies if someone
  asked to wait (e.g. "先稍等发预付invoice").
- If a colleague already created the inquiry in Zoho ("Inquiry-0012345 crm created"), it isn't created
  again. Your notes go on their record.
- If the customer is already tagged 已下单 / 不买了 in Zoho, no follow-ups are suggested. If they write
  back anyway, you still see it.
- Threads where you're only copied and a colleague is handling the customer are left to them.

**Zoho CRM.**

- **Every email to a customer is recorded as a follow-up note** on their record (title like
  "Follow-up #2 (email) 2026-10-10", with the text and a link to the thread). Replies you send straight
  from Gmail are recorded on the next scan, once only.
- **Lifecycle tags.** A customer carries one stage tag at a time. When 已下单 goes on, 不买了 / 跟进中 / … come
  off. Buttons on every item: **已下单**, **不买了**.
- **Orders.** A Sales Order is created with Account / Contact / Products and the quote PDF attached. The
  customer is tagged 已下单, and follow-ups on their quote thread stop.

## Setup (one time)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env        # then fill it in
```

1. **Gmail**: In Google Cloud Console, enable the Gmail API and create an *OAuth client ID → Desktop app*.
   Save it as `credentials.json`, run `sales-pipeline gmail-auth`, and sign in. The access covers reading,
   labels and drafts. Mail is sent only when you approve it in the dashboard.
2. **Zoho CRM**: At <https://api-console.zoho.com>, create a *Self Client* and generate a code with scope
   `ZohoCRM.modules.ALL,ZohoCRM.settings.READ`. Put the client id and secret in `.env`, run
   `sales-pipeline zoho-auth <code>`, and paste the printed `ZOHO_REFRESH_TOKEN` into `.env`.
   If your account isn't on the US data center, change `ZOHO_ACCOUNTS_URL` / `ZOHO_API_DOMAIN`.
3. **Your tags**: `sales-pipeline zoho-setup` lists the tags already in your Zoho and the module that holds
   inquiries. It shows which tag it will use for each stage (已下单 = ordered, 不买了 = not buying, 跟进中,
   已报价, 询价 … if they exist). `sales-pipeline zoho-setup --write` saves the map to `zoho_tags.json`;
   edit that file to change it. Until then only 已下单 and 不买了 are used, and no new tags are invented.
4. **You**: `SENDER_NAME`, `SENDER_PHONE` and `EMAIL_SIGNATURE` in `.env` go into every email.
5. **Claude** (optional): `ANTHROPIC_API_KEY` lets Claude read order emails and their PDF quotes/POs.
   Without it (`USE_LLM=false`), order forms are read by the built-in parser, and follow-ups work the same.

## Daily use: the dashboard

```bash
sales-pipeline ui --demo     # try it first with made-up data (nothing leaves your computer)
sales-pipeline ui            # live: http://127.0.0.1:8765, re-reads Gmail every 15 minutes
```

- **To decide**: what needs you today, sorted by priority. Each item shows the conversation (customer /
  you / colleague / accounting / CRM), what colleagues already did, and the plan.
  - **Approve & send** (`E`): routine steps run, the emails are re-checked and sent, then recorded in Zoho.
  - **Approve, keep drafts** (`A`): the same, but the emails wait in *Waiting to send* (also in Gmail Drafts).
  - Outcome buttons: **已下单**, **不买了**, snooze **1 day / 3 days / 1 week**, **Not a customer** (vendors,
    never suggested again).
  - Edit any email before sending. Follow-ups have a *Wording* picker for the alternatives.
- **Upcoming**: scheduled follow-ups with their dates. You can send one early.
- **Waiting to send**: drafts you approved. **Send now** re-checks first.
- **Activity**: everything Sales Desk did on its own (Zoho notes, tags, recorded Gmail replies, snoozes).

`sales-pipeline followups` prints the same due/upcoming list in the terminal.

## Changing the wording

The emails come from `src/sales_pipeline/templates.txt`: first reply, follow-ups 1–4 (with alternatives),
the thank-you on a decline, order confirmation, and the accounting request. Copy it, edit it, and point
`TEMPLATES_FILE` at your copy. Placeholders such as `{greeting}`, `{sender_name}` and `{sender_phone}` are
explained at the top of the file. `{greeting}` reuses the way you or a colleague last greeted the
customer ("Dear Dr. Okafor,").

## Command line (orders, without the browser)

```bash
sales-pipeline scan                      # read new/updated threads
sales-pipeline list                      # what was found; "!" lines say what needs fixing
sales-pipeline show CBSRX09242501B-2     # full extracted order (by order code or thread id)
sales-pipeline show CBSRX09242501B-2 --json > fix.json && sales-pipeline edit CBSRX09242501B-2 fix.json
sales-pipeline push CBSRX09242501B-2 --dry-run   # preview the Zoho record
sales-pipeline push CBSRX09242501B-2             # create it
```

## Safety

- Nothing reaches a customer or accounting without your approval. Every send re-reads the thread and Zoho
  first.
- A reply that still says `[write your reply here]` can't be sent.
- Sales Orders are created once: an existing one with the same order number is linked, not duplicated.
- Customer records are found by email across `ZOHO_CUSTOMER_MODULES` (e.g. Leads, then Contacts) before one is
  created.
- The page only listens on your own computer (127.0.0.1). Secrets (`.env`, `credentials.json`,
  `token.json`) and the local database are git-ignored.

## Zoho field mapping (Sales Orders)

| Zoho Sales_Orders field | From |
|---|---|
| Subject | order / quote number (e.g. `CBSRX09242501B-2`) |
| Account_Name / Contact_Name | customer company / email (found or created) |
| Ordered_Items | line items: Product_Name (found by Product_Code, then name, or created), Quantity, List_Price, Discount |
| Purchase_Order | customer PO number |
| Adjustment / Discount | shipping + dry ice + fees / order discount |
| Billing_Street / Shipping_Street | addresses from the quote/PO |
| Status | `ZOHO_SO_STATUS` (default `Created`) |
| Description | notes (Chinese translated), payment terms, sales rep, link to the Gmail thread |

To fill custom fields, extend `sales_order_payload()` in `src/sales_pipeline/pipeline.py`.

## Code map

| File | Role |
|---|---|
| `conversation.py` | reads a thread: who wrote last, follow-up count, due date, colleague activity, decline / order signals, invoice status |
| `tasks.py` | kind, priority, and the plan (routine vs. emails needing your OK) |
| `templates.py`, `templates.txt` | email wording and rendering |
| `actions.py` | approve / send (with re-checks) / snooze / outcomes; records every email in Zoho |
| `crm.py` | the customer's Zoho record: find across modules, lifecycle tags, follow-up notes |
| `pipeline.py` | scanning, scheduling, order extraction + validation, Sales Order push |
| `gmail_source.py` | Gmail API: threads (drafts excluded), attachments, labels, reply drafts |
| `zoho.py` | Zoho CRM v8 REST client (records, search, tags, notes, attachments) |
| `extract_rules.py`, `extract_llm.py` | reading order forms (rules) and quotes/POs (Claude) |
| `store.py` | local SQLite: items, activity log, ignored domains, what's been logged |
| `web.py`, `ui.html` | the dashboard (standard-library web server) |
| `demo.py` | made-up inbox + in-memory Gmail/Zoho for `ui --demo` |
| `cli.py` | `sales-pipeline` command |

Run tests with `pytest`.
