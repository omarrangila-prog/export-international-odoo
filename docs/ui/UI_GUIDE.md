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
Big "Overview" title with a round refresh button; on the right two date pills ("13 Oct - 26 Oct" = the period you choose, "compared to 29 Sep - 12 Oct" = the same number of days just before). Then, top to bottom: the **contract-to-payment pipeline** (one column per step with the real count, bars with a smooth dashed area and an axis, the question box inside the card) beside **Customers owe us** (big number, how much is late, a one-bar picture and a row per age band); **Money and material** (Invoiced as an area chart, Received in the bank and Material lifted as bars; each with a change chip such as +44% or "New", "Before: ...", hover tooltip, "Show as table"); **Bank balances** and **Who owes us most**; **Recent invoices**; **Needs attention**; **At a glance** figures; **My work / What is stuck** (priority, age, assign / put aside / escalate); material on contracts; recent activity; **Start something** (grouped shortcuts). A card the role may not see is simply absent. A percentage is shown only when there is something to compare.

## Lists, cards, records, dialogs
* **Lists:** one white rounded card; calm sentence-case column titles; airy rows; hover grey; status as pills (always with words, never colour alone).
* **Cards:** rounded with a soft shadow, a coloured edge for the state, rise slightly on hover.
* **Records:** a white rounded sheet; the steps of the record as a row of pills with the current one filled; a coloured "what to do now" banner (blue = your turn, orange = waiting, green = done, red = stopped); fields are **visible boxes** (1px edge, 12px radius) with a blue halo on focus; tabs are pills; the conversation (messages, notes, activities) is its own rounded card on the right.
* **Dialogs:** 22px radius, bold title, fields as boxes, primary button then Cancel on the left.
* **Special screens:** Ask (a chat that answers only from the books, each answer with sources and "how it was worked out", read-only), Match bank payments (three columns: the line, the decision, the evidence and effect), Party 360 (one page per customer/supplier with every figure explained).

## Reports
Top-bar entry **Reports** opens a catalog: every report asked for, what it answers, how it is worked out, where the numbers come from, and whether it is Delivered, Partly there, Blocked or Not built (with the reason). Six are real: aged receivables, bank book against bank confirmation, bank lines not yet in the books, customer invoices and collections, contracts with expected gross spread (provisional), material lifting. Each opens as a chart, a pivot and a list (the list is the "view rows" table), has filters and favourites, opens the document behind a row, and can export a spreadsheet (only for management, the auditor and the finance approvers). Their totals are tested equal to the Home figures.

## Design tokens
Font Inter. Light: page `#F4F6FA`, card `#FFFFFF`, ink `#0F1B33`, text `#1E293B`, muted `#566275`, primary blue `#1D4ED8`, chart blue `#2A78D6`, orange `#EB6834`, aqua `#1BAF7A`; status ok `#13692F`, warning `#9A4D06`, bad `#B91C1C` on soft tints. Dark: page `#0E1626`, card `#162033`, primary `#7AA2FF`. Radii 20 (cards), 14-16 (menus, search), 12 (buttons, fields), pill (chips, steps). Shadow `0 1px 2px rgba(15,27,51,.04), 0 12px 32px rgba(29,78,216,.07)`. Motion is small (8px rise, 3px hover lift) and off under "reduce motion".

## Things deliberately not done yet
Profit and loss, balance sheet, trial balance and cash-flow reports (blocked: they need approved accounts, opening balances and tax rules); the sign-in page is Odoo's own; Odoo's chat panel keeps its own colours; Urdu text; a language-model behind Ask (it is rule-based); screens not listed in `INDEX.md` follow the same patterns.

Rebuild this gallery: `NODE_PATH=$HOME/tfmsg-website/node_modules node tests/ui_gallery.js && python3 tests/ui_gallery_index.py`.
