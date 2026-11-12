// One screen, like the old FoxPro entry (client, 11 Nov 2026): no contract first. The maker chooses SUPPLIER (Purchase From) ->
// Purchase (IN) -> Sold (OUT), types the DA number, adds coils and submits; amounts are in PKR and there is no currency anywhere.
// The direct purchase-and-sale figures of the client's FoxPro recording are typed (with DEMO parties and DEMO codes): 4.574 MTL,
// purchase 229,500, sale 230,500 -> 1,049,733 / 1,054,307 / 4,574. Then the checker approves and the ledgers show the three parties.
module.exports = {
  name: '26 one-screen feeding: three parties, no contract first, PKR only, ledgers and From -> To trace',
  async run(ctx, browser) {
    const { Session, synthPdf } = require('../lib');
    const stamp = String(Date.now()).slice(-6), da = `DA-ONE-${stamp}`;
    const admin = await new Session(ctx, browser, 'admin', 'admin').start();
    await admin.rpc('ei.approval.policy', 'set_all', [true]);
    const one = async (model, domain, fields) => (await admin.rpc(model, 'search_read', [domain, fields], { limit: 1, order: 'id desc' }))[0];
    const contractsBefore = await admin.rpc('ei.contract', 'search_count', [[['contract_type', '!=', 'feeding']]]);

    const s = await new Session(ctx, browser, 'demo.contracts', 'demo', [1440, 900], { timeout: 30000 }).start();
    const p = s.page; let m = s.mark();
    await p.goto(`${ctx.base}/odoo/action-ei_da_feeding.action_ei_da_feeding`); await p.waitForSelector('.ei-fd-tabs', { timeout: 30000 });
    await p.getByRole('tab', { name: /Real entry/ }).click(); await p.getByRole('button', { name: 'New DA' }).click(); await p.waitForSelector('#ei-fd-daname');
    const form = (await p.locator('.ei-fd-main .ei-fd-card').first().innerText()).replace(/\s+/g, ' ');
    ctx.check(/Entry date/.test(form) && /DO \/ DA No/.test(form) && /SUPPLIER \(Purchase From\)/.test(form) && /Purchase \(IN\)/.test(form) && /Sold \(OUT\)/.test(form),
      '1 the new entry asks for the date, the DO / DA number and the three parties, on one screen', form.slice(0, 200));
    ctx.check(!/USD|Currency|Exchange/i.test(form) && !(await p.locator('#ei-fd-contract').isVisible()), '1 no currency and no contract is asked for (a signed contract stays under More details)');
    await p.locator('#ei-fd-supplier').selectOption({ label: 'DEMO Parent Steel Mill' });
    await p.locator('#ei-fd-pin').selectOption({ label: 'DEMO Buying Entity' });
    await p.fill('#ei-fd-daname', da);
    await p.locator('#ei-fd-sold').pressSequentially('Rehman', { delay: 40 }); await p.waitForTimeout(1200);
    await p.locator('.ei-fd-sold .ei-fd-lookrows button').first().click();
    await p.getByRole('button', { name: 'Create draft DA' }).click(); await p.waitForSelector('.ei-fd-daname');
    const chain = (await p.locator('.ei-fd-chain').innerText()).replace(/\s+/g, ' ');
    ctx.check(/DEMO Parent Steel Mill\s*→\s*DEMO Buying Entity\s*→\s*DEMO Customer - Rehman Traders/.test(chain), '2 the DA shows the chain Supplier → Purchase (IN) → Sold (OUT)', chain);
    await p.locator('.ei-fd-paper input[type="file"]').setInputFiles(synthPdf()); await p.waitForTimeout(1500);

    // coil 1: the item is searched by name; Sold (OUT) is already there; the FoxPro direct figures
    await p.getByRole('button', { name: 'Add Coil' }).click();
    await p.locator('#ei-fd-item').click(); await p.locator('#ei-fd-item').pressSequentially('DEMO HR', { delay: 40 }); await p.waitForTimeout(1200);
    await p.locator('.ei-fd-item .ei-fd-lookrows button').first().click(); await p.waitForTimeout(1200);
    ctx.check(/Rehman/.test(await p.locator('.ei-fd-pick', { hasText: 'Sold (OUT)' }).innerText()), '3 a new coil already carries the Sold (OUT) customer of the DA');
    await p.fill('#ei-fd-coil', 'ONE-1');
    const fld = (label) => p.locator('.ei-fd-editor .ei-fd-field', { hasText: label }).locator('input').first();
    await fld('Thickness').fill('0.50'); await fld('Width').fill('1219'); await fld('Weight').fill('4574');
    await p.locator('.ei-fd-pick', { hasText: 'Sales code' }).getByRole('button', { name: /Choose|Change/ }).first().click();
    await p.locator('#ei-fd-look').pressSequentially('D.01', { delay: 40 }); await p.waitForTimeout(1200);
    await p.locator('.ei-fd-lookrows button', { hasText: 'D.01' }).first().click();
    await p.locator('.ei-fd-mpick', { hasText: /^Direct purchase and sale/ }).click();
    await fld('Purchase rate / MTL').fill('229500'); await fld('Sale rate / MTL').fill('230500');
    await p.waitForSelector('.ei-fd-answer', { timeout: 40000 }); await p.waitForTimeout(1200);
    const ans = (await p.locator('.ei-fd-answer').innerText()).replace(/\s+/g, ' ');
    ctx.check(ans.includes('1,049,733.00') && ans.includes('1,054,307.00') && ans.includes('+4,574.00 PKR') && ans.includes('+1,000.00'),
      '3 the FoxPro direct figures: purchase 1,049,733.00, sale 1,054,307.00, spread 4,574.00 (1,000.00 per MTL), in PKR', ans.slice(0, 220));
    await ctx.shot(p, '26_one_screen_entry');
    // coil 2 with the keyboard: Save & Add Coil keeps the parties, the item and the method
    await p.getByRole('button', { name: 'Save & Add Coil' }).click(); await p.waitForTimeout(1800);
    const kept = (await p.locator('.ei-fd-editor').innerText()).replace(/\s+/g, ' ');
    ctx.check(/Rehman/.test(kept) && /D\.01/.test(kept) && /DEMO HR/.test(kept), '4 the next coil inherits item, Sold (OUT) and sales code', kept.slice(0, 160));
    await p.locator('#ei-fd-coil').focus(); await p.keyboard.type('ONE-2');
    await fld('Weight').fill('3000'); await fld('Purchase rate / MTL').fill('229500'); await fld('Sale rate / MTL').fill('230500'); await p.waitForTimeout(1500);
    await p.keyboard.press('Control+s'); await p.waitForTimeout(2000);
    const rows = await p.locator('.ei-fd-table tbody tr').count();
    ctx.check(rows === 2, '4 two coils on one DA (the second saved with Ctrl+S)', String(rows));
    await p.getByRole('button', { name: 'Submit for Approval' }).click(); await p.waitForSelector('.ei-fd-done.is-wait', { timeout: 30000 });
    const rec = await one('ei.da', [['name', '=', da]], ['state', 'purchase_in_id', 'sold_out_id', 'contract_id', 'parent_partner_id', 'id']);
    const acc = await one('ei.contract', [['id', '=', rec.contract_id[0]]], ['contract_type', 'state', 'currency_id', 'notes']);
    ctx.check(rec.state === 'under_review' && /Buying Entity/.test(rec.purchase_in_id[1]) && /Rehman/.test(rec.sold_out_id[1]) && /Parent Steel Mill/.test(rec.parent_partner_id[1]),
      '5 submitted with one click; the three parties are stored on the DA', JSON.stringify(rec));
    ctx.check(acc.contract_type === 'feeding' && acc.currency_id[1] === 'PKR' && /Not a signed contract/.test(acc.notes)
      && await admin.rpc('ei.contract', 'search_count', [[['contract_type', '!=', 'feeding']]]) === contractsBefore,
      '5 no contract was made by hand: the system keeps a PKR feeding account, labelled as not a signed contract', JSON.stringify(acc).slice(0, 200));
    await s.clean('5 the entry screens are clean', m);
    await s.close();

    // the checker approves it from the centre
    const c = await new Session(ctx, browser, 'demo.contractapprover', 'demo', [1440, 900], { timeout: 30000 }).start();
    const rq = await one('ei.approval.request', [['res_model', '=', 'ei.da'], ['res_id', '=', rec.id]], ['id', 'approver_id']);
    await c.rpc('ei.approval.request', 'decide', [rq.id, 'approve', 'Checked']);
    ctx.check((await one('ei.da', [['id', '=', rec.id]], ['state'])).state === 'approved', '6 a different person approves it');
    // ledgers
    m = c.mark();
    const cp = c.page;
    await cp.goto(`${ctx.base}/odoo/action-ei_da_feeding.ei_ledger_trace_action`); await cp.waitForSelector('.o_list_view', { timeout: 30000 }); await cp.waitForTimeout(800);
    const row = cp.locator('.o_data_row', { hasText: 'ONE-1' }).first(); await row.waitFor({ timeout: 15000 });
    const txt = (await row.innerText()).replace(/\s+/g, ' ');
    ctx.check(txt.includes(da) && /DEMO Parent Steel Mill/.test(txt) && /DEMO Buying Entity/.test(txt) && /Rehman/.test(txt) && /229,500/.test(txt) && /230,500/.test(txt) && /4,574/.test(txt),
      '7 From → To trace: one row per coil with supplier, Purchase (IN), Sold (OUT), rates and gross spread', txt.slice(0, 260));
    await ctx.shot(cp, '26_from_to_trace');
    for (const [act, group] of [['ei_ledger_supplier_action', 'DEMO Parent Steel Mill'], ['ei_ledger_pin_action', 'DEMO Buying Entity'], ['ei_ledger_customer_action', 'Rehman'], ['ei_ledger_pl_action', '']]) {
      await cp.goto(`${ctx.base}/odoo/action-ei_da_feeding.${act}`); await cp.waitForSelector('.o_list_view', { timeout: 30000 }); await cp.waitForTimeout(900);
      const groups = (await cp.locator('.o_group_header').allInnerTexts()).join(' | ');
      ctx.check(await cp.locator('.o_group_header').count() >= 1 && groups.includes(group), `7 ${act.replace('ei_ledger_', '').replace('_action', '')} ledger opens grouped${group ? ' and lists ' + group : ''}`, groups.slice(0, 160));
    }
    await c.clean('7 the ledgers are clean', m);
    await c.close();

    // a phone: the entry form fits
    const ph = await new Session(ctx, browser, 'demo.contracts', 'demo', [390, 844], { timeout: 30000 }).start();
    await ph.page.goto(`${ctx.base}/odoo/action-ei_da_feeding.action_ei_da_feeding`); await ph.page.waitForSelector('.ei-fd-tabs', { timeout: 30000 });
    await ph.page.getByRole('tab', { name: /Real entry/ }).click(); await ph.page.getByRole('button', { name: 'New DA' }).click(); await ph.page.waitForSelector('#ei-fd-daname');
    const fit = await ph.page.evaluate(() => ({ over: document.documentElement.scrollWidth > innerWidth,
      inside: [...document.querySelectorAll('#ei-fd-supplier, #ei-fd-pin, #ei-fd-sold, #ei-fd-daname')].every((e) => { const r = e.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth + 0.5 && r.width > 120; }) }));
    ctx.check(!fit.over && fit.inside, '8 on a phone the three parties and the DA number fit the screen', JSON.stringify(fit));
    await ctx.shot(ph.page, '26_phone_entry');
    await ph.close();
    await admin.close();
  },
};
