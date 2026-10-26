"""Sign-in with a user name and a personal four-digit PIN, beside user name and password.
A PIN is weak, so what is tested is everything around it: only a salted hash is stored, wrong tries pause and then lock the PIN of that
PERSON (whatever the address), the password is never affected, the PIN opens the web page only (never the programming interfaces),
the roles reserved for the password cannot use it, the log never holds a PIN, and a refusal always reads the same."""
import os
import re
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessDenied, AccessError, UserError, ValidationError
from psycopg2 import IntegrityError
from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.tools import mute_logger
from odoo.tests.common import JsonRpcException

from ..models import pin_policy

PW = 'Alice-long-password-9!'
GOOD = '4829'


def pin_login(env, login, pin, interactive=True):
    return env['res.users'].authenticate({'type': 'ei_pin', 'login': login, 'password': pin}, {'interactive': interactive})


def pin_alone(env, pin, interactive=True):
    """The PIN and nothing else: no user name."""
    cred = {'type': 'ei_pin', 'password': pin}
    return env['res.users'].authenticate(cred, {'interactive': interactive}), cred


@tagged('post_install', '-at_install', 'ei')
class TestPinPolicy(TransactionCase):

    def test_p01_which_pins_are_acceptable(self):
        for pin in ('4829', '0731', '5083', '9164', '2750'):
            pin_policy.check_new_pin(pin, pin)                                 # no exception
        for pin, why in (('1234', 'first ones'), ('0000', 'first ones'), ('7777', 'first ones'), ('3456', 'in a row'), ('5432', 'in a row'), ('9876', 'first ones'),
                         ('7890', 'in a row'), ('1999', 'year'), ('2024', 'year'), ('1950', 'year'), ('4747', 'pair'), ('8383', 'pair')):
            with self.assertRaises(ValidationError, msg=pin) as cm:
                pin_policy.check_new_pin(pin, pin)
            self.assertIn(why, str(cm.exception.args[0]), pin)
        for bad in ('123', '12345', 'abcd', '12a4', '', ' 123', '１２３４', None, 1234):   # fullwidth digits and numbers are not a PIN either
            with self.assertRaises(ValidationError, msg=repr(bad)):
                pin_policy.check_new_pin(bad, bad)
        with self.assertRaises(ValidationError):
            pin_policy.check_new_pin('4829', '4820')                           # the two entries must agree

    def test_p02_wrong_tries_pause_then_lock(self):
        steps = {n: pin_policy.lock_for(n) for n in range(0, 17)}
        self.assertEqual([n for n, (s, h) in steps.items() if s or h], [5, 10] + list(range(15, 17)))
        self.assertEqual(steps[5], (900, False))                               # 15 minutes
        self.assertEqual(steps[10], (3600, False))                             # an hour
        self.assertEqual(steps[15], (0, True))                                 # then it waits for an administrator
        self.assertEqual(steps[4], (0, False))


