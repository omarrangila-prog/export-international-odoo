# Export International - how the interface looks and behaves

Read this first, then look at the sheets in `sheets/` (several screens per image), then open single files from `INDEX.md` for detail.

## What this is
An ERP for a steel-trading company in Pakistan, built on Odoo 20 (community), made by Odoovations. Staff enter contracts, delivery advices, daily orders, truck loadings, bank statements, cash vouchers and invoices; managers approve. Every screen is plain-language (no accounting jargon), money is shown to the roles that may see it and hidden from the others, and nothing important is posted or approved by one person alone (maker-checker). All data in the screenshots is **synthetic DEMO data** on a staging copy. Urdu is not yet translated (Odoo ships none).

## Who is signed in (the screenshots show different roles)
| Login | Role | What changes on screen |
|---|---|---|
| demo.ceo | Executive | everything, including money cards and the whole company's stuck work |
| demo.finance, demo.accountant | Finance / accountant | money cards, invoices, bank |
| demo.contractapprover | Contract desk | contracts, delivery advices, orders; no money figures |
| demo.bank, demo.cash | Data entry | bank lines / cash vouchers; no balances |
| demo.dispatch | Logistics | truck loadings; no money |
| demo.sysadmin | System administrator | system checks instead of business figures |

## Page anatomy (every screen)
1. **Floating top bar** (white, rounded, soft shadow; dark card in dark theme): app menu icon, brand, entries (Home, Customers & Suppliers, Money, Orders & Trucks, Bills & Invoices, Month-end, Approvals, Setup; extra ones fold into "+"). The entry you are in is a **filled blue pill**. Right side: messages (red count), activities, **Ask** (blue spark), company name, signed-in person.
2. **Title strip** (no band, no rule): a big bold title, the primary button (New), the search field as one rounded card with filter chips inside, a round pager, a segmented list/cards switch.
3. **Content** sits on a faint blue-grey page with a soft glow, in white cards with 20px radius and a soft blue-tinted shadow. One 24px gutter on both sides lines up with the top bar.
4. A page taller than the window scrolls inside itself with a thin visible scrollbar at the far right.

## Home ("Overview")
Big "Overview" title with a round refresh button; on the right two date pills ("13 Oct - 26 Oct" = the period you choose, "compared to 29 Sep - 12 Oct" = the same number of days just before). For the executive, finance manager and accountant the first screen is work: **five summary figures** (bank balance, customers owe us, bank money to match, waiting for your decision, material lifted; each one says what it is made of and opens its records) with **Needs attention** (each alert has its next-step button) beside **Your decisions** (or the team queue). On a phone the secondary sections fold into one-line bars. Then, top to bottom: the **contract-to-payment pipeline** (one column per step with the real count, bars with a smooth dashed area and an axis, the question box inside the card) beside **Customers owe us** (big number, how much is late, a one-bar picture and a row per age band); **Money and material** (Invoiced as an area chart, Received in the bank and Material lifted as bars; each with a change chip such as +44% or "New", "Before: ...", hover tooltip, "Show as table"); **Bank balances** and **Who owes us most**; **Recent invoices**; **Needs attention**; **At a glance** figures; **My work / What is stuck** (priority, age, assign / put aside / escalate); material on contracts; recent activity; **Start something** (grouped shortcuts). A card the role may not see is simply absent. A percentage is shown only when there is something to compare.

## Lists, cards, records, dialogs
* **Lists:** one white rounded card; calm sentence-case column titles; airy rows; hover grey; status as pills (always with words, never colour alone).
* **Cards:** rounded with a soft shadow, a coloured edge for the state, rise slightly on hover.
* **Records:** a white rounded sheet; the steps of the record as a row of pills with the current one filled; a coloured "what to do now" banner (blue = your turn, orange = waiting, green = done, red = stopped); fields are **visible boxes** (1px edge, 12px radius) with a blue halo on focus; tabs are pills; the conversation (messages, notes, activities) is its own rounded card on the right.
* **Dialogs:** 22px radius, bold title, fields as boxes, primary button then Cancel on the left.
* **Special screens:** Ask (a chat that answers only from the books, each answer with sources and "how it was worked out", read-only), Match bank payments (three columns: the line, the decision, the evidence and effect), Party 360 (one page per customer/supplier with every figure explained).

