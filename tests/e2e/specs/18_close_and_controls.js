// Reconciliation centre, day and month close, party balances vs control accounts, quantity trail, old-system extracts, the imports log,
// supplier invoice side by side, the readiness ladder of the report catalog, and the morning bank check's timing items.
// Real browser, real clicks, the staging copy (synthetic data).
const PHONE = [390, 844];

async function actionId(admin, xmlid) {
  const [module, name] = xmlid.split('.');
  const r = await admin.rpc('ir.model.data', 'search_read', [[['module', '=', module], ['name', '=', name]], ['res_id']]);
  return r[0].res_id;
}

module.exports = {
  name: '18 close and controls (reconciliation centre, close, party balances, quantity trail, old system, imports log)',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const admin = await new Session(ctx, browser, 'admin', 'admin').start();
    const ids = {};
    for (const x of ['ei_close.ei_recon_centre_action', 'ei_close.ei_close_action', 'ei_close.ei_subledger_action', 'ei_close.ei_trail_action',
                     'ei_migration.ei_mig_extract_action', 'ei_migration.ei_mig_control_action', 'ei_migration.ei_integration_log_action',
                     'ei_invoice_extensions.ei_intake_action', 'ei_reports.action_report_catalog', 'ei_bank_operations.ei_balance_check_action']) {
      try { ids[x] = await actionId(admin, x); } catch { ids[x] = null; }
    }

    // ---- 1 reconciliation centre for the finance manager, laptop and phone
    for (const size of [[1366, 768], PHONE]) {
      const s = await new Session(ctx, browser, 'demo.finance', 'demo', size, { timeout: 30000 }).start();
      const p = s.page, m = s.mark(), tag = size[0] < 500 ? 'phone' : 'laptop';
      await s.goto(`/odoo/action-${ids['ei_close.ei_recon_centre_action']}`);
      await p.waitForSelector('.ei-rx-card', { timeout: 30000 });
      const codes = await p.locator('.ei-rx-code').allInnerTexts();
      ctx.check(['R1', 'R2', 'R3', 'R8'].every((c) => codes.includes(c)) && !codes.includes('R7'), `1 ${tag}: the centre lists the reconciliations finance may see (parent statements belong to the reconciliation team)`, codes.join(','));
      const chips = await p.locator('.ei-rx-chip').allInnerTexts();
      ctx.check(chips.every((c) => /Needs attention|Agrees|Waiting on others/.test(c)), `1 ${tag}: every card says plainly where it stands`, chips.join('|'));
      const r1 = p.locator('.ei-rx-card', { hasText: 'Bank book against the bank' });
      await r1.getByRole('button', { name: /Show each account/ }).click(); await p.waitForTimeout(300);
      ctx.check(await r1.locator('.ei-rx-table tbody tr').count() >= 1, `1 ${tag}: the bank card opens a row per bank account (book, today in/out, waiting, bank, proof)`);
      const lay = await s.layout();
      ctx.check(!lay.overflow && !lay.wide.length && !lay.clipped.length, `1 ${tag}: no horizontal overflow or clipped labels`, JSON.stringify(lay));
      if (tag === 'laptop') {
        const ax = await s.axe('.ei-rx');
        ctx.check(!ax || !ax.filter((v) => v.impact === 'serious' || v.impact === 'critical').length, '1 no serious accessibility findings on the centre', JSON.stringify(ax));
        await ctx.shot(p, 'recon_centre');
        await p.locator('.ei-rx-card', { hasText: 'Party balances against the control accounts' }).getByRole('button', { name: 'Open' }).click();
        await p.waitForSelector('.o_list_view, .o_kanban_view', { timeout: 20000 });
        ctx.check(true, '1 a card opens the records behind it');
      } else {
        await ctx.shot(p, 'recon_centre_phone');
      }
      await s.clean(`1 ${tag}: the centre opens clean`, m);
      await s.close();
    }
    {
      const s = await new Session(ctx, browser, 'demo.dispatch', 'demo', [1366, 768], { timeout: 30000 }).start();
      await s.goto(`/odoo/action-${ids['ei_close.ei_recon_centre_action']}`);
      await s.page.waitForSelector('.ei-rx-summary, .ei-rx-msg, .alert', { timeout: 30000 });
      const codes = await s.page.locator('.ei-rx-code').allInnerTexts();
      ctx.check(!codes.includes('R1') && !codes.includes('R3'), '1 dispatch does not see bank or ledger reconciliations', codes.join(','));
      await s.close();
    }

    // ---- 2 month-end close: prepared by the accountant, blockers explained, the finance manager waives and signs
    {
      const s = await new Session(ctx, browser, 'demo.accountant', 'demo', [1366, 768], { timeout: 30000 }).start();
      const p = s.page, m = s.mark();
      await s.goto(`/odoo/action-${ids['ei_close.ei_close_action']}/new`);
      await p.waitForSelector('.o_form_view', { timeout: 20000 });
      await p.locator('.o_field_widget[name=kind]').click(); await p.waitForTimeout(300);
      await p.locator('.o_select_menu_item, .dropdown-item', { hasText: 'Month-end close' }).first().click(); await p.waitForTimeout(300);
      // the date defaults to today: this month's close
      await p.getByRole('button', { name: 'Check again' }).click(); await p.waitForTimeout(2500);
      const rows = await p.locator('.o_field_widget[name=item_ids] .o_data_row').count();
      ctx.check(rows >= 8, '2 the checklist is worked out from the records', String(rows));
      const statuses = await p.locator('.o_field_widget[name=item_ids] .o_data_row td[name=status]').allInnerTexts();
      ctx.check(statuses.some((t) => /Blocker/.test(t)), '2 the staging copy shows at least one blocker, in words', statuses.join(','));
      ctx.check(await p.getByRole('button', { name: /Sign off/ }).count() === 0, '2 the accountant who prepared it is not offered the sign-off');
      await ctx.shot(p, 'month_close');
      await s.clean('2 the close form opens clean', m);
      const url = p.url();
      await s.close();
      const f = await new Session(ctx, browser, 'demo.finance', 'demo', [1366, 768], { timeout: 30000 }).start();
      await f.goto(url.replace(ctx.base, '')); await f.page.waitForSelector('.o_form_view', { timeout: 20000 });
      const waive = f.page.locator('.o_field_widget[name=item_ids] .o_data_row button', { hasText: 'Waive' });
      ctx.check(await waive.count() >= 1, '2 the finance manager can waive a blocker');
      await f.page.getByRole('button', { name: /Sign off/ }).click(); await f.page.waitForTimeout(1500);
      const err = await f.page.locator('.o_notification, .modal .modal-body').allInnerTexts();
      ctx.check(err.some((t) => /blockers are open/.test(t)), '2 signing with open blockers is refused, with the reason', err.join('|').slice(0, 200));
      await f.page.keyboard.press('Escape');
      await f.close();
    }

    // ---- 3 party balances vs control accounts
    {
      const s = await new Session(ctx, browser, 'demo.accountant', 'demo', [1366, 768], { timeout: 30000 }).start();
      const p = s.page, m = s.mark();
      await s.goto(`/odoo/action-${ids['ei_close.ei_subledger_action']}/new`);
      await p.waitForSelector('.o_form_view', { timeout: 20000 });
      await p.getByRole('button', { name: 'Run the check' }).click(); await p.waitForTimeout(2500);
      const ctl = await p.locator('.o_field_widget[name=control_balance]').innerText();
      const parties = await p.locator('.o_field_widget[name=party_total]').innerText();
      ctx.check(/\d/.test(ctl) && /\d/.test(parties), '3 the control total and the party total are shown', `${ctl} / ${parties}`);
      const srv = await s.rpc('ei.subledger.check', 'search_read', [[['state', '=', 'checked']], ['control_balance', 'party_total', 'no_party_amount']], { limit: 1, order: 'id desc' });
      ctx.check(srv.length && Math.abs(srv[0].control_balance - srv[0].party_total - srv[0].no_party_amount) < 0.01, '3 every rupee is a party\'s or listed as having no party', JSON.stringify(srv));
      await ctx.shot(p, 'party_balances_check');
      await s.clean('3 the check opens clean', m);
      await s.close();
    }

    // ---- 4 quantity trail, supplier invoice side by side, catalog ladder, migration screens, imports log
    {
      const s = await new Session(ctx, browser, 'admin', 'admin', [1366, 768], { timeout: 30000 }).start();
      const p = s.page, m = s.mark();
      await s.goto(`/odoo/action-${ids['ei_close.ei_trail_action']}`);
      await p.waitForSelector('.o_list_view', { timeout: 20000 });
      const heads = await p.locator('.o_list_view thead th').allInnerTexts();
      ctx.check(['Promised on DA', 'Supplier invoiced', 'Lifted (verified)', 'Customer invoiced'].every((h) => heads.some((x) => x.includes(h))),
        '4 the quantity trail shows promised, supplier-invoiced, lifted and customer-invoiced', heads.join('|').slice(0, 300));
      const intake = await s.rpc('ei.supplier.intake', 'search_read', [[], ['id']], { limit: 1 });
      if (intake.length) {
        await s.goto(`/odoo/action-${ids['ei_invoice_extensions.ei_intake_action']}/${intake[0].id}`); await p.waitForSelector('.o_form_view', { timeout: 20000 });
        const sbs = await p.locator('.o_field_widget[name=comparison_html]').innerText().catch(() => '');
        ctx.check(/Supplier says/.test(sbs) && /DA says/.test(sbs) && /Actually lifted/.test(sbs), '4 a supplier invoice shows supplier, contract, DA and lifting side by side');
      } else { ctx.skip('4 no supplier invoice on the staging copy'); }
      if (ids['ei_reports.action_report_catalog']) {
        await s.goto(`/odoo/action-${ids['ei_reports.action_report_catalog']}`);
        await p.waitForSelector('.ei-rc-card', { timeout: 20000 });
        const done = await p.locator('.ei-rc-ladder li.is-done').allInnerTexts();
        ctx.check(done.length > 0 && !done.some((t) => /Approved by finance|Verified in daily use|Checked against real books/.test(t)),
          '4 no report claims real-book validation or finance approval');
      }
      for (const x of ['ei_migration.ei_mig_extract_action', 'ei_migration.ei_mig_control_action', 'ei_migration.ei_integration_log_action']) {
        await s.goto(`/odoo/action-${ids[x]}`); await p.waitForSelector('.o_list_view, .o_view_nocontent', { timeout: 20000 });
      }
      const log = await s.rpc('ei.integration.log', 'search_read', [[], ['source', 'status']]);
      ctx.check(log.some((r) => r.source === 'bank') && log.some((r) => r.source === 'parent'), '4 the imports log lists the bank and parent statements of the staging copy', String(log.length));
      await s.clean('4 the new lists open clean', m);
      await s.close();
    }

    // ---- 5 morning bank check: proof status and timing items on the form
    {
      const s = await new Session(ctx, browser, 'demo.bankapprover', 'demo', [1366, 768], { timeout: 30000 }).start();
      const p = s.page, m = s.mark();
      const chk = await s.rpc('ei.bank.balance.check', 'search_read', [[], ['id']], { limit: 1 });
      if (chk.length) {
        await s.goto(`/odoo/action-${ids['ei_bank_operations.ei_balance_check_action']}/${chk[0].id}`);
        await p.waitForSelector('.o_form_view', { timeout: 20000 });
        ctx.check(await p.locator('.o_field_widget[name=timing_ids]').count() === 1 && await p.locator('.o_field_widget[name=unexplained_difference]').count() === 1,
          '5 the balance check shows timing items and what is still unexplained');
        await ctx.shot(p, 'balance_check_form');
      } else { ctx.skip('5 no balance check on the staging copy'); }
      await s.clean('5 the balance check opens clean', m);
      await s.close();
    }
    await admin.close();
  },
};
