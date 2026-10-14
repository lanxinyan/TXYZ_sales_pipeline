# TXYZ Sales Pipeline: Sales Desk for Gmail + Zoho CRM

One prioritized to-do list for the sales mailbox (`xinyan.zhang@creative-biostructure.com`).
It covers new inquiries, follow-ups on quotes, and new orders. Each item comes with a ready-made
plan. You approve it and the emails become **Gmail drafts**: you open Gmail, read each one over and
press Send yourself. Sales Desk never sends. What should change in **Zoho CRM** (notes, tags, new
Inquiry records) goes into a **Gmail feed for Cowork**, which updates Zoho by the CRM rulebook.

```
 Gmail ──scan──▶ read the thread ──▶ what's due? ──▶ To-do list ──approve──▶ re-check ──▶ Gmail draft ──▶ you press Send
 (inquiries,     (who wrote last,     (reply today,   (priority +                                           │
  quotes,         colleagues,          follow-up n,    plan)                       next scan notices it ◀───┘
  orders, sent)   order forms, PDFs)   close, order)                                        │
                                                              Feed for Cowork ◀─────────────┘──▶ Cowork updates Zoho
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
| Still no answer | **Close**: tag **No reply** | 14 days later |
| Customer says they're going elsewhere ("more expensive… our core facility") | **Thank-you reply + tag 不买了**, no more follow-ups | right away |
| "Great, thanks!" | nothing to do | |
| Went quiet 30 days – 3 months ago (quote or not; nobody kept following up, or all follow-ups went unanswered) | **Revisit**: *it's been a while… please let us know* (asks to update the quote, or for details to prepare one) | in the **Revisit** tab |
| Still no answer after the check-in | **Last follow-up** (the final one), then **No reply** | a week later, then 14 days |
| Quiet for more than 3 months | left alone | |

When a colleague asks you by name in an internal email to quote or answer ("张博士报吧", "Tony, can you
quote this?"), the item moves up and shows their request (names in `MY_NAMES`). Website-form inquiries of the
last 3 months are always looked at, also ones nobody has answered yet.

A customer who wrote to you and got an answer counts as a sales conversation even without a quote or an
inquiry form (a vendor who sends you a quote doesn't). The natural 4th follow-up (a month after the 3rd)
keeps its own wording; the check-in is for conversations that simply went quiet.

Each follow-up is firmer than the one before. Each is a reply in the same thread, with your previous
email quoted underneath. Follow-ups that aren't due yet wait in **Upcoming** and move to **To decide**
on their day.

**Emails to customers go to customers only.** No colleague and no internal mailbox (Emma Flores /
usa@, Yani, inquiry@ …) is put in To or Cc, or named in the text, and nothing in Chinese is included:
the accounting note and colleagues' comments stay internal. A reply to a forwarded inquiry stays in
the same Gmail thread (so the conversation stays together), but only the customer receives it. If you
edit a draft in Sales Desk so that it breaks these rules, it isn't made. Add colleagues yourself in
Gmail if you ever need to.

**Checking what colleagues did.** Before a plan is shown, and again right before a draft is made:

- If the customer wrote, or a colleague (Yani, Charles…) already replied or followed up, nothing is drafted
  and you see what happened. You choose **Draft anyway** or leave it. While a draft waits in Gmail, the
  same check runs on every scan and warns you on the item.
- If someone already sent the order to accounting (e.g. "麻烦收预付"), or accounting already sent the
  invoice, the invoice request is left unticked and the evidence is shown. The same applies if someone
  asked to wait (e.g. "先稍等发预付invoice").
- If a colleague already created the inquiry in Zoho ("Inquiry-0012345 crm created"), it isn't created
  again. Your notes go on their record.
- If the customer is already tagged 已下单 / 不买了 in Zoho, no follow-ups are suggested. If they write
  back anyway, you still see it.
- A conversation belongs to whoever answers the customer. If a colleague answered and you haven't written to
  that customer, it's left to them, even when the inquiry was forwarded to both of you.

**Zoho CRM, through Cowork.** Sales Desk doesn't write to Zoho itself for now (no API access yet, and the
rulebook says only Tony's CBSXY/CBSRX inquiries, each change confirmed). Instead, **Feed for Cowork**
writes a file that Cowork reads and applies, asking you before each change:

- **Note entries in the rulebook's format**, one running note per inquiry: `100626q: CBSXY10052611`
  (quote sent), `100726f: follow-up 1` (we followed up, yours or a colleague's), `100926r: wants discount`
  (the customer replied), `101226: PO received`, `100726: teleconference`, `NDA signed`, `samples received`.
  Each comes with a short excerpt, so Cowork can choose better words.
- **Inquiry numbers** found in Gmail ("Inquiry-0031002 crm created"); conversations without one get
  suggestions for a new record (Inquiry Level/Customer Type: D for free-mail, A for .gov, B for academia;
  Key Customer YES only after an order over $20,000; Team from the quote number).
- **Tags**: `No reply` after 4 unanswered follow-ups, `已下单` for orders, how each quote was sent (PDF / formal
  / in the email body) so you can pick Draft Quote / PDF Quote / formal quote, and the outcome buttons you
  pressed (**已下单**, **不买了**, **No reply**).
- **Only your conversations**: ones where you wrote to the customer, new inquiries sent to you, and orders
  sent to you. Threads you're only copied on are left out, and so is anything whose quote/order number
  belongs to another team (CBSMA …).
- Each feed only has what's new since the last one (`sales-pipeline crm-feed --all` repeats everything).

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

This step is only needed later, once Sales Desk is allowed to write to Zoho itself. Until then, skip it:
Zoho is updated by Cowork from the feed (step 6). Your account is on Zoho's US data center
(crm.zoho.com), which is what Sales Desk uses by default.

If it says your user isn't allowed to use the Zoho CRM API (`NO_PERMISSION`, `Crm_Implied_Api_Access`), a Zoho
administrator has to switch on API access for your profile: **Setup → Users and Control → Security Control →
Profiles →** your profile **→ Zoho CRM API**. You don't need to reconnect afterwards; just run
`sales-pipeline zoho-setup --write` again.

**5. Start it (every day)**: double-click **`Start Sales Desk`**. Your browser opens at
<http://127.0.0.1:8765>. Keep the black window open while you work; closing it stops Sales Desk. It reads
Gmail when it starts and every 15 minutes after that. Anything missing? Run `sales-pipeline check`, or just
re-run `1 Setup`, which ends with the same checklist.

**6. Point the feed at Cowork (once)**: open `.env` in Notepad and set `CRM_FEED_DIR` to the folder Cowork
works in, for example
`CRM_FEED_DIR=C:\Users\you\OneDrive\Jobapplication2024\creativebio\试用\CRMsystem_updates\Cowork`.
Then **Feed for Cowork** (top right of the page) writes `gmail-feed-<date>.md` there. In Cowork, say
*"Apply the newest Gmail feed in this folder"*.

**The first run**
- The first scan reads 60 days of sent mail and 30 days of inquiries and orders. It can take a minute or two,
  and items appear as they're found.
- Expect a backlog. Quotes that went quiet come up with the follow-up that fits the time that has passed (up to
  the final one), not a gentle "did you receive it?" weeks later. Work through them, snooze them, or mark them
  不买了. To start smaller, set `FOLLOWUP_QUERY=in:sent newer_than:14d` in `.env`.
- The first feed for Cowork covers the last 30 days (`sales-pipeline crm-feed --days 60` for more).

**Optional settings** (`.env`): `REVISIT_AFTER_DAYS` / `REVISIT_UNTIL_DAYS` (default 30 / 90),
`REVISIT_FOLLOWUP_DAYS` (7), `SCAN_LIMIT` (threads per search, default 300), `SENDER_NAME`, `SENDER_PHONE` (default 1-631-559-9269, from the order template),
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

Start it with **`Start Sales Desk`** (or `sales-pipeline ui`, at http://127.0.0.1:8765). The demo (`sales-pipeline ui --demo`) runs at http://127.0.0.1:8799 and shows a yellow DEMO DATA badge.

- **To decide**: what needs you today, sorted by priority. Each item shows the conversation (customer /
  you / colleague / accounting / CRM), what colleagues already did, and the plan.
  - **Approve & make Gmail drafts** (`A`): Gmail is checked for colleague activity, the routine steps run,
    and the emails go to your Gmail drafts. Then open Gmail, read them over, and press **Send** there.
  - Outcome buttons: **已下单**, **不买了**, **No reply**, snooze **1 day / 3 days / 1 week**, **Not a customer**
    (vendors, never suggested again).
  - Edit any email before approving. Follow-ups have a *Wording* picker for the alternatives. After that,
    edit in Gmail.
- **Upcoming**: scheduled follow-ups with their dates. You can make one's draft early.
- **Revisit**: customers who went quiet 30 days to 3 months ago, quote-sent ones first. Work through them at
  your pace: the check-in becomes a Gmail draft like any other email.
- What you decide (an outcome button, Skip, a snooze) stays decided until the customer or a colleague writes
  in that thread again.
- **In Gmail drafts**: drafts waiting for you to send. **Open in Gmail** opens it; **I sent it: check Gmail**
  picks it up right away (otherwise the next scan does). Sending it schedules the next follow-up. If you
  delete the draft in Gmail, the item comes back to *To decide*.
- **Feed for Cowork** (top right): writes the file for Cowork (see *Zoho CRM, through Cowork*).
- **Activity**: everything Sales Desk did on its own (drafts made, emails you sent, feeds written, snoozes).

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
sales-pipeline crm-feed                  # write the Gmail feed for Cowork into CRM_FEED_DIR
sales-pipeline list                      # what was found; "!" lines say what needs fixing
sales-pipeline show CBSRX09242501B-2     # full extracted order (by order code or thread id)
sales-pipeline show CBSRX09242501B-2 --json > fix.json && sales-pipeline edit CBSRX09242501B-2 fix.json
sales-pipeline push CBSRX09242501B-2 --dry-run   # preview the Zoho record
sales-pipeline push CBSRX09242501B-2             # create it
```

## Safety

- Sales Desk never sends email. It makes Gmail drafts; you press Send in Gmail after a final read.
- Emails to customers go to customers only, with no colleague or internal mailbox in To/Cc or in the
  text, and no Chinese. Internal emails (the accounting request) go to internal addresses only.
- Every draft re-reads the thread first (and Zoho, when connected).
- A reply that still says `[write your reply here]` can't be drafted.
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
| `actions.py` | approve (re-check, then Gmail drafts) / pick up what you sent from Gmail / snooze / outcomes |
| `safety.py` | customer emails: customers only, no internal addresses, no Chinese |
| `feed.py` | the Gmail feed for Cowork (note entries, tags, inquiry numbers, new-record suggestions) |
| `crm.py` | the customer's Zoho record when writing directly (`ZOHO_DIRECT_UPDATES`, off for now) |
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
