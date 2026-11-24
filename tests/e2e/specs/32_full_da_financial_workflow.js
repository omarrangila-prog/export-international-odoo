// One complete DA through the real screens at the client's window (1364x590), every result read back from the database:
// a commission coil and a direct coil (Copy Previous), a third coil added and removed (draft delete), a saved coil edited,
// submitted by the maker, approved by a different person in the Approvals centre, then the amounts in the supplier, Purchase (IN),
// customer and P&L ledgers, the From -> To trace and the feeding history report, to the paisa; the approved DA cancelled only by
// an approver with a reason (and gone from the approved ledgers); a whole draft DA deleted with a note on the supplier.
// DEMO parties, items and codes only.
module.exports = {
  name: '32 one complete DA: save, edit, delete, submit, approve, ledgers to the paisa, report, authorised cancel',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const stamp = String(Date.now()).slice(-6), DA = `DEMO-FULL-${stamp}`, DA_DEL = `DEMO-DEL-${stamp}`;
    const admin = await new Session(ctx, browser, 'admin', 'admin').start();
    await admin.rpc('ei.approval.policy', 'set_all', [true]);
    const one = async (model, domain, fields) => (await admin.rpc(model, 'search_read', [domain, fields], { limit: 1, order: 'id desc' }))[0];
    const lines = () => admin.rpc('ei.da.line', 'search_read', [[['da_id.name', '=', DA]], ['coil_no', 'mtl', 'weight_kg', 'feeding_method', 'purchase_rate', 'sale_rate', 'purchase_amount', 'sale_amount', 'gross_spread', 'currency_id']], { order: 'id' });
    const money = (v) => Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const s = await new Session(ctx, browser, 'demo.contracts', 'demo', [1364, 590], { timeout: 30000 }).start();
    const p = s.page; const m0 = s.mark(); let m = m0;
    const typeEnter = async (text) => { await p.keyboard.type(text, { delay: 25 }); await p.waitForTimeout(800); await p.keyboard.press('Enter'); await p.waitForTimeout(1300); };
    const txt = async (sel) => (await p.locator(sel).allInnerTexts().catch(() => [])).join(' | ').replace(/\s+/g, ' ');
    const newEntry = async (da) => {
      await p.goto(`${ctx.base}/odoo/action-ei_da_feeding.action_ei_new_feeding`); await p.waitForSelector('#ei-fd-daname', { timeout: 30000 }); await p.waitForTimeout(600);
      await p.locator('#ei-fd-daname').click(); await typeEnter(da);
      if (await p.locator('.ei-fd-supplier .ei-fd-picked').count()) await p.locator('.ei-fd-supplier .ei-fd-picked button').click();
      await p.locator('#ei-fd-supplier').click(); await typeEnter('DEMO Parent Steel');
      if (await p.locator('.ei-fd-pin .ei-fd-picked').count()) { await p.locator('.ei-fd-pin .ei-fd-picked button').click(); await p.waitForTimeout(300); }
      await p.locator('#ei-fd-pin').click(); await typeEnter('DEMO Buying'); await typeEnter('Rehman');
      await p.waitForSelector('#ei-fd-item, #ei-fd-coil', { timeout: 20000 }); await p.waitForTimeout(600);
    };
    const searchFor = async (page, text) => {          // type, Enter, and wait until Odoo shows the filter and has reloaded the list
      await page.locator('.o_searchview_input').fill(text); await page.keyboard.press('Enter');
      await page.waitForSelector(`.o_searchview_facet:has-text("${text}")`, { timeout: 15000 }).catch(() => {}); await page.waitForLoadState('networkidle').catch(() => {}); await page.waitForTimeout(900);
    };
    const openGroups = async (page) => { for (let k = 0; k < 3; k++) { const g = page.locator('.o_group_header:not(.o_group_open)').first(); if (!(await g.count())) break; await g.click({ timeout: 5000 }).catch(() => {}); await page.waitForTimeout(900); } };
    const openDa = async (page, da) => { await page.goto(`${ctx.base}/odoo/action-ei_da_feeding.action_ei_da_feeding`); await page.waitForSelector('.ei-fd-darow', { timeout: 30000 }); await page.locator('.ei-fd-darow', { hasText: da }).first().click(); await page.waitForSelector('h2.ei-fd-daname'); await page.waitForTimeout(600); };

    // 1. the DA and its first coil: Commission based (the mill's approved formula), 4.574 MTL, codes by themselves
    await newEntry(DA);
    if (await p.locator('#ei-fd-item').count()) await typeEnter('DEMO HR');
    await p.locator('#ei-fd-coil').fill(`F1-${stamp}`); await p.locator('#ei-fd-qty').fill('4.574');
    const commission = p.getByRole('radio', { name: /Commission based/ });
    const formulaOk = !(await commission.isDisabled());
    if (formulaOk) {
      await commission.click(); await p.waitForTimeout(300);
      await p.locator('.ei-fd-editor .ei-fd-rate input').fill('229500'); await p.locator('.ei-fd-editor .ei-fd-field:has-text("Sale = mill rate") input').fill('-1000');
    } else {
      await p.getByRole('radio', { name: /Direct \(no commission\)/ }).click(); await p.waitForTimeout(300);
      await p.locator('.ei-fd-editor .ei-fd-field:has-text("Purchase rate") input').fill('229500'); await p.locator('.ei-fd-editor .ei-fd-field:has-text("Sale rate") input').fill('230500');
    }
    await p.waitForSelector('.ei-fd-answer', { timeout: 30000 }); await p.waitForTimeout(500);
    await p.getByRole('button', { name: 'Save Entry' }).click(); await p.waitForTimeout(1800);
    let L = await lines();
    ctx.check(L.length === 1 && L[0].mtl === 4.574 && (formulaOk ? L[0].purchase_rate === 268051.41 && L[0].sale_rate === 270080.81 : L[0].purchase_rate === 229500),
      `1 coil 1 saved: 4.574 MTL, ${formulaOk ? 'Commission based 268,051.41 / 270,080.81 (the mill formula)' : 'Direct (the DEMO mill has no approved formula here)'}`, JSON.stringify(L[0]));

    // 2. coil 2 by Copy Previous, changed to Direct 229,500 / 230,500, 5 MTL
    await p.getByRole('button', { name: 'Copy Previous' }).click(); await p.waitForSelector('#ei-fd-coil');
    await p.locator('#ei-fd-coil').fill(`F2-${stamp}`); await p.locator('#ei-fd-qty').fill('5');
    await p.getByRole('radio', { name: /Direct \(no commission\)/ }).click(); await p.waitForTimeout(300);
    await p.locator('.ei-fd-editor .ei-fd-field:has-text("Purchase rate") input').fill('229500'); await p.locator('.ei-fd-editor .ei-fd-field:has-text("Sale rate") input').fill('230500');
    await p.waitForTimeout(1200); await p.getByRole('button', { name: 'Save Entry' }).click(); await p.waitForTimeout(1800);
    // 3. a third coil added by mistake and removed while the DA is a draft
    await p.getByRole('button', { name: 'Copy Previous' }).click(); await p.waitForSelector('#ei-fd-coil');
    await p.locator('#ei-fd-coil').fill(`F3-${stamp}`); await p.locator('#ei-fd-qty').fill('3'); await p.waitForTimeout(1200);
    await p.getByRole('button', { name: 'Save Entry' }).click(); await p.waitForTimeout(1800);
    ctx.check((await lines()).length === 3, '2 three coils on the draft (Copy Previous)');
    await p.locator('.ei-fd-table tbody tr', { hasText: `F3-${stamp}` }).first().getByRole('button', { name: 'Edit' }).click(); await p.waitForSelector('.ei-fd-editor');
    p.once('dialog', (dlg) => dlg.accept()); await p.getByRole('button', { name: 'Remove coil' }).click(); await p.waitForTimeout(1500);
    ctx.check((await lines()).length === 2 && !/F3-/.test(await txt('.ei-fd-table')), '3 draft delete: the mistaken coil is removed from the draft');
    // 4. a saved coil edited: 5 -> 6 MTL
    await p.locator('.ei-fd-table tbody tr', { hasText: `F2-${stamp}` }).first().getByRole('button', { name: 'Edit' }).click(); await p.waitForSelector('#ei-fd-qty');
    await p.locator('#ei-fd-qty').fill('6'); await p.waitForTimeout(1200); await p.getByRole('button', { name: 'Save Entry' }).click(); await p.waitForTimeout(1800);
    L = await lines();
    const c2 = L.find((l) => l.coil_no === `F2-${stamp}`);
    ctx.check(L.length === 2 && c2.mtl === 6 && c2.weight_kg === 6000 && c2.purchase_amount === 1377000 && c2.sale_amount === 1383000 && c2.gross_spread === 6000,
      '4 edit: coil 2 is now 6 MTL = 6,000 kg; purchase 1,377,000.00, sale 1,383,000.00, spread 6,000.00', JSON.stringify(c2));
    ctx.check(L.every((l) => /PKR/.test(l.currency_id[1])), '4 amounts are in PKR');
    await ctx.shot(p, '32_draft_two_coils');

    // 5. submitted by the maker; the maker cannot approve it
    await p.getByRole('button', { name: 'Submit for Approval' }).click(); await p.waitForSelector('.ei-fd-done.is-wait', { timeout: 30000 });
    const rec = await one('ei.da', [['name', '=', DA]], ['state', 'id']);
    let refused = false; try { await s.rpc('ei.da', 'action_approve', [[rec.id]]); } catch (e) { refused = true; }
    ctx.check(rec.state === 'under_review' && refused && /Pending approval|Waiting for review|Assignment required/.test(await txt('.ei-fd-done')),
      '5 submitted: the maker sees it waiting for the checker, and cannot approve it', rec.state + ' | ' + await txt('.ei-fd-done'));
    s.discard(m);
    await s.clean('1-5 the feeding screens are clean', m0);
    await s.close();

    // 6. a different person approves it in the Approvals centre (the real screen)
    const c = await new Session(ctx, browser, 'demo.contractapprover', 'demo', [1364, 590], { timeout: 30000 }).start();
    const cp = c.page; const cm = c.mark();
    await cp.goto(`${ctx.base}/odoo/action-ei_approvals.action_ei_approvals_center`).catch(() => {});
    if (!(await cp.locator('.ei-ap-page').count())) {
      await cp.goto(`${ctx.base}/odoo/action-ei_ui_theme.action_ei_home`); await cp.waitForSelector('.ei-home', { timeout: 60000 });
      await cp.locator('.o_menu_sections .dropdown-toggle, .o_menu_sections .o_nav_entry', { hasText: 'Approvals' }).first().click();
      await cp.locator('.o-dropdown--menu, .dropdown-menu').getByText('Approvals centre', { exact: true }).first().click();
    }
    await cp.waitForSelector('.ei-ap-page', { timeout: 30000 }); await cp.waitForTimeout(1200);
    await cp.locator('.ei-ap-card:visible, .ei-ap-table tbody tr:visible', { hasText: DA }).first().click(); await cp.waitForTimeout(1300);
    await cp.locator('.ei-ap-review button', { hasText: 'Approve' }).first().click();
    const ta = cp.locator('.ei-ap-ask textarea'); if (await ta.count()) await ta.fill('Checked: rates, weights and codes');
    await cp.locator('.ei-ap-ask-btns .is-primary, .ei-ap-ask .ei-ap-btn.is-primary').first().click(); await cp.waitForTimeout(2500);
    const appr = await one('ei.da', [['id', '=', rec.id]], ['state', 'approved_by']);
    const makerId = (await one('res.users', [['login', '=', 'demo.contracts']], ['id'])).id;
    ctx.check(appr.state === 'approved' && appr.approved_by && appr.approved_by[0] !== makerId, '6 approved by a different person in the Approvals centre', JSON.stringify(appr));

    // 7. ledgers and the report: the totals shown equal the coils, to the paisa
    L = await lines();
    const tot = (k) => L.reduce((a, l) => a + l[k], 0);
    const P = money(tot('purchase_amount')), S = money(tot('sale_amount')), G = money(tot('gross_spread'));
    for (const [act, what] of [['ei_ledger_supplier_action', 'supplier'], ['ei_ledger_pin_action', 'Purchase (IN)'], ['ei_ledger_customer_action', 'customer'], ['ei_ledger_pl_action', 'P&L']]) {
      await cp.goto(`${ctx.base}/odoo/action-ei_da_feeding.${act}`); await cp.waitForSelector('.o_list_view', { timeout: 30000 }); await cp.waitForTimeout(800);
      await searchFor(cp, DA);
      const t = (await cp.locator('.o_list_view').innerText()).replace(/\s+/g, ' ');
      ctx.check(t.includes(P) && t.includes(S) && t.includes(G), `7 ${what} ledger: purchase ${P}, sale ${S}, gross spread ${G} for this DA`, t.slice(0, 240));
    }
    await ctx.shot(cp, '32_pl_ledger');
    await cp.goto(`${ctx.base}/odoo/action-ei_da_feeding.ei_ledger_trace_action`); await cp.waitForSelector('.o_list_view', { timeout: 30000 });
    await searchFor(cp, DA);
    const tr = (await cp.locator('.o_list_view').innerText()).replace(/\s+/g, ' ');
    ctx.check(/DEMO Parent Steel Mill/.test(tr) && /DEMO Buying Entity/.test(tr) && /Rehman/.test(tr) && tr.includes(`F1-${stamp}`) && tr.includes(`F2-${stamp}`) && !tr.includes(`F3-${stamp}`),
      '7 From → IN → OUT trace: supplier, buying entity and customer on both coils; the deleted coil is not there', tr.slice(0, 240));
    await cp.goto(`${ctx.base}/odoo/action-ei_da_feeding.ei_feeding_history_action`); await cp.waitForSelector('.o_list_view, .o_pivot_view, .o_graph_view', { timeout: 30000 }); await cp.waitForTimeout(800);
    const sw = cp.locator('.o_control_panel .o_switch_view.o_list:visible'); if (await sw.count()) { await sw.first().click(); await cp.waitForSelector('.o_list_view'); }
    await searchFor(cp, `F1-${stamp}`); await openGroups(cp);   // its first search box is the coil number
    const hist = (await cp.locator('.o_list_view').innerText()).replace(/\s+/g, ' ');
    const c1 = L.find((l) => l.coil_no === `F1-${stamp}`);
    ctx.check(hist.includes(`F1-${stamp}`) && hist.includes(DA) && hist.includes(money(c1.gross_spread)), `7 the DA feeding history report finds coil F1 of ${DA} with its gross spread ${money(c1.gross_spread)}`, hist.slice(0, 240));
    await ctx.shot(cp, '32_history_report');
    await c.clean('6-7 approval, ledgers and report screens are clean', cm);

    // 8. authorised reversal: only an approver cancels an approved DA, with a reason; it then leaves the approved ledgers
    const mk = await new Session(ctx, browser, 'demo.contracts', 'demo').start();
    let makerRefused = false; try { await mk.rpc('ei.da', 'action_cancel', [[rec.id], 'maker tries']); } catch (e) { makerRefused = true; }
    let noReason = false; try { await c.rpc('ei.da', 'action_cancel', [[rec.id], '']); } catch (e) { noReason = true; }
    await c.rpc('ei.da', 'action_cancel', [[rec.id], 'TRAINING: DA withdrawn by the mill']);
    const cx = await one('ei.da', [['id', '=', rec.id]], ['state', 'cancel_reason']);
    const still = await admin.rpc('ei.da.line', 'search_count', [[['da_id', '=', rec.id], ['state', 'in', ['approved', 'fulfilled', 'closed']]]]);
    ctx.check(makerRefused && noReason && cx.state === 'cancelled' && /withdrawn/.test(cx.cancel_reason) && still === 0,
      '8 the maker cannot cancel an approved DA; an approver must give a reason; cancelled, it leaves the approved ledgers', JSON.stringify(cx));
    await c.close(); await mk.close();

    // 9. a whole draft DA deleted, with a note on the supplier
    const s2 = await new Session(ctx, browser, 'demo.contracts', 'demo', [1364, 590], { timeout: 30000 }).start();
    const q = s2.page;
    await q.goto(`${ctx.base}/odoo/action-ei_da_feeding.action_ei_new_feeding`); await q.waitForSelector('#ei-fd-daname', { timeout: 30000 });
    const id2 = await admin.rpc('ei.feeding.desk', 'da_create', [{ name: DA_DEL, supplier_id: (await one('res.partner', [['name', '=', 'DEMO Parent Steel Mill']], ['id'])).id,
      purchase_in_id: (await one('res.partner', [['name', 'ilike', 'DEMO Buying Entity']], ['id'])).id }]);
    await openDa(q, DA_DEL);
    q.once('dialog', (dlg) => dlg.accept()); await q.getByRole('button', { name: 'Delete draft' }).click(); await q.waitForTimeout(1500);
    const gone = await admin.rpc('ei.da', 'search_count', [[['id', '=', id2]]]);
    const note = await admin.rpc('mail.message', 'search_count', [[['model', '=', 'res.partner'], ['body', 'ilike', DA_DEL]]]);
    ctx.check(gone === 0 && note >= 1, '9 a draft DA deleted from the screen; the deletion is written on the supplier', JSON.stringify({ gone, note }));
    await s2.close();
    await admin.close();
  },
};
