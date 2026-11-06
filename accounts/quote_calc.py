"""Server-side recalculation for multi-package quotations.

The client sends its own totals, but they are never trusted: every amount is derived here from the
package copies, mirroring calcTotals() in the frontend (src/lib/platform.ts).
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MAX_PACKAGES = 50
MAX_LINES = 50
CENT = Decimal('0.01')


class QuoteError(ValueError):
    pass


def money(value, label):
    if isinstance(value, bool) or value is None:
        raise QuoteError(f'{label} must be a number.')
    try:
        amount = Decimal(str(value))
    except InvalidOperation as error:
        raise QuoteError(f'{label} must be a number.') from error
    if not amount.is_finite() or amount < 0:
        raise QuoteError(f'{label} cannot be negative.')
    return amount


def rounded(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def text(value, label, limit, required=False):
    if value is None:
        value = ''
    if not isinstance(value, str) or len(value) > limit:
        raise QuoteError(f'{label} is invalid.')
    value = value.strip()
    if required and not value:
        raise QuoteError(f'{label} is required.')
    return value


def clean_package(raw):
    if not isinstance(raw, dict):
        raise QuoteError('Package is invalid.')
    team, materials = raw.get('team', []), raw.get('materials', [])
    if not all(isinstance(lines, list) and len(lines) <= MAX_LINES for lines in (team, materials)):
        raise QuoteError('Package details are invalid.')
    package = {
        'id': text(raw.get('id'), 'Package id', 100),
        'title': text(raw.get('title'), 'Package title', 150, required=True),
        'price': money(raw.get('price', 0), 'Package price'),
        'count_in_total': raw.get('count_in_total') is True,
        'team': [],
        'materials': [text(m, 'Material', 300) for m in materials if text(m, 'Material', 300)],
        'gift': text(raw.get('gift'), 'Gift or note', 2000),
    }
    for row in team:
        if not isinstance(row, dict):
            raise QuoteError('Team row is invalid.')
        qty = money(row.get('qty', 1), 'Team quantity')
        role = text(row.get('role'), 'Team role', 150)
        if role:
            package['team'].append({'qty': max(1, int(qty)), 'role': role})
    return package


def number(value):
    return int(value) if value == value.to_integral_value() else float(value)


def recalculate(snapshot):
    """Return a copy of the snapshot with cleaned packages and server-computed amounts.

    Snapshots without a packages list (older quotations) are returned unchanged.
    """
    if 'packages' not in snapshot:
        return snapshot
    raw_packages = snapshot['packages']
    if not isinstance(raw_packages, list) or not 1 <= len(raw_packages) <= MAX_PACKAGES:
        raise QuoteError('Add between 1 and 50 packages.')
    packages = [clean_package(p) for p in raw_packages]

    subtotal = rounded(sum((p['price'] for p in packages if p['count_in_total']), Decimal(0)))
    discount = rounded(money(snapshot.get('discount', 0), 'Discount'))
    if discount > subtotal:
        raise QuoteError('Discount cannot exceed the subtotal.')
    total = rounded(subtotal - discount)
    advance = money(snapshot.get('advance', 0), 'Advance')

    snapshot = {k: v for k, v in snapshot.items() if k not in ('discount_type', 'discount_input', 'gst_percent', 'gst')}
    return {
        **snapshot,
        'packages': [{**p, 'price': number(p['price'])} for p in packages],
        'items': [{'name': p['title'], 'price': number(p['price'])} for p in packages if p['count_in_total']],
        'subtotal': number(subtotal),
        'discount': number(discount),
        'total': number(total),
        'advance': number(advance),
        'balance': number(rounded(total - advance)),
    }