## The app on every device (`ei_app_shell`)
* **Install it.** In Chrome, Edge, Safari or on Android, "Install app" / "Add to Home Screen" puts **Export International** on the phone or desktop with its own icon and colours, opening without the browser bar. (Checked: Chromium reports no installability or manifest errors. It needs the site to be served over https on a real server.) Without a network it shows an "Offline" page; nothing can be entered offline.
* **Phone (under 768 px):** a bottom bar with Home and the three sections you use most, and **More** for the rest; a section opens a sheet of its screens with large rows. The Home figures become a swipe strip so the first alert and its next-step button are on the first screen. The bar leaves room for the notch and the home bar, hides while the keyboard is open, and every button is at least 44 px.
* **Laptop and tablet:** **workspace tabs** under the top bar, like a browser. Each place you work in (a menu screen) is a tab; moving around inside it (list, record, next record) stays in its tab; the pages you leave stay open and come back where you left them (that screen or record, not the filters you typed) and are remembered in this browser. "+" opens a new tab, the x or a middle click closes one, the arrow keys move between them, at most eight. On a phone the open pages are listed under **More**.
* **Undo and redo** on a record: arrows beside the save controls, and Ctrl+Z / Ctrl+Y (Ctrl+Shift+Z) when the cursor is not inside a text box (inside one the browser undoes the typing). It undoes edits to the record's own fields (text, numbers, dates, choices, links to another record), one step at a time. An undo is an ordinary edit: it needs the same right to write, a locked or approved record refuses it, and the record's history shows both. It does **not** add or remove lines (Discard does that) and it does **not** reverse a business action (approve, post, pay): those have their own reversal with a reason and a second person.

## Sign-in
A white card on the same soft page: brand line, a STAGING pill when this is not the live system, then a switch **Password | PIN**. Password: user name + password, as before. PIN: user name + four digits (masked, number pad on a phone). A refusal always reads the same, so it never says which part was wrong. A PIN is set by the person from their name menu (**Sign-in PIN**), after typing the password. Details and limits: `docs/pin_login.md`.

## Reports
Top-bar entry **Reports** opens a catalog: every report asked for, what it answers, how it is worked out, where the numbers come from, and whether it is Delivered, Partly there, Blocked or Not built (with the reason). Six are real: aged receivables, bank book against bank confirmation, bank lines not yet in the books, customer invoices and collections, contracts with expected gross spread (provisional), material lifting. Each opens as a chart, a pivot and a list (the list is the "view rows" table), has filters and favourites, opens the document behind a row, and can export a spreadsheet (only for management, the auditor and the finance approvers). Their totals are tested equal to the Home figures.

## Design tokens
Font Inter. Light: page `#F4F6FA`, card `#FFFFFF`, ink `#0F1B33`, text `#1E293B`, muted `#566275`, primary blue `#1D4ED8`, chart blue `#2A78D6`, orange `#EB6834`, aqua `#1BAF7A`; status ok `#13692F`, warning `#9A4D06`, bad `#B91C1C` on soft tints. Dark: page `#0E1626`, card `#162033`, primary `#7AA2FF`. Radii 20 (cards), 14-16 (menus, search), 12 (buttons, fields), pill (chips, steps). Shadow `0 1px 2px rgba(15,27,51,.04), 0 12px 32px rgba(29,78,216,.07)`. Motion is small (8px rise, 3px hover lift) and off under "reduce motion".

## Things deliberately not done yet
Profit and loss, balance sheet, trial balance and cash-flow reports (blocked: they need approved accounts, opening balances and tax rules); Odoo's chat panel keeps its own colours; Urdu text; a language-model behind Ask (it is rule-based); screens not listed in `INDEX.md` follow the same patterns.

Rebuild this gallery: `NODE_PATH=$HOME/tfmsg-website/node_modules node tests/ui_gallery.js && python3 tests/ui_gallery_index.py`.
