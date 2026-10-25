# Screenshot index

Build: branch `exi-one-upgrade`, Odoo 20.0 nightly 20261018, staging database `ei20b` (synthetic DEMO data, company Export International (staging), PKR). Captured 26 Oct 2026 with headless Chromium. Passwords for the demo logins are in `docs/deployment_runbook.md`.

## `exi_one/` - the redesign, curated
| File | Route | Role | Width | Theme |
|---|---|---|---|---|
| home_admin_light_1440.png | `/odoo` (Home) | Administrator (all roles, executive layout) | 1440 | light |
| home_ceo_dark_1440.png | `/odoo` | CEO (`demo.ceo`) | 1440 | dark |
| home_ceo_light_phone_390.png, home_ceo_dark_phone_390.png | `/odoo` | CEO | 390 | light, dark |
| home_contract_operator_1440.png | `/odoo` | Contract desk (`demo.contractapprover`): workflow first, no money | 1440 | light |
| home_sysadmin_1440.png | `/odoo` | System administrator with no business role: system checks | 1440 | light |
| home_right_to_left_1440.png, home_right_to_left_375.png | `/odoo` | CEO with the language set to Arabic (stands in for Urdu) | 1440, 375 | light |
| party360_ceo_desktop.png, party360_ceo_phone_390.png | `/odoo/action-ei_party360.action_ei_party360` | CEO, party "Rehman" | 1440, 390 | light |
| bank_payments_list_1440.png | `/odoo/action-ei_bank_operations.ei_bank_line_action` | Administrator | 1440 | light |
| bank_line_form_dark_1440.png | bank line form | Administrator | 1440 | dark |

## `e2e/` - written by every run of the browser suite (`tests/run_e2e.sh`)
`role_<login>.png` one Home per role persona; `resp_<theme>_<width>_<screen>.png` the key screens at the widths the suite checks; `party360_*`, `rtl_*`. Overwritten on each run; the list of checks that produced them is `docs/e2e_results.md`.

## Older folders
`final/` and `p360/` are earlier reviews of the previous Home and of Party 360 before the redesign (kept as the "before" evidence). `docs/screenshots/` is the Odoo 19 era smoke test.
