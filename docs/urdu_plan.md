# Urdu and right-to-left: what is done, what is not

**Status (25 Oct 2026): right-to-left layout is built and tested. Urdu text is NOT translated yet, on purpose.**

## What Odoo gives us (checked, not assumed)
* Odoo 20 ships **no Urdu translation** (no `ur.po` in `base`, `web`, `mail` or `account`) and no `ur_PK` language record. Arabic, Persian and Hebrew exist and are right-to-left.
* `rtlcss` is installed on this machine, so Odoo compiles a flipped stylesheet for any right-to-left language.
* So: even after we translate our screens, Odoo's own screens (accounting, settings, chatter) stay English for an Urdu user unless Odoo's strings are translated too.

## Done and tested
* Our Home, search and Party 360 are written with logical CSS properties (`inline-start/end`) and are flipped by `rtlcss`.
* End-to-end spec `tests/e2e/specs/06_rtl_layout.js` switches a user to Arabic (a right-to-left language Odoo can load) and checks, at 375 px and 1440 px: the page direction is right-to-left, the title sits on the right, no horizontal overflow, nothing clipped, figures keep their styling, search still opens, no console or server errors; Party 360 does not overflow. The font stack already includes Noto Nastaliq Urdu for when Urdu text arrives.
* The translatable strings are exported for a reviewer: `docs/i18n/ei_ui.pot` (`odoo i18n export`, 695 entries).

## Not done, and why it is not a quick job
1. **A native reviewer.** A finance interface must not carry unreviewed machine Urdu. A half-translated screen looks worse than a clean English one.
2. **Sentence fragments.** Several screens build a sentence from pieces around a number or name ("Showing the first N of M", "Your role cannot see these sections: ...", "The N items that need a second person ..."). Urdu word order differs, so those pieces cannot be translated one by one. They must first become whole sentences with placeholders in the JavaScript (`_t("... %s ...")`). Candidates: the My Work footer and empty-state lines, the hidden-sections notice, the search "nothing found" line, the Party 360 empty state, the quiet-figures summary.
3. **Odoo's own words** (menus we did not rename, field labels on forms, status words) need their own Urdu file, or a decision that those stay English.
4. **Language record.** Create `ur_PK` (Urdu, `ur`, right-to-left, `%d/%m/%Y`, grouping 3) and load our `ur.po` files; then switch the Arabic stand-in in spec 06 to Urdu.

## Proposed glossary (DRAFT, to be reviewed by an Urdu-speaking accountant before any use)
| English | Draft Urdu |
|---|---|
| Contract | معاہدہ |
| Delivery advice (DA) | ڈیلیوری ایڈوائس (ڈی اے) |
| Daily order | روزانہ آرڈر |
| Truck loading / lifting | ٹرک لوڈنگ / اٹھانا |
| Supplier invoice | سپلائر انوائس |
| Customer invoice | کسٹمر انوائس |
| Bank balance | بینک بیلنس |
| Customers owe us | کسٹمرز کے ذمے ہماری رقم |
| We owe suppliers | ہمارے ذمے سپلائرز کی رقم |
| Approve | منظور کریں |
| Verify | تصدیق کریں |
| Post (into the books) | کھاتے میں درج کریں |
| Match (a payment) | ادائیگی ملائیں |
| Waiting for a person | کسی کے فیصلے کا منتظر |
| Needs attention | توجہ درکار ہے |
| Old code | پرانا کوڈ |
| Reconciliation | مطابقت / ملان |

Wording such as "gross spread", "provisional" and the status words must be agreed with the accountant, because they carry accounting meaning.

## Plan
Refactor the fragments (2), export again, have the glossary and strings reviewed, import `ur.po` for `ei_ui_theme` and `ei_party360`, create the language record, run spec 06 with Urdu, and record screenshots. Estimate: a few days including the review, mostly waiting for the reviewer.
