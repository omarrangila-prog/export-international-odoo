// Every daily entry, typed through the screens by one person (the DEMO trainer, who has the daily-work roles) with routine approval
// OFF (the client's default): contract -> DA in the feeding desk -> daily order -> truck loading -> supplier invoice -> customer invoice,
// then a cash voucher, a cash count and the morning bank balance. Each step must show no error AND leave the record in the state the
// step promises, read back from the database. The policy is switched back ON at the end for the specs that check second-person controls.
const NOISE = /favicon|Failed to load resource: the server responded with a status of 40[34]/;

module.exports = {
  name: '24 every daily entry, typed through the screens (approval off)',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const stamp = String(Date.now()).slice(-7);
    // a real image of a paper (as a phone photo would be), drawn here: a stub PDF cannot be previewed and Odoo logs that as an error
    const pc = await browser.newContext({ viewport: { width: 600, height: 400 } }); const pp = await pc.newPage();
    await pp.setContent('<body style="font:20px Arial;padding:30px"><h2>TRAINING ONLY</h2><p>Synthetic paper for the browser suite</p></body>');
    const DOC = { name: 'paper.png', mimeType: 'image/png', buffer: await pp.screenshot() }; await pc.close();
    const admin = await new Session(ctx, browser, 'admin', 'admin').start();
    await admin.rpc('ei.approval.policy', 'set_all', [false]);
    // arrangement: a fresh supplier, so today's daily order for it is certainly new
    const mill = await admin.rpc('res.partner', 'create', [{ name: `DEMO Entry Mill ${stamp}`, is_company: true }]);
    const one = async (model, domain, fields) => (await admin.rpc(model, 'search_read', [domain, fields], { limit: 1, order: 'id desc' }))[0];
    let s;
    try {
      s = await new Session(ctx, browser, 'demo.trainer', 'demo', [1440, 900], { timeout: 20000 }).start();
      const p = s.page;
      const go = async (xmlid) => { await p.goto(`${ctx.base}/odoo/action-${xmlid}`); await p.waitForSelector('.o_action_manager .o_action', { timeout: 30000 }); await p.waitForTimeout(800); };
      const fld = (name, root) => (root || p.locator('.o_form_view').first()).locator(`.o_field_widget[name="${name}"]`).first();
      const typeIn = async (name, text, root) => { const i = fld(name, root).locator('input, textarea').first(); await i.click(); await i.fill(String(text)); };
      const m2o = async (name, term, pick, root) => {
        const i = fld(name, root).locator('input').first(); await i.click(); await i.fill(''); await i.pressSequentially(term, { delay: 40 });
        await p.waitForTimeout(1100);
        const items = p.locator('.o-autocomplete--dropdown-item');
        await (pick ? items.filter({ hasText: pick }) : items).first().click(); await p.waitForTimeout(500);
      };
      const save = async () => { await p.locator('.o_form_button_save:visible').first().click(); await p.waitForTimeout(1400); };
      const attach = async () => { await p.locator('.o-mail-Chatter input[type="file"], .o-mail-Form-chatter input[type="file"]').first().setInputFiles(DOC); await p.waitForTimeout(1800); };
      const header = async (text) => { await p.locator('.o_form_statusbar button:visible, .o_statusbar_buttons button:visible', { hasText: text }).first().click(); await p.waitForTimeout(1500); };
      const newRec = async () => { await p.locator('.o_list_button_add:visible, .o-kanban-button-new:visible').first().click(); await p.waitForSelector('.o_form_view, .o_selected_row', { timeout: 20000 }); await p.waitForTimeout(600); };
      const step = async (label, fn) => {
        const mark = s.mark();
        let detail = '';
        try { detail = (await fn()) || ''; } catch (e) { detail = 'STOPPED: ' + String(e.message).split('\n')[0].slice(0, 160); await ctx.shot(p, 'FAIL_24_' + label.split(':')[0].replace(/\W+/g, '_')).catch(() => {}); }
        const dlg = await s.dialog(); const errs = s.since(mark).filter(e => !NOISE.test(e.text));
        const bad = /^STOPPED|^WRONG/.test(detail) || dlg || errs.length;
        ctx.check(!bad, label, bad ? (dlg ? 'dialog: ' + dlg : errs.length ? `${errs[0].kind}: ${errs[0].text}` : detail) : '');
        if (dlg) await p.keyboard.press('Escape').catch(() => {});
        return !bad;
      };
      const expect = (got, want, what) => (got === want ? '' : `WRONG ${what}: ${got} (expected ${want})`);

      // 1 contract: typed, line added in its dialog, paper attached, Save & Continue makes it active at once
      const ref = `DEMO/ENTRY/${stamp}`;
      await step('contract: typed, saved, paper attached and made active with Save & Continue', async () => {
        await go('ei_contract_da.ei_contract_action'); await newRec();
        await m2o('parent_partner_id', `DEMO Entry Mill ${stamp}`); await typeIn('contract_ref', ref);
        await p.locator('.o_field_widget[name="line_ids"] .o_field_x2many_list_row_add a, .o_field_widget[name="line_ids"] .o_field_x2many_list_row_add button').first().click();
        await p.waitForSelector('.modal .o_form_view', { timeout: 15000 });
        const dlg = p.locator('.modal .o_form_view').last();
        await m2o('product_id', 'DEMO HR Coil', null, dlg); await typeIn('ordered_mtl', '20', dlg);
        await typeIn('purchase_rate', '200000', dlg); await typeIn('sale_rate', '201000', dlg);
        await p.locator('.modal-footer button.btn-primary:visible', { hasText: /Save/ }).first().click(); await p.waitForTimeout(1200);
        await save(); await attach(); await header('Save & Continue');
        const c = await one('ei.contract', [['contract_ref', '=', ref]], ['state']);
        return expect(c && c.state, 'active', 'contract state');
      });
      const contract = await one('ei.contract', [['contract_ref', '=', ref]], ['line_ids']);
      if (contract) await admin.rpc('ei.contract.line', 'action_set_ownership', [contract.line_ids, 'direct_dispatch', 'browser suite: mill dispatches']);

      // 2 DA in the feeding desk: one coil (direct rates), Save & Continue confirms it and prepares today's daily order
      const da = `DA-ENTRY-${stamp}`;
      let orderLink = false;
      await step('DA: created in the feeding desk, coil fed, Save & Continue confirms it and prepares the daily order', async () => {
        await go('ei_da_feeding.action_ei_da_feeding'); await p.waitForSelector('.ei-fd-method', { timeout: 30000 });
        await p.getByRole('tab', { name: /Real entry/ }).click(); await p.getByRole('button', { name: 'New DA' }).click(); await p.waitForSelector('.ei-fd-more', { state: 'attached', timeout: 15000 }); await p.evaluate(() => { document.querySelector('.ei-fd-more').open = true; });
        await p.waitForFunction((r) => [...document.querySelectorAll('#ei-fd-contract option')].some((o) => o.textContent.includes(r)), ref);
        const opts = await p.locator('#ei-fd-contract option').evaluateAll((os) => os.map((o) => [o.value, o.textContent]));
        await p.locator('#ei-fd-contract').selectOption(opts.find(([, t]) => t.includes(ref))[0]);
        await p.fill('#ei-fd-daname', da); await p.locator('.ei-fd-main .ei-fd-field.is-wide input').last().fill('M/S DEMO CUSTOMER - REHMAN TRADERS');
        await p.getByRole('button', { name: 'Create draft DA' }).click(); await p.waitForSelector('.ei-fd-daname');
        await p.locator('.ei-fd-paper input[type="file"]').setInputFiles(DOC); await p.waitForTimeout(1500);
        await p.getByRole('button', { name: 'Add Coil' }).click();
        await p.fill('#ei-fd-coil', 'E-1'); await p.locator('.ei-fd-editor .ei-fd-field', { hasText: 'Weight' }).locator('input').fill('4000');
        for (const [label, term, row] of [['Sold (OUT)', 'Rehman', null], ['Sales code', 'D.01', 'D.01']]) {
          await p.locator('.ei-fd-pick', { hasText: label }).getByRole('button', { name: /Choose|Change/ }).first().click();
          await p.locator('#ei-fd-look').pressSequentially(term, { delay: 50 }); await p.waitForTimeout(1200);
          await p.locator('.ei-fd-lookrows button', row ? { hasText: row } : {}).first().click(); await p.waitForTimeout(400);
        }
        await p.locator('.ei-fd-mpick', { hasText: /^Direct purchase and sale/ }).click();
        await p.locator('.ei-fd-editor .ei-fd-field', { hasText: 'Purchase rate / MTL' }).locator('input').fill('200000');
        await p.locator('.ei-fd-editor .ei-fd-field', { hasText: 'Sale rate / MTL' }).locator('input').fill('201000');
        await p.waitForSelector('.ei-fd-answer', { timeout: 40000 });
        await p.getByRole('button', { name: 'Save Draft' }).click(); await p.waitForTimeout(1500);
        await p.getByRole('button', { name: 'Save & Continue' }).click(); await p.waitForSelector('.ei-fd-done, .ei-fd-wait', { timeout: 30000 });
        orderLink = await p.getByRole('button', { name: /Open the daily order/ }).count() || await p.getByRole('link', { name: /Open the daily order/ }).count();
        const d = await one('ei.da', [['name', '=', da]], ['state']);
        return expect(d && d.state, 'approved', 'DA state') || (orderLink ? '' : 'WRONG no daily order was prepared');
      });

      // 3 daily order: opened from the desk, Save & Continue approves it
      await step('daily order: opened from the DA and confirmed with Save & Continue', async () => {
        const link = p.getByRole('button', { name: /Open the daily order/ }).or(p.getByRole('link', { name: /Open the daily order/ })).first();
        await link.click(); await p.waitForSelector('.o_form_view', { timeout: 20000 }); await p.waitForTimeout(900);
        await header('Save & Continue');
        const o = await one('ei.daily.order', [['parent_partner_id', '=', mill]], ['state', 'line_ids']);
        return expect(o && o.state, 'approved', 'daily order state') || expect(o.line_ids.length, 1, 'order lines');
      });

      // 4 truck loading: DA line, truck, gate pass, tons, gate pass attached, verified with Save & Continue
      await step('truck loading: typed, gate pass attached, verified with Save & Continue', async () => {
        await go('ei_material_lifting.ei_lifting_action'); await newRec();
        await m2o('da_line_id', da, da); await typeIn('vehicle_no', 'TKE-' + stamp.slice(-4)); await typeIn('gate_pass_no', 'GP-E-' + stamp); await typeIn('claimed_mtl', '4');
        await save(); await attach(); await header('Save & Continue');
        const ok = p.locator('.modal').getByRole('button', { name: 'Verify', exact: true });
        if (await ok.count()) { await ok.click(); await p.waitForTimeout(1500); }
        const l = await one('ei.lifting', [['gate_pass_no', '=', 'GP-E-' + stamp]], ['state']);
        return expect(l && l.state, 'verified', 'loading state');
      });

      // 5 supplier invoice: typed with its line and HS code, invoice attached, checks run -> matched
      await step('supplier invoice: typed, attached, Run checks matches it', async () => {
        await go('ei_invoice_extensions.ei_intake_action'); await newRec();
        await m2o('partner_id', `DEMO Entry Mill ${stamp}`); await typeIn('invoice_number', 'SUP-E-' + stamp);
        const dt = fld('invoice_date').locator('input'); await dt.click();
        await dt.fill(new Date().toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: 'numeric' })); await p.keyboard.press('Tab'); await p.waitForTimeout(400);
        await p.locator('.o_field_widget[name="line_ids"] .o_field_x2many_list_row_add a, .o_field_widget[name="line_ids"] .o_field_x2many_list_row_add button').first().click();
        const row = p.locator('.o_field_widget[name="line_ids"] .o_selected_row');
        await m2o('da_line_id', da, da, row); await typeIn('received_mtl', '4', row); await typeIn('unit_rate', '200000', row); await typeIn('hs_code', '7208.3990', row);
        await typeIn('stated_total', '800000');
        await save(); await attach(); await header('Run checks');
        const i = await one('ei.supplier.intake', [['invoice_number', '=', 'SUP-E-' + stamp]], ['state']);
        return expect(i && i.state, 'matched', 'supplier invoice state');
      });

      // 6 customer invoice from the verified loading
      await step('customer invoice: made from the verified truck loading', async () => {
        await go('ei_invoice_extensions.ei_billable_action');
        const r = p.locator('.o_data_row', { hasText: da }).first(); await r.waitFor({ timeout: 15000 });
        await r.locator('.o_list_record_selector input').click(); await p.waitForTimeout(500);
        await p.locator('.o_cp_action_menus button, button:has-text("Actions")').first().click();
        await p.locator('.o-dropdown--menu, .dropdown-menu').getByText('Invoice verified liftings').first().click();
        await p.waitForSelector('.modal .o_form_view', { timeout: 15000 }); await p.waitForTimeout(800);
        await p.locator('.modal-footer button.btn-primary').first().click(); await p.waitForTimeout(2500);
        const l = await one('ei.lifting', [['gate_pass_no', '=', 'GP-E-' + stamp]], ['invoice_move_id']);
        return l && l.invoice_move_id ? '' : 'WRONG no customer invoice on the loading';
      });

      // 7 cash voucher: typed, receipt attached, posted with Save & Continue (the trainer has accounting rights)
      await step('cash voucher: typed, receipt attached, posted with Save & Continue', async () => {
        await go('ei_cashbook.ei_cash_voucher_action'); await newRec();
        await m2o('journal_id', 'Cash'); await m2o('category_id', 'Office');
        await typeIn('amount', '1850'); await typeIn('description', 'E2E tea and stationery ' + stamp);
        await save(); await attach(); await header('Save & Continue');
        const v = await one('ei.cash.voucher', [['description', '=', 'E2E tea and stationery ' + stamp]], ['state', 'amount']);
        return expect(v && v.state, 'posted', 'voucher state') || expect(v.amount, 1850, 'voucher amount');
      });

      // 8 cash count: the book side shows while counting, the typed total is kept
      await step('cash count: typed total kept, book side and difference shown', async () => {
        // one count per cash box per day (a rule): take the latest day that has no count yet, so the suite can run again
        let day = new Date();
        for (let i = 0; i < 400 && await admin.rpc('ei.cash.count', 'search_count', [[['date', '=', day.toISOString().slice(0, 10)]]]); i++) day = new Date(day - 86400e3);
        await go('ei_cashbook.ei_cash_count_action'); await newRec();
        await m2o('journal_id', 'Cash'); await p.waitForTimeout(1200);
        await fld('date').locator('button, input').first().click(); await p.waitForTimeout(400);    // Odoo 20 shows a date as a button until clicked
        const dt = fld('date').locator('input').first();
        await dt.fill(day.toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: 'numeric', timeZone: 'UTC' })); await p.keyboard.press('Tab'); await p.waitForTimeout(500);
        await typeIn('counted_amount', '50000'); await p.keyboard.press('Tab'); await p.waitForTimeout(800);
        const diff = (await fld('now_difference').innerText()).trim();
        await save();
        const c = await one('ei.cash.count', [], ['counted_amount', 'id']);
        return expect(c && c.counted_amount, 50000, 'counted amount') || (diff ? '' : 'WRONG the difference is empty while counting');
      });

      // 9 morning bank balance: a row typed in the list and saved
      await step('morning bank balance: a bank row typed and saved', async () => {
        await go('ei_bank_operations.ei_balance_check_action');
        const before = await admin.rpc('ei.bank.balance.check', 'search_count', [[]]);
        await newRec();
        const row = p.locator('.o_selected_row').first();
        const root = (await row.count()) ? row : p.locator('.o_form_view').first();
        await m2o('journal_id', 'Meezan', null, root);
        const sel = fld('confirmed_via', root).locator('select'); if (await sel.count()) await sel.selectOption({ index: 1 });
        await typeIn('bank_balance', '250000', root);
        await p.locator('.o_list_button_save:visible, .o_form_button_save:visible').first().click(); await p.waitForTimeout(1500);
        const after = await admin.rpc('ei.bank.balance.check', 'search_count', [[]]);
        return expect(after, before + 1, 'bank balance rows');
      });
      await ctx.shot(p, '24_every_entry_end');
    } finally {
      if (s) await s.close();
      await admin.rpc('ei.approval.policy', 'set_all', [true]);
      await admin.close();
    }
  },
};
