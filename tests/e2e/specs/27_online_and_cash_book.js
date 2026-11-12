// Online Feeding and the Cash Book, as the client's old-system recording of 12 Nov 2026 shows them, with DEMO codes (the client's own
// codes stay out of this public repository): two online receipts of 100,000 and 200,000 (credit the party, debit the bank), the
// printed day book with 300,000 Dr = 300,000 Cr, a balance brought forward kept apart, a code that is not in the code list held back,
// Delete Draft, maker-checker, the ledgers by code, and the new top bar.
module.exports = {
  name: '27 online feeding and cash book: two-sided entries in the old codes, approval, ledgers, day book, top bar',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const stamp = String(Date.now()).slice(-6);
    const admin = await new Session(ctx, browser, 'admin', 'admin').start();
    await admin.rpc('ei.approval.policy', 'set_all', [true]);
    const one = async (model, domain, fields) => (await admin.rpc(model, 'search_read', [domain, fields], { limit: 1, order: 'id desc' }))[0];
    const logins = { 'DEMO Bankapprover': 'demo.bankapprover', 'DEMO Finance': 'demo.finance', 'DEMO Cashapprover': 'demo.cashapprover' };

    const s = await new Session(ctx, browser, 'demo.trainer', 'demo', [1440, 900], { timeout: 30000 }).start();
    const p = s.page; let m = s.mark();
    const bar = (await p.locator('.o_menu_sections').innerText()).replace(/\s+/g, ' ');
    ctx.check(/Online Feeding/.test(bar) && /New Feeding Entry/.test(bar) && /Cash Book/.test(bar) && /Daily Entries/.test(bar) && /Ledgers/.test(bar),
      '1 the top bar is the day: Online Feeding, New Feeding Entry, Cash Book, Daily Entries, Ledgers', bar.slice(0, 200));
    ctx.check(!/Practice/.test(bar) && !/DA feeding desk/.test(bar), '1 no practice page and no second feeding screen in the top bar');

    const pick = async (field, term) => {
      const inp = p.locator(`.o_field_widget[name=${field}] input`);
      await inp.click(); await inp.fill(''); await inp.pressSequentially(term, { delay: 40 });
      await p.locator('.o-autocomplete--dropdown-item', { hasText: term }).first().click(); await p.waitForTimeout(500);
    };
    const newOnline = async (amount, credit, debit, extra = {}) => {
      await s.menu('Online Feeding'); await p.waitForSelector('.o_list_view, .o_view_nocontent', { timeout: 30000 });
      await p.locator('.o_list_button_add, button.o-kanban-button-new').first().click(); await p.waitForSelector('.o_form_view');
      await p.locator('.o_field_widget[name=amount] input').fill(String(amount));
      await pick('credit_code_id', credit); await pick('debit_code_id', debit);
      await p.locator('.o_field_widget[name=credit_narration] input').fill(`RECEIVED ONLINE ${stamp}`);
      for (const [f, v] of Object.entries(extra)) await p.locator(`.o_field_widget[name=${f}] input`).fill(v);
    };
    // A: 100,000, credit the party, debit the bank
    await newOnline(100000, 'D.01', 'D.50', { proof_ref: `SMS-${stamp}-A` });
    const nameA = (await p.locator('.o_field_widget[name=credit_name]').innerText()).trim();
    ctx.check(/DEMO CUSTOMER/i.test(nameA), '2 typing the code shows its name at once (credit side)', nameA);
    await p.getByRole('button', { name: 'Save & Submit' }).click(); await p.waitForTimeout(2500);
    const stA = (await p.locator('.o_statusbar_status .o_arrow_button_current, .o_statusbar_status [aria-checked=true]').first().innerText()).trim();
    ctx.check(/Waiting for approval/i.test(stA), '2 Save & Submit: the entry waits for a different person', stA);
    const info = (await p.locator('.o_form_sheet .alert-info').first().innerText().catch(() => '')).replace(/\s+/g, ' ');
    ctx.check(/Checker: DEMO/.test(info), '2 the assigned checker is named on the entry', info.slice(0, 120));
    await ctx.shot(p, '27_online_entry_submitted');
    // B: 200,000
    await newOnline(200000, 'D.02', 'D.52', { proof_ref: `SMS-${stamp}-B` });
    await p.getByRole('button', { name: 'Save & Submit' }).click(); await p.waitForTimeout(2500);
    s.discard(m);
    // wrong code list: a customer code as the bank
    await newOnline(5, 'D.01', 'D.02');
    m = s.mark();
    await p.locator('.o_form_button_save').click(); await p.waitForTimeout(1500);
    const err = (await p.locator('.o_error_dialog, .modal-dialog, .o_notification').first().innerText().catch(() => '')).replace(/\s+/g, ' ');
    ctx.check(/not a BANK code/.test(err), '3 a customer code on the bank side is refused, in plain words', err.slice(0, 160));
    await p.keyboard.press('Escape'); await p.waitForTimeout(400);
    await p.locator('.o_form_button_cancel').click().catch(() => {}); await p.waitForTimeout(800);
    // the same SMS twice
    await newOnline(7, 'D.02', 'D.50', { proof_ref: `sms-${stamp}-a` });
    await p.locator('.o_form_button_save').click(); await p.waitForTimeout(1500);
    const dup = (await p.locator('.o_error_dialog, .modal-dialog, .o_notification').first().innerText().catch(() => '')).replace(/\s+/g, ' ');
    ctx.check(/already on DB\//.test(dup), '3 the same bank SMS reference cannot be fed twice', dup.slice(0, 160));
    await p.keyboard.press('Escape'); await p.waitForTimeout(400);
    await p.locator('.o_form_button_cancel').click().catch(() => {}); await p.waitForTimeout(800);
    s.discard(m); m = s.mark();

    // the checker decides (a different person); the maker cannot
    const rows = await admin.rpc('ei.daybook.entry', 'search_read', [[['credit_narration', '=', `RECEIVED ONLINE ${stamp}`], ['state', '=', 'submitted']], ['id', 'name', 'amount']], {});
    ctx.check(rows.length === 2, '4 two online entries wait for approval', JSON.stringify(rows));
    for (const r of rows) {
      const rq = await one('ei.approval.request', [['res_model', '=', 'ei.daybook.entry'], ['res_id', '=', r.id], ['state', '=', 'pending']], ['id', 'approver_id']);
      let refused = false; try { await s.rpc('ei.approval.request', 'decide', [rq.id, 'approve', 'mine']); } catch (e) { refused = /different person|not an authorised/.test(e.message); }
      if (r.amount === 100000) ctx.check(refused, '4 the maker cannot approve their own entry');
      const c = await new Session(ctx, browser, logins[rq.approver_id[1]] || 'demo.finance', 'demo').start();
      await c.rpc('ei.approval.request', 'decide', [rq.id, 'approve', 'Checked against the bank']);
      await c.close();
    }
    const after = await admin.rpc('ei.daybook.entry', 'search_read', [[['credit_narration', '=', `RECEIVED ONLINE ${stamp}`]], ['state', 'bank_status']], {});
    ctx.check(after.every((r) => r.state === 'approved') && after.every((r) => r.bank_status === 'proof'),
      '4 approved; still "proof received, not bank-confirmed" until a bank statement line is linked', JSON.stringify(after));

    // ledgers by code
    await s.menu('Ledgers', 'Bank & cash ledger'); await p.waitForSelector('.o_list_view', { timeout: 30000 }); await p.waitForTimeout(800);
    const groups = (await p.locator('.o_group_header').allInnerTexts()).join(' | ').replace(/\s+/g, ' ');
    ctx.check(/D\.50 DEMO BANK ONE/.test(groups) && /D\.52 DEMO BANK TWO/.test(groups), '5 bank & cash ledger: each bank code with its lines', groups.slice(0, 200));
    await p.locator('.o_group_header', { hasText: 'D.50 DEMO BANK ONE' }).click(); await p.waitForTimeout(800);
    const leg = (await p.locator('.o_data_row').first().innerText()).replace(/\s+/g, ' ');
    ctx.check(/100,000\.00/.test(leg) && /D\.01/.test(leg), '5 the bank line shows 100,000.00 Dr against the party code', leg.slice(0, 200));
    await ctx.shot(p, '27_bank_ledger');
    // the printed day book of today: 300,000 Dr = 300,000 Cr
    const wiz = await s.rpc('ei.daybook.print', 'create', [{ kind: 'online' }]);
    const html = await (await s.bctx.request.get(`${ctx.base}/report/html/ei_daybook.report_daybook/${wiz}`)).text();
    const flat = html.replace(/<[^>]+>/g, ' ').replace(/&nbsp;| /g, ' ').replace(/\s+/g, ' ');
    ctx.check(/Total of the entries\s*Rs\.\s*300,000\.00\s*Rs\.\s*300,000\.00/.test(flat), '6 printed day book: Cr 300,000.00 and Dr 300,000.00', (flat.match(/Total of the entries.{0,80}/) || [''])[0]);
    await s.clean('6 online feeding, ledgers and the day book are clean', m);

    // Cash Book: a balance brought forward, apart
    m = s.mark();
    await s.menu('Cash Book', 'Cash book entries'); await p.waitForSelector('.o_list_view, .o_view_nocontent', { timeout: 30000 });
    await p.locator('.o_list_button_add').first().click(); await p.waitForSelector('.o_form_view');
    await p.locator('.o_field_widget[name=kind] label', { hasText: 'Balance brought forward' }).click(); await p.waitForTimeout(500);
    await p.locator('.o_field_widget[name=amount] input').fill('14603760');
    await pick('credit_code_id', 'D.51');
    const debitHidden = !(await p.locator('.o_field_widget[name=debit_code_id]').isVisible());
    ctx.check(debitHidden, '7 a balance brought forward has one code: the second side disappears once it is chosen');
    await p.getByRole('button', { name: 'Save & Submit' }).click(); await p.waitForTimeout(2500);
    const ob = await one('ei.daybook.entry', [['kind', '=', 'opening'], ['amount', '=', 14603760]], ['state', 'name']);
    ctx.check(ob && ob.state === 'submitted', '7 the balance brought forward is submitted for approval like any entry', JSON.stringify(ob));
    // a cash entry whose debit code is not in the code list: kept as a draft, never submitted
    await s.menu('Cash Book', 'Cash book entries'); await p.waitForSelector('.o_list_view', { timeout: 30000 });
    await p.locator('.o_list_button_add').first().click(); await p.waitForSelector('.o_form_view'); await p.waitForTimeout(500);
    await p.locator('.o_field_widget[name=kind] label', { hasText: 'Cash book' }).click(); await p.waitForTimeout(300);
    await p.locator('.o_field_widget[name=amount] input').fill('10000000');
    await pick('credit_code_id', 'D.52');
    await p.locator('.o_field_widget[name=chq_no] input').fill(`CHQ-${stamp}`); await p.locator('.o_field_widget[name=slip_no] input').fill(`SLIP-${stamp}`);
    await p.locator('.o_field_widget[name=missing_code] input').fill('X.99'); await p.keyboard.press('Tab'); await p.waitForTimeout(800);
    await p.locator('.o_field_widget[name=missing_side] input').click(); await p.locator('.o_select_menu_item', { hasText: 'Debit' }).first().click();
    await p.locator('.o_form_button_save').click(); await p.waitForTimeout(1500);
    const warn = (await p.locator('.o_form_sheet .alert-warning').first().innerText().catch(() => '')).replace(/\s+/g, ' ');
    ctx.check(/X\.99 is not in the code list/.test(warn), '8 the code that is not in the list is shown as needing the accountant', warn.slice(0, 160));
    const m2 = s.mark();
    await p.getByRole('button', { name: 'Save & Submit' }).click(); await p.waitForTimeout(1500);
    const blk = (await p.locator('.o_error_dialog, .modal-dialog').first().innerText().catch(() => '')).replace(/\s+/g, ' ');
    ctx.check(/X\.99 is not in the code list/.test(blk), '8 it cannot be submitted: nothing is guessed', blk.slice(0, 160));
    await p.keyboard.press('Escape'); await p.waitForTimeout(500); s.discard(m2);
    // Delete Draft: the held-back entry is deleted, and the deletion is recorded
    const draft = await one('ei.daybook.entry', [['chq_no', '=', `CHQ-${stamp}`]], ['name', 'state']);
    ctx.check(draft && draft.state === 'draft', '9 it stays a draft', JSON.stringify(draft));
    p.once('dialog', (d) => d.accept());
    await p.getByRole('button', { name: 'Delete draft' }).click(); await p.waitForTimeout(800);
    const modalOk = p.locator('.modal-footer .btn-primary'); if (await modalOk.count()) { await modalOk.first().click(); }
    await p.waitForTimeout(2000);
    const gone = await admin.rpc('ei.daybook.entry', 'search_count', [[['chq_no', '=', `CHQ-${stamp}`]]]);
    const logged = await admin.rpc('ei.daybook.deleted', 'search_count', [[['name', '=', draft.name]]]);
    ctx.check(gone === 0 && logged === 1, '9 Delete draft removes it and records who deleted it', `left ${gone}, logged ${logged}`);
    await s.clean('9 the cash book screens are clean', m);
    await s.close();

    // phone: the online entry form fits
    const ph = await new Session(ctx, browser, 'demo.trainer', 'demo', [390, 844], { timeout: 30000 }).start();
    await ph.page.goto(`${ctx.base}/odoo/action-ei_daybook.ei_daybook_online_action/new`); await ph.page.waitForSelector('.o_form_view', { timeout: 30000 });
    const fit = await ph.page.evaluate(() => ({ over: document.documentElement.scrollWidth > innerWidth + 1,
      inside: [...document.querySelectorAll('.o_field_widget[name=amount], .o_field_widget[name=credit_code_id], .o_field_widget[name=debit_code_id]')]
        .every((e) => { const r = e.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth + 0.5 && r.width > 100; }) }));
    ctx.check(!fit.over && fit.inside, '10 on a phone the amount and both codes fit the screen', JSON.stringify(fit));
    await ctx.shot(ph.page, '27_phone_online');
    await ph.close();
    await admin.close();
  },
};
