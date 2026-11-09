// A typed amount must be visible. Odoo lays the currency label over a money input; the theme's boxed-input background once
// covered it, so every amount typed (cash voucher, cash count, supplier invoice total) looked empty (found 9 Nov 2026).
module.exports = {
  name: '22 money fields show what is typed (light and dark)',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    for (const dark of [false, true]) {
      const s = await new Session(ctx, browser, 'demo.cash', 'demo', [1440, 900], dark ? { cookies: [{ name: 'color_scheme', value: 'dark', path: '/' }] } : {}).start();
      const p = s.page; const m = s.mark(); const tag = dark ? 'dark' : 'light';
      const admin = await new Session(ctx, browser, 'admin', 'admin').start();
      const act = (await admin.rpc('ir.model.data', 'search_read', [[['module', '=', 'ei_cashbook'], ['name', '=like', '%voucher_action%']], ['res_id']]))[0];
      await admin.close();
      await s.goto(`/odoo/action-${act.res_id}/new`); await p.waitForSelector('.o_form_view', { timeout: 20000 });
      const box = p.locator('.o_field_widget[name="amount"]');
      await box.locator('input').click(); await box.locator('input').fill('1850'); await p.keyboard.press('Tab'); await p.waitForTimeout(500);
      const st = await box.evaluate((e) => {
        const ov = e.querySelector('.o_input.position-absolute'); const inp = e.querySelector('input'); const r = inp.getBoundingClientRect();
        const hit = document.elementFromPoint(r.right - 20, r.top + r.height / 2);
        return { overlay: ov ? getComputedStyle(ov).backgroundColor : 'none', value: inp.value, inputOnTop: hit === inp || inp.contains(hit) || (ov && getComputedStyle(ov).backgroundColor === 'rgba(0, 0, 0, 0)') };
      });
      ctx.check(st.value.replace(/,/g, '').startsWith('1850') && (st.overlay === 'none' || st.overlay === 'rgba(0, 0, 0, 0)'), `${tag}: the amount typed on a cash voucher is visible (the currency layer is see-through)`, JSON.stringify(st));
      await s.clean(`${tag}: the voucher form is clean`, m);
      await s.close();
    }
  },
};
