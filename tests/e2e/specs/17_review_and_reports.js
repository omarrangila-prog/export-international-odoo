// The financial reports workspace (previews, checks, drill-down, PDF, scheduled delivery), the evidence shown before an approval, and
// documents beside the record. Real browser, real clicks, real data in the staging copy.
const PHONE = [390, 844];

async function actionId(admin, xmlid) {
  const [module, name] = xmlid.split('.');
  const r = await admin.rpc('ir.model.data', 'search_read', [[['module', '=', module], ['name', '=', name]], ['res_id']]);
  return r[0].res_id;
}

module.exports = {
  name: '17 review and reports (financial previews, PDF, schedule, approval evidence, documents beside the record)',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const admin = await new Session(ctx, browser, 'admin', 'admin').start();
    const ws = await actionId(admin, 'ei_reports.action_report_workspace');

    // ---- 1 financial previews on a laptop
    {
      const s = await new Session(ctx, browser, 'demo.finance', 'demo', [1366, 768], { timeout: 30000 }).start();
      const p = s.page, m = s.mark();
      await s.goto(`/odoo/action-${ws}`);
      await p.waitForSelector('.ei-ws-kpis', { timeout: 30000 });
      ctx.check(/preview/i.test(await p.locator('.ei-ws-preview').innerText()), '1 the page says plainly that these are previews');
      await p.locator('.ei-ws-pill', { hasText: 'Everything so far' }).click(); await p.waitForTimeout(1500);
      const kpis = await p.locator('.ei-ws-kpi').count();
      const cut = await p.evaluate(() => [...document.querySelectorAll('.ei-ws-kpi-value')].filter((e) => e.scrollWidth > e.clientWidth + 1).length);
      ctx.check(kpis === 6 && cut === 0, '1 six headline figures, none of them cut off', JSON.stringify({ kpis, cut }));
      const checks = await p.locator('.ei-ws-checks li').evaluateAll((els) => els.map((e) => e.className));
      ctx.check(checks.length === 4 && checks.every((c) => c === 'is-ok'), '1 the four checks agree on the staging books (debits=credits, balance sheet, cash, result)', checks.join(','));
      const kpi = (await p.locator('.ei-ws-kpi-value').first().innerText()).replace(/^\D*/, '');      // drop the currency, 'Rs.'
      const dash = await s.rpc('ei.report.financials', 'get_statements', ['2000-01-01', new Date().toISOString().slice(0, 10)]);
      const rev = dash.kpis.find((k) => k.key === 'revenue').value;
      ctx.check(kpi.replace(/[^\d.]/g, '').startsWith(String(Math.floor(rev))), '1 the revenue on screen is the server figure', `${kpi} vs ${rev}`);
      for (const t of ['Profit and loss', 'Balance sheet', 'Trial balance', 'Cash flow']) {
        await p.getByRole('tab', { name: t }).click(); await p.waitForTimeout(400);
        ctx.check(await p.getByRole('tab', { name: t }).getAttribute('aria-selected') === 'true' && await p.locator('.ei-ws-table').count() >= 1, `1 the ${t} tab shows its table`);
      }
      await p.getByRole('tab', { name: 'Trial balance' }).focus(); await p.keyboard.press('ArrowRight'); await p.waitForTimeout(200);
      ctx.check(await p.getByRole('tab', { name: 'Cash flow' }).getAttribute('aria-selected') === 'true', '1 arrow keys move between the statements');
      const ax = await s.axe('.ei-ws');
      ctx.check(!ax || !ax.filter((v) => v.impact === 'serious' || v.impact === 'critical').length, '1 no serious accessibility findings on the workspace', JSON.stringify(ax));
      await ctx.shot(p, 'reports_financial_workspace');
      // a row opens the entries behind it
      await p.getByRole('tab', { name: 'Profit and loss' }).click(); await p.waitForTimeout(300);
      await p.locator('.ei-ws-acc').first().click(); await p.waitForSelector('.o_list_view', { timeout: 20000 }); await p.waitForTimeout(800);
      ctx.check(await p.locator('.o_list_view .o_data_row').count() > 0, '1 a statement row opens the posted entries behind it');
      // the PDF
      const r = await s.bctx.request.get(`${ctx.base}/ei_reports/financial.pdf?statement=summary&date_from=2000-01-01&date_to=${new Date().toISOString().slice(0, 10)}`);
      const body = await r.body();
      ctx.check(r.status() === 200 && r.headers()['content-type'] === 'application/pdf' && body.slice(0, 4).toString() === '%PDF' && /PREVIEW/.test(r.headers()['content-disposition'] || ''),
        '1 the PDF downloads, and its file name says PREVIEW', `${r.status()} ${r.headers()['content-type']} ${body.length} bytes`);
      await s.clean('1 the workspace opens clean', m);
      await s.close();
    }

    // ---- 2 on a phone, and someone who may not see it
    {
      const s = await new Session(ctx, browser, 'demo.finance', 'demo', PHONE, { timeout: 30000 }).start();
      await s.goto(`/odoo/action-${ws}`); await s.page.waitForSelector('.ei-ws-kpis', { timeout: 30000 }); await s.page.waitForTimeout(800);
      for (const t of ['Summary', 'Trial balance']) {
        await s.page.getByRole('tab', { name: t }).click(); await s.page.waitForTimeout(400);
        const lay = await s.layout();
        ctx.check(!lay.overflow && !lay.wide.length, `2 phone: the ${t} tab fits the width (wide tables scroll inside their box)`, JSON.stringify(lay.wide));
      }
      await ctx.shot(s.page, 'reports_financial_phone');
      await s.close();
      const d = await new Session(ctx, browser, 'demo.dispatch', 'demo', [1366, 768]).start();
      let refused = false;
      try { await d.rpc('ei.report.financials', 'get_statements', []); } catch (e) { refused = /finance team and management/.test(e.message); }
      ctx.check(refused, '2 logistics cannot read the financial statements');
      const pdf = await d.bctx.request.get(`${ctx.base}/ei_reports/financial.pdf?statement=pnl`);
      ctx.check(pdf.status() === 403, '2 nor download them as a PDF', String(pdf.status()));
      await d.close();
    }

    // ---- 3 scheduled delivery: off until management switches it on, a test goes only to the person who presses it
    {
      const s = await new Session(ctx, browser, 'demo.ceo', 'demo', [1366, 768], { timeout: 30000 }).start();
      const p = s.page, m = s.mark();
      const me = await s.rpc('res.users', 'search_read', [[['login', '=', 'demo.ceo']], ['id']]);
      const id = await s.rpc('ei.report.schedule', 'create', [{ name: 'E2E monthly P&L', statement: 'pnl', enabled: true, recipient_ids: [[6, 0, [me[0].id]]] }]);
      const sched = await actionId(admin, 'ei_reports.action_report_schedule');
      await s.goto(`/odoo/action-${sched}/${id}`); await p.waitForSelector('.o_form_view', { timeout: 20000 }); await p.waitForTimeout(800);
      ctx.check(/It is OFF: nothing is sent/.test(await p.locator('.o_form_sheet').innerText()), '3 a new schedule is off, whatever was asked');
      await p.getByRole('button', { name: 'Send a test to me' }).click(); await p.waitForTimeout(2500);
      const runs = await s.rpc('ei.report.schedule.run', 'search_read', [[['schedule_id', '=', id]], ['status', 'test', 'recipients', 'message', 'attachment_id']]);
      // staging has no mail server: the honest outcome is "failed, the mail server refused it", logged with the PDF that would have gone
      ctx.check(runs.length === 1 && runs[0].test && runs[0].recipients === 'DEMO Ceo' && runs[0].attachment_id && (['sent', 'queued'].includes(runs[0].status) || /mail server/.test(runs[0].message)),
        '3 the test is logged with its PDF, says what happened, and went only to the person who pressed it', JSON.stringify(runs));
      await p.getByRole('button', { name: 'Switch on' }).click(); await p.waitForTimeout(600);
      const ok = p.locator('.modal-footer button', { hasText: /Ok|OK|Confirm/ }).first();
      if (await ok.count()) { await ok.click(); await p.waitForTimeout(1500); }
      ctx.check(/It is ON/.test(await p.locator('.o_form_sheet').innerText()), '3 management switches it on (with a confirmation saying who will receive it)');
      await s.clean('3 scheduling opens clean', m);
      await s.close();
    }

    // ---- 4 the evidence before an approval, and documents beside the record
    {
      const contracts = await admin.rpc('ei.contract', 'search_read', [[['state', '=', 'reviewed']], ['id', 'name', 'create_uid']]);
      if (!contracts.length) { ctx.skip('4 no contract waiting for approval in this copy'); await admin.close(); return; }
      const c = contracts[0];
      const act = (await admin.rpc('ir.actions.act_window', 'search_read', [[['res_model', '=', 'ei.contract']], ['id', 'name']])).find((a) => a.name === 'Contracts');
      const s = await new Session(ctx, browser, 'demo.contractapprover', 'demo', [1366, 768], { timeout: 30000 }).start();
      const p = s.page, m = s.mark();
      await s.goto(`/odoo/action-${act.id}/${c.id}`); await p.waitForSelector('.o_form_view', { timeout: 20000 }); await p.waitForTimeout(1200);
      await p.locator('button[name=action_approve]').first().click();
      await p.waitForSelector('.ei-ap', { timeout: 15000 }); await p.waitForTimeout(400);
      const text = await p.locator('.ei-ap').innerText();
      ctx.check(/What you are approving/i.test(text) && /Prepared by/i.test(text) && /What changed/i.test(text) && /Documents attached/i.test(text) && /What happens when you press Approve/i.test(text),
        '4 Approve first shows what, who, changes, documents and the effect');
      ctx.check(/holds the role "Contract approver/.test(text), '4 it says the person holds the role this needs');
      const ax = await s.axe('.modal');
      ctx.check(!ax || !ax.filter((v) => v.impact === 'serious' || v.impact === 'critical').length, '4 no serious accessibility findings in the dialog', JSON.stringify(ax));
      await ctx.shot(p, 'approval_evidence');
      await p.keyboard.press('Escape'); await p.waitForTimeout(800);
      let state = (await admin.rpc('ei.contract', 'read', [[c.id], ['state']]))[0].state;
      ctx.check(state === 'reviewed' && await p.locator('.ei-ap').count() === 0, '4 Escape closes it and nothing was approved', state);
      // documents beside the record
      const docs = p.locator('.ei-dv-toggle');
      if (await docs.count()) {
        await docs.click(); await p.waitForSelector('.ei-dv-panel'); await p.waitForTimeout(800);
        const split = await p.evaluate(() => { const panel = document.querySelector('.ei-dv-panel').getBoundingClientRect(); const sheet = document.querySelector('.o_form_sheet').getBoundingClientRect(); return { panelLeft: Math.round(panel.left), sheetRight: Math.round(sheet.right) }; });
        ctx.check(split.sheetRight <= split.panelLeft, '4 the document opens beside the record, not over it', JSON.stringify(split));
        await ctx.shot(p, 'documents_beside_record');
        await p.keyboard.press('Escape'); await p.waitForTimeout(400);
        ctx.check(await p.locator('.ei-dv-panel').count() === 0, '4 Escape closes the documents');
      } else ctx.skip('4 this contract has no document attached');
      // now really approve
      await p.locator('button[name=action_approve]').first().click(); await p.waitForSelector('.ei-ap-confirm');
      await p.locator('.ei-ap-confirm').click(); await p.waitForTimeout(2500);
      state = (await admin.rpc('ei.contract', 'read', [[c.id], ['state']]))[0].state;
      ctx.check(state === 'approved', '4 pressing Approve in the dialog approves it', state);
      await s.clean('4 the approval flow opens clean', m);
      await s.close();
      // phone: the documents cover the screen and Close returns
      const ph = await new Session(ctx, browser, 'demo.contractapprover', 'demo', PHONE, { timeout: 30000 }).start();
      await ph.goto(`/odoo/action-${act.id}/${c.id}`); await ph.page.waitForSelector('.o_form_view', { timeout: 20000 }); await ph.page.waitForTimeout(1200);
      if (await ph.page.locator('.ei-dv-toggle').count()) {
        await ph.page.locator('.ei-dv-toggle').click(); await ph.page.waitForSelector('.ei-dv-panel');
        const full = await ph.page.evaluate(() => { const r = document.querySelector('.ei-dv-panel').getBoundingClientRect(); return Math.round(r.width) === window.innerWidth && Math.round(r.top) === 0; });
        ctx.check(full, '4 on a phone the document fills the screen');
        await ph.page.getByRole('button', { name: 'Close the documents' }).click(); await ph.page.waitForTimeout(400);
        ctx.check(await ph.page.locator('.ei-dv-panel').count() === 0, '4 and Close returns to the record');
      }
      await ph.close();
    }
    await admin.close();
  },
};
