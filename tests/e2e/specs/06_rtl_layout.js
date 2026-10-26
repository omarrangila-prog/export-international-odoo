// Right-to-left layout. Odoo ships no Urdu, so the layout is proven with Arabic (also right-to-left and also loaded by Odoo's own
// language wizard). What this checks is the LAYOUT: direction flips, nothing overflows or clips, search and menus still work.
// Urdu text is a separate piece of work (see docs/urdu_plan.md); the same layout carries it.
module.exports = {
  name: '06 right-to-left layout (Arabic stands in for Urdu)',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const admin = await new Session(ctx, browser, 'admin', 'admin').start();
    const LANG = 'ar_001';
    const row = (await admin.rpc('res.lang', 'search_read', [[['code', '=', LANG]], ['active']], { context: { active_test: false } }))[0];
    if (!row) { ctx.skip('Arabic is not available in this Odoo build'); await admin.close(); return; }
    if (!row.active) {
      const id = await admin.rpc('base.language.install', 'create', [{ lang_ids: [[6, 0, [row.id]]] }]);
      await admin.rpc('base.language.install', 'lang_install', [[id]]);
    }
    const ceo = (await admin.rpc('res.users', 'search_read', [[['login', '=', 'demo.ceo']], ['id']]))[0].id;
    await admin.rpc('res.users', 'write', [[ceo], { lang: LANG }]);
    try {
      for (const [w, h] of [[375, 812], [1440, 900]]) {
        const s = await new Session(ctx, browser, 'demo.ceo', 'demo', [w, h], { timeout: 25000 }).start();
        const p = s.page, m = s.mark();
        await p.goto(ctx.base + '/odoo'); await p.waitForSelector('.ei-home .ei-top', { timeout: 40000 }); await p.waitForTimeout(800);
        // Odoo applies the direction to the body, not as an attribute on <html>
        ctx.check(await p.evaluate(() => getComputedStyle(document.body).direction === 'rtl'), `${w}px: the page direction is right-to-left`);
        const x = await p.evaluate(() => { const r = document.createRange(); r.selectNodeContents(document.querySelector('.ei-top-title')); const t = r.getBoundingClientRect(); return t.left + t.width / 2; });
        ctx.check(x > w / 2, `${w}px: the company title text sits on the right`, String(x));
        const lay = await s.layout();
        ctx.check(!lay.overflow && !lay.wide.length, `${w}px: no horizontal overflow in right-to-left`, JSON.stringify(lay.wide));
        ctx.check(!lay.clipped.length, `${w}px: no clipped buttons or badges in right-to-left`, lay.clipped.join(' | '));
        const kp = await p.locator('.ei-sum, .ei-kpi').first().evaluate(el => parseFloat(getComputedStyle(el).borderTopLeftRadius));
        ctx.check(kp >= 16, `${w}px: figures keep their card styling`, String(kp));
        await p.locator('#ei-search-q').fill('DA-DEMO'); await p.waitForSelector('.ei-search-hit', { timeout: 10000 });
        ctx.check(await p.locator('.ei-search-pop').isVisible(), `${w}px: search results still open`);
        await s.clean(`${w}px: right-to-left Home has no console or server errors`, m);
        await ctx.shot(p, `rtl_home_${w}`);
        // Party 360 too
        await s.goto('/odoo/action-ei_party360.action_ei_party360'); await p.waitForSelector('.ei-p360');
        const lay2 = await s.layout();
        ctx.check(!lay2.overflow && !lay2.wide.length, `${w}px: Party 360 has no horizontal overflow in right-to-left`, JSON.stringify(lay2.wide));
        await s.close();
      }
    } finally {
      await admin.rpc('res.users', 'write', [[ceo], { lang: 'en_US' }]);   // leave the data as it was
      await admin.close();
    }
  },
};
