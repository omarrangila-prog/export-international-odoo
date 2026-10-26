# EXI ONE design system

Where it lives: tokens in `addons/ei_ui_theme/static/src/scss/theme.scss` (light) and `theme.dark.scss` (dark); the Home page in
`static/src/home/`; the search box in `static/src/search/`; shared icons in `static/src/common/icons.js`. Party 360 reuses the same tokens.
Nothing here replaces Odoo's web client: it is Odoo-supported assets (SCSS, Owl components, one `ir.http` override for the colour scheme).

## Principles
1. **Five-second clarity.** The first screen says what needs attention, what the business position is, and what to do next.
2. **Nothing invented.** Every number is counted from records the signed-in person may read, and opens those records. A section a role cannot see is absent, never a zero.
3. **Status is never colour alone.** Every status has a word and an icon (and a hidden label for screen readers).
4. **Layers.** (1) figures, (2) action centre (alerts, My Work, launcher), (3) insight (charts, pipeline, activity). The role profile only reorders them.

## Tokens (CSS custom properties, `--ei-*`)
| Group | Tokens | Notes |
|---|---|---|
| Ink and text | `ink` `text` `muted` `faint` `on-ink` | `ink` is headline colour in both themes (navy in light, near-white in dark). `nav-bg` is the top bar |
| Surfaces | `bg` `card` `surface-2` `line` `line-strong` | Home cards (since the Overview redesign, 26 Oct) use `--h-r` 20px radius, a hairline `--h-edge` and a soft brand-tinted `--h-shadow` (declared on `.ei-home`, stepped for dark in `theme.dark.scss`); the page carries a faint blue/aqua glow `--h-glow`. Other screens keep the 12px card |
| Brand | `primary` `primary-hover` `primary-soft` `primary-line` `on-primary` `focus` | One accent (blue). Focus ring is 3px, always visible |
| Status | `ok` `warn` `bad` `info`, each with `-soft` and `-line` | Text colour on its own soft tint is >= 4.5:1 in both themes |
| Chart | `s1` blue, `s2` orange, `s3` aqua (+ `-ink` for icons/text, `-soft` for icon chips, `-lite` for the pale end of a bar gradient), `seq-0..4` one-hue ramp | The first three slots of the validated palette, checked ALL-PAIRS in light and dark (dataviz validator: all pass; aqua on white is 2.74:1, so every aqua figure also shows its number and has a table view). Invoiced = blue, Received = orange, Material lifted = aqua |
| Shape | `radius` 12px, `shadow`, `shadow-hover`, `shadow-pop` | |
| Type | `font` | System UI stack (Inter if present, then Segoe UI/system-ui, Noto Nastaliq for Urdu). Figures use tabular numerals |

Measured contrast (WCAG ratio; 4.5 needed for text): light muted/card 6.2, muted/page 5.7, faint/page 4.5+, green on green tint 4.5+, amber on tint 5.6, red on tint 5.7, blue on tint 5.8;
dark muted/card 6.7, status colours on their tints 5.5 to 7.7. Axe-core runs on Home in the end-to-end suite and fails the build on any serious or critical finding.

## Scale
Type: page title 44 (Home Overview; 32 on a phone), card title 16, big number 38 (32 in a period card, 30 in a pipeline column), KPI value 28 (21 small), section heading 18, body 14-14.5, meta 12.5-13. Numbers are tabular and tightly tracked (-0.03em). Spacing: 4/8/12/16/24/28 rhythm. Touch targets: 44px on touch devices.
Motion: 120-200ms colour/position changes only; none for money values; all motion is switched off under `prefers-reduced-motion`.

## Components (Home)
Compact header (company, person and role, search, freshness, refresh, approvals pill, reminders pill, theme) - KPI tile (label, value, sub-line, basis chip, opens records) -
alert row (severity word + icon + count + why) - task row (priority, step, record, party, amount, age, assignee, "Next:", one verb button, more menu) -
filter chips - bar chart with legend, hover/focus tooltip and "Show as table" - horizontal ranked bars - meter - pipeline stage - launcher group - modal (focus on open, Esc closes) -
toast (polite live region) - skeleton - empty state ("No alerts", "Nothing is waiting for you") - error state with a retry.

## Role profiles (Home)
| Profile | Chosen when the user has | Leads with | Figures |
|---|---|---|---|
| Executive | management role | figures, alerts, trends | 8 money and reconciliation figures |
| Finance manager | accounting manager, bank approver or cash approver | figures, alerts, My Work | 6 money figures |
| Accountant | accountant, bank poster, reconciliation or invoicing role | My Work, figures | bank, receivables, payables where permitted |
| Logistics | dispatch officer or lifting reviewer | My Work, figures | loadings to verify, still to lift, open orders, to invoice |
| Contract desk | contract staff/approver or order approver | My Work, figures | contracts, DAs, still to lift, open orders |
| Data entry | bank officer, cash clerk or importer | My Work, launcher | counts for their own queue |
| System administrator | Odoo administrator | system checks, alerts | PDF engine, mail, jobs, accounts |

A profile never grants access; the ORM and access rules do. Money figures need the finance, management or auditor role (same rule as the Detailed report).

