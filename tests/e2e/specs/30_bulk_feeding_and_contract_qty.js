// The client's 22 Nov 2026 requests, in the real browser: the DA paper is optional and sits in a small "Attach DA (Optional)"
// button at the top right (upload, preview, replace, remove, kept after reopening); Copy Previous; Add Multiple Coils (20 and 50
// rows, one shared rate, pasted columns, saved together, never twice); Apply Rate to Selected with a confirmation and a correction;
// the contract quantity (500 MTL, 425 entered, 75 remaining; +50 -> 25; over-allocation refused, also between two people at once);
// submit -> a different person approves -> ledgers; and every control reachable on laptops, zoom levels and phones.
// DEMO parties, items and codes only. Every outcome is read back from the database.
module.exports = {
  name: '30 bulk feeding: optional paper, copy previous, 20/50 coils, apply rate, contract quantity, approval, sizes',
  async run(ctx, browser) {
    const { Session, synthPdf } = require('../lib');
    const stamp = String(Date.now()).slice(-6), DA_A = `DA-BULK-${stamp}`, DA_PRE = `DA-DEC-PRE-${stamp}`, DA_F = `DA-DEC-${stamp}`;
    const admin = await new Session(ctx, browser, 'admin', 'admin').start();
    await admin.rpc('ei.approval.policy', 'set_all', [true]);
    const one = async (model, domain, fields) => (await admin.rpc(model, 'search_read', [domain, fields], { limit: 1, order: 'id desc' }))[0];
    const all = async (model, domain, fields) => admin.rpc(model, 'search_read', [domain, fields], { order: 'id' });
    const count = async (model, domain) => admin.rpc(model, 'search_count', [domain]);
    const lines = (da, extra = []) => all('ei.da.line', [['da_id.name', '=', da], ...extra], ['coil_no', 'mtl', 'purchase_rate', 'sale_rate', 'customer_id', 'feeding_method']);
    const s = await new Session(ctx, browser, 'demo.contracts', 'demo', [1440, 900], { timeout: 30000 }).start();
    const p = s.page; const m0 = s.mark(); let m = m0;
    const typeEnter = async (text) => { await p.keyboard.type(text, { delay: 30 }); await p.waitForTimeout(700); await p.keyboard.press('Enter'); await p.waitForTimeout(1300); };
    const txt = async (sel) => (await p.locator(sel).first().innerText().catch(() => '')).replace(/\s+/g, ' ');
    const openDa = async (page, da) => {
      await page.goto(`${ctx.base}/odoo/action-ei_da_feeding.action_ei_da_feeding`); await page.waitForSelector('.ei-fd-darow', { timeout: 30000 });
      await page.locator('.ei-fd-darow', { hasText: da }).first().click(); await page.waitForSelector('h2.ei-fd-daname'); await page.waitForTimeout(700);
    };
    const newEntry = async (da) => {
      await p.goto(`${ctx.base}/odoo/action-ei_da_feeding.action_ei_new_feeding`); await p.waitForSelector('#ei-fd-daname', { timeout: 30000 }); await p.waitForTimeout(600);
      await p.locator('#ei-fd-daname').click(); await typeEnter(da);
      if (await p.locator('.ei-fd-supplier .ei-fd-picked').count()) await p.locator('.ei-fd-supplier .ei-fd-picked button').click();
      await p.locator('#ei-fd-supplier').click(); await typeEnter('DEMO Parent Steel');
      if (await p.locator('.ei-fd-pin .ei-fd-picked').count()) { await p.locator('.ei-fd-pin .ei-fd-picked button').click(); await p.waitForTimeout(300); }
      await p.locator('#ei-fd-pin').click(); await typeEnter('DEMO Buying');
      await typeEnter('Rehman');
      await p.waitForSelector('#ei-fd-item, #ei-fd-coil', { timeout: 20000 }); await p.waitForTimeout(500);
    };
    // the first coil by keyboard: item, coil, weight (MTL), sales code, direct 229,500 / 230,500, Save Entry
    const firstCoil = async (coil, mtl) => {
      if (await p.locator('#ei-fd-item').count()) await typeEnter('DEMO HR');          // an account with one item takes it by itself
      await p.locator('#ei-fd-coil').click(); await typeEnter(coil);
      await p.keyboard.press('Enter'); await p.keyboard.press('Enter'); await p.keyboard.press('Enter'); await p.waitForTimeout(300);
      await p.keyboard.type(mtl, { delay: 30 }); await p.keyboard.press('Enter'); await p.waitForTimeout(400);
      await p.keyboard.press('Enter'); await p.waitForSelector('#ei-fd-look'); await typeEnter('D.01');
      await p.getByRole('radio', { name: /Direct purchase/ }).click(); await p.waitForTimeout(400);
      await p.keyboard.type('229500', { delay: 25 }); await p.keyboard.press('Enter'); await p.waitForTimeout(300);
      await p.keyboard.type('230500', { delay: 25 }); await p.waitForTimeout(1300);
      await p.getByRole('button', { name: 'Save Entry' }).click(); await p.waitForTimeout(1800);
    };
    const paste = (loc, text) => loc.evaluate((el, t) => { const dt = new DataTransfer(); dt.setData('text/plain', t); el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true })); }, text);

    // ---------------------------------------------------------------- A: the paper is optional, small, at the top right
    await newEntry(DA_A);
    const head = await p.locator('.ei-fd-dahead').boundingBox(), btn = await p.locator('.ei-fd-attachbtn').boundingBox();
    ctx.check(/Attach DA\s*\(Optional\)/.test(await txt('.ei-fd-attachbtn')) && btn && head && btn.x + btn.width > head.x + head.width * 0.6 && btn.y < head.y + 60 && btn.height <= 44,
      'A1 "Attach DA (Optional)" is a small button at the top right of the entry', JSON.stringify({ btn, head }));
    ctx.check(await p.locator('.ei-fd-split input[type=file]').count() === 0 && !(await p.locator('.ei-fd-docframe, .ei-fd-docimg').count()),
      'A1 no paper card in the middle of the form (no upload box, no preview) until the button is pressed');
    await firstCoil('BK-01', '5');
    ctx.check(await count('ei.da.line', [['da_id.name', '=', DA_A]]) === 1 && await count('ir.attachment', [['res_model', '=', 'ei.da'], ['res_id', '=', (await one('ei.da', [['name', '=', DA_A]], ['id'])).id]]) === 0
      && !/attach/i.test(await txt('.ei-fd-error')), 'A2 a coil is saved with no paper and no "attach the paper" message');
    await ctx.shot(p, '30_A_attach_button');
    const daA = (await one('ei.da', [['name', '=', DA_A]], ['id'])).id;
    await p.locator('.ei-fd-attachbtn').click(); await p.waitForSelector('.ei-fd-docpop');
    ctx.check(/optional/i.test(await txt('.ei-fd-docpop')), 'A3 the panel says the paper is optional');
    await p.locator('.ei-fd-docpop input.ei-fd-docfile').setInputFiles({ ...synthPdf(), name: `DA-${stamp}.pdf` }); await p.waitForTimeout(1800);
    ctx.check(await p.locator('.ei-fd-docpop iframe.ei-fd-docframe').count() === 1 && new RegExp(`DA-${stamp}\\.pdf`).test(await txt('.ei-fd-attachbtn')),
      'A4 upload: the file name shows on the button and the PDF preview opens in the panel', await txt('.ei-fd-attachbtn'));
    await ctx.shot(p, '30_A_paper_preview');
    await p.locator('.ei-fd-docpop label', { hasText: 'Replace' }).locator('input').setInputFiles({ ...synthPdf('TRAINING ONLY - second copy'), name: `DA-${stamp}-v2.pdf` }); await p.waitForTimeout(1800);
    const atts = await all('ir.attachment', [['res_model', '=', 'ei.da'], ['res_id', '=', daA]], ['name']);
    const notes = (await all('mail.message', [['model', '=', 'ei.da'], ['res_id', '=', daA]], ['body'])).map((x) => x.body).join(' ');
    ctx.check(atts.length === 1 && atts[0].name === `DA-${stamp}-v2.pdf` && /replaced by/.test(notes), 'A5 replace: the new file takes its place and the replacement is written on the DA', JSON.stringify(atts));
    await p.locator('.ei-fd-docpop').getByRole('button', { name: 'Close' }).click();
    await openDa(p, DA_A);
    ctx.check(new RegExp(`DA-${stamp}-v2\\.pdf`).test(await txt('.ei-fd-attachbtn')), 'A6 reopened: the attached paper is still there');

    // ---------------------------------------------------------------- B: Copy Previous
    await p.getByRole('button', { name: 'Copy Previous' }).click(); await p.waitForSelector('#ei-fd-coil'); await p.waitForTimeout(1200);
    const ed = await txt('.ei-fd-editor');
    const coilVal = await p.locator('#ei-fd-coil').inputValue(), qtyVal = await p.locator('#ei-fd-qty').inputValue();
    const pr = await p.locator('.ei-fd-editor .ei-fd-field', { hasText: 'Purchase rate / MTL' }).locator('input').inputValue();
    const sr = await p.locator('.ei-fd-editor .ei-fd-field', { hasText: 'Sale rate / MTL' }).locator('input').inputValue();
    ctx.check(coilVal === '' && qtyVal === '' && /DEMO HR/.test(ed) && /D\.01/.test(ed) && /Rehman/.test(ed) && pr === '229500' && sr === '230500',
      'B1 Copy Previous: item, Sold OUT, codes, method and both rates are copied; coil number and weight are empty', JSON.stringify({ coilVal, qtyVal, pr, sr }));
    await p.fill('#ei-fd-coil', 'BK-02'); await p.fill('#ei-fd-qty', '5.12'); await p.waitForTimeout(1300);
    await p.getByRole('button', { name: 'Save Entry' }).click(); await p.waitForTimeout(1800);
    const b2 = (await lines(DA_A, [['coil_no', '=', 'BK-02']]))[0];
    ctx.check(b2 && b2.mtl === 5.12 && b2.purchase_rate === 229500 && b2.sale_rate === 230500 && /10\.120/.test(await txt('.ei-fd-table tfoot')),
      'B2 the copied coil saves with its own weight; the DA total is 10.120 MTL', JSON.stringify(b2) + ' ' + await txt('.ei-fd-table tfoot'));

    // ---------------------------------------------------------------- C: 20 coils in one action, one shared rate, saved together
    await p.getByRole('button', { name: 'Add Multiple Coils' }).click(); await p.waitForSelector('.ei-fd-bulk');
    await p.locator('.ei-fd-nrows', { hasText: /^20$/ }).click(); await p.locator('.ei-fd-addrows').click(); await p.waitForTimeout(500);
    ctx.check(await p.locator('.ei-fd-btable tbody tr').count() === 20 && /DEMO HR/.test(await txt('.ei-fd-bshared')), 'C1 Add Rows: 20 editable coil rows on the same screen, sharing the previous coil\'s details');
    await p.locator('.ei-fd-bsale').fill('231000');                                     // the shared rate for all 20
    await p.locator('.ei-fd-bcoil').first().click();
    for (let i = 1; i <= 20; i++) { await p.keyboard.type(`BC-${String(i).padStart(2, '0')}`, { delay: 8 }); await p.keyboard.press('Enter'); await p.keyboard.type(String(4 + i / 100), { delay: 8 }); await p.keyboard.press('Enter'); }
    await p.waitForTimeout(400);
    const focusIsSave = await p.evaluate(() => document.activeElement && document.activeElement.classList.contains('ei-fd-bsave'));
    const sum20 = Array.from({ length: 20 }, (_, i) => 4000 + (i + 1) * 10).reduce((a, b) => a + b, 0) / 1000;
    ctx.check(focusIsSave && new RegExp(sum20.toFixed(3).replace('.', '\\.')).test(await txt('.ei-fd-btable tfoot')), `C2 typed with Enter row by row; after the last weight Enter stops on "Save all"; ${sum20.toFixed(3)} MTL on 20 rows`, await txt('.ei-fd-btable tfoot'));
    await ctx.shot(p, '30_C_twenty_rows');
    await p.locator('.ei-fd-bsave').click(); await p.waitForSelector('.ei-fd-bulk', { state: 'detached', timeout: 30000 }); await p.waitForTimeout(800);
    const c20 = await lines(DA_A, [['coil_no', '=like', 'BC-%']]);
    ctx.check(c20.length === 20 && c20.every((l) => l.sale_rate === 231000 && l.purchase_rate === 229500 && /Rehman/.test(l.customer_id[1])) && Math.abs(c20.reduce((a, l) => a + l.mtl, 0) - sum20) < 1e-6,
      'C3 the 20 coils are saved together, each its own record, with the shared rate (229,500 / 231,000) and customer', String(c20.length));
    await openDa(p, DA_A);
    ctx.check(await p.locator('.ei-fd-table tbody tr').count() === 22 && new RegExp((10.12 + sum20).toFixed(3).replace('.', '\\.')).test(await txt('.ei-fd-table tfoot')),
      'C4 reopened: 22 coils and the right total', await txt('.ei-fd-table tfoot'));

    // ---------------------------------------------------------------- D: 50 coils, pasted from Excel, Save pressed twice
    await p.getByRole('button', { name: 'Add Multiple Coils' }).click(); await p.waitForSelector('.ei-fd-bulk');
    await p.locator('.ei-fd-bcount').fill('50'); const t0 = Date.now(); await p.locator('.ei-fd-bcount').press('Enter');
    await p.waitForFunction(() => document.querySelectorAll('.ei-fd-btable tbody tr').length === 50, null, { timeout: 10000 }); const addMs = Date.now() - t0;
    const excel = Array.from({ length: 50 }, (_, i) => `BD-${String(i + 1).padStart(2, '0')}\t5`).join('\r\n');
    const t1 = Date.now(); await paste(p.locator('.ei-fd-bcoil').first(), excel); await p.waitForFunction(() => { const r = document.querySelectorAll('.ei-fd-bqty'); return r.length === 50 && r[49].value === '5'; }, null, { timeout: 10000 });
    const pasteMs = Date.now() - t1;
    ctx.check(addMs < 3000 && pasteMs < 3000 && /250\.000/.test(await txt('.ei-fd-btable tfoot')), `D1 50 rows appear in ${addMs} ms; two columns pasted from Excel fill all 50 in ${pasteMs} ms; 250.000 MTL`, await txt('.ei-fd-btable tfoot'));
    await p.locator('.ei-fd-bqty').nth(49).fill('5.5'); await p.waitForTimeout(200);
    ctx.check(/250\.500/.test(await txt('.ei-fd-btable tfoot')), 'D2 one row changed alone: the total follows (250.500 MTL)');
    await ctx.shot(p, '30_D_fifty_rows');
    await p.locator('.ei-fd-bsave').dblclick(); await p.waitForSelector('.ei-fd-bulk', { state: 'detached', timeout: 60000 }); await p.waitForTimeout(1500);
    const c50 = await lines(DA_A, [['coil_no', '=like', 'BD-%']]);
    ctx.check(c50.length === 50 && Math.abs(c50.reduce((a, l) => a + l.mtl, 0) - 250.5) < 1e-6 && await count('ei.da.line', [['da_id.name', '=', DA_A]]) === 72,
      'D3 Save pressed twice: exactly 50 coils were added (72 on the DA), total exact', String(c50.length));

    // ---------------------------------------------------------------- E: Apply Rate to Selected, a wrong rate and its correction
    const tick = async (coil) => p.locator('.ei-fd-table tbody tr', { hasText: coil }).first().locator('.ei-fd-selrow').check();
    const five = ['BD-01', 'BD-02', 'BD-03', 'BD-04', 'BD-05'];
    for (const c of five) await tick(c);
    ctx.check(/5 coil/.test(await txt('.ei-fd-ratebar .ei-fd-step')), 'E1 five rows selected: the "Apply Rate to Selected" bar opens');
    await p.locator('.ei-fd-rpurchase').fill('230000'); await p.locator('.ei-fd-rapply').click(); await p.waitForSelector('.ei-fd-rconfirm');
    const conf = await txt('.ei-fd-rconfirm');
    ctx.check(/Apply this rate to 5 selected coil/.test(conf) && /5,737,500\.00 → 5,750,000\.00/.test(conf), 'E2 a confirmation first: "Apply this rate to 5 selected coils?" with the purchase total before and after', conf.slice(0, 220));
    ctx.check((await lines(DA_A, [['coil_no', 'in', five]])).every((l) => l.purchase_rate === 229500), 'E2 nothing changes before Yes');
    await ctx.shot(p, '30_E_confirm');
    await p.locator('.ei-fd-ryes').click(); await p.waitForTimeout(2000);
    ctx.check((await lines(DA_A, [['coil_no', 'in', five]])).every((l) => l.purchase_rate === 230000), 'E3 the (wrong) rate 230,000 is on the 5 selected coils');
    for (const c of five) await tick(c);
    await p.locator('.ei-fd-rpurchase').fill('229500'); await p.locator('.ei-fd-rapply').click(); await p.waitForSelector('.ei-fd-rconfirm'); await p.locator('.ei-fd-ryes').click(); await p.waitForTimeout(2000);
    const fixedRows = await lines(DA_A, [['coil_no', 'in', five]]), others = await lines(DA_A, [['coil_no', 'not in', five]]);
    ctx.check(fixedRows.every((l) => l.purchase_rate === 229500 && l.sale_rate === 231000) && others.every((l) => l.purchase_rate === 229500)
      && others.filter((l) => /^BK-/.test(l.coil_no)).every((l) => l.sale_rate === 230500),
      'E4 corrected once for the 5 selected (purchase back to 229,500; their sale rate 231,000 untouched); the other 67 coils keep their own rates', JSON.stringify(fixedRows.map((l) => [l.coil_no, l.purchase_rate, l.sale_rate])));
    await p.locator('.ei-fd-selall').check(); await p.waitForTimeout(300);
    ctx.check(/72 coil/.test(await txt('.ei-fd-ratebar .ei-fd-step')), 'E5 Select All selects the 72 coils');
    await p.locator('.ei-fd-selall').uncheck();

    // ---------------------------------------------------------------- F: contract quantity 500 MTL, 425 entered, 75 remaining
    const pa = await one('ei.da', [['name', '=', DA_A]], ['parent_partner_id', 'purchase_in_id', 'sold_out_id']);       // the same three parties as typed above
    const sup = pa.parent_partner_id[0], pin = pa.purchase_in_id[0], cust = pa.sold_out_id[0];
    const pre = await admin.rpc('ei.feeding.desk', 'da_create', [{ supplier_id: sup, purchase_in_id: pin, sold_out_id: cust, name: DA_PRE }]);
    const bk1 = await one('ei.da.line', [['da_id.name', '=', DA_A], ['coil_no', '=', 'BK-01']], ['product_id', 'customer_code_id']);
    const prod = bk1.product_id[0];
    const cl = (await admin.rpc('ei.feeding.desk', 'ensure_line', [pre, prod])).contract_line_id;
    await admin.rpc('ei.feeding.desk', 'quota_create', [pre, `December 2026 ${stamp}`, '500']);
    const shared = { contract_line_id: cl, method: 'direct_no_commission', purchase_rate: '229500', sale_rate: '230500', customer_id: cust, customer_code_id: bk1.customer_code_id[0] };
    await admin.rpc('ei.feeding.desk', 'save_lines', [pre, shared, Array.from({ length: 85 }, (_, i) => ({ coil_no: `PRE-${i + 1}`, weight_kg: '5000' }))]);   // 425 MTL already fed
    await newEntry(DA_F);
    const strip = await txt('.ei-fd-quota');
    ctx.check(/Total 500\.000 MTL/.test(strip) && /Entered 425\.000/.test(strip) && /Remaining to enter 75\.000 MTL/.test(strip),
      'F1 the new DA joins the supplier\'s open contract by itself: Total 500.000, Entered 425.000, Remaining 75.000 MTL', strip);
    await ctx.shot(p, '30_F_500_425_75');
    await firstCoil('F-01', '5');
    await p.getByRole('button', { name: 'Add Multiple Coils' }).click(); await p.waitForSelector('.ei-fd-bulk');
    await p.locator('.ei-fd-bcount').fill('9'); await p.locator('.ei-fd-bcount').press('Enter'); await p.waitForTimeout(300);
    await paste(p.locator('.ei-fd-bcoil').first(), Array.from({ length: 9 }, (_, i) => `F-${String(i + 2).padStart(2, '0')}\t5`).join('\n')); await p.waitForTimeout(300);
    ctx.check(/remaining 25\.000 MTL/.test(await txt('.ei-fd-bulk')), 'F2 before saving the batch, the screen shows what will remain (25.000 MTL)', (await txt('.ei-fd-bulk')).slice(-160));
    await p.locator('.ei-fd-bsave').click(); await p.waitForSelector('.ei-fd-bulk', { state: 'detached', timeout: 30000 }); await p.waitForTimeout(800);
    ctx.check(/Entered 475\.000/.test(await txt('.ei-fd-quota')) && /Remaining to enter 25\.000 MTL/.test(await txt('.ei-fd-quota')), 'F3 a batch of 50 MTL: entered 475.000, remaining 25.000 MTL', await txt('.ei-fd-quota'));
    m = s.mark();
    await p.getByRole('button', { name: 'Copy Previous' }).click(); await p.waitForSelector('#ei-fd-coil'); await p.fill('#ei-fd-coil', 'F-OVER'); await p.fill('#ei-fd-qty', '30'); await p.waitForTimeout(1300);
    ctx.check(/Only 25\.000 MTL remains/.test(await txt('.ei-fd-overq')), 'F4 a 30 MTL coil: the screen warns before saving ("Only 25.000 MTL remains")');
    await p.getByRole('button', { name: 'Save Entry' }).click(); await p.waitForTimeout(1800);
    ctx.check(await count('ei.da.line', [['coil_no', '=', 'F-OVER']]) === 0 && /more than the total/.test(await txt('.ei-fd-error')), 'F4 and the server refuses it: nothing is saved past the contract', await txt('.ei-fd-error'));
    await p.locator('.ei-fd-editor').getByRole('button', { name: 'Close', exact: true }).click();
    await p.locator('.ei-fd-table tbody tr', { hasText: 'F-01' }).first().getByRole('button', { name: 'Edit' }).click(); await p.waitForSelector('#ei-fd-qty');
    await p.fill('#ei-fd-qty', '31'); await p.waitForTimeout(1300); await p.getByRole('button', { name: 'Save Entry' }).click(); await p.waitForTimeout(1500);
    ctx.check((await lines(DA_F, [['coil_no', '=', 'F-01']]))[0].mtl === 5 && /more than the total/.test(await txt('.ei-fd-error')), 'F5 editing a draft coil past the total (5 -> 31 MTL) is refused too');
    await p.locator('.ei-fd-editor').getByRole('button', { name: 'Close', exact: true }).click();
    s.discard(m);                                         // the two refusals above were provoked on purpose
    await p.locator('.ei-fd-table tbody tr', { hasText: 'F-02' }).first().getByRole('button', { name: 'Edit' }).click(); await p.waitForSelector('.ei-fd-editor');
    p.once('dialog', (dlg) => dlg.accept()); await p.getByRole('button', { name: 'Remove coil' }).click(); await p.waitForTimeout(1500);
    ctx.check(/Remaining to enter 30\.000 MTL/.test(await txt('.ei-fd-quota')), 'F6 removing a draft coil gives its 5 MTL back: remaining 30.000 MTL', await txt('.ei-fd-quota'));
    // two people at the same moment, 20 MTL each, 30 MTL left: exactly one is accepted
    const s2 = await new Session(ctx, browser, 'demo.contractapprover', 'demo', [1280, 800], { timeout: 30000 }).start();
    const daF = (await one('ei.da', [['name', '=', DA_F]], ['id'])).id;
    const race = await Promise.allSettled([
      s.rpc('ei.feeding.desk', 'save_line', [daF, false, { ...shared, coil_no: 'RACE-A', weight_kg: '20000' }]),
      s2.rpc('ei.feeding.desk', 'save_line', [pre, false, { ...shared, coil_no: 'RACE-B', weight_kg: '20000' }]),
    ]);
    const won = await count('ei.da.line', [['coil_no', 'in', ['RACE-A', 'RACE-B']]]);
    const q = await one('ei.feeding.quota', [['name', '=', `December 2026 ${stamp}`]], ['entered_mtl', 'remaining_mtl', 'total_mtl']);
    ctx.check(won === 1 && q.entered_mtl === 490 && q.remaining_mtl === 10, 'F7 two people save 20 MTL each at the same moment with 30 MTL left: one is accepted, one refused; 490 entered, 10 remaining',
      JSON.stringify({ won, q, r: race.map((r) => r.status) }));

    // ---------------------------------------------------------------- G: submit -> another person approves -> quantities and ledgers
    await openDa(p, DA_F);
    m = s.mark();
    await p.getByRole('button', { name: 'Submit for Approval' }).click(); await p.waitForSelector('.ei-fd-done.is-wait', { timeout: 30000 });
    const recF = await one('ei.da', [['name', '=', DA_F]], ['state', 'id']);
    ctx.check(recF.state === 'under_review', 'G1 the maker submits the DA with its coils for approval (no paper needed)', recF.state);
    await ctx.shot(p, '30_G_submitted');
    let refused = false; try { await s.rpc('ei.da', 'action_approve', [[recF.id]]); } catch (e) { refused = true; }
    ctx.check(refused && (await one('ei.da', [['id', '=', recF.id]], ['state'])).state === 'under_review', 'G2 the maker cannot approve their own DA');
    s.discard(m);
    const rq = await one('ei.approval.request', [['res_model', '=', 'ei.da'], ['res_id', '=', recF.id]], ['id']);
    await s2.rpc('ei.approval.request', 'decide', [rq.id, 'approve', 'Checked against the contract']);
    const after = await one('ei.da', [['id', '=', recF.id]], ['state', 'approved_by', 'total_mtl']);
    const maker = (await one('res.users', [['login', '=', 'demo.contracts']], ['id'])).id;
    const q2 = await one('ei.feeding.quota', [['name', '=', `December 2026 ${stamp}`]], ['entered_mtl', 'confirmed_mtl', 'remaining_mtl']);
    ctx.check(after.state === 'approved' && after.approved_by && after.approved_by[0] !== maker && Math.abs(q2.confirmed_mtl - after.total_mtl) < 1e-6 && q2.entered_mtl === 490,
      `G3 a different person approves; the contract shows ${after.total_mtl.toFixed(3)} MTL confirmed (this DA) of 490.000 entered`, JSON.stringify({ after, q2 }));
    const sp = s2.page;
    await sp.goto(`${ctx.base}/odoo/action-ei_da_feeding.ei_ledger_trace_action`); await sp.waitForSelector('.o_list_view', { timeout: 30000 }); await sp.waitForTimeout(800);
    await sp.locator('.o_searchview_input').fill(DA_F); await sp.keyboard.press('Enter'); await sp.waitForTimeout(1500);
    const tr = (await sp.locator('.o_list_view').innerText()).replace(/\s+/g, ' ');
    ctx.check(/F-01/.test(tr) && /DEMO Parent Steel Mill/.test(tr) && /Rehman/.test(tr) && /229,500/.test(tr), 'G4 From -> To trace lists the approved coils with supplier, customer and rates', tr.slice(0, 200));
    await openDa(sp, DA_PRE);                              // an approved DA leaves the recent list: the earlier DA on the same contract shows it
    await sp.locator('.ei-fd-quota').getByRole('button', { name: 'Details' }).click(); await sp.waitForTimeout(300);
    const qd = (await sp.locator('.ei-fd-quota').innerText()).replace(/\s+/g, ' ');
    ctx.check(new RegExp('Confirmed ' + after.total_mtl.toFixed(3).replace('.', '\\.')).test(qd) && /Remaining to enter 10\.000 MTL/.test(qd), 'G5 the contract strip (on the other DA of the same contract) shows the confirmed quantity and 10.000 MTL remaining', qd);
    await s2.close();
    await s.clean('A-G the feeding screens are clean (refusals provoked on purpose are excluded)', m0);
    await s.close();

    // ---------------------------------------------------------------- H: laptops, zoom and phones
    const sizes = [['1366x768 100%', 1366, 768], ['1366x768 125%', 1093, 614], ['1366x768 150%', 911, 512], ['1366x768 200%', 683, 384],
      ['1280x720', 1280, 720], ['1024x768', 1024, 768], ['phone 390', 390, 844], ['phone 320', 320, 568]];
    for (const [label, w, h] of sizes) {
      const v = await new Session(ctx, browser, 'demo.contracts', 'demo', [w, h], { timeout: 30000 }).start();
      const g = v.page;
      try {
        await openDa(g, DA_A);
        const reach = (want) => g.evaluate((w) => {
          const ok = (el) => { if (!el) return false; el.scrollIntoView({ block: 'center', inline: 'center' }); const b = el.getBoundingClientRect(); const t = document.elementFromPoint(b.left + Math.min(8, b.width / 2), b.top + b.height / 2); return !!t && (t === el || el.contains(t) || t.contains(el)); };
          const res = {}; for (const [k, sel] of Object.entries(w)) res[k] = ok(document.querySelector(sel));
          res.overflow = document.documentElement.scrollWidth > innerWidth + 1;
          return res;
        }, want);
        await g.locator('.ei-fd-table tbody tr').first().locator('.ei-fd-selrow').check(); await g.waitForTimeout(300);
        const r1 = await reach({ attach: '.ei-fd-attachbtn', quota: '.ei-fd-quota', selall: '.ei-fd-selall', rateBox: '.ei-fd-rpurchase', apply: '.ei-fd-rapply' });
        await g.locator('.ei-fd-selall').uncheck(); await g.waitForTimeout(200);
        await g.getByRole('button', { name: 'Add Multiple Coils' }).click(); await g.waitForSelector('.ei-fd-bulk');
        await g.locator('.ei-fd-nrows', { hasText: /^5$/ }).click(); await g.locator('.ei-fd-addrows').click(); await g.waitForTimeout(400);
        const r2 = await reach({ addrows: '.ei-fd-addrows', lastCoil: '.ei-fd-btable tbody tr:last-child .ei-fd-bcoil', lastQty: '.ei-fd-btable tbody tr:last-child .ei-fd-bqty', saveAll: '.ei-fd-bsave' });
        const r = { ...r1, ...r2, overflow: r1.overflow || r2.overflow };
        const bad = Object.entries(r).filter(([k, val]) => (k === 'overflow' ? val : !val)).map(([k]) => k);
        ctx.check(!bad.length, `H ${label}: paper button, contract quantity, select all, apply rate, add rows, the last row's boxes and Save all can all be reached and clicked; no sideways page scroll`, JSON.stringify(r));
        await ctx.shot(g, `30_H_${label.replace(/[^0-9a-z]+/gi, '_')}`);
      } catch (e) { ctx.check(false, `H ${label}`, String(e.message).split('\n')[0]); }
      await v.close();
    }
    await admin.close();
  },
};
