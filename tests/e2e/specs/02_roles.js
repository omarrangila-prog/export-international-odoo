// Role-specific Home pages. Each persona logs in the way a person would; the checks say what must be there AND what
// must NOT be there (least privilege). The CEO case is the regression for the access error found on 25 Oct 2026.
const ROLES = [
  { key: 'CEO / executive', login: 'demo.ceo', profile: 'executive', role: 'Executive view',
    kpis: ['Bank balances', 'Customers owe us', 'We owe suppliers', 'Collected today', 'Bank money to match', 'Cash in hand', 'Expected gross spread', 'Differences with parent companies'],
    sections: ['Needs attention', 'Money and material', 'From contract to payment'], money: true, drill: true },
  { key: 'Finance manager', login: 'demo.finance', profile: 'finance', role: 'Finance manager',
    kpis: ['Bank balances', 'Customers owe us', 'We owe suppliers', 'Collected today', 'Bank money to match', 'Cash in hand'], absent: ['Expected gross spread'], money: true, drill: true },
  { key: 'Accountant', login: 'demo.accountant', profile: 'accountant', role: 'Accountant', kpis: ['Customers owe us', 'We owe suppliers'], absent: ['Expected gross spread'], money: true, drill: true },
  { key: 'Contract operator', login: 'demo.contractapprover', profile: 'contract', role: 'Contract desk',
    kpis: ['Active contracts', 'Delivery advices to approve', 'Still to lift', 'Open daily orders'], absent: ['Customers owe us', 'Bank balances', 'Cash in hand', 'Expected gross spread', 'Invoiced and received'], money: false },
  { key: 'Data entry (bank)', login: 'demo.bank', profile: 'data_entry', role: 'Data entry', kpis: ['Bank payments to check'], absent: ['Customers owe us', 'Bank balances', 'We owe suppliers', 'Expected gross spread'], money: false },
  { key: 'Data entry (cash)', login: 'demo.cash', profile: 'data_entry', role: 'Data entry', kpis: ['Cash vouchers waiting for approval'], absent: ['Customers owe us', 'Bank balances', 'Contracts'], money: false },
  { key: 'Logistics', login: 'demo.dispatch', profile: 'logistics', role: 'Logistics', kpis: ['Truck loadings to verify', 'Still to lift'], absent: ['Customers owe us', 'Bank balances', 'Cash in hand', 'Expected gross spread'], money: false },
  { key: 'System administrator', login: 'demo.sysadmin', profile: 'admin', role: 'System administrator', sections: ['System checks'], absent: ['Customers owe us', 'Bank balances', 'Expected gross spread'], money: false },
];

module.exports = {
  name: '02 role-specific Home pages and access',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    for (const r of ROLES) {
      const s = await new Session(ctx, browser, r.login, 'demo').start();
      const p = s.page, m = s.mark();
      try {
        await p.waitForSelector('.ei-home .ei-top', { timeout: 30000 }); await p.waitForTimeout(800);
        const text = await p.innerText('.ei-home');
        ctx.check(await p.getAttribute('.ei-home', 'data-profile') === r.profile, `${r.key}: gets the ${r.profile} layout`);
        ctx.check(text.includes(r.role), `${r.key}: header names the role "${r.role}"`);
        for (const k of r.kpis || []) ctx.check(text.includes(k), `${r.key}: shows "${k}"`);
        for (const k of r.absent || []) ctx.check(!text.includes(k), `${r.key}: does NOT show "${k}"`);
        for (const k of r.sections || []) ctx.check(text.toLowerCase().includes(k.toLowerCase()), `${r.key}: has the "${k}" section`);
        if (!r.money) ctx.check(!/Rs\.\s?[\d,]+\.\d\d/.test(text) || r.login === 'demo.bank', `${r.key}: no money figures on the page`);
        await s.clean(`${r.key}: Home loads with no error`, m);
        if (r.drill) {
          // every money figure must open its records for this role (the CEO used to get an access error here)
          const kpiButtons = p.locator('.ei-kpi');
          const n = await kpiButtons.count();
          for (let i = 0; i < n; i++) {
            const label = (await p.locator('.ei-kpi .ei-kpi-label').nth(i).innerText()).trim();
            const before = s.mark();
            await p.locator('.ei-kpi').nth(i).click(); await p.waitForTimeout(1500);
            const opened = await p.locator('.o_list_view, .o_kanban_view, .o_form_view').count();
            await s.clean(`${r.key}: "${label}" opens its records` + (opened ? '' : ' (no list shown)'), before);
            await s.home();
          }
        }
        await ctx.shot(p, 'role_' + r.login.replace('demo.', ''));
      } catch (e) { ctx.check(false, `${r.key}: Home checks`, String(e.message).split('\n')[0].slice(0, 160)); }
      await s.close();
    }
  },
};
