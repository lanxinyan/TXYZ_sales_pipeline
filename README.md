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
- A conversation belongs to whoever answers the customer. If a colleague answered and you haven't written to
  that customer, it's left to them, even when the inquiry was forwarded to both of you.

**Zoho CRM.**

- **Every email to a customer is recorded as a follow-up note** on their record (title like
  "Follow-up #2 (email) 2026-10-10", with the text and a link to the thread). Replies you send straight
  from Gmail are recorded on the next scan, once only.
- **Lifecycle tags.** A customer carries one stage tag at a time. When 已下单 goes on, 不买了 / 跟进中 / … come
  off. Buttons on every item: **已下单**, **不买了**.
- **Orders.** A Sales Order is created with Account / Contact / Products and the quote PDF attached. The
  customer is tagged 已下单, and follow-ups on their quote thread stop.

## Getting started

Everything runs on your own computer. You need about 20 minutes once; after that it's one double-click a day.
The files to double-click are in the `launchers` folder (Windows `.bat`, Mac `.command`).

**1. Install Python and the app (once)**
1. Install **Python 3.10 or newer** from <https://www.python.org/downloads/>. On Windows, tick
   **"Add python.exe to PATH"** in the installer.
2. Get this project: on GitHub, green **Code** button → **Download ZIP**, then unzip it somewhere permanent
   (e.g. Documents/SalesDesk).
3. Double-click **`1 Setup`** (`Windows - 1 Setup.bat` or `Mac - 1 Setup.command`). It installs everything
   into the folder and ends with a checklist of what's still to do.
   - Windows may say "Windows protected your PC": click *More info* → *Run anyway*.
   - Mac may say it can't verify the developer: Control-click the file → *Open* → *Open*.

**2. Look around with made-up data (optional)**: double-click **`2 Try demo`**. Your browser opens Sales Desk
with fictional customers; nothing touches Gmail or Zoho. Close the black window to stop.

**3. Connect Gmail (once, ~10 minutes)**, signed in to Google as xinyan.zhang@creative-biostructure.com:
1. Open <https://console.cloud.google.com>, pick **New project** in the project menu at the top, and name it
   *Sales Desk*.
2. Search for **Gmail API** in the top search bar, then click **Enable**.
3. Search for **OAuth consent screen** (also called *Google Auth Platform*). Give the app the name *Sales Desk*,
   enter your email, and choose **Internal** as the audience (only your company). Then **Create**.
   If *Internal* isn't offered, choose *External* and add your own address under *Test users*.
4. Go to **Clients** (or *Credentials → Create credentials → OAuth client ID*). Choose application type
   **Desktop app**, click **Create**, then **Download JSON**.
5. Rename the downloaded file to **`credentials.json`** and put it in the Sales Desk folder, next to `README.md`.

The first time you start Sales Desk (step 5), your browser asks you to sign in to Google and allow access.
If your company's Google admin blocks this, ask them to allow internal apps to use the Gmail API.

**4. Connect Zoho CRM (once, ~5 minutes)**
1. Open <https://api-console.zoho.com>, signed in with your Zoho CRM account. Choose **Add Client** →
   **Self Client** → **Create**.
2. Double-click **`3 Connect Zoho`**. Paste the **Client ID** and **Client Secret** it asks for; they're on
   the Self Client's *Client Secret* tab.
3. On the Self Client's **Generate Code** tab, fill in the scope `ZohoCRM.modules.ALL,ZohoCRM.settings.READ`,
   a duration of 10 minutes and a description of *Sales Desk*. Click **Create**, copy the code, and paste it into
   the window. Codes expire, so do this within the 10 minutes.
4. It saves everything to `.env`, then lists your Zoho modules and tags (see *Where customers live in Zoho*).
   Check that it picked the module holding your inquiries.

Your account is on Zoho's US data center (crm.zoho.com), which is what Sales Desk uses by default.

**5. Start it (every day)**: double-click **`Start Sales Desk`**. Your browser opens at
<http://127.0.0.1:8765>. Keep the black window open while you work; closing it stops Sales Desk. It reads
Gmail when it starts and every 15 minutes after that. Anything missing? Run `sales-pipeline check`, or just
re-run `1 Setup`, which ends with the same checklist.

**The first run**
- The first scan reads 60 days of sent mail and 30 days of inquiries and orders. It can take a minute or two,
  and items appear as they're found.
- Expect a backlog. Quotes that went quiet come up with the follow-up that fits the time that has passed (up to
  the final one), not a gentle "did you receive it?" weeks later. Work through them, snooze them, or mark them
  不买了. To start smaller, set `FOLLOWUP_QUERY=in:sent newer_than:14d` in `.env`.
- Only replies you send from now on are recorded in Zoho; past ones aren't back-filled.

**Optional settings** (`.env`): `SENDER_NAME`, `SENDER_PHONE` (default 1-631-559-9269, from the order template),
`EMAIL_SIGNATURE`. Add `ANTHROPIC_API_KEY` to let Claude read order emails and their PDF quotes/POs. Without
it, order forms are read by the built-in parser, and follow-ups work the same.

## Where customers live in Zoho

Zoho has built-in modules with fixed internal names (*API names*): `Leads`, `Contacts`, `Accounts`, `Deals`.
An account can rename them, hide them, or add its own modules. You won't find a tab called "Leads" if yours
was renamed or hidden. The records your colleagues create, named like `Inquiry-0012345`, live in a module
shown in Zoho as something like *Inquiries* / *询价*. That's either the renamed Leads module or a custom module.

Sales Desk works this out on its own:

1. It looks for the module labelled Inquiries / 询价, whatever its internal name.
2. Then it tries `Leads`, then `Contacts`, if your account has them.
3. In each module it finds the field that holds the email address.
4. New inquiries are created in the first module, filling only fields that module has. An auto-numbered name
   like `Inquiry-0012345` is left for Zoho to assign.

To see the names yourself:

- **Address bar**: open the module's tab in Zoho and look at the URL, `…/crm/org…/tab/<name>/…`. `tab/Leads`
  means it's the built-in Leads module; something like `tab/CustomModule3` means a custom module.
- **Zoho Setup** (gear icon) → Developer Hub (*Developer Space* in older versions) → APIs → **API Names** lists
  each module's displayed name next to its API name.
- **`sales-pipeline zoho-setup`** prints the same list and marks the modules it will use.

To override the choice, set `ZOHO_CUSTOMER_MODULES` in `.env` (comma-separated API names, searched in order).

## Daily use: the dashboard

Start it with **`Start Sales Desk`** (or `sales-pipeline ui`; `sales-pipeline ui --demo` for made-up data).

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
- Customer records are found by email across the customer modules (see below) before one is
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
| `cli.py` | `sales-pipeline` command (`check`, `ui`, `zoho-auth`, `zoho-setup`, ...) |
| `launchers/` | double-click setup / demo / connect-Zoho / start files for Windows and Mac |

Run tests with `pytest`.
