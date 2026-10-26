// A button a person can see must be a button that person may press. For every demo role, every menu entry of the application is opened,
// and every "New" that is offered is pressed: it must open a form or a dialog, never an Access Error. (Found in the screenshot gallery:
// the CEO was offered New on eight card screens and every click ended in an Access Error. The cure was in the view, not in the access
// rules, which are unchanged: unit tests `test_visible_actions` prove who may create.)
const ROLES = [
  ['demo.ceo', 'executive'], ['demo.finance', 'finance manager'], ['demo.accountant', 'accountant'], ['demo.contractapprover', 'contract approver'],
  ['demo.contracts', 'contract maker'], ['demo.bank', 'bank data entry'], ['demo.cash', 'cash data entry'], ['demo.dispatch', 'logistics'], ['demo.sysadmin', 'administrator'],
];
const NEW = '.o_control_panel .o_list_button_add, .o_control_panel .o_form_button_create, .o_control_panel .o-kanban-button-new, .o_control_panel .o_pivot_add?';

module.exports = {
  name: '13 visible actions (every role, every menu entry, every New that is offered)',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    let pressedTotal = 0;
    for (const [login, label] of ROLES) {
      const s = await new Session(ctx, browser, login, 'demo', [1440, 900], { timeout: 30000 }).start();
      const p = s.page;
      const menus = await p.evaluate(async () => {
        const j = await (await fetch('/web/webclient/load_menus')).json();
        const out = []; const walk = (id, trail) => { const m = j[id]; if (!m) return; const t = id === 'root' ? [] : [...trail, m.name]; if (m.actionID && id !== 'root' && t[0] === 'Export International') out.push({ action: m.actionID, path: t.slice(1).join(' > ') }); for (const c of m.children || []) walk(c, t); };
        walk('root', []);
        const seen = new Set(); return out.filter(m => !seen.has(m.action) && seen.add(m.action));
      });
      let opened = 0, pressed = 0; const problems = [];
      for (const m of menus) {
        const before = s.mark();
        try {
          await p.goto(`${ctx.base}/odoo/action-${m.action}`);
          await p.waitForSelector('.o_action_manager .o_action, .modal .modal-content', { timeout: 20000 });
          await p.waitForTimeout(500);
          if (await p.locator('.modal .modal-content').count()) {            // a wizard opened as a dialog
            const t = (await p.locator('.modal .modal-content').first().innerText()).slice(0, 200);
            if (/Access Error|not allowed/i.test(t)) problems.push(`${m.path}: opening it shows "${t.replace(/\s+/g, ' ').slice(0, 80)}"`); else opened++;
            continue;
          }
          opened++;
          const add = p.locator(NEW.replace(', .o_control_panel .o_pivot_add?', '')).first();
          if (await add.count() && await add.isVisible()) {
            await add.click(); await p.waitForTimeout(900);
            pressed++;
            const dlg = await s.dialog();
            const opened_ok = await p.locator('.o_form_view .o_form_sheet, .modal .modal-content, .o_list_renderer .o_selected_row').count();   // a form, a dialog, or a new inline row
            if (dlg || /Access Error/i.test(await p.locator('.modal').allInnerTexts().then(a => a.join(' ')))) problems.push(`${m.path}: New leads to an error: ${dlg || 'Access Error'}`);
            else if (!opened_ok) problems.push(`${m.path}: New opened nothing`);
          }
          const errs = s.since(before).filter(e => !/favicon|Failed to load resource: the server responded with a status of 40[34]/.test(e.text));
          if (errs.length) problems.push(`${m.path}: ${errs[0].kind}: ${errs[0].text.slice(0, 80)}`);
        } catch (e) { problems.push(`${m.path}: ${String(e.message).split('\n')[0].slice(0, 80)}`); }
      }
      pressedTotal += pressed;
      ctx.check(!problems.length, `${label}: all ${menus.length} menu entries open and every offered New works (${opened} opened, ${pressed} New pressed)`, problems.slice(0, 4).join(' | '));
      await s.close();
    }
    ctx.check(pressedTotal >= 20, 'the audit really pressed New in many places', String(pressedTotal));
  },
};
