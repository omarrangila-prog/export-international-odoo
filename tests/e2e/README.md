# Real-browser end-to-end suite

Runs Chromium (Playwright) against a real Odoo 20 server on a fresh copy of the pristine staging database. It is part of the
standard run: `tests/run_all.sh` (unit tests, then this). On its own: `tests/run_e2e.sh [--spec NAME]`.

Needs: Node 20+, `playwright` and `axe-core` resolvable from `NODE_PATH` (this machine: `~/tfmsg-website/node_modules`), a Chromium for Playwright,
PostgreSQL, the Odoo 20 unpack in `~/odoo20` and `wkhtmltopdf` on the path (`migration/env.sh` adds it) because one flow prints a real PDF.

How it works: `migration/build_staging.sh ei_e2e_tpl` builds the pristine template once (a few minutes; rebuilt automatically when a module manifest is newer, or with
`EI_E2E_REBUILD=1`); every run clones it, updates the clone to the current code, starts a loopback-only server on port 8372 and runs the specs in `specs/` in order.
Results: `docs/e2e_results.md`, screenshots in `docs/ui/e2e/`. Exit code 1 if any check fails.

| Spec | What it proves |
|---|---|
| 01 | Every action and wizard that returns a window action: revise, amend, new version, email composer, print a real PDF, generate order, cancel-order wizard, invoice wizard, the three import wizards, dashboard and its drill-downs (on the pre-upgrade code the cancel, invoice and import wizards fail: `docs/e2e_baseline_reproduction.md`) |
| 02 | Seven role personas see the right Home and nothing more; every money figure opens its records (the CEO access regression) |
| 03 | Every figure, alert, pipeline stage and launcher button opens real records; My Work snooze, assign and escalate change real data; search; Ctrl+K; dark theme |
| 04 | Party 360: keyboard search, explain-this-number, drill-down, role limits, compact on a phone |
| 05 | Six widths (375, 390, 768, 1024, 1440, 1920) x key screens x light and dark: no overflow, nothing clipped, no console or server errors, axe finds nothing serious on our screens |
| 06 | Right-to-left layout (Arabic stands in for Urdu): direction, nothing overflows or clips, search works, Party 360 fits |
| 07 | Automation rules: preview creates nothing, run creates exactly the previewed reminders for the right colleague, running twice does not duplicate, non-managers cannot see or change rules |
| 08 | Match bank payments: a suggestion stays a suggestion until confirmed, evidence note rules, proposals are never saved, saving an allocation posts nothing, unidentified / reject / ask / put aside, keyboard, roles, phone step flow, light + dark axe |
| 09 | Ask (read-only assistant): top-bar button, answers equal the books, sources and "how worked out" on every answer, choosing between parties, not understanding, refusing to change anything (nothing moves), questions logged for management, a role without finance never sees money, phone/tablet/desktop layout, light + dark axe |
| 10 | Overview on Home: period choice, cards equal the records and compare with the days before, pipeline counts, who owes most opens the party, recent invoices, the question box, an operator never sees money, phone/tablet/desktop, dark axe |
| 11 | Standard screens (lists, cards, records, dialogs, pick-lists): computed styles of what the browser drew (rounded white card, soft shadow, gutter lined up with the top bar, boxed fields, filled step pill, visible Cancel), hover lift, mouse-wheel scrolling, axe contrast, dark theme, phone. Note: `--spec` matches file names by substring, so use `--spec 11_` (`11` also matches `05_responsive_a11y`) |

| 12 | Reports: the catalog, the six real reports (chart, pivot, list), filters, drill-through, who may export, every total equal to the Home figure |
| 13 | Every role x every menu entry x every "New" that is offered: it opens a form or a dialog, never an Access Error |
| 14 | Home first screen: at 1366x768 and on a phone the summary figures and the first alert or decision (with its next step) are in the first screen; money figures never wrap; secondary sections start folded on a phone; 1280 and 683 px (200 % zoom) |
| 15 | Sign-in with a PIN: both tabs, set it from the name menu, sign in with it, wrong PIN and unknown name read alike, the administrator is never offered one, removal, the log never holds a PIN, phone |

Reproducing a bug first: run `node tests/e2e/run.js --base http://127.0.0.1:PORT --spec 01` against an older checkout (git worktree of `b7ef73e` and a database built from it); the result of doing exactly that is in `docs/e2e_baseline_reproduction.md`.
