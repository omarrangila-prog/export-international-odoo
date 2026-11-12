// The DA feeding desk: practice with the six methods from the client's handwritten sample (numbers only, nothing posted),
// then a real draft DA fed coil by coil on the staging copy, sent for review and refused while its customer code is unverified.
const GOLDEN = {
  normal_sale: ['268,051.41', '270,080.81', '+2,029.40', '+9,282.48'],
  high_profit_sale: ['268,051.41', '281,080.81', '+13,029.40', '+59,596.48'],
  loss_sale: ['268,051.41', '261,080.81', '−6,970.60', '−31,883.52'],
  sale_at_mill_rate: ['268,051.41', '271,080.81', '+3,029.40', '+13,856.48'],
  purchase_with_cn: ['267,064.61', '271,080.81', '+4,016.20', '+18,370.10'],
  direct_no_commission: ['229,500.00', '230,500.00', '+1,000.00', '+4,574.00'],
};

async function pickIn(p, label, term) {
  await p.locator('.ei-fd-pick', { hasText: label }).getByRole('button', { name: /Choose|Change/ }).first().click();
  await p.fill('#ei-fd-look', term); await p.waitForTimeout(700);
  await p.locator('.ei-fd-lookrows button').first().click(); await p.waitForTimeout(300);
}

