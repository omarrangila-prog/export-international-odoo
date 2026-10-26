// Every clickable thing on Home must lead somewhere real, and the My Work actions must change real data.
module.exports = {
  name: '03 Home: every click, My Work actions, search, theme',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const s = await new Session(ctx, browser, 'admin', 'admin').start();
    const p = s.page;
    const back = async () => { await s.home(); };
    const shown = async () => (await p.locator('.o_list_view, .o_kanban_view, .o_form_view, .modal, .ei-p360').count()) > 0;
    const closeModal = async () => { if (await p.locator('.modal').count()) { await p.keyboard.press('Escape'); await p.waitForTimeout(300); } };

    await s.home();
    // ---------- structure
    const text = await p.innerText('.ei-home');
    for (const h of ['AT A GLANCE', 'NEEDS ATTENTION', 'MY WORK TODAY', 'FROM CONTRACT TO PAYMENT', 'MONEY AND MATERIAL']) ctx.check(text.toUpperCase().includes(h), `Home has the "${h.toLowerCase()}" section`);
    ctx.check(await p.locator('.ei-top input[type=search]').count() === 1 && await p.locator('.ei-top .ei-fresh').count() === 1, 'compact header has search and "Updated" time');

    // ---------- every figure, alert, pipeline stage and launcher button opens real records
    const sweep = async (selector, label) => {
      const n = await p.locator(selector).count();
      ctx.check(n > 0, `${label}: ${n} found`);
      for (let i = 0; i < n; i++) {
        const name = (await p.locator(selector).nth(i).innerText()).split('\n').filter(Boolean).slice(0, 2).join(' / ').slice(0, 60);
        const m = s.mark();
        await p.locator(selector).nth(i).click(); await p.waitForTimeout(1300);
        const ok = await shown();
        await s.clean(`${label}: "${name}" opens` + (ok ? '' : ' - nothing shown'), m);
        await closeModal(); await back();
      }
    };
    await sweep('.ei-kpi', 'figure');
    await sweep('.ei-alert', 'alert');
    await sweep('.ei-stage', 'pipeline stage');
    {   // the starting points live in the header's New menu (a launcher at the foot of the page is gone for management roles)
      const n = await s.rpc('ei.home', 'get_data', ['14d']).then(d => d.quick.reduce((t, g) => t + g.items.length, 0));
      ctx.check(n > 0, `quick action: ${n} in the New menu`);
      for (let i = 0; i < n; i++) {
        const m = s.mark();
        await p.locator('.ei-newbtn').click(); await p.waitForSelector('.ei-newitem');
        const name = (await p.locator('.ei-newitem').nth(i).innerText()).split('\n')[0].slice(0, 50);
        await p.locator('.ei-newitem').nth(i).click(); await p.waitForTimeout(1300);
        const ok = await shown();
        await s.clean(`quick action: "${name}" opens` + (ok ? '' : ' - nothing shown'), m);
        await closeModal(); await back();
      }
    }

    // ---------- My Work: open
    {
      const m = s.mark();
      await p.locator('.ei-task .ei-btn-primary').first().click(); await p.waitForTimeout(1500);
      ctx.check(await p.locator('.o_form_view').count() > 0, 'My Work: the action button opens the record form'); await s.clean('My Work: opening a task is clean', m); await back();
    }
    // ---------- My Work: snooze -> disappears, appears under "Put aside", comes back
    {
      const before = await p.locator('.ei-task').count();
      const first = (await p.locator('.ei-task .ei-task-title').first().innerText()).trim();
      await p.locator('.ei-task .ei-more').first().click();
      await p.getByRole('menuitem', { name: /Put aside until tomorrow/ }).click(); await p.waitForTimeout(1200);
      const toast = await p.locator('.ei-toast').innerText().catch(() => '');
      ctx.check(/Put aside/.test(toast), 'snooze confirms with a message', toast);
      const titles = await p.locator('.ei-task .ei-task-title').allInnerTexts();
      ctx.check(!titles.map(t => t.trim()).includes(first), `snoozed task "${first}" left the list`);
      await p.getByRole('button', { name: /^Put aside/ }).click(); await p.waitForTimeout(1200);
      ctx.check((await p.locator('.ei-task .ei-task-title').allInnerTexts()).map(t => t.trim()).includes(first), 'it is listed under "Put aside"');
      await p.getByRole('button', { name: 'Bring back' }).first().click(); await p.waitForTimeout(1200);
      await p.getByRole('button', { name: /^All/ }).click(); await p.waitForTimeout(500);
      ctx.check((await p.locator('.ei-task .ei-task-title').allInnerTexts()).map(t => t.trim()).includes(first), 'bringing it back puts it on the list again');
      void before;
    }
    // ---------- keyboard only: open the row menu, move in it, open a dialog, stay inside it, come back
    {
      const more = p.locator('.ei-task .ei-more').first();
      await more.focus(); await p.keyboard.press('Enter'); await p.waitForTimeout(400);
      const role1 = await p.evaluate(() => document.activeElement && document.activeElement.getAttribute('role'));
      ctx.check(role1 === 'menuitem', 'keyboard: opening the row menu puts focus on its first item', String(role1));
      const first = await p.evaluate(() => document.activeElement.innerText);
      await p.keyboard.press('ArrowDown');
      const second = await p.evaluate(() => document.activeElement.innerText);
      ctx.check(first !== second, 'keyboard: arrow keys move between the menu items');
      await p.keyboard.press('Escape'); await p.waitForTimeout(300);
      ctx.check(await p.locator('.ei-menu').count() === 0, 'keyboard: Escape closes the menu');
      ctx.check(await p.evaluate(() => document.activeElement.classList.contains('ei-more')), 'keyboard: focus returns to the button that opened it');
      await p.keyboard.press('Enter'); await p.waitForTimeout(300);
      const esc = p.getByRole('menuitem', { name: /Escalate to management/ });
      if (await esc.count()) {
        await esc.focus(); await p.keyboard.press('Enter'); await p.waitForTimeout(500);
        ctx.check(await p.evaluate(() => document.activeElement && document.activeElement.tagName === 'TEXTAREA'), 'keyboard: a dialog opens with focus in its first field');
        const seen = new Set();
        for (let i = 0; i < 6; i++) { await p.keyboard.press('Tab'); seen.add(await p.evaluate(() => !!document.activeElement.closest('.ei-modal'))); }
        ctx.check([...seen].join() === 'true', 'keyboard: Tab stays inside the open dialog');
        await p.keyboard.press('Escape'); await p.waitForTimeout(400);
        ctx.check(await p.locator('.ei-modal').count() === 0, 'keyboard: Escape closes the dialog');
        ctx.check(await p.evaluate(() => document.activeElement.classList.contains('ei-more')), 'keyboard: focus goes back to the row menu button');
      } else { await p.keyboard.press('Escape'); ctx.skip('keyboard dialog check: no task can be escalated in this data'); }
    }
    // ---------- My Work: assign -> real Odoo activity for the chosen person
    {
      const row = p.locator('.ei-task', { hasText: 'Approve contract' }).first();
      if (await row.count()) {
        await row.locator('.ei-more').click(); await p.getByRole('menuitem', { name: /Assign to someone/ }).click(); await p.waitForTimeout(800);
        const options = await p.locator('.ei-modal select option').allInnerTexts();
        ctx.check(options.length > 0 && options.every(o => /DEMO|Administrator/.test(o)), 'assign dialog offers only people who may do this step', options.join(', '));
        await p.locator('.ei-modal textarea').fill('E2E: please check today');
        await p.locator('.ei-modal .ei-btn-primary').click(); await p.waitForTimeout(1500);
        ctx.check(/Assigned to/.test(await row.innerText()), 'the row now shows who it is assigned to');
        const acts = await s.rpc('mail.activity', 'search_count', [[['res_model', '=', 'ei.contract'], ['summary', 'ilike', 'Please handle']]]);
        ctx.check(acts >= 1, 'a real Odoo activity was created', String(acts));
      } else ctx.skip('assign: no contract waiting for approval in this data');
    }
    // ---------- My Work: escalate needs a reason, then notifies managers
    {
      const row = p.locator('.ei-task', { hasText: 'Approve delivery advice' }).first();
      if (await row.count()) {
        await row.locator('.ei-more').click(); await p.getByRole('menuitem', { name: /Escalate to management/ }).click(); await p.waitForTimeout(600);
        const refused = s.mark();
        await p.locator('.ei-modal textarea').fill('x'); await p.locator('.ei-modal .ei-btn-primary').click(); await p.waitForTimeout(1000);
        s.discard(refused);
        ctx.check(await p.locator('.ei-modal .ei-banner-bad').count() === 1, 'escalating without a real reason is refused with a message');
        await p.locator('.ei-modal textarea').fill('E2E: supplier is waiting at the gate'); await p.locator('.ei-modal .ei-btn-primary').click(); await p.waitForTimeout(1500);
        ctx.check(/Escalated/.test(await row.innerText()), 'the row shows an Escalated badge');
        const n = await s.rpc('mail.activity', 'search_count', [[['res_model', '=', 'ei.da'], ['summary', '=like', 'Escalated:%']]]);
        ctx.check(n >= 1, 'managers received a real reminder', String(n));
      } else ctx.skip('escalate: no delivery advice waiting for approval in this data');
    }

    // ---------- search: keyboard, grouping, permissions
    await back();
    await p.keyboard.press('/');
    ctx.check(await p.evaluate(() => document.activeElement && document.activeElement.id) === 'ei-search-q', 'pressing "/" focuses the search box');
    await p.keyboard.type('Rehman'); await p.waitForSelector('.ei-search-hit', { timeout: 8000 });
    ctx.check(await p.locator('.ei-search-group-label').count() >= 1, 'results are grouped under headings');
    ctx.check((await p.locator('.ei-search-hit-title mark').count()) >= 1, 'the typed text is highlighted in the results');
    await p.keyboard.press('Enter'); await p.waitForSelector('.ei-p360-party', { timeout: 15000 });
    ctx.check(/Rehman/i.test(await p.innerText('.ei-p360-name')), 'Enter opens the chosen party (Party 360)');
    await back();
    // results arrive after a short debounce: wait for the answer to THIS query, never read the previous one
    const answer = async (q, re) => {
      await p.locator('#ei-search-q').fill(q);
      // group headings are uppercased by CSS, so compare without case
      return p.waitForFunction(([r, f]) => new RegExp(r, f).test((document.querySelector('.ei-search-pop') || {}).innerText || ''), [re.source, 'i'], { timeout: 8000 }).then(() => true, () => false);
    };
    ctx.check(await answer('GP-DEMO-101', /Truck loadings/), 'a gate-pass number finds the truck loading');
    ctx.check(await answer('INV/26', /Customer invoices/), 'an invoice number finds the customer invoice');
    ctx.check(await answer('zzzzqq', /Nothing found/), 'a search with no match says so plainly');
    ctx.check(await answer('%%', /Nothing found/), 'typing % is searched literally, not as a wildcard');

    // ---------- Ctrl+K palette on any screen
    await s.menu('Orders & Trucks', 'Contracts');
    await p.keyboard.press('Control+k'); await p.waitForSelector('.o_command_palette', { timeout: 8000 });
    await p.keyboard.type('DA-DEMO-5501'); await p.waitForTimeout(1500);
    ctx.check(/Delivery advices: DA-DEMO-5501/.test(await p.locator('.o_command_palette').innerText()), 'Ctrl+K finds records from any screen');
    await p.keyboard.press('Enter'); await p.waitForTimeout(1500);
    ctx.check(/ei\.da/.test(p.url()), 'choosing a result opens that record', p.url());

    // ---------- permissions: a cash clerk finds no contracts or delivery advices
    const c = await new Session(ctx, browser, 'demo.cash', 'demo').start();
    await c.home(); await c.page.locator('#ei-search-q').fill('DA-DEMO'); await c.page.waitForTimeout(1500);
    const popText = await c.page.locator('.ei-search-pop').innerText();
    ctx.check(/Nothing found/.test(popText) && !/Delivery advices/.test(popText), 'search never returns records the user may not read (cash clerk, DAs)');
    await c.close();

    // ---------- theme: dark mode is real (colours change) and returns
    await back();
    const lightBg = await p.evaluate(() => getComputedStyle(document.querySelector('.ei-home')).backgroundColor);
    await p.locator('button[aria-label^="Switch to the dark"]').click(); await p.waitForSelector('.ei-home .ei-top', { timeout: 40000 }); await p.waitForTimeout(1200);
    const darkBg = await p.evaluate(() => getComputedStyle(document.querySelector('.ei-home')).backgroundColor);
    ctx.check(lightBg !== darkBg && /rgb\(14, 22, 38\)/.test(darkBg), 'dark theme changes the page colours', `${lightBg} -> ${darkBg}`);
    const navDark = await p.evaluate(() => getComputedStyle(document.body).backgroundColor);
    ctx.check(/rgb\(14, 22, 38\)/.test(navDark), 'dark theme reaches the whole app, not only Home', navDark);
    await p.locator('button[aria-label^="Switch to the light"]').click(); await p.waitForSelector('.ei-home .ei-top', { timeout: 40000 });
    ctx.check(await p.evaluate(() => getComputedStyle(document.querySelector('.ei-home')).backgroundColor) === lightBg, 'switching back restores the light theme');
    await s.clean('Home session had no console, page or server errors', 0);
    await s.close();
  },
};
