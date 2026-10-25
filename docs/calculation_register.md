# Calculation (formula) register

## Confirmed examples from the client's own text (illustrative, NOT universal rules)
| Id | Example | Source | How it is handled |
|---|---|---|---|
| C1 | Purchase 200,000 and sale 210,000 per MTL -> spread 10,000 per MTL | PDF s.2 | `spread_per_mtl = sale - purchase`; for 10 MTL expected gross spread 100,000. Labelled **before commission, costs and taxes; not profit** |
| C2 | 210,000 less 1.32% -> Mill Rate 207,228 | PDF s.2 | Engine step `deduction_pct`; seeded as a **draft** formula with a signed test; usable only after an accountant approves it |
| C3 | "18% sales tax and 0.1% additional tax" on ISL / Aisha contracts | PDF s.2 | Not seeded. Engine can express tax steps, but the base is unconfirmed, so none is approved |
| C4 | End Coils: direct rate, no commission; "210,000 @ 18% is the End Coil Mill Rate" | PDF s.2 | Ambiguous (is 18% a deduction?). Nothing inferred |

## Engine (`ei_contract_da/models/formula_engine.py`)
Decimal arithmetic, no `eval`. Step kinds: `deduction_pct`, `surcharge_pct`, `tax_amount`, `tax_included_extract`, `commission_amount`, `fixed_add`.
A formula is a list of steps (result name, kind, base, parameter name). The rates are supplied per contract line.
Rounding mode (`final_only` / `each_step`) is a required, accountant-owned setting; the two give different results (tested: 1659.17 vs 1659.16).

## Controls
* A formula is `draft -> approved -> retired`; approval needs >= 1 step, >= 1 passing signed test, an approver who is not the author.
* Approved formulas are immutable; changes are a new version. A contract line snapshots inputs, formula id/version and every step result **at contract approval**; later versions never rewrite it (tested).
* Quantities: `remaining = ordered - allocated`; `remaining_to_lift = DA MTL - verified lifted MTL` (verified liftings only).

## Open questions that block approving real formulas
Tax base (basic rate or rate after deduction), tax-inclusive vs exclusive, tax-on-tax for the additional tax, commission base, withholding treatment, rounding method, and the full gross-to-net profit equation. See `open_decisions.md`.
