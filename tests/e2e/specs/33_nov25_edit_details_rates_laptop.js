// The client's 25 Nov 2026 requests in the real browser at their laptop windows (1360x610, 1364x640, 100%): PageDown / keyboard
// reach the last rate and Save; a field near the bottom scrolls into view; a dropdown near the bottom is not clipped; typed values
// survive a window resize; an unsold draft is allowed; Change item previews and keeps the coil; Edit details changes this coil only
// (a size off the item needs a reason); unsaved changes are protected (Close asks, Undo); signed sale adjustments -1000 / +10000 /
// +1000 persist after reopening; a typed sale rate needs a reason; a "10000" in an item name never becomes a rate; Sold To chosen
// later flows into the coils and fills the sales code; an unknown code is not guessed. DEMO data only; results read from the database.
module.exports = {
  name: '33 Nov 25: laptop scroll and keyboard, Edit details / Change item, signed rates, unsaved changes, unsold draft',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const stamp = String(Date.now()).slice(-6), DA = `DEMO-ED-${stamp}`;
    const admin = await new Session(ctx, browser, 'admin', 'admin').start();
    const one = async (model, domain, fields) => (await admin.rpc(model, 'search_read', [domain, fields], { limit: 1, order: 'id desc' }))[0];
    const count = (model, domain) => admin.rpc(model, 'search_count', [domain]);
    const ton = (await one('ir.model.data', [['module', '=', 'uom'], ['name', '=', 'product_uom_ton']], ['res_id'])).res_id;
    for (const n of [`DEMO GP 0.50X1219 ${stamp}`, `DEMO GP 0.60X1000 ${stamp}`, `DEMO GP 0.50X1219 10000 CSAH (P) ${stamp}`]) await admin.rpc('product.product', 'create', [{ name: n, uom_id: ton, uom_po_id: ton }]).catch(() => admin.rpc('product.product', 'create', [{ name: n, uom_id: ton }]));
    const line = (coil) => one('ei.da.line', [['da_id.name', '=', DA], ['coil_no', '=', coil]], ['product_id', 'coil_grade', 'coil_thickness', 'coil_width', 'mtl', 'weight_kg', 'sale_offset', 'sale_rate', 'sale_typed', 'rate_note', 'size_note', 'customer_id', 'customer_code_id']);

    const s = await new Session(ctx, browser, 'demo.contracts', 'demo', [1360, 610], { timeout: 30000 }).start();
    const p = s.page; const m0 = s.mark();
    const typeEnter = async (text) => { await p.keyboard.type(text, { delay: 20 }); await p.waitForTimeout(900); await p.keyboard.press('Enter'); await p.waitForTimeout(1300); };
    const txt = async (sel) => (await p.locator(sel).allInnerTexts().catch(() => [])).join(' | ').replace(/\s+/g, ' ');
    const edit = async (coil) => { await p.locator('.ei-fd-table tbody tr', { hasText: coil }).first().getByRole('button', { name: 'Edit' }).click(); await p.waitForSelector('#ei-fd-qty'); await p.waitForTimeout(600); };
    const save = async () => { await p.getByRole('button', { name: 'Save Entry' }).click(); await p.waitForTimeout(1800); };

    // T21: an unsold draft (Sold To left empty) is a valid draft
    await p.goto(`${ctx.base}/odoo/action-ei_da_feeding.action_ei_new_feeding`); await p.waitForSelector('#ei-fd-daname', { timeout: 30000 }); await p.waitForTimeout(600);
    await p.locator('#ei-fd-daname').click(); await typeEnter(DA);
    if (await p.locator('.ei-fd-supplier .ei-fd-picked').count()) await p.locator('.ei-fd-supplier .ei-fd-picked button').click();
    await p.locator('#ei-fd-supplier').click(); await typeEnter('DEMO Parent Steel');
    if (await p.locator('.ei-fd-pin .ei-fd-picked').count()) { await p.locator('.ei-fd-pin .ei-fd-picked button').click(); await p.waitForTimeout(300); }
    await p.locator('#ei-fd-pin').click(); await typeEnter('DEMO Buying');
    await p.keyboard.press('Enter'); await p.waitForSelector('#ei-fd-item, #ei-fd-coil', { timeout: 20000 }); await p.waitForTimeout(700);
    const da = await one('ei.da', [['name', '=', DA]], ['id', 'sold_out_id', 'state']);
    ctx.check(da && !da.sold_out_id && da.state === 'draft' && /Not sold yet/.test(await txt('.ei-fd-chain')), 'T21 Sold To left empty: a draft "Not sold yet", no customer made up', JSON.stringify(da));

    // T31 + T35 + T37: an item with its size, 5.600 MTL, Commission based, mill -1,000 with its working shown
    if (!(await p.locator('#ei-fd-item').count())) { await p.locator('.ei-fd-item .ei-fd-picked').getByRole('button', { name: /Change item/ }).click(); await p.waitForTimeout(400); }
    await p.locator('#ei-fd-item').click(); await typeEnter(`DEMO GP 0.50X1219 ${stamp}`);
    ctx.check((await p.locator('#ei-fd-thick').inputValue()) === '0.50' && (await p.locator('#ei-fd-width').inputValue()) === '1219' && /0\.50X1219/.test(await txt('.ei-fd-item .ei-fd-picked')),
      'T31 the item is chosen (shown by name) and its thickness 0.50 / width 1219 fill themselves', await txt('.ei-fd-item'));
    await p.locator('#ei-fd-coil').fill(`ED-${stamp}`); await p.locator('#ei-fd-grade').fill('SEC'); await p.locator('#ei-fd-qty').fill('5.600'); await p.waitForTimeout(400);
    ctx.check(/5,600 kg = 5\.6 MTL/.test(await txt('.ei-fd-qty .ei-fd-hint')), 'T35 5.600 MTL reads "= 5,600 kg = 5.6 MTL"', await txt('.ei-fd-qty .ei-fd-hint'));
    await p.locator('.ei-fd-unit button', { hasText: 'kg' }).click(); await p.waitForTimeout(400);
    ctx.check(/0\.0056 MTL/.test(await txt('.ei-fd-smallw')), 'T36 the same 5.600 typed as kg is 0.0056 MTL and is flagged, never taken as 5.6 MTL', await txt('.ei-fd-smallw'));
    await p.locator('.ei-fd-unit button', { hasText: 'MTL' }).click(); await p.waitForTimeout(300);
    await p.getByRole('radio', { name: /Commission based/ }).click(); await p.waitForTimeout(300);
    await p.locator('.ei-fd-editor .ei-fd-rate input').fill('229500'); await p.locator('.ei-fd-offset-in').fill('-1000'); await p.waitForSelector('.ei-fd-answer', { timeout: 30000 }); await p.waitForTimeout(600);
    ctx.check(/Mill 271,080\.81 − 1,000\.00 = sale 270,080\.81/.test(await txt('.ei-fd-adjhint')), 'T37 the adjustment shows its working: "Mill 271,080.81 − 1,000.00 = sale 270,080.81"', await txt('.ei-fd-adjhint'));
    await save();
    let l = await line(`ED-${stamp}`);
    ctx.check(l && l.mtl === 5.6 && l.weight_kg === 5600 && l.coil_grade === 'SEC' && l.sale_offset === -1000 && l.sale_rate === 270080.81 && !l.customer_id,
      'T14/T15 the unsold draft coil is saved: 5.6 MTL = 5,600 kg, SEC, mill -1,000 = 270,080.81, no customer', JSON.stringify(l));
    ctx.check(await count('account.move', [['ref', 'ilike', DA]]) === 0, 'T14 saving a draft posts nothing');

    // T32: Edit details changes this coil only; a size off the item needs a reason; the item stays
    await edit(`ED-${stamp}`); await p.locator('.ei-fd-editdet').click(); await p.waitForTimeout(400);
    ctx.check(await p.evaluate(() => document.activeElement.id) === 'ei-fd-grade' && /The item stays/.test(await txt('.ei-fd-detnote')), 'T32 "Edit details" goes to Grade and says the item stays');
    await p.locator('#ei-fd-grade').fill('PRIME'); await p.locator('#ei-fd-width').fill('1250'); await p.waitForTimeout(400);
    ctx.check(/width 1250, item 1219/.test(await txt('.ei-fd-sizenote')), 'T32 a width off the item size asks why, beside the boxes', await txt('.ei-fd-sizenote'));
    let mk = s.mark(); await save(); s.discard(mk);           // refused on purpose
    ctx.check(/write why/i.test(await txt('.ei-fd-editor .ei-fd-error')) && (await line(`ED-${stamp}`)).coil_width === '1219', 'T32 without a reason it is not saved (the coil keeps 1219)', await txt('.ei-fd-editor .ei-fd-error'));
    await p.locator('.ei-fd-sizenote input').fill('TRAINING: the mill cut this coil to 1250'); await save();
    l = await line(`ED-${stamp}`);
    ctx.check(l.coil_grade === 'PRIME' && l.coil_width === '1250' && /1250/.test(l.size_note) && new RegExp(`0\\.50X1219 ${stamp}`).test(l.product_id[1]) && l.mtl === 5.6 && l.sale_rate === 270080.81,
      'T32 Edit details saved: grade PRIME, width 1250 with its reason; item, weight and rates unchanged', JSON.stringify(l));

    // T34: unsaved changes are protected; Undo puts the saved values back
    await edit(`ED-${stamp}`); await p.locator('#ei-fd-qty').fill('7.25'); await p.waitForTimeout(300);
    let asked = ''; p.once('dialog', async (dlg) => { asked = dlg.message(); await dlg.dismiss(); });
    await p.locator('.ei-fd-editor').getByRole('button', { name: 'Close', exact: true }).click(); await p.waitForTimeout(500);
    ctx.check(/Discard the changes/.test(asked) && (await p.locator('#ei-fd-qty').inputValue()) === '7.25', 'T34 Close with unsaved changes asks first; "No" keeps the typed value', asked);
    await p.locator('.ei-fd-undo').click(); await p.waitForTimeout(600);
    ctx.check((await p.locator('#ei-fd-qty').inputValue()) === '5.6', 'T34 "Undo changes" puts back the saved weight', await p.locator('#ei-fd-qty').inputValue());

    // T33: Change item previews what changes and keeps the coil's own values
    await p.locator('.ei-fd-chgitem').click(); await p.waitForSelector('#ei-fd-item'); await p.locator('#ei-fd-item').click();
    let preview = ''; p.once('dialog', async (dlg) => { preview = dlg.message(); await dlg.accept(); });
    await typeEnter(`DEMO GP 0.60X1000 ${stamp}`);
    ctx.check(/Thickness 0\.50 → 0\.60, width 1250 → 1000/.test(preview) && /Coil No, weight, grade, codes and rates stay/.test(preview), 'T33 Change item asks first and lists exactly what changes', preview.replace(/\s+/g, ' '));
    await p.locator('.ei-fd-sizenote input').count().then(async (n) => { if (n) await p.locator('.ei-fd-sizenote input').fill(''); });
    await save();
    l = await line(`ED-${stamp}`);
    ctx.check(new RegExp(`0\\.60X1000 ${stamp}`).test(l.product_id[1]) && l.coil_thickness === '0.60' && l.coil_width === '1000' && l.coil_grade === 'PRIME' && l.mtl === 5.6 && l.sale_offset === -1000 && !l.size_note,
      'T33 the new item and its size; Coil No, weight, grade and the -1,000 adjustment kept', JSON.stringify(l));

    // T38 + T39: +10,000 and the ± button (-1,000 -> +1,000), kept after reopening
    await edit(`ED-${stamp}`); await p.locator('.ei-fd-offset-in').fill('10000'); await p.waitForTimeout(900); await save();
    ctx.check((await line(`ED-${stamp}`)).sale_rate === 281080.81, 'T38 mill +10,000 = 281,080.81');
    await edit(`ED-${stamp}`); await p.locator('.ei-fd-offset-in').fill('1000'); await p.locator('.ei-fd-flip').click(); await p.waitForTimeout(400);
    ctx.check((await p.locator('.ei-fd-offset-in').inputValue()) === '-1000', 'T39 the ± button turns +1,000 into -1,000');
    await p.locator('.ei-fd-flip').click(); await p.waitForTimeout(900); await save();
    await p.reload(); await p.waitForSelector('.ei-fd-darow'); await p.locator('.ei-fd-darow', { hasText: DA }).first().click(); await p.waitForSelector('.ei-fd-table'); await edit(`ED-${stamp}`);
    l = await line(`ED-${stamp}`);
    ctx.check(l.sale_offset === 1000 && l.sale_rate === 272080.81 && (await p.locator('.ei-fd-offset-in').inputValue()) === '1000' && l.coil_grade === 'PRIME',
      'T39 +1,000 kept after reopening: sale 272,080.81; the coil\'s details unchanged', JSON.stringify(l));

    // T40: a typed sale rate needs a reason that stays on the coil
    await p.locator('.ei-fd-editor label', { hasText: 'Type the sale rate instead' }).locator('input').check(); await p.waitForTimeout(300);
    await p.locator('.ei-fd-editor .ei-fd-field', { hasText: 'Sale rate / MTL' }).locator('input').fill('271500'); await p.waitForTimeout(900); mk = s.mark(); await save(); s.discard(mk);    // refused on purpose
    ctx.check(/sale rate is typed/.test(await txt('.ei-fd-editor .ei-fd-error')), 'T40 a typed sale rate without a reason is refused', await txt('.ei-fd-editor .ei-fd-error'));
    await p.locator('.ei-fd-ratenote input').fill('TRAINING: agreed with the buyer'); await save();
    l = await line(`ED-${stamp}`);
    ctx.check(l.sale_typed && l.sale_rate === 271500 && /agreed/.test(l.rate_note), 'T40 with the reason it is saved and the reason stays on the coil', JSON.stringify(l));

    // T41: "10000" in an item name is never a rate
    await p.getByRole('button', { name: 'Add Coil' }).click(); await p.waitForSelector('#ei-fd-coil');
    if (!(await p.locator('#ei-fd-item').count())) { await p.locator('.ei-fd-chgitem').click(); await p.waitForTimeout(300); }
    await p.locator('#ei-fd-item').click(); await typeEnter(`DEMO GP 0.50X1219 10000 CSAH (P) ${stamp}`);
    await p.locator('#ei-fd-coil').fill(`ED2-${stamp}`); await p.locator('#ei-fd-qty').fill('5'); await p.getByRole('radio', { name: /Commission based/ }).click();
    await p.locator('.ei-fd-editor .ei-fd-rate input').fill('229500'); await p.locator('.ei-fd-offset-in').fill('-1000'); await p.waitForTimeout(1200); await save();
    const l2 = await line(`ED2-${stamp}`);
    ctx.check(l2 && l2.sale_offset === -1000 && l2.sale_rate === 270080.81, 'T41 an item named "... 10000 CSAH (P)" keeps the typed -1,000; nothing taken from the name', JSON.stringify(l2));

    // T22: Sold To chosen later flows into the coils and fills the sales code
    await p.locator('.ei-fd-soldchange').click(); await p.locator('#ei-fd-soldnew').click(); await typeEnter('Rehman');
    await p.locator('.ei-fd-soldall').click(); await p.waitForTimeout(1500);
    const sold = await admin.rpc('ei.da.line', 'search_read', [[['da_id.name', '=', DA]], ['customer_id']]);
    ctx.check(sold.length === 2 && sold.every((x) => x.customer_id && /Rehman/.test(x.customer_id[1])), 'T22 Sold To chosen later: both unsold coils follow', JSON.stringify(sold));
    await p.getByRole('button', { name: 'Add Coil' }).click(); await p.waitForSelector('#ei-fd-coil'); await p.waitForTimeout(800);
    ctx.check(/D\.01/.test(await txt('.ei-fd-pick[data-f="customer_code"]')) && /from the DA/.test(await txt('.ei-fd-pick[data-f="customer"]')), 'T22 a new coil shows Rehman "from the DA" and its sales code D.01 by itself', await txt('.ei-fd-picks'));

    // T29/T30: an unknown code typed + Enter: nothing guessed, nothing made
    const codes = await count('ei.legacy.code', []);
    await p.locator('.ei-fd-pick[data-f="trade_code"] > button').click(); await p.waitForSelector('#ei-fd-look'); await p.locator('#ei-fd-look').pressSequentially('D.99', { delay: 20 }); await p.keyboard.press('Enter'); await p.waitForTimeout(1300);
    ctx.check(await count('ei.legacy.code', []) === codes && /No match for “D\.99”|Nothing found/.test(await txt('.ei-fd-editor')) && !/D\.99/.test(await txt('.ei-fd-pick[data-f="trade_code"] .ei-fd-picked')),
      'T29/T30 an unknown code (D.99) is not guessed or created; the field stays empty');
    await p.keyboard.press('Escape');

    // T09: a typed value survives a window resize
    await p.locator('#ei-fd-coil').fill(`RZ-${stamp}`); await p.locator('#ei-fd-qty').fill('4.321');
    for (const [w, h] of [[1024, 768], [390, 844], [1364, 640], [1360, 610]]) { await p.setViewportSize({ width: w, height: h }); await p.waitForTimeout(300); }
    ctx.check((await p.locator('#ei-fd-coil').inputValue()) === `RZ-${stamp}` && (await p.locator('#ei-fd-qty').inputValue()) === '4.321', 'T09 unsaved coil number and weight survive resizing to tablet, phone and back');
    await s.clean('the screens are clean (the two refusals provoked on purpose excluded)', m0);
    await s.close();

    // T01 / T02 / T08 at the recorded laptop windows, 100%: keyboard and PageDown reach the last rate and Save; a field near the
    // bottom comes into view; a code list near the bottom is not clipped
    for (const [w, h] of [[1360, 610], [1364, 640]]) {
      const v = await new Session(ctx, browser, 'demo.contracts', 'demo', [w, h], { timeout: 30000 }).start();
      const q = v.page;
      await q.goto(`${ctx.base}/odoo/action-ei_da_feeding.action_ei_da_feeding`); await q.waitForSelector('.ei-fd-darow', { timeout: 30000 });
      await q.locator('.ei-fd-darow', { hasText: DA }).first().click(); await q.waitForSelector('h2.ei-fd-daname');
      await q.locator('.ei-fd-table tbody tr').first().getByRole('button', { name: 'Edit' }).click(); await q.waitForSelector('.ei-fd-savebtn'); await q.waitForTimeout(700);
      await q.evaluate(() => { document.querySelector('.ei-fd').scrollTop = 0; });
      const box = await q.locator('.ei-fd').boundingBox(); await q.mouse.click(box.x + 8, box.y + box.height / 2);      // focus the page, as a person clicking on it
      for (let i = 0; i < 12; i++) { await q.keyboard.press('PageDown'); await q.waitForTimeout(120); }
      const r = await q.evaluate(() => {
        const sc = document.querySelector('.ei-fd'), save = document.querySelector('.ei-fd-savebtn').getBoundingClientRect();
        const hit = document.elementFromPoint(save.left + save.width / 2, save.top + save.height / 2);
        return { atBottom: sc.scrollTop + sc.clientHeight >= sc.scrollHeight - 4, saveOnScreen: save.bottom <= innerHeight && save.top >= 0, saveClickable: !!hit && !!hit.closest('.ei-fd-savebtn') };
      });
      // a field near the bottom: Tab into the last rate box brings it into view
      await q.evaluate(() => { document.querySelector('.ei-fd').scrollTop = 0; });
      await q.locator('.ei-fd-editor .ei-fd-rate input').focus(); await q.waitForTimeout(300);
      const rateSeen = await q.evaluate(() => { const b = document.activeElement.getBoundingClientRect(); return b.top >= 0 && b.bottom <= innerHeight; });
      // a code list opened near the bottom: its rows are on screen
      await q.locator('.ei-fd-pick[data-f="pl_code"] > button, .ei-fd-pick[data-f="pl_code"] .ei-fd-picked button').first().click(); await q.waitForSelector('#ei-fd-look');
      await q.locator('#ei-fd-look').pressSequentially('D', { delay: 30 }); await q.waitForTimeout(1300);
      const listOk = await q.evaluate(() => { const rows = [...document.querySelectorAll('.ei-fd-look .ei-fd-lookrows button')]; const box = document.querySelector('.ei-fd-look').getBoundingClientRect(); return { rows: rows.length, onScreen: box.top >= 0 && box.top < innerHeight - 40 }; });
      ctx.check(r.atBottom && r.saveOnScreen && r.saveClickable && rateSeen && listOk.onScreen,
        `T01/T02/T08 ${w}x${h} at 100%: PageDown reaches the bottom and Save Entry is on screen and clickable; the rate box scrolls into view on focus; a code list near the bottom opens on screen`, JSON.stringify({ ...r, rateSeen, listOk }));
      await ctx.shot(q, `33_${w}x${h}_bottom`);
      await v.close();
    }
    await admin.close();
  },
};
