// Six widths x key screens x light/dark: no horizontal overflow, nothing clipped, no console/server errors, and
// automated accessibility (axe, WCAG 2 A/AA) with zero serious or critical findings on our own screens.
const { VIEWPORTS } = require('../lib');

const SCREENS = [
  { key: 'Home', url: '/odoo', wait: '.ei-home .ei-top', own: '.ei-home', dark: true },
  { key: 'Contracts (cards)', url: '/odoo/action-ei_contract_da.ei_contract_action', wait: '.o_kanban_view, .o_list_view', dark: true },
  { key: 'Bank payments to check (list)', url: '/odoo/action-ei_bank_operations.ei_bank_line_action', wait: '.o_list_view', dark: true },
  { key: 'Ask', url: '/odoo/action-ei_assistant.action_ei_assistant', wait: '.ei-ask .ei-ask-welcome', own: '.ei-ask', dark: true },
  { key: 'Reports', url: '/odoo/action-ei_reports.action_report_catalog', wait: '.ei-rc-card', own: '.ei-rc', dark: true },
  { key: 'Aged receivables (list)', url: '/odoo/action-ei_reports.action_report_ar_aging', wait: '.o_graph_view, .o_pivot, .o_list_view' },
  { key: 'Match bank payments', url: '/odoo/action-ei_matching.action_ei_matching', wait: '.ei-mt .ei-mt-cols', own: '.ei-mt', dark: true },
  { key: 'Parent statements (cards)', url: '/odoo/action-ei_parent_reconciliation.ei_parent_statement_action', wait: '.o_kanban_view, .o_list_view' },
  { key: 'Cash vouchers (cards)', url: '/odoo/action-ei_cashbook.ei_cash_voucher_action', wait: '.o_kanban_view, .o_list_view' },
];

module.exports = {
  name: '05 responsive layout and accessibility (6 widths, light + dark)',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    for (const scheme of ['light', 'dark']) {
      const cookies = [{ name: 'color_scheme', value: scheme, path: '/' }];
      const s = await new Session(ctx, browser, 'admin', 'admin', [1440, 900], { cookies, timeout: 20000 }).start();
      const p = s.page;
      ctx.check(!(await s.cssErrors()).length, `${scheme}: every stylesheet bundle compiles (no "css error")`, (await s.cssErrors()).join(' | '));
      const screens = scheme === 'dark' ? SCREENS.filter(sc => sc.dark) : SCREENS;
      for (const sc of screens) {
        for (const [w, h] of VIEWPORTS) {
          if (scheme === 'dark' && ![375, 1024, 1920].includes(w)) continue;
          await p.setViewportSize({ width: w, height: h });
          const m = s.mark();
          await s.goto(sc.url); await p.waitForSelector(sc.wait, { timeout: 25000 }).catch(() => {}); await p.waitForTimeout(900);
          const lay = await s.layout();
          const tag = `${scheme} ${w}px ${sc.key}`;
          ctx.check(!lay.overflow && !lay.wide.length, `${tag}: no horizontal overflow`, JSON.stringify(lay.wide));
          ctx.check(!lay.clipped.length, `${tag}: no clipped buttons or badges`, lay.clipped.join(' | '));
          await s.clean(`${tag}: no console or server errors`, m);
          if ((scheme === 'light' && (w === 1440 || w === 390)) || (scheme === 'dark' && (w === 1920 || w === 375))) await ctx.shot(p, `resp_${scheme}_${w}_${sc.key.replace(/\W+/g, '_')}`);
          if (sc.own && [375, 1440].includes(w)) {
            const v = await s.axe(sc.own);
            const bad = (v || []).filter(x => ['serious', 'critical'].includes(x.impact));
            ctx.check(v !== null && !bad.length, `${tag}: no serious accessibility findings (axe)`, bad.map(x => `${x.id}(${x.n}): ${x.first}`).join(' | '));
          }
        }
      }
      await s.close();
    }
  },
};
