"""The DA feeding methods, as pure functions (Decimal, no database).

Sources: the client's Daily Working Tasks pp.3-6 and the six handwritten examples on one ISL Delivery Advice.
Purchase side: the parent's approved formula (Formula Register) gives the mill rate, the dealer net purchase rate and,
when a credit note is entered for THIS coil, the final net purchase rate. Sale side: the mill rate plus or minus an
amount the operator types (or a sale rate typed directly). Direct: both rates typed, no commission.

Every result here is a GROSS spread per metric ton and an illustrative total for the coil's tons. It is not a tax
result, not an invoice total and not accounting profit.
"""
from decimal import Decimal, ROUND_HALF_UP

from odoo.addons.ei_contract_da.models import formula_engine as fe

D = fe.D
CENT = Decimal('0.01')
TON = Decimal('0.001')

# key: (label, purchase basis, default sale offset in the training lab, plain explanation)
METHODS = {
    'normal_sale': ("Normal sale", 'dealer_net', Decimal('-1000'),
                    "Bought at the dealer net rate; sold at the mill rate less a small amount."),
    'high_profit_sale': ("High-profit sale", 'dealer_net', Decimal('10000'),
                         "Bought at the dealer net rate; sold above the mill rate."),
    'loss_sale': ("Loss sale", 'dealer_net', Decimal('-10000'),
                  "Bought at the dealer net rate; sold below what it cost. Needs a reason and an approver."),
    'sale_at_mill_rate': ("Sale at mill rate", 'dealer_net', Decimal('0'),
                          "Bought at the dealer net rate; sold at exactly the mill rate. The spread is the dealer commission."),
    'purchase_with_cn': ("Purchase with CN", 'with_cn', Decimal('0'),
                         "A credit note on THIS coil lowers its purchase rate (less 1.32% on the CN); sold at the mill rate."),
    'direct_no_commission': ("Direct purchase and sale, no commission", 'direct', None,
                             "Both rates are typed as agreed. No mill-rate steps and no commission."),
    'purchase_without_commission': ("Purchase without commission", 'blocked', None,
                                    "Waiting for the client's own example and the accountant's rule. It cannot be calculated or used yet."),
}
ORDER = list(METHODS)
FORMULA_KEYS = ('mill_rate', 'dealer_net_purchase_rate', 'net_cn', 'final_net_purchase_rate')
LABELS = {
    'basic_rate': "Basic rate", 'sales_tax_18': "18% added to the basic rate", 'after_sales_tax': "Rate after 18%",
    'additional_0_1': "0.1% added to the rate after 18%", 'mill_rate': "Mill rate", 'dealer_commission': "Dealer commission (1.32% of basic)",
    'dealer_net_purchase_rate': "Dealer net purchase rate", 'cn_amount': "Credit note (CN) on this coil",
    'cn_commission': "1.32% taken off the CN", 'net_cn': "Net CN", 'final_net_purchase_rate': "Purchase rate after CN",
}


class FeedingError(ValueError):
    pass


def money(x):
    return D(x).quantize(CENT, rounding=ROUND_HALF_UP)


def tons_from_kg(kg):
    """4,574.00 kg -> 4.574 MTL. Exact: a metric ton is 1,000 kg."""
    return (D(kg) / Decimal(1000)).quantize(TON, rounding=ROUND_HALF_UP)


def feed(method, quantity, steps=None, rounding_mode='final_only', basic_rate=None, params=None,
         sale_offset=None, sale_rate=None, purchase_rate=None, cn_amount=None):
    """One coil, one method -> dict. Raises FeedingError in plain words when the inputs cannot give an answer."""
    if method not in METHODS:
        raise FeedingError("Unknown feeding method %r." % method)
    label, basis, _default, _why = METHODS[method]
    if basis == 'blocked':
        raise FeedingError("'%s' is waiting for the client's example and the accountant's rule; it cannot be used yet." % label)
    qty = D(quantity)
    if qty <= 0:
        raise FeedingError("The quantity must be more than zero.")
    rows = []
    if basis == 'direct':
        if purchase_rate in (None, '') or sale_rate in (None, ''):
            raise FeedingError("Type both the purchase rate and the sale rate.")
        purchase, sale, mill = money(purchase_rate), money(sale_rate), None
        rows += [{'key': 'purchase', 'label': "Purchase rate (typed)", 'value': purchase},
                 {'key': 'sale', 'label': "Sale rate (typed)", 'value': sale}]
    else:
        if not steps:
            raise FeedingError("This method needs the parent's approved rate formula.")
        if basic_rate in (None, '') or D(basic_rate) <= 0:
            raise FeedingError("Type the basic rate.")
        cn = D(cn_amount or 0) if basis == 'with_cn' else Decimal(0)
        if basis == 'with_cn' and cn <= 0:
            raise FeedingError("Type the credit note amount for this coil.")
        p = dict(params or {})
        p['cn_amount'] = cn
        try:
            frows, values = fe.evaluate(steps, basic_rate, 1, p, 2, rounding_mode)
        except fe.FormulaError as e:
            raise FeedingError("The rate formula cannot be worked out: %s" % e)
        missing = [k for k in FORMULA_KEYS if k not in values]
        if missing:
            raise FeedingError("The formula does not give: %s." % ', '.join(missing))
        rows.append({'key': 'basic_rate', 'label': LABELS['basic_rate'], 'value': money(basic_rate)})
        for r in frows:
            if basis != 'with_cn' and r['key'] in ('cn_amount', 'cn_commission', 'net_cn', 'final_net_purchase_rate'):
                continue
            rows.append({'key': r['key'], 'label': LABELS.get(r['key'], r['key']), 'value': r['result'], 'step': r['kind'],
                         'on': r['base_ref'], 'param': str(r['param_value']) if r['param_value'] is not None else ''})
        mill = values['mill_rate']
        purchase = values['final_net_purchase_rate'] if basis == 'with_cn' else values['dealer_net_purchase_rate']
        if sale_rate not in (None, ''):
            sale = money(sale_rate)
        else:
            sale = money(mill + D(sale_offset or 0))
        rows.append({'key': 'sale', 'label': "Sale rate (mill rate %s %s)" % ('+' if sale >= mill else '-', money(abs(sale - mill))),
                     'value': sale})
    # every coil carries both rates: a zero or negative rate is a typing slip, never a price
    if purchase <= 0:
        raise FeedingError("The purchase rate must be more than zero (it is %s)." % purchase)
    if sale <= 0:
        raise FeedingError("The sale rate must be more than zero (it is %s). Check the mill rate +/- amount." % sale)
    spread = money(sale - purchase)
    total = money(spread * qty)
    return {
        'method': method, 'label': label, 'purchase_rate': purchase, 'sale_rate': sale, 'mill_rate': mill,
        'sale_offset': None if mill is None else money(sale - mill), 'spread_per_mtl': spread, 'quantity': qty,
        'total_spread': total, 'result': 'profit' if spread > 0 else 'loss' if spread < 0 else 'even', 'rows': rows,
    }
