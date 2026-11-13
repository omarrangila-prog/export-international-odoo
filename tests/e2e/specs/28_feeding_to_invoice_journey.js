// The whole journey of one fed DA with maker-checker ON, through the screens, each step done by the person whose job it is:
// feeding entry (no contract) -> checker approves -> daily order generated and approved -> invoice number and HS code added later ->
// stock ownership classified -> truck loading submitted and verified (duplicate gate pass refused) -> supplier invoice checked ->
// customer invoice made and posted -> corrected by a credit note. DEMO parties and codes only.
module.exports = {
  name: '28 one fed DA to customer invoice and credit note, maker-checker on',
  async run(ctx, browser) {
    const { Session, synthPdf } = require('../lib');
    const stamp = String(Date.now()).slice(-6);
    const admin = await new Session(ctx, browser, 'admin', 'admin').start();
    await admin.rpc('ei.approval.policy', 'set_all', [true]);
    const one = async (model, domain, fields) => (await admin.rpc(model, 'search_read', [domain, fields], { limit: 1, order: 'id desc' }))[0];
    const logins = {};
    for (const u of await admin.rpc('res.users', 'search_read', [[['login', '=like', 'demo.%']], ['name', 'login']])) logins[u.name] = u.login;
    const sessions = {};
    const as = async (login) => sessions[login] || (sessions[login] = await new Session(ctx, browser, login, 'demo', [1440, 900], { timeout: 30000 }).start());
    // the assigned checker decides in the approvals centre's engine (the centre's own screens are covered by spec 25)
    const approve = async (model, id) => {
      const rq = await one('ei.approval.request', [['res_model', '=', model], ['res_id', '=', id], ['state', '=', 'pending']], ['id', 'approver_id']);
      if (!rq || !rq.approver_id) return 'no assigned checker';
      const c = await as(logins[rq.approver_id[1]]);
      await c.rpc('ei.approval.request', 'decide', [rq.id, 'approve', 'Checked']);
      return logins[rq.approver_id[1]];
    };

    const s = await as('demo.trainer'); const p = s.page; let m = s.mark();
    const fld = (name, root) => (root || p.locator('.o_form_view').first()).locator(`.o_field_widget[name="${name}"]`).first();
    const typeIn = async (name, text, root) => { const i = fld(name, root).locator('input, textarea').first(); await i.click(); await i.fill(String(text)); };
    const m2o = async (name, term, pick, root) => {
      const i = fld(name, root).locator('input').first(); await i.click(); await i.fill(''); await i.pressSequentially(term, { delay: 40 });
      await p.waitForTimeout(1100); const items = p.locator('.o-autocomplete--dropdown-item');
      await (pick ? items.filter({ hasText: pick }) : items).first().click(); await p.waitForTimeout(500);
    };
    const header = async (pg, text) => { await pg.locator('.o_form_statusbar button:visible, .o_statusbar_buttons button:visible', { hasText: text }).first().click(); await pg.waitForTimeout(1600); };
    // the chatter's attachment thumbnails ask for a few files Odoo answers 404 (the same noise spec 24 filters); everything else counts
    const NOISE = /Failed to load resource: the server responded with a status of 404/;
    const clean = async (sess, label, mark) => { const dlg = await sess.dialog(); const errs = sess.since(mark).filter((e) => !NOISE.test(e.text));
      return ctx.check(!dlg && !errs.length, label, dlg ? 'dialog: ' + dlg : errs.map((e) => e.kind + ': ' + e.text).slice(0, 2).join(' | ')); };
    const attach = async () => { await p.locator('.o-mail-Chatter input[type="file"], .o-mail-Form-chatter input[type="file"]').first().setInputFiles(synthPdf()); await p.waitForTimeout(1800); };

    // 1 the feeding entry, submitted
    const da = `DA-JRN-${stamp}`;
    await p.goto(`${ctx.base}/odoo/action-ei_da_feeding.action_ei_new_feeding`); await p.waitForSelector('#ei-fd-daname', { timeout: 30000 });
    await p.locator('#ei-fd-supplier').selectOption({ label: 'DEMO Parent Steel Mill' }); await p.locator('#ei-fd-pin').selectOption({ label: 'DEMO Buying Entity' });
    await p.fill('#ei-fd-daname', da);
    await p.locator('#ei-fd-sold').pressSequentially('Rehman', { delay: 40 }); await p.waitForTimeout(1200); await p.locator('.ei-fd-sold .ei-fd-lookrows button').first().click();
    await p.getByRole('button', { name: 'Create draft DA' }).click(); await p.waitForSelector('.ei-fd-daname');
    await p.locator('.ei-fd-paper input[type="file"]').setInputFiles(synthPdf()); await p.waitForTimeout(1500);
    await p.getByRole('button', { name: 'Add Coil' }).click();
    await p.locator('#ei-fd-item').click(); await p.locator('#ei-fd-item').pressSequentially('DEMO HR', { delay: 40 }); await p.waitForTimeout(1200);
    await p.locator('.ei-fd-item .ei-fd-lookrows button').first().click(); await p.waitForTimeout(1200);
    await p.fill('#ei-fd-coil', 'JRN-1');
    const coilField = (label) => p.locator('.ei-fd-editor .ei-fd-field', { hasText: label }).locator('input').first();
    await coilField('Weight').fill('4574');
    await p.locator('.ei-fd-pick', { hasText: 'Sales code' }).getByRole('button', { name: /Choose|Change/ }).first().click();
    await p.locator('#ei-fd-look').pressSequentially('D.01', { delay: 40 }); await p.waitForTimeout(1200); await p.locator('.ei-fd-lookrows button', { hasText: 'D.01' }).first().click();
    await p.locator('.ei-fd-mpick', { hasText: /^Direct purchase and sale/ }).click();
    await coilField('Purchase rate / MTL').fill('229500'); await coilField('Sale rate / MTL').fill('230500');
    await p.waitForSelector('.ei-fd-answer', { timeout: 40000 }); await p.getByRole('button', { name: 'Save Draft' }).click(); await p.waitForTimeout(1800);
    await p.getByRole('button', { name: 'Submit for Approval' }).click(); await p.waitForSelector('.ei-fd-done.is-wait', { timeout: 30000 });
    const rec = await one('ei.da', [['name', '=', da]], ['id', 'state', 'line_ids']);
    ctx.check(rec.state === 'under_review', '1 the fed DA is submitted for approval', rec.state);
    ctx.check(!!(await approve('ei.da', rec.id)) && (await one('ei.da', [['id', '=', rec.id]], ['state'])).state === 'approved', '1 a different person approves it');
    await s.clean('1 feeding entry and submission are clean', m);

    // 2 the daily order: generated from the approved DA, submitted, approved by a checker
    m = s.mark();
    await p.goto(`${ctx.base}/odoo/action-ei_contract_da.ei_da_action/${rec.id}`); await p.waitForSelector('.o_form_view', { timeout: 30000 });
    await header(p, 'Generate Daily Order'); await p.waitForSelector('.o_form_view', { timeout: 20000 });
    const order = await one('ei.daily.order.line', [['da_id', '=', rec.id]], ['order_id', 'id']);
    ctx.check(!!order, '2 the daily order is generated from the approved DA', JSON.stringify(order));
    const sub = p.locator('.o_statusbar_buttons button:visible', { hasText: /Submit for Approval/ });
    if (await sub.count()) { await sub.first().click(); await p.waitForTimeout(1600); }
    ctx.check(!!(await approve('ei.daily.order', order.order_id[0])) && (await one('ei.daily.order', [['id', '=', order.order_id[0]]], ['state'])).state === 'approved',
      '2 the daily order is approved by a checker');
    // 3 the supplier invoice number and HS code arrive later: typed on the approved order's line
    await p.reload(); await p.waitForSelector('.o_form_view'); await p.waitForTimeout(1000);
    const cell = p.locator('.o_field_widget[name="line_ids"] .o_data_row').first().locator('td[name="invoice_ref"]');
    await cell.click(); await p.waitForTimeout(500);
    await p.locator('.o_field_widget[name="line_ids"] .o_selected_row [name="invoice_ref"] input').fill(`SUP-JRN-${stamp}`);
    await p.locator('.o_field_widget[name="line_ids"] .o_selected_row [name="hs_code"] input').fill('7208.3990');
    await p.locator('.o_form_button_save:visible').first().click(); await p.waitForTimeout(1500);
    const ol = await one('ei.daily.order.line', [['id', '=', order.id]], ['invoice_ref', 'hs_code']);
    ctx.check(ol.invoice_ref === `SUP-JRN-${stamp}` && ol.hs_code === '7208.3990', '3 invoice number and HS code are added later on the approved order', JSON.stringify(ol));
    await s.clean('2-3 daily order screens are clean', m);

    // 4 stock ownership (a contract approver), then the truck loading
    const fin = await as('demo.contractapprover'); const fp = fin.page; let mf = fin.mark();
    const lineId = rec.line_ids[0];
    m = s.mark();
    await p.goto(`${ctx.base}/odoo/action-ei_material_lifting.ei_lifting_action/new`); await p.waitForSelector('.o_form_view', { timeout: 30000 });
    await m2o('da_line_id', da, da); await m2o('order_line_id', da, null);
    await typeIn('vehicle_no', 'TKJ-' + stamp.slice(-3)); await typeIn('gate_pass_no', 'GP-JRN-' + stamp); await typeIn('claimed_mtl', '2');
    await p.locator('.o_form_button_save:visible').first().click(); await p.waitForTimeout(1500); await attach();
    const lift = await one('ei.lifting', [['gate_pass_no', '=', 'GP-JRN-' + stamp]], ['id', 'state']);
    await fp.goto(`${ctx.base}/odoo/action-ei_material_lifting.ei_lifting_action/${lift.id}`); await fp.waitForSelector('.o_form_view', { timeout: 30000 });
    await header(fp, 'Classify stock ownership'); await fp.waitForSelector('.modal .o_form_view');
    await fp.locator('.modal .o_field_widget[name="ownership"] label', { hasText: 'Direct supplier-to-customer dispatch' }).click();
    await fp.locator('.modal .o_field_widget[name="reason"] input').fill('Mill dispatches to the customer (training)');
    await fp.locator('.modal-footer button.btn-primary').click(); await fp.waitForTimeout(1500);
    ctx.check((await one('ei.contract.line', [['da_line_ids', 'in', [lineId]]], ['stock_ownership'])).stock_ownership === 'direct_dispatch',
      '4 a contract approver classifies the stock ownership from the lifting screen');
    await fin.clean('4 ownership dialog is clean', mf);
    await p.reload(); await p.waitForSelector('.o_form_view'); await p.waitForTimeout(800);
    await header(p, 'Submit for Approval');
    ctx.check(!!(await approve('ei.lifting', lift.id)) && (await one('ei.lifting', [['id', '=', lift.id]], ['state'])).state === 'verified', '4 the truck loading is verified by a reviewer');
    const tr = await one('ei.da.line', [['id', '=', lineId]], ['lifted_mtl', 'remaining_to_lift', 'lifting_status', 'trace_invoice', 'trace_hs']);
    ctx.check(tr.lifted_mtl === 2 && Math.abs(tr.remaining_to_lift - 2.574) < 1e-6 && tr.lifting_status === 'part' && tr.trace_invoice === `SUP-JRN-${stamp}` && tr.trace_hs === '7208.3990',
      '4 the coil shows 2.000 lifted, 2.574 remaining, partly lifted, with the invoice number and HS code', JSON.stringify(tr));
    let dup = false;
    try { await s.rpc('ei.lifting', 'create', [{ da_line_id: lineId, vehicle_no: 'X', gate_pass_no: 'GP-JRN-' + stamp, claimed_mtl: 1 }]); } catch (e) { dup = true; }
    ctx.check(dup, '4 the same gate pass cannot be entered twice');
    await clean(s, '4 lifting screens are clean', m);

    // 5 the supplier invoice, checked against the DA and the loading
    m = s.mark();
    await p.goto(`${ctx.base}/odoo/action-ei_invoice_extensions.ei_intake_action/new`); await p.waitForSelector('.o_form_view', { timeout: 30000 });
    await m2o('partner_id', 'DEMO Parent Steel Mill', 'DEMO Parent Steel Mill'); await typeIn('invoice_number', `SUP-JRN-${stamp}`);
    const dt = fld('invoice_date').locator('input'); await dt.click(); await dt.fill(new Date().toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: 'numeric' })); await p.keyboard.press('Tab');
    await p.locator('.o_field_widget[name="line_ids"] .o_field_x2many_list_row_add a, .o_field_widget[name="line_ids"] .o_field_x2many_list_row_add button').first().click();
    const row = p.locator('.o_field_widget[name="line_ids"] .o_selected_row');
    await m2o('da_line_id', da, da, row); await typeIn('received_mtl', '2', row); await typeIn('unit_rate', '229500', row); await typeIn('hs_code', '7208.3990', row);
    await typeIn('stated_total', '459000');
    await p.locator('.o_form_button_save:visible').first().click(); await p.waitForTimeout(1400); await attach(); await header(p, 'Run checks');
    ctx.check((await one('ei.supplier.intake', [['invoice_number', '=', `SUP-JRN-${stamp}`]], ['state'])).state === 'matched', '5 the supplier invoice matches the DA and the loading');
    await clean(s, '5 supplier invoice screens are clean', m);

    // 6 the customer invoice from the verified loading, posted; then corrected with a credit note
    m = s.mark();
    await p.goto(`${ctx.base}/odoo/action-ei_invoice_extensions.ei_billable_action`); await p.waitForSelector('.o_list_view', { timeout: 30000 });
    const r = p.locator('.o_data_row', { hasText: da }).first(); await r.waitFor({ timeout: 15000 });
    await r.locator('.o_list_record_selector input').click(); await p.waitForTimeout(500);
    await p.locator('.o_cp_action_menus button, button:has-text("Actions")').first().click();
    await p.locator('.o-dropdown--menu, .dropdown-menu').getByText('Invoice verified liftings').first().click();
    await p.waitForSelector('.modal .o_form_view', { timeout: 15000 }); await p.waitForTimeout(800);
    await p.locator('.modal-footer button.btn-primary').first().click(); await p.waitForTimeout(2500);
    const inv = (await one('ei.lifting', [['id', '=', lift.id]], ['invoice_move_id'])).invoice_move_id;
    ctx.check(!!inv, '6 the customer invoice is made from the verified loading');
    await p.goto(`${ctx.base}/odoo/action-account.action_move_out_invoice_type/${inv[0]}`); await p.waitForSelector('.o_form_view', { timeout: 30000 });
    await header(p, 'Confirm');
    let mv = await one('account.move', [['id', '=', inv[0]]], ['state', 'amount_total', 'partner_id']);
    ctx.check(mv.state === 'posted' && mv.amount_total === 461000, '6 posted for 2.000 MTL x 230,500 = 461,000.00', JSON.stringify(mv));
    await header(p, 'Credit Note'); await p.waitForSelector('.modal .o_form_view', { timeout: 15000 });
    await p.locator('.modal .o_field_widget[name="reason"] input, .modal .o_field_widget[name="reason"] textarea').first().fill('Training: wrong quantity');
    await p.locator('.modal-footer button', { hasText: /Reverse|Credit Note/ }).first().click(); await p.waitForSelector('.o_form_view', { timeout: 20000 }); await p.waitForTimeout(1200);
    await header(p, 'Confirm');
    const cn = await one('account.move', [['reversed_entry_id', '=', inv[0]]], ['state', 'amount_total']);
    ctx.check(cn && cn.state === 'posted' && cn.amount_total === 461000, '6 a posted credit note reverses it; the original invoice stays', JSON.stringify(cn));
    const bal = await admin.rpc('account.move.line', 'search_read', [[['partner_id', '=', mv.partner_id[0]], ['move_id', 'in', [inv[0]]], ['account_id.account_type', '=', 'asset_receivable']], ['amount_residual']]);
    ctx.check(bal.length && bal[0].amount_residual === 0, '6 the customer owes nothing for this invoice after the credit note', JSON.stringify(bal));
    await clean(s, '6 invoice and credit note screens are clean', m);
    for (const x of Object.values(sessions)) await x.close();
    await admin.close();
  },
};
