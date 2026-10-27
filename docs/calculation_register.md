# Calculation (formula) register

## Confirmed examples from the client's own text (illustrative, NOT universal rules)
| Id | Example | Source | How it is handled |
|---|---|---|---|
| C1 | Purchase 200,000 and sale 210,000 per MTL -> spread 10,000 per MTL | PDF s.2 | `spread_per_mtl = sale - purchase`; for 10 MTL expected gross spread 100,000. Labelled **before commission, costs and taxes; not profit** |
| C2 | 210,000 less 1.32% -> Mill Rate 207,228 | PDF s.2 | Engine step `deduction_pct`; seeded as a **draft** formula with a signed test; usable only after an accountant approves it |
| C3 | ISL and ASML detailed calculation (11-page version, pp.3-4): 18% of basic added; 0.1% of the 18%-inclusive rate added = Mill Rate; commission 1.32% of the **basic** rate; Dealer Net Purchase Rate = Mill Rate - commission. ISL 239,950 -> Mill 283,424.14, net 280,256.80; ASML 244,450 -> Mill 288,739.45, net 285,512.71 | PDF pp.3-4 | Seeded as a **separate draft** formula `ISL_ASML_DEALER_NET` with 7 signed tests (all pass). C2 is not changed or removed |
| C3a | Optional CN per coil (p.5): CN less 1.32% of the CN = net CN; final rate = Dealer Net - net CN. ASML with CN 1,000 -> 13.20, 986.80, final 284,525.91 | PDF p.5 | Same formula, steps `cn_amount` .. `final_net_purchase_rate`. CN amount is a parameter of **each contract line (coil)**, with its own CN text; review is refused when an amount has no text. A coil without CN enters 0 and its final rate equals Dealer Net (tested) |
| C4 | End Coils: direct rate, no commission; "210,000 @ 18% is the End Coil Mill Rate" | PDF p.5 | Ambiguous (does 210,000 include the 18%?). Nothing inferred; no formula seeded. A line never picks a formula by itself, so nothing is applied automatically |
| C5 | Direct local purchase: buy 200,000, sell 201,000 -> 1,000 per MTL | PDF p.5 | Same as C1: expected gross spread, never called profit |

## The "Mill Rate" conflict and how it is kept safe
The 11-page document uses "Mill Rate" for two different figures: the p.3 narrative (and the earlier version of the document) calls the
figure **after** deducting 1.32% the Mill Rate (C2), while the worked examples on pp.3-4 call the figure **before** the commission the
Mill Rate and the figure after it the Dealer Net Purchase Rate (C3). The two rules give different numbers (239,950: C2 gives 236,782.66,
C3 gives 280,256.80). So:
* Both stay, as two formula codes. Neither is approved; the earlier staging copy showed C2 approved by a DEMO accountant, which is not a business sign-off.
* Approved contracts keep the snapshot of the formula and version they were approved with; approving C3 later does not rewrite any of them.
* The calculation panel on each contract line shows the formula code, version, rounding mode, every input and every step.
* Before C3 is approved for real use, the accountant signs: the labels, which suppliers and dates it covers, whether CN is per MTL (as built) or a coil total, the rounding mode (both give the same results on the worked examples: tested), and the accounting/tax treatment of the 18%, 0.1%, commission and CN (open decision 31). A price worksheet is not a tax-invoice rule.

## Engine (`ei_contract_da/models/formula_engine.py`)
Decimal arithmetic, no `eval`. Step kinds: `deduction_pct`, `surcharge_pct`, `tax_amount`, `tax_included_extract`, `commission_amount`, `fixed_add`,
`input_amount` (an amount entered on the line, e.g. CN), `add_ref` / `subtract_ref` (combine two earlier results, named by `operand_ref`).
A formula is a list of steps (result name, kind, base, parameter name). The rates are supplied per contract line.
Rounding mode (`final_only` / `each_step`) is a required, accountant-owned setting; the two give different results (tested: 1659.17 vs 1659.16).

## Controls
* A formula is `draft -> approved -> retired`; approval needs >= 1 step, >= 1 passing signed test, an approver who is not the author.
* Approved formulas are immutable; changes are a new version. A contract line snapshots inputs, formula id/version and every step result **at contract approval**; later versions never rewrite it (tested).
* Quantities: `remaining = ordered - allocated`; `remaining_to_lift = DA MTL - verified lifted MTL` (verified liftings only).

## Open questions that block approving real formulas
Tax base (basic rate or rate after deduction), tax-inclusive vs exclusive, tax-on-tax for the additional tax, commission base, withholding treatment, rounding method, and the full gross-to-net profit equation. See `open_decisions.md`.