module.exports = {
  name: '20 DA feeding desk (six methods in practice, a real coil to review)',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const admin = await new Session(ctx, browser, 'admin', 'admin').start();
    const act = (await admin.rpc('ir.model.data', 'search_read', [[['module', '=', 'ei_da_feeding'], ['name', '=', 'action_ei_da_feeding']], ['res_id']]))[0].res_id;
    const count = async () => Promise.all(['ei.da', 'ei.da.line', 'account.move'].map((m) => admin.rpc(m, 'search_count', [[]])));

    // ---- 1 practice: every card equals the client's example to the cent, and nothing is written
    const s = await new Session(ctx, browser, 'demo.contracts', 'demo', [1440, 900], { timeout: 30000 }).start();
    const p = s.page;
    let m = s.mark();
    const before = await count();
    await s.goto(`/odoo/action-${act}`);
    await p.waitForSelector('.ei-fd-method', { timeout: 30000 });
    ctx.check(/TRAINING/.test(await p.locator('.ei-fd-train').innerText()), '1 practice says plainly that nothing is posted');
    for (const [key, want] of Object.entries(GOLDEN)) {
      const card = p.locator(`.ei-fd-method[data-method="${key}"]`);
      const figs = (await card.locator('.ei-fd-figs dd').allInnerTexts()).map((t) => t.trim());
      const total = (await card.locator('.ei-fd-total b').nth(1).innerText()).trim();
      ctx.check(figs[0] === want[0] && figs[1] === want[1] && figs[2] === want[2] && total === want[3], `1 ${key}: purchase, sale, spread and coil total match the handwritten example`, `${figs.join(' / ')} / ${total}`);
    }
    const pending = p.locator('.ei-fd-method[data-method="purchase_without_commission"]');
    ctx.check(await pending.locator('.ei-fd-figs').count() === 0 && /client/.test(await pending.innerText()), '1 "Purchase without commission" shows no invented numbers and says it waits for the client');
    await p.locator('.ei-fd-method[data-method="purchase_with_cn"]').getByRole('button', { name: 'Show calculation' }).click();
    const steps = await p.locator('.ei-fd-method[data-method="purchase_with_cn"] .ei-fd-steps').innerText();
    ctx.check(['41,310.00', '270,810.00', '270.81', '271,080.81', '3,029.40', '268,051.41', '13.20', '986.80', '267,064.61'].every((v) => steps.includes(v)), '1 "Show calculation" shows every step of the CN example');
    await p.locator('.ei-fd-inputs input').first().fill('239950'); await p.waitForTimeout(1200);
    const isl = (await p.locator('.ei-fd-method[data-method="sale_at_mill_rate"] .ei-fd-figs dd').first().innerText()).trim();
    ctx.check(isl === '280,256.80', '1 a new basic rate re-works every card (ISL p.3 example: dealer net 280,256.80)', isl);
    await p.getByRole('button', { name: 'Back to the sample numbers' }).click(); await p.waitForTimeout(800);
    await ctx.shot(p, 'feeding_practice');
    ctx.check(JSON.stringify(before) === JSON.stringify(await count()), '1 practice wrote nothing (DAs, DA lines, journal entries unchanged)', JSON.stringify(before));
    await s.clean('1 practice opens clean', m);

    // ---- 2 real entry: a new draft DA, the paper attached, one coil with a credit note
    m = s.mark();
    await p.getByRole('tab', { name: /Real entry/ }).click();
    await p.getByRole('button', { name: 'New DA' }).click(); await p.waitForSelector('.ei-fd-more', { state: 'attached', timeout: 15000 }); await p.evaluate(() => { document.querySelector('.ei-fd-more').open = true; });
    await p.waitForSelector('#ei-fd-contract option:nth-child(2)', { state: 'attached', timeout: 15000 });
    const opt = await p.locator('#ei-fd-contract option').evaluateAll((os) => os.map((o) => [o.value, o.textContent]));
    const isl1 = opt.find(([, t]) => /DEMO\/ISL\/001/.test(t));
    await p.locator('#ei-fd-contract').selectOption(isl1[0]);
    const daName = 'DA-E2E-' + Date.now().toString().slice(-6);
    await p.fill('#ei-fd-daname', daName);
    await p.locator('.ei-fd-main input[type="datetime-local"]').first().fill('2026-11-06T16:03');
    await p.locator('.ei-fd-main .ei-fd-field.is-wide input').last().fill('M/S DEMO PRINTED TRADERS');
    await p.getByRole('button', { name: 'Create draft DA' }).click();
    await p.waitForSelector('.ei-fd-daname', { timeout: 15000 });
    await p.locator('.ei-fd-paper input[type="file"]').setInputFiles(require('../lib').synthPdf());
    await p.waitForTimeout(1200);
    ctx.check(await p.locator('.ei-fd-docframe').count() === 1, '2 the attached paper is shown beside the entry');
    const shownTime = await p.locator('.ei-fd-work input[type="datetime-local"]').first().inputValue();
    ctx.check(shownTime === '2026-11-06T16:03', '2 the printed order time comes back as typed (Karachi time), apart from the DA date', shownTime);
    await p.getByRole('button', { name: 'Add Coil' }).click();
    await p.fill('#ei-fd-coil', 'E2E-COIL-1');
    await p.locator('.ei-fd-editor .ei-fd-field:has-text("Weight") input').fill('4574');
    ctx.check((await p.locator('.ei-fd-editor .ei-fd-hint').first().innerText()).includes('4.574'), '2 4,574 kg shows as 4.574 MTL straight away');
    const pick = async (label, term) => {
      await p.locator('.ei-fd-pick', { hasText: label }).getByRole('button', { name: /Choose|Change/ }).first().click();
      await p.fill('#ei-fd-look', term); await p.waitForTimeout(700);
      await p.locator('.ei-fd-lookrows button').first().click(); await p.waitForTimeout(300);
    };
    await pick('Sold (OUT)', 'Rehman');
    await pick('Sales code', '1.2');
    await p.getByRole('radio', { name: /Purchase with CN/ }).click();
    await p.locator('.ei-fd-editor .ei-fd-field:has-text("Credit note on THIS coil") input').fill('1000');
    await p.locator('.ei-fd-editor .ei-fd-field:has-text("Credit note text") input').fill('CN 1000 (synthetic)');
    await p.waitForTimeout(1200);
    const ans = (await p.locator('.ei-fd-answer .ei-fd-figs dd').allInnerTexts()).map((t) => t.trim());
    ctx.check(ans[0] === '244,289.00' && ans[1] === '248,047.80', '2 the coil is worked out from the contract formula: dealer net 245,275.80 less net CN 986.80; sold at the mill rate', ans.join(' / '));
    await p.getByRole('button', { name: 'Save Draft' }).click(); await p.waitForTimeout(1500);
    const row = await p.locator('.ei-fd-table tbody tr').first().innerText();
    ctx.check(/E2E-COIL-1/.test(row) && /Code to check/.test(row), '2 the saved coil is listed, flagged because its customer code is not verified', row.replace(/\s+/g, ' '));
    await p.getByRole('button', { name: /Save & Continue|Submit for Approval/ }).click(); await p.waitForTimeout(1500);
    const da = (await admin.rpc('ei.da', 'search_read', [[['name', '=', daName]], ['state', 'total_mtl']]))[0];
    ctx.check(da && da.state === 'under_review' && Math.abs(da.total_mtl - 4.574) < 1e-9, '2 the DA went to review with 4.574 MTL', JSON.stringify(da));
    await s.clean('2 real entry is clean', m);
    await s.close();

    // ---- 3 the approver cannot approve it while the code is unverified
    const ap = await new Session(ctx, browser, 'demo.contractapprover', 'demo').start();
    let refused = '';
    try { await ap.rpc('ei.da', 'action_approve', [[da.id]]); } catch (e) { refused = String(e.message || e); }
    ctx.check(/not yet verified/.test(refused), '3 approval is refused: the customer code is not verified, nothing is guessed', refused.slice(0, 160));
    await ap.close();

    // ---- 5 PKR only (client, 11 Nov 2026): no currency selector, no exchange rate on a new entry
    const u = await new Session(ctx, browser, 'demo.contracts', 'demo', [1440, 900], { timeout: 30000 }).start();
    const up = u.page;
    m = u.mark();
    await u.goto(`/odoo/action-${act}`); await up.waitForSelector('.ei-fd-method', { timeout: 30000 });
    await up.getByRole('tab', { name: /Real entry/ }).click();
    await up.getByRole('button', { name: 'New DA' }).click(); await up.waitForSelector('#ei-fd-daname');
    const form = await up.locator('.ei-fd-main .ei-fd-card').first().innerText();
    ctx.check(!(await up.locator('.ei-fd-curseg, [role="radio"]:has-text("USD")').count()) && !/USD|Exchange rate|Currency/i.test(form) && /amounts in PKR/.test(form),
      '5 a new entry has no currency selector and no exchange rate: amounts are in PKR', form.replace(/\s+/g, ' ').slice(0, 160));
    let usdRefused = '';
    try { const usd = (await admin.rpc('res.currency', 'search_read', [[['name', '=', 'USD'], ['active', 'in', [true, false]]], ['id']]))[0];
      const mill = (await admin.rpc('res.partner', 'search_read', [[['name', '=', 'DEMO Parent Steel Mill']], ['id']]))[0];
      await u.rpc('ei.contract', 'create', [{ parent_partner_id: mill.id, contract_ref: 'E2E-USD-' + Date.now(), currency_id: usd.id }]); } catch (e) { usdRefused = String(e.message || e); }
    ctx.check(/PKR only/.test(usdRefused), '5 the server refuses a new entry in USD', usdRefused.slice(0, 120));
    await u.clean('5 the PKR-only form is clean', m);
    await u.close();

    // ---- 6 the reports: feeding history and the credit note register, from the approved DEMO DA
    const r = await new Session(ctx, browser, 'demo.contracts', 'demo', [1440, 900], { timeout: 30000 }).start();
    m = r.mark();
    await r.menu('Orders & Trucks', 'DA feeding history');
    await r.page.waitForSelector('.o_list_view', { timeout: 20000 });
    await r.page.locator('.o_facet_remove').first().click().catch(() => {}); await r.page.waitForTimeout(800);
    const hist = (await r.page.locator('.o_list_view').innerText()).replace(/\s+/g, ' ');
    ctx.check(['DEMO-COIL-01', 'DEMO-COIL-02', 'DEMO-COIL-03'].every((c) => hist.includes(c)), '6 the feeding history lists the fed coils');
    const lossRow = r.page.locator('.o_data_row', { hasText: 'DEMO-COIL-03' });
    ctx.check(/Loss/.test(await lossRow.innerText()) && await lossRow.evaluate((e) => e.classList.contains('text-danger')), '6 a coil sold below cost is shown as a loss, in red');
    await ctx.shot(r.page, 'feeding_history');
    await r.menu('Orders & Trucks', 'Credit note register');
    await r.page.waitForSelector('.o_list_view', { timeout: 20000 });
    const cnText = (await r.page.locator('.o_data_row', { hasText: 'DEMO-COIL-02' }).innerText()).replace(/\s+/g, ' ');
    ctx.check(await r.page.locator('.o_data_row', { hasText: 'DEMO-COIL-01' }).count() === 0 && /DEMO-COIL-02/.test(cnText) && /986\.80/.test(cnText) && /5,052\.42/.test(cnText),
      '6 the CN register lists only the coil with a CN: net 986.80 per MTL, 5,052.42 for its 5.120 MTL', cnText);
    await ctx.shot(r.page, 'feeding_cn_register');
    await r.clean('6 the reports open clean', m);
    await r.close();

    // ---- 4 phone: practice fits the screen
    const ph = await new Session(ctx, browser, 'demo.contracts', 'demo', [390, 844], { timeout: 30000 }).start();
    await ph.goto(`/odoo/action-${act}`);
    await ph.page.waitForSelector('.ei-fd-method', { timeout: 30000 });
    const l = await ph.layout();
    ctx.check(!l.overflow && !l.wide.length, '4 phone: no sideways scroll', JSON.stringify(l.wide));
    await ctx.shot(ph.page, 'feeding_phone');
    await ph.close();
    await admin.close();
  },
};
