"""Deterministic, side-effect-free rate engine. Decimal arithmetic, no eval, no database.

A formula is an ordered list of steps; each step names its output (`key`), a `kind`, the earlier
value it works on (`base_ref`, 'basic_rate' or a previous key) and a parameter name (`param`).
The engine does NOT know any business rule: which steps exist, what bases they use and what rate
they are fed is data that an accountant approves in the Formula Register.
"""
from decimal import Decimal, ROUND_HALF_UP

HUNDRED = Decimal(100)

KINDS = {
    # name: (label, needs_param)
    'deduction_pct': 'base x (1 - p/100)',
    'surcharge_pct': 'base x (1 + p/100)',
    'tax_amount': 'base x p/100  (tax added on top of the base)',
    'tax_included_extract': 'base x p/(100+p)  (tax contained in a tax-inclusive base)',
    'commission_amount': 'base x p/100',
    'fixed_add': 'base + p  (per-unit charge)',
}


class FormulaError(ValueError):
    pass


def D(x):
    return x if isinstance(x, Decimal) else Decimal(str(x))


def quantize(x, places=2):
    return D(x).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def evaluate(steps, basic_rate, quantity=1, params=None, places=2, rounding_mode='final_only'):
    """Return (rows, values). rows are dicts for display: key, kind, base_ref, param, param_value, base, result, total."""
    params = {k: D(v) for k, v in (params or {}).items()}
    values = {'basic_rate': D(basic_rate)}
    rows = []
    quantity = D(quantity)
    for st in steps:
        key, kind, ref, pname = st['key'], st['kind'], st['base_ref'], st.get('param')
        if kind not in KINDS:
            raise FormulaError('unknown step kind %r' % kind)
        if key in values:
            raise FormulaError('duplicate step key %r' % key)
        if ref not in values:
            raise FormulaError('step %r uses %r before it is defined' % (key, ref))
        if pname not in params:
            raise FormulaError('missing parameter %r for step %r' % (pname, key))
        base, p = values[ref], params[pname]
        if kind == 'deduction_pct':
            out = base * (1 - p / HUNDRED)
        elif kind == 'surcharge_pct':
            out = base * (1 + p / HUNDRED)
        elif kind in ('tax_amount', 'commission_amount'):
            out = base * p / HUNDRED
        elif kind == 'tax_included_extract':
            out = base * p / (HUNDRED + p)
        else:  # fixed_add
            out = base + p
        if rounding_mode == 'each_step':
            out = quantize(out, places)
        values[key] = out
        rows.append({'key': key, 'kind': kind, 'base_ref': ref, 'param': pname, 'param_value': p,
                     'base': base, 'result': quantize(out, places), 'total': quantize(out * quantity, places)})
    return rows, {k: quantize(v, places) for k, v in values.items()}


def spread_per_unit(sale_rate, purchase_rate):
    return D(sale_rate) - D(purchase_rate)


def gross_spread(quantity, sale_rate, purchase_rate):
    """Expected gross spread BEFORE commission, costs and taxes. Not profit."""
    return D(quantity) * spread_per_unit(sale_rate, purchase_rate)
