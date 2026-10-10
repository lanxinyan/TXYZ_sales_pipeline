# Cowork task 1 — learn how we use the Zoho CRM "Inquiry" module

Paste everything below the line into Claude Cowork (Claude desktop app). Log in to
Zoho CRM in the browser first. This task only **reads** records; it never edits.

---

You are helping Tony (Sr. Project Manager, Creative Biostructure, xinyan.zhang@creative-biostructure.com)
learn the house rules of our Zoho CRM before you are allowed to update it. Your job in this task is
**read-only research**: study real Inquiry records and write a rulebook. Do not click Save, Edit,
Delete, Add Tag, Add Note, Convert, Send Email, or anything else that changes a record. If a page
opens in edit mode by accident, press Cancel.

## Where to look

- Zoho CRM (crm.zoho.com) → left sidebar **CRM Teamspace** → module **Inquiry**.
- Use the view **All Inquiry** (also look at the views "BS系列询价", "service" and "CBSXY_RX" to see
  what separates them).
- Related modules worth a glance when an inquiry links to them: Contacts, Company, T Quotes, T Orders,
  Follow Ups, Requirements, Order Processes.

## What to study

Open at least **120 Inquiry records**: the newest 60, about 30 from 6–12 months ago, and at least
30 that ended with the tag 已下单 or Status "Ordered" (sort or filter by Tags/Status to find them).
Include records owned by Tony and by colleagues. For each record, look at the whole page:
the fields, the Tags, the **Notes** section, the Timeline/History (who changed what, and when),
and linked emails/quotes/orders.

Answer these questions with evidence (counts, and anonymised examples):

1. **Creating an inquiry.** Which fields are filled at creation? The red mandatory ones are
   Inquiry Method, Inquiry Level, Inquiry Type, Key Customer, New or Returned Customer,
   Customer Type, 客户类型 (and Services and Products of Interested / Cat NO when present).
   For each one: the list of values actually used, how often, and what in the customer's email
   decides the value (e.g. website form → which Inquiry Method; a university → which Customer Type).
   How are Teams (CBSXY / CBSRX), Layout and Owner chosen? Which optional fields are usually filled
   at creation and which are left empty?
2. **The Auto Number** (Inquiry-00xxxxx): how it appears in the Gmail thread afterwards
   (e.g. "Inquiry-00xxxxx crm created") and whether other numbers (Quote Number) are added later.
3. **Tags.** Every tag you find, with how many records carry it. For the frequent ones
   (待报价, 重要报价, formal quote, 跟进中, 待客户提供…, 待供货, 下单ing, 已下单, 不买了, 老客户 and
   any other common ones): what situation it means, at which point in the conversation it is
   added, which tags it replaces or is removed with, and which tags can sit together
   (e.g. 老客户 next to a stage tag). Write the usual order a record moves through.
4. **Notes.** Notes are a short running log of what happened since the inquiry, e.g.
   `091426f: interested` = follow-up on 09/14/26, customer is interested. Work out the exact format:
   date style, every letter code after the date (f = follow-up; find the others — quote, order,
   reply, call, sample…?), how the summary is worded (language, length, abbreviations), whether a
   new line/note is added each time or one note is extended, and what events always get a note.
   Collect 30+ real note lines (anonymised) as examples.
5. **Status and other fields that change later.** Which fields get updated as the deal moves
   (Status, Quote Number, Inquiry Level, amounts, dates, Owner…), what triggers each change, and
   which fields are **never** touched after creation.
6. **What not to do.** Patterns of fields that stay empty, tags that are only set by certain people,
   records that are left to their owner, anything that looks like a mistake people later corrected.
7. **Gaps.** Anything inconsistent between people or over time, and questions you need Tony to
   decide.

## Privacy

Customer names, emails, phone numbers and companies stay in the CRM. In everything you write,
replace them with placeholders like [Customer], [University], [Company]. Product names, catalog
numbers, tag names, field names and note wording may be kept.

## Output

Write one file, `inquiry-rulebook.md`, in the folder Tony gave you, with these sections:

1. Summary (10 lines: the rules that matter most)
2. Creating an inquiry — table: field | allowed values (with counts) | how to choose | example
3. Tags — table: tag | meaning | when to add | removed when | can coexist with | count
4. Stage flow — the usual sequence of tags/Status from first email to ordered or lost
5. Notes — format, letter codes, 30+ example lines, when a note is required
6. Fields updated later — field | trigger | example; and the list of fields never changed
7. Don'ts
8. Open questions for Tony

Then tell Tony, in a few lines, the most surprising things you found and list the open questions.
Do not change anything in the CRM.
