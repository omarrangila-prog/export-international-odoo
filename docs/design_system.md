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
| Surfaces | `bg` `card` `surface-2` `line` `line-strong` | Cards have a 1px border and a very light shadow; no glass, no gradients |
| Brand | `primary` `primary-hover` `primary-soft` `primary-line` `on-primary` `focus` | One accent (blue). Focus ring is 3px, always visible |
| Status | `ok` `warn` `bad` `info`, each with `-soft` and `-line` | Text colour on its own soft tint is >= 4.5:1 in both themes |
| Chart | `s1` blue, `s2` orange, `seq-0..4` one-hue ramp | Series pair validated for colour-blind separation and 3:1 contrast in light and dark (dataviz validator: all checks pass) |
| Shape | `radius` 12px, `shadow`, `shadow-hover`, `shadow-pop` | |
| Type | `font` | System UI stack (Inter if present, then Segoe UI/system-ui, Noto Nastaliq for Urdu). Figures use tabular numerals |

Measured contrast (WCAG ratio; 4.5 needed for text): light muted/card 6.2, muted/page 5.7, faint/page 4.5+, green on green tint 4.5+, amber on tint 5.6, red on tint 5.7, blue on tint 5.8;
dark muted/card 6.7, status colours on their tints 5.5 to 7.7. Axe-core runs on Home in the end-to-end suite and fails the build on any serious or critical finding.

## Scale
Type: page title 20, section label 12 (uppercase, tracked), KPI value 28 (20 small), body 14-14.5, meta 12.5-13. Spacing: 4/8/12/16/24/28 rhythm. Touch targets: 44px on touch devices.
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
