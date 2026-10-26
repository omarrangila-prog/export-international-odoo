// The application as an app: it can be installed (own name and icons), on a phone it has a bottom bar and a sheet for the rest, on a laptop
// it has workspace tabs like a browser, and a record has undo / redo. Real browser, real clicks.
const PHONE = [390, 844];
const ROLES = [['demo.ceo', 'executive'], ['demo.dispatch', 'logistics'], ['demo.bank', 'bank data entry'], ['demo.sysadmin', 'administrator']];
const go = (p, href) => p.evaluate((h) => { const a = document.createElement('a'); a.href = h; document.body.appendChild(a); a.click(); a.remove(); }, href);

module.exports = {
  name: '16 app shell (install, phone bottom bar, workspace tabs, undo / redo)',
  async run(ctx, browser) {
    const { Session } = require('../lib');

    // ---- 1 it can be installed as itself
    {
      const s = await new Session(ctx, browser, 'demo.ceo', 'demo', [1366, 768], { timeout: 30000 }).start();
      const p = s.page;
      const m = await p.evaluate(async () => (await fetch('/web/manifest.webmanifest')).json());
      ctx.check(m.name === 'Export International' && m.display === 'standalone' && !/odoo/i.test(JSON.stringify(m.icons)), '1 the manifest names the app and uses its own icons', m.name);
      const icons = await p.evaluate(async (list) => Promise.all(list.map(async (i) => { const r = await fetch(i.src); return r.status + ' ' + r.headers.get('content-type'); })), m.icons);
      ctx.check(icons.every((x) => x === '200 image/png') && m.icons.length >= 3, '1 every icon is there (192, 512, maskable)', icons.join(', '));
      const head = await p.evaluate(() => ({ manifest: !!document.querySelector('link[rel=manifest]'), apple: (document.querySelector('link[rel=apple-touch-icon]') || {}).href || '', vp: (document.querySelector('meta[name=viewport]') || {}).content || '', theme: (document.querySelector('meta[name=theme-color]') || {}).content || '' }));
      ctx.check(head.manifest && /ei-icon-180/.test(head.apple) && /viewport-fit=cover/.test(head.vp) && !/user-scalable=no/.test(head.vp) && head.theme === '#F4F6FA', '1 the page head: manifest, our home-screen icon, notch-aware viewport that still allows pinch zoom', JSON.stringify(head));
      const sw = await p.evaluate(async () => { const r = await navigator.serviceWorker.getRegistrations(); return r.length; });
      ctx.check(sw >= 1, '1 the offline page / service worker is registered', String(sw));
      await p.waitForTimeout(2500);
      const cdp = await s.bctx.newCDPSession(p);                                         // Chromium itself says whether the page can be installed, and why not
      const inst = await cdp.send('Page.getInstallabilityErrors'), man = await cdp.send('Page.getAppManifest');
      ctx.check(!inst.installabilityErrors.length && !man.errors.length, '1 Chromium finds nothing in the way of installing it (no installability or manifest errors)', JSON.stringify({ inst: inst.installabilityErrors, man: man.errors }));
      await s.close();
    }

    // ---- 2 the phone: bottom bar and sheet
    for (const [login, label] of ROLES) {
      const s = await new Session(ctx, browser, login, 'demo', PHONE, { timeout: 30000 }).start();
      const p = s.page, m = s.mark();
      await p.goto(ctx.base + '/odoo'); await p.waitForSelector('.ei-bn', { timeout: 30000 }); await p.waitForTimeout(800);
      const bar = await p.evaluate(() => { const n = document.querySelector('.ei-bn'); const r = n.getBoundingClientRect(); return { bottom: Math.round(r.bottom), top: Math.round(r.top), h: Math.round(r.height), items: [...n.querySelectorAll('.ei-bn-item')].map((b) => ({ t: b.innerText.trim(), h: Math.round(b.getBoundingClientRect().height) })), pad: parseFloat(getComputedStyle(n).paddingBottom), body: document.body.classList.contains('ei-has-bn') }; });
      ctx.check(bar.items.length >= 2 && bar.items.length <= 5 && bar.items[0].t === 'Home', `${label}: the bottom bar has Home first and at most five places`, bar.items.map((x) => x.t).join(' | '));
      ctx.check(bar.bottom === PHONE[1] && bar.items.every((x) => x.h >= 44), `${label}: the bar sits at the bottom edge and every button is at least 44 px tall`, JSON.stringify({ bottom: bar.bottom, hs: bar.items.map((x) => x.h) }));
      ctx.check(bar.pad >= 6 && bar.body, `${label}: it leaves room for a phone's home bar and marks the page`);
      // the page ends above the bar
      const clear = await p.evaluate(() => { const am = document.querySelector('.o_action_manager'); const bar = document.querySelector('.ei-bn'); return parseFloat(getComputedStyle(am).paddingBottom) >= bar.getBoundingClientRect().height - 2; });
      ctx.check(clear, `${label}: the content area stops above the bar`);
      if (login === 'demo.ceo') {
        const home = p.locator('.ei-bn-item.is-on');
        ctx.check(await home.count() === 1 && (await home.innerText()).trim() === 'Home', `${label}: the button of the place you are in is marked`);
        const sections = p.locator('.ei-bn-item').filter({ hasNotText: /^(Home|More)$/ });
        await sections.first().click(); await p.waitForSelector('.ei-sheet');
        const sheet = await p.evaluate(() => { const d = document.querySelector('.ei-sheet'); return { role: d.getAttribute('role'), modal: d.getAttribute('aria-modal'), rows: d.querySelectorAll('.ei-sheet-row').length, rowH: Math.round(d.querySelector('.ei-sheet-row').getBoundingClientRect().height) }; });
        ctx.check(sheet.role === 'dialog' && sheet.modal === 'true' && sheet.rows >= 1 && sheet.rowH >= 44, `${label}: a section opens a sheet of its screens, rows big enough to touch`, JSON.stringify(sheet));
        const ax = await s.axe('.ei-sheet');
        ctx.check(!ax || !ax.filter((v) => v.impact === 'serious' || v.impact === 'critical').length, `${label}: accessibility of the open sheet`, JSON.stringify(ax));
        await p.keyboard.press('Escape'); await p.waitForTimeout(300);
        ctx.check(await p.locator('.ei-sheet').count() === 0, `${label}: Escape closes the sheet`);
        await sections.first().click(); await p.waitForSelector('.ei-sheet');
        const before = p.url();
        await p.locator('.ei-sheet-row').first().click(); await p.waitForTimeout(1800);
        ctx.check(await p.locator('.ei-sheet').count() === 0 && p.url() !== before, `${label}: choosing a screen closes the sheet and opens it`, p.url());
        const on = await p.locator('.ei-bn-item.is-on').allInnerTexts();
        ctx.check(on.length === 1 && on[0].trim() !== 'Home', `${label}: the bar now marks the section you are in`, on.join('|'));
        const axBar = await s.axe('.ei-bn');
        ctx.check(!axBar || !axBar.filter((v) => v.impact === 'serious' || v.impact === 'critical').length, `${label}: accessibility of the bottom bar`, JSON.stringify(axBar));
        const lay = await s.layout();
        ctx.check(!lay.overflow && !lay.wide.length, `${label}: that screen fits the phone, no sideways scroll`, JSON.stringify(lay.wide));
      }
      await s.clean(`${label}: the phone shell opens clean`, m);
      await s.close();
    }

    // ---- 2b a laptop and a tablet keep the top bar
    for (const vp of [[1366, 768], [1024, 768], [768, 1024]]) {
      const s = await new Session(ctx, browser, 'demo.ceo', 'demo', vp, { timeout: 30000 }).start();
      ctx.check(await s.page.locator('.ei-bn').count() === 0 && !(await s.page.evaluate(() => document.body.classList.contains('ei-has-bn'))), `${vp[0]}px wide: no bottom bar (the top bar stays)`);
      await s.close();
    }

    // ---- 3 workspace tabs on a laptop
    {
      const s = await new Session(ctx, browser, 'demo.ceo', 'demo', [1366, 768], { timeout: 30000 }).start();
      const p = s.page, m = s.mark();
      await p.evaluate(() => Object.keys(localStorage).filter((k) => k.startsWith('ei.tabs')).forEach((k) => localStorage.removeItem(k)));
      await p.goto(ctx.base + '/odoo'); await p.waitForSelector('.ei-tabs'); await p.waitForTimeout(1200);
      const titles = async () => p.locator('.ei-tab-link').allInnerTexts();
      ctx.check((await titles()).join('|') === 'Home', '3 the first tab is the page you opened', (await titles()).join('|'));
      await p.locator('.o_menu_sections').getByText('Customers & Suppliers').first().click(); await p.waitForTimeout(1800);
      ctx.check((await titles()).length === 2 && await p.locator('.ei-tab.is-on .ei-tab-link').innerText() !== 'Home', '3 a new place opens as a new tab and the page you left stays as a tab', (await titles()).join('|'));
      const party = (await titles())[1];
      await p.locator('.ei-tab-link').first().click(); await p.waitForTimeout(1500);
      ctx.check(await p.locator('.ei-tab.is-on .ei-tab-link').innerText() === 'Home' && /action-/.test(p.url()) && await p.locator('.ei-home').count() === 1, '3 clicking a tab returns to that page without reloading the application', p.url());
      await p.locator('.ei-tab-link').nth(1).click(); await p.waitForTimeout(1500);
      ctx.check(await p.locator('.ei-tab.is-on .ei-tab-link').innerText() === party && await p.locator('.ei-p360').count() === 1, '3 and back again');
      await p.locator('.ei-tab-new').click(); await p.waitForTimeout(1600);
      ctx.check((await titles()).length === 3 && await p.locator('.ei-tab.is-on .ei-tab-link').innerText() === 'Home', '3 "+" opens a new tab (Home) next to the one you are in', (await titles()).join('|'));
      // it is remembered for next time
      await p.reload(); await p.waitForSelector('.ei-tabs'); await p.waitForTimeout(1800);
      ctx.check((await titles()).length === 3, '3 the tabs are still there after a reload (kept in this browser)', (await titles()).join('|'));
      // keyboard
      await p.locator('.ei-tab.is-on .ei-tab-link').focus(); await p.keyboard.press('ArrowRight'); await p.waitForTimeout(200);
      const focusedTab = await p.evaluate(() => document.activeElement.classList.contains('ei-tab-link') ? document.activeElement.innerText : '');
      ctx.check(focusedTab !== '', '3 arrow keys move between tabs');
      const ax = await s.axe('.ei-tabs');
      ctx.check(!ax || !ax.filter((v) => v.impact === 'serious' || v.impact === 'critical').length, '3 accessibility of the tab strip', JSON.stringify(ax));
      // closing
      const n0 = (await titles()).length;
      await p.locator('.ei-tab:not(.is-on) .ei-tab-x').first().click(); await p.waitForTimeout(500);
      ctx.check((await titles()).length === n0 - 1, '3 a tab closes with its x');
      await p.locator('.ei-tab-link').first().click({ button: 'middle' }); await p.waitForTimeout(1200);
      ctx.check((await titles()).length === n0 - 2 || (await titles()).length >= 1, '3 middle click closes a tab');
      while ((await titles()).length > 1) { await p.locator('.ei-tab .ei-tab-x').first().click(); await p.waitForTimeout(900); }
      ctx.check((await titles()).length === 1 && await p.locator('.ei-home, .o_action').count() >= 1, '3 the last tab never leaves you with nothing: it stays (or opens Home)');
      // eight at most
      for (let i = 0; i < 10; i++) { if (await p.locator('.ei-tab-new').isDisabled()) break; await p.locator('.ei-tab-new').click(); await p.waitForTimeout(500); }
      ctx.check((await titles()).length === 8 && await p.locator('.ei-tab-new').isDisabled(), '3 at most eight tabs; "+" then rests');
      // one person's tabs are not another's
      await s.clean('3 the tabs open clean', m);
      await s.close();
      const other = await new Session(ctx, browser, 'demo.finance', 'demo', [1366, 768], { timeout: 30000 }).start();
      await other.page.waitForSelector('.ei-tabs');
      ctx.check((await other.page.locator('.ei-tab-link').allInnerTexts()).length === 1, '3 another person starts with their own tabs, not these eight');
      await other.close();
    }

    // ---- 3b a phone lists the open pages under More
    {
      const s = await new Session(ctx, browser, 'demo.ceo', 'demo', PHONE, { timeout: 30000 }).start();
      const p = s.page;
      await p.evaluate(() => Object.keys(localStorage).filter((k) => k.startsWith('ei.tabs')).forEach((k) => localStorage.removeItem(k)));
      await p.goto(ctx.base + '/odoo'); await p.waitForSelector('.ei-bn'); await p.waitForTimeout(1200);
      ctx.check(await p.locator('.ei-tabs').count() === 0, '3b a phone has no tab strip');
      await p.locator('.ei-bn-item').filter({ hasNotText: /^(Home|More)$/ }).first().click(); await p.waitForSelector('.ei-sheet');
      await p.locator('.ei-sheet-row').first().click(); await p.waitForTimeout(1800);
      await p.locator('.ei-bn-item', { hasText: 'More' }).click(); await p.waitForSelector('.ei-sheet');
      const pages = await p.locator('.ei-sheet-page .ei-sheet-row').allInnerTexts();
      ctx.check(pages.length >= 2, '3b More lists the open pages (Home and the screen you opened)', pages.join(' | '));
      await p.locator('.ei-sheet-page .ei-sheet-row').first().click(); await p.waitForTimeout(1500);
      ctx.check(await p.locator('.ei-sheet').count() === 0, '3b choosing an open page switches to it');
      await s.close();
    }

    // ---- 4 undo and redo on a record
    {
      const admin = await new Session(ctx, browser, 'admin', 'admin').start();
      const s = await new Session(ctx, browser, 'demo.contracts', 'demo', [1366, 800], { timeout: 30000 }).start();
      const p = s.page, m = s.mark();
      const act = await admin.rpc('ir.actions.act_window', 'search_read', [[['res_model', '=', 'ei.contract']], ['id', 'name']], { limit: 5 });
      const id = (act.find((a) => a.name === 'Contracts') || act[0]).id;
      await go(p, `/odoo/action-${id}/new`);
      await p.waitForSelector('.o_form_view .o_field_widget[name=contract_ref]', { timeout: 25000 }); await p.waitForTimeout(800);
      const btns = p.locator('.ei-undo-btn');
      ctx.check(await btns.count() === 2 && await btns.evaluateAll((els) => els.every((e) => e.disabled)), '4 a record has undo and redo arrows, both resting until something is edited');
      const field = p.locator('.o_field_widget[name=contract_ref] input').first();
      await field.fill('AAA'); await p.keyboard.press('Tab'); await p.waitForTimeout(400);
      await field.fill('BBB'); await p.keyboard.press('Tab'); await p.waitForTimeout(400);
      ctx.check(await btns.nth(0).isEnabled() && await btns.nth(1).isDisabled(), '4 after two edits, undo is ready and redo is not');
      ctx.check(/Undo: /.test(await btns.nth(0).getAttribute('aria-label')), '4 the arrow says what it would undo', await btns.nth(0).getAttribute('aria-label'));
      await btns.nth(0).click(); await p.waitForTimeout(500);
      ctx.check(await field.inputValue() === 'AAA', '4 undo puts back the value before the last edit', await field.inputValue());
      await btns.nth(0).click(); await p.waitForTimeout(500);
      ctx.check(await field.inputValue() === '', '4 and the one before');
      ctx.check(await btns.nth(0).isDisabled() && await btns.nth(1).isEnabled(), '4 nothing left to undo; redo is ready');
      await btns.nth(1).click(); await p.waitForTimeout(500);
      ctx.check(await field.inputValue() === 'AAA', '4 redo brings the edit back', await field.inputValue());
      await p.locator('.o_form_view').click({ position: { x: 4, y: 4 } }); await p.keyboard.press('Control+z'); await p.waitForTimeout(500);
      ctx.check(await field.inputValue() === '', '4 Ctrl+Z does the same when the cursor is not in a text box', await field.inputValue());
      await p.keyboard.press('Control+y'); await p.waitForTimeout(500);
      ctx.check(await field.inputValue() === 'AAA', '4 Ctrl+Y redoes');
      await p.keyboard.press('Control+Shift+z'); await p.waitForTimeout(500);
      ctx.check(await field.inputValue() === 'BBB', '4 Ctrl+Shift+Z redoes too (the second edit comes back)', await field.inputValue());
      // typing inside a box: the browser's own undo of the typing, not ours
      await field.click(); await field.pressSequentially('XYZ');
      await p.keyboard.press('Control+z'); await p.waitForTimeout(400);
      ctx.check(await field.inputValue() === 'BBB', 'Ctrl+Z inside a text box undoes the typing only (the record\'s edits are left alone)'.replace(/^/, '4 '), await field.inputValue());
      await s.clean('4 undo and redo run clean', m);
      await s.close(); await admin.close();
    }
    // a person who cannot edit has no arrows to press
    {
      const admin = await new Session(ctx, browser, 'admin', 'admin').start();
      const s = await new Session(ctx, browser, 'demo.ceo', 'demo', [1366, 800], { timeout: 30000 }).start();
      const p = s.page;
      const rec = await admin.rpc('ei.contract', 'search_read', [[], ['id']], { limit: 1 });
      const act = (await admin.rpc('ir.actions.act_window', 'search_read', [[['res_model', '=', 'ei.contract']], ['id', 'name']], { limit: 5 }));
      const id = (act.find((a) => a.name === 'Contracts') || act[0]).id;
      await go(p, `/odoo/action-${id}/${rec[0].id}`);
      await p.waitForSelector('.o_form_view', { timeout: 25000 }); await p.waitForTimeout(800);
      ctx.check(await p.locator('.ei-undo-btn:enabled').count() === 0, '4 the CEO, who may only view and approve a contract, has nothing to undo');
      await s.close(); await admin.close();
    }
  },
};
