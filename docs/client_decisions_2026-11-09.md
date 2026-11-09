# Client decisions, 9 November 2026: approval off by default, PKR and USD only

These decisions come from the client's final handoff. They replace earlier "second person approves everything" designs.

## 1. Routine approval is optional and off by default
- **Workflows covered:** contracts, delivery advices (DA), daily order requests, cash vouchers and truck loadings (lifting). The rules live in the `ei.approval.policy` and `ei.review.option.mixin` models (in `ei_legacy_master`).
- **When approval is off (the default):** the person entering the record confirms it with **Save & Continue** (`action_confirm`, or `action_verify` on a loading). No second person is needed.
- **Switching it on:** an administrator ticks "Require approval" per workflow under **Settings › Export International** (config parameters `ei_approval.<flow>`).
- **One record:** a person can tick **Send for review** on a single record. Either way, the old flow applies: the approver role and the maker-checker rule.
- **What approval-off never switches off:**
  - access rights and record rules;
  - accounting rights (a cash voucher posts only for a user with accounting rights; otherwise it stays submitted for one);
  - the DA paper, quantity, rate, customer-code and exchange-rate checks;
  - unique gate passes, contract references and invoice numbers;
  - the supplier-invoice mismatch override (an exception, not a routine approval).
- **The pre-approval box** (`ei_app_shell`) follows the same policy. With approval off, it tells the person "you confirm it yourself".
- **Tests:** `export_international/tests/test_policy.py` and browser spec `21_optional_approval.js` cover the default. Existing tests and the browser suite switch the policy on, because they check the second-person controls; `tests/run_e2e.sh` does this.

## 2. New entries in PKR or USD only
- **Where it applies:** contracts, supplier invoices, parent statements and LCs offer only PKR and USD (`ei.two.currency.mixin`). A new entry in any other currency is refused.
- **Older records** in another currency are left untouched and can still be edited.
- **The DA feeding desk** offers a PKR | USD choice when a DA is started.
- **A USD DA** shows Odoo's exchange rate and the PKR equivalent. It cannot be approved without a rate on or before its date.

## 3. Other fixes found while making the training film
- **Money fields on forms:** the amount typed was invisible, because the theme painted over Odoo's currency label layer. Fixed in `ei_ui_theme/static/src/scss/screens.scss`; browser spec `22_money_fields.js` checks it in light and dark.
- **Cash count:**
  - the book side (opening, received, paid out, book) now shows live while counting;
  - a typed total is kept;
  - the record has a readable name.
- **Cash clerks** can now read cash categories, so they can pick one on a voucher.
- **DA feeding desk:**
  - a wrong customer code is warned about while typing;
  - Save & Continue never undoes a confirmed DA when today's order cannot be prepared;
  - the default DA date is the local day.
- **Morning bank balance list:** the bank column has room; rarely used columns are hidden by default.

## Not done
- **The proposed new top menu** (HOME | DAILY WORK | MONEY | CONTRACTS & DA | …). The current menu stays, and the "Approvals" menu is still shown even when every approval is off.
- **A dedicated keyboard-only test of the desk.**
- **A test that report filters are kept** when moving between reports.
