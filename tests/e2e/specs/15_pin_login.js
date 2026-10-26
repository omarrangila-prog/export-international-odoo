// Sign-in with a four-digit PIN ALONE (no user name), beside user name and password: the real page in a real browser.
// What is proved: both ways are offered and only the chosen field is sent; a person sets their own PIN from the name menu only after
// typing the password (and weak PINs are refused in plain words); that PIN then signs them in; a wrong PIN and an unknown name read
// exactly the same and the page stays on the PIN tab; the number pad works on a phone; the system administrator is never offered a PIN; removing the
// PIN closes the way; the page fits a phone. (Locking after repeated wrong tries is proved in the unit tests, not by hammering this server:
// Odoo's own per-address cooldown would then refuse the next sign-ins of this run.)
const LOGIN = 'demo.contracts', PASSWORD = 'demo', PIN = '4829';

async function signInPage(ctx, browser, vp = [1280, 800]) {
  const { Session } = require('../lib');
  const bctx = await browser.newContext({ viewport: { width: vp[0], height: vp[1] }, locale: 'en-US', colorScheme: 'light' });
  const p = await bctx.newPage(); p.setDefaultTimeout(15000);
  const view = Object.assign(new Session(ctx, browser, 'x', 'x'), { page: p, bctx });
  await p.goto(ctx.base + '/web/login'); await p.waitForSelector('form.oe_login_form');
  return { bctx, p, view };
}
const visible = (p, sel) => p.locator(sel).first().isVisible();

