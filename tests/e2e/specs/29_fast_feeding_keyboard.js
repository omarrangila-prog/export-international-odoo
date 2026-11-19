// The client's 19 Nov 2026 video, replayed: New Feeding Entry opens the working form at once (no "Create draft DA" step),
// Enter moves to the next box and takes an EXISTING match only (typing "ZZQX" never makes a party), the weight has an explicit
// unit (4,574 kg = 4.574 MTL; 4.574 typed as kg is caught and needs a tick), the same DA number is offered instead of copied,
// and every box and the Save button are reachable at 100-200% zoom on the recorded 1364 x 612 window, laptops and phones.
// DEMO parties, items and codes only.
module.exports = {
  name: '29 fast feeding: direct form, Enter to the next box, units, duplicate DA, zoom and scrolling',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const stamp = String(Date.now()).slice(-6), da = `DA-KEY-${stamp}`;
    const admin = await new Session(ctx, browser, 'admin', 'admin').start();
    const one = async (model, domain, fields) => (await admin.rpc(model, 'search_read', [domain, fields], { limit: 1, order: 'id desc' }))[0];
    const count = async (model, domain) => admin.rpc(model, 'search_count', [domain]);
    const s = await new Session(ctx, browser, 'demo.contracts', 'demo', [1364, 612], { timeout: 30000 }).start();
    const p = s.page; let m = s.mark();
    const focused = () => p.evaluate(() => { const a = document.activeElement; return a ? (a.id || a.className || a.tagName) : ''; });
    const typeEnter = async (text) => { await p.keyboard.type(text, { delay: 35 }); await p.waitForTimeout(700); await p.keyboard.press('Enter'); await p.waitForTimeout(1300); };

    // T01/T02: the working form opens at once, everything on one page, no Create draft DA
    await p.goto(`${ctx.base}/odoo/action-ei_da_feeding.action_ei_new_feeding`); await p.waitForSelector('#ei-fd-daname', { timeout: 30000 }); await p.waitForTimeout(800);
    ctx.check(!(await p.getByRole('button', { name: /Create draft DA/ }).count()) && await p.locator('#ei-fd-gocoil').count() === 1,
      'T01 New Feeding Entry opens the form at once: no "Create draft DA" step; the coil follows on the same screen');
    ctx.check(/DA No/.test(await p.locator('.ei-fd-newhead').innerText()) && /Supplier/.test(await p.locator('.ei-fd-newhead').innerText()), 'T02 date, DA No, Supplier, Purchased By and Sold To on one page');

    // T03/T04: Enter moves on; Enter in a search takes an existing name and never creates "ZZQX"
    await p.locator('#ei-fd-daname').click(); await typeEnter(da);
    if (await p.locator('.ei-fd-supplier .ei-fd-picked').count()) await p.locator('.ei-fd-supplier .ei-fd-picked button').click();
    await p.locator('#ei-fd-supplier').click(); await typeEnter('DEMO Parent Steel');
    ctx.check(/DEMO Parent Steel Mill/.test(await p.locator('.ei-fd-supplier').innerText()) && ['ei-fd-pin', 'ei-fd-sold'].includes(await focused()), 'T03 Enter takes the supplier and moves to the next open box (Purchased By)', await focused());
    if (await p.locator('.ei-fd-pin .ei-fd-picked').count()) { await p.locator('.ei-fd-pin .ei-fd-picked button').click(); await p.waitForTimeout(400); }
    const partnersBefore = await count('res.partner', []);
    await p.locator('#ei-fd-pin').click(); await typeEnter('ZZQX');
    ctx.check(await count('res.partner', []) === partnersBefore && /No match for/.test(await p.locator('.ei-fd-error').innerText().catch(() => '')) && !(await p.locator('.ei-fd-pin .ei-fd-picked').count()),
      'T04 Enter on a part of a name that matches nothing creates nothing and says so', String((await count('res.partner', [])) - partnersBefore));
    await p.locator('#ei-fd-pin').fill(''); await typeEnter('DEMO Buying');
    ctx.check(await focused() === 'ei-fd-sold', 'T03 Enter after Purchased By moves to Sold To', await focused());
    await typeEnter('Rehman');
    await p.waitForSelector('#ei-fd-item', { timeout: 20000 }); await p.waitForTimeout(600);
    ctx.check(await focused() === 'ei-fd-item' && !!(await one('ei.da', [['name', '=', da]], ['id'])), 'T03 Enter after Sold To opens the coil on the same screen, cursor in Item (the draft is kept behind the scenes)', await focused());
    await typeEnter('DEMO HR');
    ctx.check(await focused() === 'ei-fd-coil', 'T03 Enter takes the item and moves to Coil No', await focused());
    await typeEnter('KEY-1');                       // -> grade
    await p.keyboard.press('Enter'); await p.keyboard.press('Enter'); await p.keyboard.press('Enter'); await p.waitForTimeout(300);   // grade, thickness, width
    ctx.check(await focused() === 'ei-fd-qty', 'T03 Enter walks Grade, Thickness and Width to the Weight', await focused());
    await p.keyboard.type('4.574', { delay: 40 }); await p.waitForTimeout(500);
    ctx.check(/4,574 kg = 4\.574 MTL/.test(await p.locator('.ei-fd-qty .ei-fd-hint').innerText()), 'T13 4.574 MTL is shown as 4,574 kg');
    await p.keyboard.press('Enter'); await p.waitForTimeout(500);
    ctx.check(/ei-fd-btn/.test(await focused()), 'T03 Enter after the weight goes to the first code to choose', await focused());
    await p.keyboard.press('Enter'); await p.waitForSelector('#ei-fd-look'); await typeEnter('D.01');
    const codeTxt = await p.locator('.ei-fd-picks').innerText().catch(() => '');
    ctx.check(/D\.01/.test(await p.locator('.ei-fd-pick[data-f="customer_code"]').innerText()), 'T18 the sales code is chosen by its exact text D.01 with its name', codeTxt.replace(/\s+/g, ' ') + ' | focus ' + await focused());
    await p.getByRole('radio', { name: /Direct purchase/ }).click(); await p.waitForTimeout(500);
    await p.keyboard.type('229500', { delay: 30 }); await p.keyboard.press('Enter'); await p.waitForTimeout(300);
    await p.keyboard.type('230500', { delay: 30 }); await p.waitForTimeout(1500); await p.keyboard.press('Enter'); await p.waitForTimeout(400);
    ctx.check(/ei-fd-savebtn/.test(await focused()), 'T06 Enter after the last rate stops on Save Entry; nothing is saved by accident', await focused());
    ctx.check(await count('ei.da.line', [['da_id.name', '=', da]]) === 0, 'T06 no coil saved before the person presses Save');
    await p.keyboard.press('Enter'); await p.waitForTimeout(2000);
    let l1 = await one('ei.da.line', [['da_id.name', '=', da], ['coil_no', '=', 'KEY-1']], ['weight_kg', 'mtl', 'purchase_rate', 'sale_rate', 'gross_spread']);
    ctx.check(l1 && l1.weight_kg === 4574 && l1.mtl === 4.574 && l1.gross_spread === 4574, 'T12/T20 saved with the keyboard only: 4,574 kg = 4.574 MTL, 229,500 / 230,500 -> 4,574 spread', JSON.stringify(l1));
    await ctx.shot(p, '29_saved_keyboard');

    // T14: 4.574 typed as kg is caught; a tick is needed to keep it
    await p.getByRole('button', { name: 'Add Coil' }).click(); await p.waitForSelector('#ei-fd-qty');
    await p.fill('#ei-fd-coil', 'KEY-2'); await p.locator('.ei-fd-unit button', { hasText: 'kg' }).click(); await p.fill('#ei-fd-qty', '4.574'); await p.waitForTimeout(1200);
    ctx.check(await p.locator('.ei-fd-smallw').count() === 1 && /0\.004574 MTL/.test(await p.locator('.ei-fd-smallw').innerText()), 'T14 4.574 kg shows 0.004574 MTL with a warning, not 0.005', await p.locator('.ei-fd-smallw').innerText().catch(() => ''));
    await p.locator('.ei-fd-editor .ei-fd-field', { hasText: 'Purchase rate / MTL' }).locator('input').fill('229500');
    await p.locator('.ei-fd-editor .ei-fd-field', { hasText: 'Sale rate / MTL' }).locator('input').fill('230500'); await p.waitForTimeout(1200);
    await p.getByRole('button', { name: 'Save Entry' }).click(); await p.waitForTimeout(1200);
    ctx.check(await count('ei.da.line', [['da_id.name', '=', da], ['coil_no', '=', 'KEY-2']]) === 0, 'T14 not saved until it is confirmed');
    await p.locator('.ei-fd-smallw').getByRole('button', { name: /It is 4\.574 MTL/ }).click(); await p.waitForTimeout(600);
    ctx.check(/4,574 kg = 4\.574 MTL/.test(await p.locator('.ei-fd-qty .ei-fd-hint').innerText()) && !(await p.locator('.ei-fd-smallw').count()), 'T13 one click turns it into 4.574 MTL');
    await p.getByRole('button', { name: 'Save Entry' }).click(); await p.waitForTimeout(1800);
    const l2 = await one('ei.da.line', [['da_id.name', '=', da], ['coil_no', '=', 'KEY-2']], ['weight_kg', 'mtl']);
    ctx.check(l2 && l2.weight_kg === 4574 && l2.mtl === 4.574, 'T21 second coil saved; the DA has two coils', JSON.stringify(l2) + ' ' + (await p.locator('.ei-fd-error').allInnerTexts()).join(' | '));

    // T15: reopen and see the same values
    await p.goto(`${ctx.base}/odoo/action-ei_da_feeding.action_ei_da_feeding`); await p.waitForSelector('.ei-fd-darow', { timeout: 30000 }); await p.locator('.ei-fd-darow', { hasText: da }).first().click(); await p.waitForSelector('.ei-fd-table');
    const tbl = (await p.locator('.ei-fd-table').innerText()).replace(/\s+/g, ' ');
    ctx.check(/KEY-1/.test(tbl) && /KEY-2/.test(tbl) && /9\.148/.test(tbl), 'T15 reopened: both coils and 9.148 MTL are there', tbl.slice(0, 200));

    // T16: the same DA number again is offered, never copied
    await p.goto(`${ctx.base}/odoo/action-ei_da_feeding.action_ei_new_feeding`); await p.waitForSelector('#ei-fd-daname', { timeout: 30000 });
    await p.fill('#ei-fd-daname', da);
    if (await p.locator('.ei-fd-supplier .ei-fd-picked').count()) await p.locator('.ei-fd-supplier .ei-fd-picked button').click();
    await p.locator('#ei-fd-supplier').click(); await typeEnter('DEMO Parent Steel');
    if (await p.locator('#ei-fd-pin').count()) { await p.locator('#ei-fd-pin').click(); await typeEnter('DEMO Buying'); }
    await p.locator('#ei-fd-gocoil').click(); await p.waitForTimeout(1500);
    ctx.check(/already in the system/.test(await p.locator('.ei-fd-warnbox').first().innerText().catch(() => '')) && await count('ei.da', [['name', '=', da]]) === 1,
      'T16 the same DA number is offered (Open / Add coil to it); no second DA is made');
    await ctx.shot(p, '29_duplicate_offered');
    await p.getByRole('button', { name: 'Add coil to it' }).first().click(); await p.waitForSelector('#ei-fd-item, #ei-fd-coil', { timeout: 15000 });
    ctx.check(/KEY-1/.test(await p.locator('.ei-fd-table').innerText()), 'T16 "Add coil to it" opens that DA with a new coil ready');
    await s.clean('fast feeding screens are clean', m);
    await s.close();

    // T07-T11: every box and the Save button reachable at 100-200% zoom on the recorded window, laptops and phones
    const sizes = [['1364x612 100%', 1364, 612], ['1364x612 125%', 1091, 490], ['1364x612 150%', 909, 408], ['1364x612 175%', 779, 350], ['1364x612 200%', 682, 306],
      ['1366x768', 1366, 768], ['1280x720', 1280, 720], ['1024x768', 1024, 768], ['phone 390x844', 390, 844], ['phone 320x568', 320, 568]];
    for (const [label, w, h] of sizes) {
      const v = await new Session(ctx, browser, 'demo.contracts', 'demo', [w, h], { timeout: 30000 }).start();
      const q = v.page;
      try {
        await q.goto(`${ctx.base}/odoo/action-ei_da_feeding.action_ei_da_feeding`); await q.waitForSelector('.ei-fd-darow', { timeout: 30000 });
        await q.locator('.ei-fd-darow', { hasText: da }).first().click(); await q.waitForSelector('.ei-fd-table');
        await q.locator('.ei-fd-table tbody tr').first().getByRole('button', { name: 'Edit' }).click(); await q.waitForSelector('.ei-fd-savebtn'); await q.waitForTimeout(900);
        const r = await q.evaluate(() => {
          const sc = document.querySelector('.ei-fd'); const before = sc.scrollTop; sc.scrollTop = sc.scrollHeight; const scrolled = sc.scrollTop > before || sc.scrollHeight <= sc.clientHeight;
          const btn = document.querySelector('.ei-fd-savebtn'); btn.scrollIntoView({ block: 'center' });
          const b = btn.getBoundingClientRect(); const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
          const inputs = [...document.querySelectorAll('.ei-fd-editor input:not([type=checkbox]):not([type=file])')].filter((e) => e.offsetParent);
          const reach = inputs.every((e) => { e.scrollIntoView({ block: 'center' }); const x = e.getBoundingClientRect(); const t = document.elementFromPoint(x.left + Math.min(10, x.width / 2), x.top + x.height / 2); return t === e || e.contains(t); });
          const label = parseFloat(getComputedStyle(document.querySelector('.ei-fd-field > span')).fontSize);
          return { scrolled, saveReachable: !!hit && (hit === btn || btn.contains(hit)), inputs: inputs.length, reach, label, overflow: document.documentElement.scrollWidth > innerWidth + 1 };
        });
        ctx.check(r.scrolled && r.saveReachable && r.reach && r.label >= 12 && !r.overflow, `T07-T11 ${label}: the form scrolls, all ${r.inputs} coil boxes and Save Entry can be reached and clicked, labels ${r.label}px, no sideways page scroll`, JSON.stringify(r));
        await ctx.shot(q, `29_size_${label.replace(/[^0-9a-z]+/gi, '_')}`);
      } catch (e) { ctx.check(false, `T07-T11 ${label}`, String(e.message).split('\n')[0]); }
      await v.close();
    }
    await admin.close();
  },
};
