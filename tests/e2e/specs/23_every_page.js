// Every page, opened the way each person can reach it: for every demo role, every menu entry of the application is opened, the
// first record shown is opened, and every tab of that record is clicked. For the administrator (who sees every menu) every view of
// every screen (list, cards, pivot, graph, calendar, ...) is switched to as well. A page passes only when it shows no error
// dialog, no console or page error, no failed server call and no server error. Nothing is typed or saved; a menu entry that runs a
// one-off task (Setup > Load LC register from old codes) runs it, as a person clicking it would.
const ROLES = [
  ['admin', 'administrator (every menu, every view)', true, 'admin'], ['demo.sysadmin', 'system administrator'], ['demo.ceo', 'executive'], ['demo.finance', 'finance manager'], ['demo.accountant', 'accountant'],
  ['demo.contractapprover', 'contract approver'], ['demo.contracts', 'contract maker'], ['demo.bank', 'bank data entry'], ['demo.cash', 'cash data entry'],
  ['demo.dispatch', 'logistics'], ['demo.invoicing', 'invoicing'], ['demo.recon', 'reconciliation'], ['demo.trainer', 'daily-work trainer'],
];
const NOISE = /favicon|Failed to load resource: the server responded with a status of 40[34]/;

module.exports = {
  name: '23 every page (every role, every menu entry, its first record and tabs; every view for the administrator)',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    let total = 0;
    for (const [login, label, allViews, pass] of ROLES) {
      let s;
      try { s = await new Session(ctx, browser, login, pass || 'demo', [1440, 900], { timeout: 20000 }).start(); }
      catch (e) { ctx.check(false, `${label}: signs in`, String(e.message).split('\n')[0].slice(0, 120)); continue; }
      const p = s.page;
      const menus = await p.evaluate(async () => {
        const j = await (await fetch('/web/webclient/load_menus')).json();
        const out = []; const walk = (id, trail) => { const m = j[id]; if (!m) return; const t = id === 'root' ? [] : [...trail, m.name]; if (m.actionID && id !== 'root' && t[0] === 'Export International') out.push({ action: m.actionID, path: t.slice(1).join(' > ') }); for (const c of m.children || []) walk(c, t); };
        walk('root', []);
        const seen = new Set(); return out.filter(m => !seen.has(m.action) && seen.add(m.action));
      });
      const problems = []; let pages = 0, records = 0, views = 0, tabs = 0;
      const note = async (where, since) => {
        const dlg = await s.dialog();
        const errs = s.since(since).filter(e => !NOISE.test(e.text));
        if (dlg) problems.push(`${where}: ${dlg}`);
        else if (errs.length) problems.push(`${where}: ${errs[0].kind}: ${errs[0].text.slice(0, 100)}`);
        if (dlg) { await p.keyboard.press('Escape').catch(() => {}); }
      };
      for (const m of menus) {
        let mark = s.mark();
        try {
          await p.goto(`${ctx.base}/odoo/action-${m.action}`);
          await p.waitForSelector('.o_action_manager .o_action, .modal .modal-content', { timeout: 20000 });
          await p.waitForTimeout(700); pages++;
          await note(m.path, mark);
          if (await p.locator('.modal .modal-content').count()) continue;            // a wizard: opening it is the page
          if (allViews) {
            const sw = await p.locator('.o_control_panel .o_switch_view:visible').evaluateAll(bs => bs.map(b => [...b.classList].find(c => /^o_(list|kanban|pivot|graph|calendar|activity|form|map|gantt|hierarchy)$/.test(c))).filter(Boolean));
            for (const v of sw) {
              mark = s.mark();
              await p.locator(`.o_control_panel .o_switch_view.${v}`).first().click();
              await p.waitForTimeout(1100); views++;
              await note(`${m.path} [${v.slice(2)} view]`, mark);
            }
            if (sw.length) { await p.goto(`${ctx.base}/odoo/action-${m.action}`); await p.waitForSelector('.o_action_manager .o_action', { timeout: 20000 }); await p.waitForTimeout(600); }
          }
          const row = p.locator('.o_list_renderer .o_data_row:visible, .o_kanban_renderer .o_kanban_record:not(.o_kanban_ghost):visible').first();
          if (await row.count()) {
            mark = s.mark();
            const isList = await p.locator('.o_list_renderer .o_data_row:visible').count();
            const target = isList ? row.locator('td.o_data_cell:not(.o_list_record_selector):not(.o_list_button)').first() : row;
            await target.click(); await p.waitForTimeout(1300);
            const form = await p.locator('.o_form_view').count();
            if (form) {
              records++;
              await note(`${m.path} > first record`, mark);
              const tabsHere = p.locator('.o_form_view .o_notebook .nav-link:visible');
              const n = await tabsHere.count();
              for (let i = 0; i < n; i++) { mark = s.mark(); await tabsHere.nth(i).click(); await p.waitForTimeout(450); tabs++; await note(`${m.path} > first record > tab ${i + 1}`, mark); }
              if (await p.locator('.o_form_view .o_form_status_indicator_buttons .o_form_button_cancel:visible').count()) await p.locator('.o_form_button_cancel:visible').first().click();
            } else {
              await note(`${m.path} > first row`, mark);
            }
          }
        } catch (e) { problems.push(`${m.path}: ${String(e.message).split('\n')[0].slice(0, 100)}`); }
      }
      total += pages + records + views + tabs;
      ctx.check(!problems.length, `${label}: ${pages} pages, ${records} records, ${tabs} tabs${allViews ? `, ${views} other views` : ''} open with no error`,
        problems.slice(0, 5).join(' | '));
      if (problems.length > 5) console.log('    more:', problems.slice(5).join(' | '));
      await s.close();
    }
    ctx.check(total >= 300, 'the walk really opened many pages', String(total));
  },
};