module.exports = {
  name: '15 sign-in with a PIN (set it, use it, wrong tries, who may not, phone)',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const admin = await new Session(ctx, browser, 'admin', 'admin').start();
    const uid = (await admin.rpc('res.users', 'search_read', [[['login', '=', LOGIN]], ['id']]))[0].id;
    await admin.rpc('res.users', 'action_ei_pin_reset', [[uid]]);                       // start from "no PIN", whatever the demo data holds
    const state = async () => (await admin.rpc('res.users', 'read', [[uid], ['ei_pin_state']]))[0].ei_pin_state;

    // ---- 1 the sign-in page offers both ways, and only the chosen field is sent
    let { bctx, p, view } = await signInPage(ctx, browser);
    const tabs = p.locator('.ei-login-tabs .ei-login-tab');
    ctx.check(await tabs.count() === 2 && (await tabs.allInnerTexts()).join('|') === 'Password|PIN', '1 the page offers Password and PIN');
    ctx.check(await tabs.nth(0).getAttribute('aria-pressed') === 'true' && await visible(p, '#password') && !await visible(p, '#ei_pin'), '1 it opens on the password, as before');
    ctx.check(await p.locator('input[name=type]').inputValue() === 'password' && await p.locator('#ei_pin').isDisabled(), '1 only the password field is sent');
    await ctx.shot(p, 'login_password');
    await tabs.nth(1).click();
    ctx.check(await tabs.nth(1).getAttribute('aria-pressed') === 'true' && await visible(p, '#ei_pin') && !await visible(p, '#password'), '1 the PIN tab shows the PIN field and hides the password');
    ctx.check(await p.locator('input[name=type]').inputValue() === 'ei_pin' && await p.locator('#password').isDisabled() && !await p.locator('#ei_pin').isDisabled(), '1 now only the PIN is sent, as type "ei_pin"');
    ctx.check(!await visible(p, '#login') && await p.locator('#login').isDisabled(), '1 the PIN tab does not ask for a user name: the four digits say who it is');
    await p.locator('#ei_pin').pressSequentially('4a8 b2');
    ctx.check(await p.locator('#ei_pin').inputValue() === '482', '1 the PIN field takes digits only', await p.locator('#ei_pin').inputValue());
    ctx.check(await p.locator('#ei_pin').getAttribute('inputmode') === 'numeric' && await p.locator('#ei_pin').getAttribute('maxlength') === '4', '1 four digits at most, and a phone shows the number pad');
    await p.fill('#ei_pin', ''); await ctx.shot(p, 'login_pin');
    const axe = await view.axe('form.oe_login_form');
    ctx.check(!axe || !axe.filter(v => v.impact === 'serious' || v.impact === 'critical').length, '1 accessibility on the PIN tab', JSON.stringify(axe));
    await tabs.nth(0).click();
    const axe2 = await view.axe('form.oe_login_form');
    ctx.check(!axe2 || !axe2.filter(v => v.impact === 'serious' || v.impact === 'critical').length, '1 accessibility on the password tab', JSON.stringify(axe2));
    await bctx.close();

    // ---- 2 a person sets their own PIN: the password is asked for, a weak PIN is refused in words, a good one is saved
    const s = await new Session(ctx, browser, LOGIN, PASSWORD, [1280, 800], { timeout: 20000 }).start();
    let m = s.mark();
    const q = s.page;
    await q.locator('.o_user_menu').first().click();
    const item = q.getByRole('menuitem', { name: 'Sign-in PIN' });
    await item.first().waitFor({ timeout: 8000 }).catch(() => {});
    ctx.check(await item.count() === 1, '2 the name menu offers "Sign-in PIN"');
    await item.click(); await q.waitForSelector('.modal .ei-pin-dialog');
    const dlg = q.locator('.modal .ei-pin-dialog');
    ctx.check(/no PIN yet/i.test(await dlg.innerText()), '2 it says there is no PIN yet');
    const save = q.locator('.modal .btn-primary', { hasText: 'Save PIN' });
    ctx.check(await save.isDisabled(), '2 Save is off until a password and two equal PINs are typed');
    await q.fill('#ei_pin_password', 'not my password'); await q.locator('#ei_pin_new').pressSequentially(PIN); await q.locator('#ei_pin_confirm').pressSequentially(PIN);
    await save.click(); await q.waitForSelector('.ei-pin-bad');
    ctx.check(/password is not right/i.test(await q.locator('.ei-pin-bad').innerText()) && await state() === 'none', '2 a wrong password saves nothing', await q.locator('.ei-pin-bad').innerText());
    await q.fill('#ei_pin_password', PASSWORD);
    await q.fill('#ei_pin_new', ''); await q.locator('#ei_pin_new').pressSequentially('1234'); await q.fill('#ei_pin_confirm', ''); await q.locator('#ei_pin_confirm').pressSequentially('1234');
    await save.click(); await q.waitForFunction(() => /first ones/.test(document.querySelector('.ei-pin-bad')?.textContent || ''));
    ctx.check(await state() === 'none', '2 "1234" is refused in plain words and nothing is saved', await q.locator('.ei-pin-bad').innerText());
    s.discard(m);                                                                        // the two refusals above were provoked on purpose
    await q.fill('#ei_pin_new', ''); await q.locator('#ei_pin_new').pressSequentially(PIN); await q.fill('#ei_pin_confirm', ''); await q.locator('#ei_pin_confirm').pressSequentially('4828');
    ctx.check(await save.isDisabled(), '2 two different PINs cannot be saved');
    await q.fill('#ei_pin_confirm', ''); await q.locator('#ei_pin_confirm').pressSequentially(PIN);
    await ctx.shot(q, 'pin_dialog');
    await save.click(); await q.waitForSelector('.ei-pin-ok');
    ctx.check(/PIN is saved/i.test(await q.locator('.ei-pin-ok').innerText()) && await state() === 'set', '2 a good PIN is saved', await q.locator('.ei-pin-ok').innerText());
    ctx.check(await q.locator('#ei_pin_password').inputValue() === '' && await q.locator('#ei_pin_new').inputValue() === '', '2 nothing typed stays in the dialog');
    const stored = await admin.rpc('ei.pin.credential', 'search_read', [[['user_id', '=', uid]], ['set_on', 'failed_count']]).catch(() => null);
    ctx.check(stored === null || stored.length === 1, '2 one PIN record for this person');
    await s.clean('2 setting a PIN opens clean', m);
    await s.close();

    // ---- 3 the PIN alone signs them in; a wrong PIN reads like any refusal and the page stays on the PIN tab
    ({ bctx, p, view } = await signInPage(ctx, browser));
    await p.locator('.ei-login-tab[data-mode=pin]').click();
    await p.locator('#ei_pin').pressSequentially('5083');                                  // the fourth digit sends it
    await p.waitForSelector('.alert-danger');
    const wrongText = (await p.locator('.alert-danger').innerText()).replace(/\s+/g, ' ').trim();
    ctx.check(/That did not work/.test(wrongText) && !/lock/i.test(wrongText), '3 a wrong PIN: one plain sentence', wrongText);
    ctx.check(await p.locator('.ei-login-tab[data-mode=pin]').getAttribute('aria-pressed') === 'true' && !await visible(p, '#login'), '3 the page stays on the PIN tab, still without a name');
    await ctx.shot(p, 'login_pin_error');
    await p.locator('#ei_pin').pressSequentially(PIN);
    await p.waitForSelector('.o_navbar', { timeout: 60000 });
    const info = await p.evaluate(async () => (await (await fetch('/web/session/get_session_info', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"jsonrpc":"2.0","method":"call","params":{}}' })).json()).result);
    ctx.check(info.uid === uid, '3 the four digits alone sign in the person they belong to', `uid ${info.uid} expected ${uid}`);
    await bctx.close();

    // ---- 3b a phone: the number pad fills the same field and sends at the fourth digit
    ({ bctx, p, view } = await signInPage(ctx, browser, [390, 844]));
    await p.locator('.ei-login-tab[data-mode=pin]').click();
    ctx.check(await visible(p, '.ei-keypad') && (await p.locator('.ei-key[data-key="5"]').boundingBox()).height >= 44, '3b the number pad shows on a phone, keys big enough to touch');
    for (const k of ['4', '8', 'back', '8', 'clear', '4', '8', '2', '9']) await p.locator(`.ei-key[data-key="${k}"]`).click();
    await p.waitForSelector('.o_navbar', { timeout: 60000 });
    ctx.check(true, '3b typing 4, 8, delete, 8, clear, 4, 8, 2, 9 on the pad signs in (delete and clear work)');
    await bctx.close();

    // ---- 4 the password still works on the same page, after the PIN was set
    ({ bctx, p, view } = await signInPage(ctx, browser));
    await p.fill('#login', LOGIN); await p.fill('#password', PASSWORD); await p.keyboard.press('Enter');
    await p.waitForSelector('.o_navbar', { timeout: 60000 });
    ctx.check(true, '4 user name and password still sign in');
    await bctx.close();

    // ---- 5 the system administrator is never offered a PIN
    const root = await new Session(ctx, browser, 'demo.sysadmin', 'demo', [1280, 800], { timeout: 20000 }).start();
    await root.page.locator('.o_user_menu').first().click();
    ctx.check(await root.page.getByRole('menuitem', { name: 'Sign-in PIN' }).count() === 0 && await root.page.getByRole('menuitem', { name: 'Log out' }).count() === 1, '5 the system administrator has no "Sign-in PIN" in the name menu');
    await root.close();

    // ---- 6 an administrator removes it: the way is closed, the password still works, and the log says what happened
    await admin.rpc('res.users', 'action_ei_pin_reset', [[uid]]);
    ctx.check(await state() === 'none', '6 an administrator can remove a PIN (never read or choose one)');
    ({ bctx, p, view } = await signInPage(ctx, browser));
    await p.locator('.ei-login-tab[data-mode=pin]').click();
    await p.locator('#ei_pin').pressSequentially(PIN);
    await p.waitForSelector('.alert-danger');
    ctx.check(/That did not work/.test(await p.locator('.alert-danger').innerText()), '6 the removed PIN no longer signs in');
    await bctx.close();
    const log = await admin.rpc('ei.pin.log', 'search_read', [[['user_id', '=', uid]], ['event', 'success', 'reason']]);
    const kinds = log.map(r => `${r.event}:${r.success ? 'ok' : 'no'}`);
    ctx.check(kinds.includes('set:ok') && kinds.includes('signin:ok') && kinds.includes('reset:ok'), '6 the log holds the set, the good sign-ins and the removal', kinds.join(' '));
    const refused = await admin.rpc('ei.pin.log', 'search_read', [[['pin_only', '=', true], ['success', '=', false]], ['reason', 'user_id', 'login']]);
    ctx.check(refused.length >= 2 && refused.every(r => !r.user_id && !r.login), '6 refused PIN-alone sign-ins are logged and nobody is blamed for them', JSON.stringify(refused.slice(0, 2)));
    ctx.check(!JSON.stringify(log).includes(PIN) && !JSON.stringify(log).includes('5083'), '6 the log never holds a PIN');

    // ---- 7 a phone
    ({ bctx, p, view } = await signInPage(ctx, browser, [390, 844]));
    await p.locator('.ei-login-tab[data-mode=pin]').click();
    const lay = await view.layout();
    ctx.check(!lay.overflow && !lay.wide.length, '7 the PIN tab fits a phone: no sideways scroll', JSON.stringify(lay));
    ctx.check((await p.locator('#ei_pin').boundingBox()).height >= 44, '7 the PIN field is a comfortable touch target');
    await ctx.shot(p, 'login_pin_phone');
    await bctx.close();
    await admin.close();
  },
};
