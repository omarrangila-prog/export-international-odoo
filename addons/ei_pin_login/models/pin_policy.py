"""What a PIN may be, and how a wrong one is answered. Plain functions with no database access, so the rules can be read (and tested)
on their own."""
import re

from odoo import _
from odoo.exceptions import AccessDenied, ValidationError

PIN_RE = re.compile(r'[0-9]{4}')           # ASCII digits only (\d would also accept other scripts)

# Wrong PINs since the last good one -> what happens next. The counter belongs to the PERSON, not to the address, so guessing from many
# addresses does not help. Password sign-in is never affected by any of this. 15 wrong guesses is 0.15 % of the 10 000 possible PINs.
PAUSE_AFTER = ((10, 3600), (5, 900))        # 5 wrong -> 15 minutes, 10 wrong -> 1 hour
HARD_LOCK_AFTER = 15                         # 15 wrong -> locked until an administrator unlocks it (or the person sets a new PIN with the password)
IP_WINDOW_SECONDS = 900                      # one address may fail this many times, over all names together, in 15 minutes
IP_LIMIT = 20

_EASY = {'1234', '1111', '0000', '1212', '7777', '1004', '2000', '4444', '2222', '6969', '9999', '3333', '5555', '6666', '1122', '1313', '8888',
         '4321', '2001', '1010', '2580', '0852', '1357', '2468', '1379', '0123', '9876', '2323', '3434', '1221'}
_DIGITS = '0123456789'


def why_too_easy(pin):
    """None if the PIN is acceptable, else a short reason in plain words."""
    if pin in _EASY or len(set(pin)) == 1:
        return _('That PIN is one of the first ones anybody tries. Choose another.')
    if pin in _DIGITS + _DIGITS[:3] or pin in (_DIGITS + _DIGITS[:3])[::-1]:
        return _('Digits in a row (such as 3456) are too easy to guess. Choose another.')
    if 1900 <= int(pin) <= 2035:
        return _('A year (such as a birth year) is too easy to guess. Choose another.')
    if pin[:2] == pin[2:]:
        return _('A repeated pair (such as 4747) is too easy to guess. Choose another.')
    return None


def check_new_pin(pin, confirm=None):
    """Raises ValidationError with a sentence the person can act on."""
    if not isinstance(pin, str) or not PIN_RE.fullmatch(pin):
        raise ValidationError(_('A PIN is exactly four digits, 0 to 9.'))
    if confirm is not None and confirm != pin:
        raise ValidationError(_('The two PINs are not the same.'))
    reason = why_too_easy(pin)
    if reason:
        raise ValidationError(reason)


def lock_for(failures):
    """(seconds, hard) for the number of wrong PINs since the last good one; (0, False) means keep trying."""
    if failures >= HARD_LOCK_AFTER:
        return 0, True
    for limit, seconds in PAUSE_AFTER:
        if failures == limit:
            return seconds, False
    return 0, False


class EiPinDenied(AccessDenied):
    """A refused PIN sign-in. The person always sees the same sentence; the reason is only for the sign-in log."""

    def __init__(self, reason, user_id=False):
        super().__init__()
        self.reason = reason
        self.user_id = user_id
