// Party 360: keyboard search, explain-this-number, drill-down, role limits, compact on a phone.
module.exports = {
  name: '04 Party 360',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    let s = await new Session(ctx, browser, 'demo.ceo', 'demo').start();
    let p = s.page, m = s.mark();
    await s.menu('Customers & Suppliers'); await p.waitForSelector('.ei-p360');
    ctx.check(await p.isVisible('.ei-p360-empty'), 'empty state explains what to type');
    await p.focus('#ei-p360-q'); await p.keyboard.type('Rehman'); await p.waitForSelector('.ei-p360-opt');
    ctx.check((await p.getAttribute('#ei-p360-q', 'aria-expanded')) === 'true', 'the result list is announced as open');
    await p.keyboard.press('ArrowDown'); await p.keyboard.press('ArrowUp'); await p.keyboard.press('Enter');
    await p.waitForSelector('.ei-p360-party');
    ctx.check(/Rehman/i.test(await p.innerText('.ei-p360-name')), 'Enter opens the chosen party');
    ctx.check(await p.locator('.ei-p360-kpi').count() >= 3 && await p.isVisible('.ei-p360-asof'), 'figures and the "read at" time are shown');
    const w360 = await s.wheelScroll('.ei-p360');
    ctx.check(w360.max > 300 && w360.top >= w360.max - 2 && w360.win === 0 && w360.scrollbarWidth !== 'none', 'Party 360: the mouse wheel takes a person to the end of the page, and its scrollbar is not hidden', JSON.stringify(w360));
    await p.evaluate(() => { document.querySelector('.ei-p360').scrollTop = 0; });
    const btn = p.locator('.ei-p360-kpi .ei-p360-link[aria-expanded]').first();
    await btn.click(); await p.waitForTimeout(300);
    ctx.check(await btn.getAttribute('aria-expanded') === 'true' && await p.isVisible('.ei-p360-explain'), '"How is this worked out?" opens the explanation');
    const show = p.locator('.ei-p360-link', { hasText: 'Show the records' }).first();
    await show.click(); await p.waitForTimeout(1800);
    await s.clean('"Show the records" opens the records for the CEO', m);
    ctx.check(await p.locator('.o_list_view, .o_kanban_view').count() > 0, 'a list of the counted records is shown');
    await ctx.shot(p, 'party360_ceo_desktop');
    await s.close();

    // ---- phone: compact, no horizontal overflow
    s = await new Session(ctx, browser, 'demo.ceo', 'demo', [390, 844]).start(); p = s.page; m = s.mark();
    await s.goto('/odoo/action-ei_party360.action_ei_party360'); await p.waitForSelector('.ei-p360');
    await p.focus('#ei-p360-q'); await p.keyboard.type('Rehman'); await p.waitForSelector('.ei-p360-opt'); await p.keyboard.press('Enter'); await p.waitForSelector('.ei-p360-party');
    await p.waitForTimeout(600);
    const h = await p.evaluate(() => document.querySelector('.ei-p360').scrollHeight);
    ctx.check(h < 3400, `the phone page is compact (${h}px tall; was 4900px)`, String(h));
    const lay = await s.layout();
    ctx.check(!lay.overflow && !lay.wide.length && !lay.clipped.length, 'phone: no horizontal overflow or clipped buttons', JSON.stringify(lay));
    await ctx.shot(p, 'party360_ceo_phone');
    await s.close();

    // ---- cash clerk: sections hidden are named, not shown as zero
    s = await new Session(ctx, browser, 'demo.cash', 'demo').start(); p = s.page;
    await s.menu('Customers & Suppliers'); await p.waitForSelector('.ei-p360');
    await p.focus('#ei-p360-q'); await p.keyboard.type('Rehman'); await p.waitForSelector('.ei-p360-opt'); await p.keyboard.press('Enter'); await p.waitForSelector('.ei-p360-party');
    ctx.check(await p.isVisible('.ei-p360-notice'), 'cash clerk is told which sections their role cannot see');
    ctx.check(!(await p.isVisible('.ei-p360-chains')), 'cash clerk does not see the contract-to-payment chains');
    await s.close();
  },
};
