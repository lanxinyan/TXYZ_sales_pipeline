# Teaching Claude Cowork the CRM

The Sales Desk app handles Gmail. Until our Zoho account has API access, the Zoho
side is done by **Claude Cowork** (the Claude desktop app), which uses Zoho through
your own browser login.

Step by step:

1. **Learn** — open Cowork, give it a folder to write into (e.g. `Documents\Sales Desk\cowork`),
   log in to Zoho in the browser, and paste the text from
   [`1 - Learn the Inquiry module.md`](1%20-%20Learn%20the%20Inquiry%20module.md).
   It reads 120+ Inquiry records **without changing anything** and writes `inquiry-rulebook.md`.
2. **Check** — read the rulebook, answer its open questions, and correct anything wrong right in
   the file. This file becomes the rulebook Cowork follows from then on.
3. **Use** — only after you approve the rulebook: a second prompt (to be written from the
   rulebook) lets Cowork create inquiries, add notes and set tags, and asks you before
   each change at first.

When the Zoho admin turns on API access, the same rulebook goes into the Sales Desk
so these updates show up in its to-do list as well.