## Dark theme
Odoo 20 Community ships a dark asset bundle but answers "light" for everyone. `ir.http.color_scheme` answers from the browser's `color_scheme` cookie (set by the Home theme button; the same cookie Odoo's charts read).
`theme.dark.scss` re-declares the tokens and maps Odoo's own surfaces (lists, forms, kanban cards, menus, dialogs, search) to them. Odoo screens we have not styled keep Odoo's default and are listed in `docs/release_status.md`.

## Right-to-left and Urdu
Home and Party 360 use logical CSS properties (`inline-start/end`) and the compiled bundle is flipped by `rtlcss` (installed) when a user's language is right-to-left. Status of the Urdu strings is in `docs/release_status.md`.

## Accessibility (what is built and checked)
Landmarks and headings; every icon is `aria-hidden` and every icon button has a label; search is an ARIA combobox with `aria-activedescendant`; menus use `role=menu`; dialogs are modal with Esc;
tables and charts have a text alternative ("Show as table"); statuses carry words; `aria-pressed` on toggles; polite live region for confirmations. Keyboard: `/` focuses search, Ctrl+K opens Odoo's palette (now searching records too), Tab order follows reading order.
Not yet done: supervised screen-reader pass and a keyboard-only task study with real staff.

## The Overview (Home, 26 Oct 2026)
Reference: the user supplied a dashboard they liked (a rounded-card overview with a big title, a period choice with "compared to", a gradient pipeline chart, a big number with a change chip, a question box). We took the visual language only, never the content: every number is real or absent.
* **Top bar (all screens, both themes):** a light, rounded bar that floats clear of the window edges (dark card in dark mode), the open screen as a filled blue pill (`aria-current`, set by `static/src/nav/nav_current.js`), round icon buttons for messages and activities with a red count, "Ask" with a blue spark, the company and the signed-in person. Odoo's own markup and keyboard behaviour are untouched.
* **Scrolling:** the Home and Party 360 are their own scroll containers with a thin, rounded scrollbar in the page's greys (`scrollbar-color`, `::-webkit-scrollbar`). Odoo's `.o_action { overflow: hidden; scrollbar-width: none }` wins over a plain `overflow-y: auto`, so the rule is `.o_web_client > .o_action_manager > .o_action.ei-home:not(.o_action_delegate_scroll)`; a test scrolls with the real mouse wheel.
* **Header:** the title "Overview" with a round refresh button beside it, the period on the right as two date pills (the period, a choice; the days it is compared to, fixed), one line of context, then search.
* **Hero:** the contract-to-payment pipeline (a column per step: what it is, the real count, what waits for a person) over one picture: gradient bars, a dashed smooth area through their tops, an axis in whole numbers (0, half, top), a tooltip on hover; the question box (Ask) is the foot of that card. Beside it "Customers owe us": the big number, how much of it is late, a one-bar picture of how late, and one row per band with an icon tile and a bar (a table view on the round button).
* **Period cards:** Invoiced (smooth area with an end dot that follows the hover), Received in the bank (bars), Material lifted (bars): big number, a change chip, "Before: <earlier figure>", a day-by-day chart with hover, "Show as table", and an arrow that opens exactly the records added up. The change is only a percentage when there is something to compare ("New" and "No activity" otherwise).
* **Lists:** bank balances (finance only, with whether the bank confirmed them) and who owes most (initials avatar, share bar, opens the party); recent invoices (or truck loadings for operators) with due date and a status in words, right after the cards.
* **Rules that did not change:** a card the role may not see is absent; money only for finance, management and the auditor; charts never carry meaning by colour alone; light, dark and right-to-left share one file; motion is off under `prefers-reduced-motion`.

## Standard screens (lists, cards, records, dialogs, menus) - 26 Oct 2026
The same language as the Overview, in `ei_ui_theme/static/src/scss/screens.scss` (tokens only, so the dark theme follows):
* **Page:** a faint brand glow on the page colour; one gutter (24px, 12px on a phone) that lines up with the floating top bar.
* **Title strip:** no band and no rule; a 28px bold title, the search field as one rounded card with its filters inside (focus = blue edge and a soft halo), round pager buttons, the view switch as a rounded segmented control.
* **Lists:** one white rounded card with a soft shadow; calm sentence-case column titles (muted, 12.5px, 600); airy rows; hover grey, selection blue; links blue; the footer total bold. A list inside a record is a quiet bordered table that still scrolls sideways.
* **Cards (kanban):** rounded, soft shadow, rise 3px on hover (the entry animation never overrides it: `animation-fill-mode: backwards`).
* **Records:** a white rounded sheet; the steps as a row of pills with the current one filled; fields as **visible boxes** (1px edge, 12px radius, 42px high, a halo on focus) so a person sees where to type before touching anything; tabs as pills; the conversation as its own rounded card.
* **Dialogs and menus:** 22px radius, soft shadow, 21px bold title, footer buttons left, a visible Cancel; menus and pick-lists 16px radius with soft hover.
* **Contrast:** Odoo's own greys were 4.3:1 on white; muted text is now our 7:1 grey everywhere, including chatter dates. Odoo's white disc behind round buttons is removed (it showed as a white tile in dark mode).
* **Checked by** `tests/e2e/specs/11_screens.js` (computed styles, boxes, mouse wheel, axe contrast; light, dark, phone).