@tagged('post_install', '-at_install', 'ei')
class TestPinSignIn(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.enterClassContext(cls.registry_test_mode())                         # the counters and the log use a cursor of their own: let it share this test's transaction
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        cls.alice = Users.create({'name': 'Alice Pin', 'login': 'pin.alice', 'password': PW, 'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])]})
        cls.bob = Users.create({'name': 'Bob Pin', 'login': 'pin.bob', 'password': 'Bob-long-password-7!', 'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])]})
        cls.root = Users.create({'name': 'Rita Admin', 'login': 'pin.rita', 'password': 'Rita-long-password-5!',
                                 'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('base.group_system').id])]})
        cls.Cred = cls.env['ei.pin.credential']
        cls.Log = cls.env['ei.pin.log']

    def set_pin(self, user=None, pin=GOOD, password=PW):
        user = user or self.alice
        return self.env['res.users'].with_user(user).ei_set_pin(password, pin, pin)

    def cred(self, user=None):
        self.env.invalidate_all()                                               # the counters are written by a transaction of their own
        return self.Cred.sudo().search([('user_id', '=', (user or self.alice).id)])

    def refused(self, login='pin.alice', pin=GOOD):
        # not assertRaises: Odoo's version rolls the transaction back to a savepoint, which would also undo the counters, and in
        # real life a refused sign-in is exactly the case where they must survive
        try:
            pin_login(self.env, login, pin)
        except AccessDenied as e:
            return e
        self.fail(f'{login} with {pin!r} was let in')

    # ---- setting a PIN
    def test_s01_setting_a_pin_needs_the_password_and_stores_only_a_keyed_hash(self):
        users = self.env['res.users'].with_user(self.alice)
        with self.assertRaises(UserError):
            users.ei_set_pin('wrong password', GOOD, GOOD)                    # a borrowed, unlocked screen cannot plant a PIN
        with self.assertRaises(UserError):
            users.ei_set_pin('', GOOD, GOOD)
        self.assertFalse(self.cred())
        self.set_pin()
        stored = self.cred().pin_index
        self.assertRegex(stored, r'^[0-9a-f]{64}$')
        self.assertNotIn(GOOD, stored)
        with patch.dict(os.environ, {'EI_PIN_PEPPER': 'another key kept outside the database'}):
            self.assertNotEqual(self.Cred._index(GOOD), stored, 'the hash depends on a key that is not in the database')
        self.assertEqual(self.env['ei.pin.credential'].sudo().search_count([('user_id', '=', self.alice.id)]), 1)
        self.assertTrue(self.cred().set_on)

    def test_s02_weak_and_malformed_pins_are_refused_by_the_server(self):
        users = self.env['res.users'].with_user(self.alice)
        for pin in ('1234', '0000', '1999', '3456', '4747', 'abcd', '123', '12345'):
            with self.assertRaises(ValidationError, msg=pin):
                users.ei_set_pin(PW, pin, pin)
        self.assertFalse(self.cred())

    def test_s03_a_person_removes_their_own_pin_with_the_password(self):
        self.set_pin()
        users = self.env['res.users'].with_user(self.alice)
        with self.assertRaises(UserError):
            users.ei_remove_pin('nope')
        self.assertTrue(self.cred())
        users.ei_remove_pin(PW)
        self.assertFalse(self.cred())
        self.refused()                                                         # no PIN, no way in

    # ---- signing in
    def test_g01_the_pin_signs_in_and_only_the_right_one(self):
        self.set_pin()
        info = pin_login(self.env, 'pin.alice', GOOD)
        self.assertEqual((info['uid'], info['auth_method']), (self.alice.id, 'ei_pin'))
        self.assertTrue(self.cred().last_used)
        for wrong in ('4828', '0731', '9999'):
            self.refused(pin=wrong)

    def test_g02_every_refusal_reads_the_same(self):
        self.set_pin()
        reasons = {'wrong PIN': self.refused(pin='5083'), 'unknown name': self.refused(login='nobody.here'), 'no PIN set': self.refused(login='pin.bob'),
                   'not four digits': self.refused(pin='48'), 'letters': self.refused(pin='abcd'), 'empty': self.refused(pin='')}
        self.assertEqual({e.args for e in reasons.values()}, {AccessDenied().args}, 'the person must not be able to tell which one it was')

    def test_g03_a_pin_is_not_a_password_and_a_password_is_not_a_pin(self):
        self.set_pin()
        with self.assertRaises(AccessDenied):
            self.env['res.users'].authenticate({'type': 'password', 'login': 'pin.alice', 'password': GOOD}, {'interactive': True})
        self.refused(pin=PW)
        with self.assertRaises(AccessDenied):
            self.env['res.users']._check_uid_passwd(self.alice.id, GOOD)       # nor does it open the programming interfaces
        with self.assertRaises(AccessDenied):
            pin_login(self.env, 'pin.alice', GOOD, interactive=False)
        self.assertEqual(self.env['res.users'].authenticate({'type': 'password', 'login': 'pin.alice', 'password': PW}, {'interactive': True})['uid'], self.alice.id)

    def test_g04_two_people_cannot_hold_the_same_pin_and_probing_for_taken_ones_is_stopped(self):
        self.set_pin()
        bob = self.env['res.users'].with_user(self.bob)
        with self.assertRaises(UserError) as cm:
            bob.ei_set_pin('Bob-long-password-7!', GOOD, GOOD)                 # alice has it: one flat sentence, no name
        self.assertNotIn('Alice', str(cm.exception))
        self.assertFalse(self.cred(self.bob))
        pin_login(self.env, 'pin.alice', GOOD)                                  # and hers is untouched
        with mute_logger('odoo.sql_db'), self.assertRaises(IntegrityError):    # the database says so too
            self.Cred.sudo().create({'user_id': self.bob.id, 'pin_index': self.cred().pin_index})
        # five PINs refused as "not available" in an hour and a person is told to wait: they cannot try every PIN to learn whose it is
        for _n in range(pin_policy.SET_REFUSED_LIMIT):
            self.Log._write_apart({'event': 'set', 'success': False, 'reason': 'not_available', 'user_id': self.bob.id, 'actor_id': self.bob.id, 'login': 'pin.bob', 'ip': 'n/a'})
        with self.assertRaises(UserError) as cm:
            bob.ei_set_pin('Bob-long-password-7!', '6120', '6120')             # even a free PIN
        self.assertIn('Too many PINs were refused', str(cm.exception))

    # ---- wrong tries
    def test_l01_wrong_tries_pause_then_lock_the_pin_but_never_the_password(self):
        self.set_pin()
        for _n in range(4):
            self.refused(pin='5083')
        self.assertEqual(self.cred().failed_count, 4)
        pin_login(self.env, 'pin.alice', GOOD)                                  # a good one in time clears the count
        self.assertEqual(self.cred().failed_count, 0)
        for _n in range(5):
            self.refused(pin='5083')
        cred = self.cred()
        self.assertEqual(cred.failed_count, 5)
        self.assertGreater(cred.locked_until, fields.Datetime.now() + timedelta(minutes=14))
        self.refused(pin=GOOD)                                                  # paused: even the right PIN waits
        self.assertEqual(self.cred().failed_count, 5, 'tries during a pause are not counted')
        self.assertEqual(self.env['res.users'].authenticate({'type': 'password', 'login': 'pin.alice', 'password': PW}, {'interactive': True})['uid'], self.alice.id)
        cred.locked_until = fields.Datetime.now() - timedelta(seconds=1)       # the quarter hour is over
        pin_login(self.env, 'pin.alice', GOOD)
        self.assertEqual(self.cred().failed_count, 0)

    def test_l02_an_hour_after_ten_and_a_hard_lock_after_fifteen(self):
        self.set_pin()

        def wrong(n):
            for _i in range(n):
                self.cred().locked_until = False                                # skip the waiting, keep the count
                self.refused(pin='5083')
        wrong(10)
        self.assertEqual(self.cred().failed_count, 10)
        self.assertGreater(self.cred().locked_until, fields.Datetime.now() + timedelta(minutes=59))
        wrong(5)
        cred = self.cred()
        self.assertEqual(cred.failed_count, 15)
        self.assertTrue(cred.hard_locked)
        cred.locked_until = fields.Datetime.now() - timedelta(days=3)           # waiting does not help any more
        self.refused(pin=GOOD)
        self.env['res.users'].with_user(self.root).browse(self.alice.id).action_ei_pin_unlock()
        self.assertEqual(self.cred().failed_count, 0)
        pin_login(self.env, 'pin.alice', GOOD)                                  # the old PIN works again after the lock is lifted

    def test_l03_the_lock_belongs_to_the_person_not_to_the_address(self):
        self.set_pin()
        for _n in range(5):
            self.refused(pin='5083')                                            # (no request here, so no address at all)
        self.refused(pin=GOOD)
        self.set_pin(pin='6120')                                                # choosing a new PIN (with the password) also clears it
        self.assertEqual(self.cred().failed_count, 0)
        pin_login(self.env, 'pin.alice', '6120')

    def test_l04_one_address_failing_everywhere_is_stopped(self):
        for n in range(pin_policy.IP_LIMIT - 1):
            self.Log._write_apart({'event': 'signin', 'success': False, 'reason': 'wrong_pin', 'login': f'x{n}', 'ip': '203.0.113.7'})
        self.assertFalse(self.Log._ip_throttled('203.0.113.7'))
        self.Log._write_apart({'event': 'signin', 'success': False, 'reason': 'wrong_pin', 'login': 'y', 'ip': '203.0.113.7'})
        self.assertTrue(self.Log._ip_throttled('203.0.113.7'))
        self.assertFalse(self.Log._ip_throttled('203.0.113.8'))
        self.assertFalse(self.Log._ip_throttled('n/a'))
        old = self.Log.sudo().search([('ip', '=', '203.0.113.7')])
        old.write({'at': fields.Datetime.now() - timedelta(minutes=16)})        # it recovers after 15 minutes
        self.assertFalse(self.Log._ip_throttled('203.0.113.7'))

    # ---- who may use a PIN
    def test_r01_the_system_administrator_signs_in_with_the_password_only(self):
        with self.assertRaises(AccessError):
            self.env['res.users'].with_user(self.root).ei_set_pin('Rita-long-password-5!', GOOD, GOOD)
        self.Cred.sudo()._set_pin(self.root, GOOD)                              # even a PIN planted by other means is refused
        self.refused(login='pin.rita')
        self.assertFalse(self.root._ei_pin_allowed())
        self.env['ir.config_parameter'].sudo().set_str('ei.pin.blocked_groups', 'none')
        self.assertTrue(self.root._ei_pin_allowed())                            # a deliberate decision of the company
        pin_login(self.env, 'pin.rita', GOOD)

    def test_r02_the_switch_turns_the_whole_thing_off(self):
        self.set_pin()
        self.env['ir.config_parameter'].sudo().set_bool('ei.pin.enabled', False)
        self.refused()
        self.assertFalse(self.alice._ei_pin_allowed())
        with self.assertRaises(AccessError):
            self.set_pin(pin='6120')
        self.env['ir.config_parameter'].sudo().set_bool('ei.pin.enabled', True)
        pin_login(self.env, 'pin.alice', GOOD)
        self.assertTrue(self.alice._ei_pin_allowed())

    def test_r03_an_administrator_can_remove_or_unlock_but_nobody_else_and_nobody_can_read(self):
        self.set_pin()
        with self.assertRaises(AccessError):
            self.alice.with_user(self.bob).action_ei_pin_reset()
        with self.assertRaises(AccessError):
            self.alice.with_user(self.bob).action_ei_pin_unlock()
        self.alice.with_user(self.root).action_ei_pin_reset()
        self.assertFalse(self.cred())
        self.refused()
        with self.assertRaises(AccessError):
            self.Cred.with_user(self.alice).search([])                          # no screen or RPC call can read the hashes
        with self.assertRaises(AccessError):
            self.Cred.with_user(self.root).create({'user_id': self.bob.id, 'pin_hash': 'x'})   # not even an administrator can choose a PIN for someone

    def test_r04_a_password_set_by_someone_else_removes_the_pin_but_your_own_change_keeps_it(self):
        self.set_pin()
        self.alice.with_user(self.alice).sudo().write({'password': 'Alice-another-long-pass-3!'})              # the person changes their own password
        self.assertTrue(self.cred())
        self.alice.with_user(self.root).write({'password': 'Reset-by-admin-long-pass-4!'})              # an administrator sets it
        self.assertFalse(self.cred())
        self.refused()
        self.assertTrue(self.Log.sudo().search([('user_id', '=', self.alice.id), ('event', '=', 'reset'), ('actor_id', '=', self.root.id)]))

    # ---- the PIN alone
    def test_a01_the_pin_alone_signs_in_the_person_it_belongs_to(self):
        self.set_pin()
        self.set_pin(self.bob, pin='6120', password='Bob-long-password-7!')
        info, cred = pin_alone(self.env, GOOD)
        self.assertEqual((info['uid'], info['auth_method']), (self.alice.id, 'ei_pin'))
        self.assertEqual(cred['login'], 'pin.alice', 'the session needs to know who signed in')
        self.assertEqual(pin_alone(self.env, '6120')[0]['uid'], self.bob.id)
        e = None
        try:
            pin_alone(self.env, '5083')
        except AccessDenied as ex:
            e = ex
        self.assertIsNotNone(e)
        self.assertEqual(e.args, AccessDenied().args)                           # the same sentence as every other refusal
        for bad in ('48', 'abcd', ''):
            with self.assertRaises(AccessDenied):
                pin_alone(self.env, bad)
        with self.assertRaises(AccessDenied):
            pin_alone(self.env, GOOD, interactive=False)                        # a PIN alone opens the web page only

    def test_a02_a_pin_alone_is_logged_as_such_and_refusals_count_for_the_whole_system(self):
        self.set_pin()
        self.Cred.sudo()._set_pin(self.root, '7359')                            # a reserved role: found, then refused, and counted all the same
        for pin in ('5083', '7359'):
            try:
                pin_alone(self.env, pin)
            except AccessDenied:
                pass
        pin_alone(self.env, GOOD)
        rows = self.Log.sudo().search([('pin_only', '=', True)]).sorted('id')
        self.assertEqual([(r.success, r.reason) for r in rows], [(False, 'wrong_pin'), (False, 'role_not_allowed'), (True, 'ok')])
        self.assertEqual(rows[0].login, '')                                      # nobody is blamed for a wrong PIN
        self.assertEqual(self.Log._pin_only_refused(1), 2)

    def test_a03_too_many_refused_pins_from_anywhere_rest_pin_sign_in_for_everybody_but_not_the_password(self):
        self.set_pin()
        for n in range(pin_policy.PIN_ONLY_HOUR_LIMIT - 1):
            self.Log._write_apart({'event': 'signin', 'success': False, 'reason': 'wrong_pin', 'login': '', 'ip': f'198.51.100.{n}', 'pin_only': True})
        self.assertFalse(self.Log._pin_only_paused())
        pin_alone(self.env, GOOD)                                               # still open
        self.Log._write_apart({'event': 'signin', 'success': False, 'reason': 'wrong_pin', 'login': '', 'ip': '198.51.100.99', 'pin_only': True})
        self.assertTrue(self.Log._pin_only_paused())
        with self.assertRaises(AccessDenied) as cm:
            pin_alone(self.env, GOOD)                                           # even the right one rests
        self.assertIn('resting', str(cm.exception.args[0]))
        pin_login(self.env, 'pin.alice', GOOD)                                   # with a name it is the person's own count, not the system's
        self.assertEqual(self.env['res.users'].authenticate({'type': 'password', 'login': 'pin.alice', 'password': PW}, {'interactive': True})['uid'], self.alice.id)
        self.Log.sudo().search([('pin_only', '=', True)]).write({'at': fields.Datetime.now() - timedelta(hours=2)})
        self.assertFalse(self.Log._pin_only_paused())                           # an hour later it opens again
        for n in range(pin_policy.PIN_ONLY_DAY_LIMIT):                          # a slow guesser is stopped by the daily limit
            self.Log._write_apart({'event': 'signin', 'success': False, 'reason': 'wrong_pin', 'login': '', 'ip': f'203.0.113.{n}', 'pin_only': True})
        self.Log.sudo().search([('ip', '=like', '203.0.113.%')]).write({'at': fields.Datetime.now() - timedelta(hours=5)})
        self.assertTrue(self.Log._pin_only_paused())

    def test_a04_the_switch_for_the_pin_alone_asks_for_the_name_again(self):
        self.set_pin()
        self.env['ir.config_parameter'].sudo().set_bool('ei.pin.only_enabled', False)
        with self.assertRaises(AccessDenied):
            pin_alone(self.env, GOOD)
        pin_login(self.env, 'pin.alice', GOOD)                                   # name + PIN still works

    def test_a05_pin_sign_in_only_from_the_named_networks(self):
        ok = self.env['res.users']._ei_pin_network_ok
        params = self.env['ir.config_parameter'].sudo()
        self.assertTrue(ok('203.0.113.5'))                                      # nothing named: from anywhere
        params.set_str('ei.pin.allowed_networks', '10.0.0.0/8, 203.0.113.7')
        self.assertTrue(ok('10.20.30.40') and ok('203.0.113.7') and ok('n/a'))
        self.assertFalse(ok('203.0.113.8') or ok('192.168.1.5') or ok('not an address'))
        params.set_str('ei.pin.allowed_networks', 'garbage, also garbage')
        with mute_logger('odoo.addons.ei_pin_login.models.res_users'):
            self.assertFalse(ok('10.20.30.40'), 'a value that names no network closes PIN sign-in, it never opens it')

    def test_a06_a_first_pin_chosen_by_an_operator_is_accepted_whatever_it_is(self):
        # provisioning (migration/provision_pins.py) bypasses the rules a person's own choice must meet; it still cannot give two people one PIN
        self.Cred.sudo()._set_pin(self.alice, '4444')
        self.assertEqual(pin_alone(self.env, '4444')[0]['uid'], self.alice.id)
        with self.assertRaises(UserError):
            self.Cred.sudo()._set_pin(self.bob, '4444')

    # ---- the log
    def test_o01_the_log_records_what_happened_and_never_a_pin_or_a_password(self):
        self.set_pin()
        self.refused(pin='5083')
        self.refused(login='Alice-long-password-9!', pin=GOOD)                  # a password typed into the name box
        pin_login(self.env, 'pin.alice', GOOD)
        self.env['res.users'].with_user(self.alice).ei_remove_pin(PW)
        rows = self.Log.sudo().search([])
        kinds = [(r.event, r.success, r.reason) for r in rows.sorted('id')]
        self.assertEqual(kinds, [('set', True, False), ('signin', False, 'wrong_pin'), ('signin', False, 'unknown_name'), ('signin', True, 'ok'), ('removed', True, False)])
        blob = ' '.join(str(r.read(['login', 'reason', 'ip'])) for r in rows)
        for secret in (GOOD, '5083', PW):
            self.assertNotIn(secret, blob)
        self.assertIn('(not a known name)', blob)

    def test_o02_old_activity_is_cleaned_up(self):
        self.Log._write_apart({'event': 'signin', 'success': False, 'reason': 'wrong_pin', 'login': 'pin.alice', 'ip': '203.0.113.9'})
        self.Log.sudo().search([('ip', '=', '203.0.113.9')]).write({'at': fields.Datetime.now() - timedelta(days=181)})
        self.Log._gc_old_activity()
        self.assertFalse(self.Log.sudo().search([('ip', '=', '203.0.113.9')]))

    def test_o03_the_users_form_tells_an_administrator_the_state_of_the_pin(self):
        def state():
            self.env.invalidate_all()
            return self.alice.with_user(self.root).ei_pin_state
        self.assertEqual(state(), 'none')
        self.set_pin()
        self.assertEqual(state(), 'set')
        for _n in range(5):
            self.refused(pin='5083')
        self.assertEqual(state(), 'paused')
        self.cred().hard_locked = True
        self.assertEqual(state(), 'locked')


@tagged('post_install', '-at_install', 'ei')
class TestPinWebSignIn(HttpCase):
    """The real sign-in page, with real requests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.alice = cls.env['res.users'].with_context(no_reset_password=True).create(
            {'name': 'Alice Web', 'login': 'pin.web', 'password': PW, 'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])]})
        cls.env['res.users'].with_user(cls.alice).ei_set_pin(PW, GOOD, GOOD)
        cls.env.cr.flush()

    def csrf(self):
        self.opener.cookies.clear()
        page = self.url_open('/web/login').text
        return re.search(r'name="csrf_token" value="([^"]+)"', page).group(1), page

    def uid(self):
        try:
            return self.make_jsonrpc_request('/web/session/get_session_info', {}).get('uid')
        except JsonRpcException:                                                 # not signed in: the session has expired / never began
            return None

    def post(self, **data):
        token, _page = self.csrf()
        return self.url_open('/web/login', data=dict(csrf_token=token, redirect='', **data))

    def test_w01_the_page_offers_both_ways(self):
        _token, page = self.csrf()
        self.assertIn('ei-login-tabs', page)
        self.assertIn('name="ei_pin"', page)
        self.assertIn('name="password"', page)                                   # Odoo's own password field is untouched
        self.assertIn('data-mode="pin"', page)
        self.assertIn('data-pin-only="1"', page)                                 # the PIN tab asks for the four digits only
        self.assertIn('ei-keypad', page)
        self.env['ir.config_parameter'].sudo().set_bool('ei.pin.enabled', False)
        self.env.cr.flush()
        _token, page = self.csrf()
        self.assertNotIn('ei-login-tabs', page)
        self.assertNotIn('name="ei_pin"', page)

    def test_w02_user_name_and_pin_signs_in(self):
        res = self.post(login='pin.web', type='ei_pin', ei_pin=GOOD)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.uid(), self.alice.id)
        info = self.make_jsonrpc_request('/web/session/get_session_info', {})
        self.assertTrue(info['ei_pin_allowed'])                                  # the name menu offers "Sign-in PIN"
        self.env['ir.config_parameter'].sudo().set_bool('ei.pin.enabled', False)
        self.assertFalse(self.make_jsonrpc_request('/web/session/get_session_info', {})['ei_pin_allowed'])

    def test_w03_user_name_and_password_still_signs_in(self):
        res = self.post(login='pin.web', type='password', password=PW)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.uid(), self.alice.id)

    def test_w04_a_wrong_pin_shows_one_sentence_and_stays_on_the_pin_tab(self):
        res = self.post(login='pin.web', type='ei_pin', ei_pin='5083')
        self.assertFalse(self.uid())
        self.assertIn('That did not work', res.text)
        self.assertIn('data-server-mode="pin"', res.text)
        unknown = self.post(login='someone.else', type='ei_pin', ei_pin='5083')
        self.assertIn('That did not work', unknown.text)                        # a name that does not exist reads exactly the same
        alert = lambda r: re.sub(r'\s+', ' ', re.search(r'class="alert alert-danger"[^>]*>(.*?)</p>', r.text, re.S).group(1)).strip()
        self.assertEqual(alert(res), alert(unknown))

    def test_w07_the_pin_alone_signs_in_and_a_wrong_one_reads_like_every_other_refusal(self):
        wrong = self.post(type='ei_pin', ei_pin='5083')
        self.assertFalse(self.uid())
        self.assertIn('That did not work', wrong.text)
        self.assertIn('data-server-mode="pin"', wrong.text)
        res = self.post(type='ei_pin', ei_pin=GOOD)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.uid(), self.alice.id)

    def test_w08_from_another_network_the_page_says_so(self):
        self.env['ir.config_parameter'].sudo().set_str('ei.pin.allowed_networks', '203.0.113.0/24')
        self.env.cr.flush()
        res = self.post(type='ei_pin', ei_pin=GOOD)
        self.assertFalse(self.uid())
        self.assertIn('only available from the office network', res.text)
        self.env['ir.config_parameter'].sudo().set_str('ei.pin.allowed_networks', '127.0.0.1')
        self.env.cr.flush()
        self.post(type='ei_pin', ei_pin=GOOD)
        self.assertEqual(self.uid(), self.alice.id)

    def test_w05_a_pin_posted_as_a_password_does_nothing(self):
        self.post(login='pin.web', type='password', password=GOOD)
        self.assertFalse(self.uid())

    def test_w06_a_pin_does_not_open_the_programming_interfaces(self):
        db = self.env.cr.dbname
        self.assertFalse(self.xmlrpc_common.authenticate(db, 'pin.web', GOOD, {}))

