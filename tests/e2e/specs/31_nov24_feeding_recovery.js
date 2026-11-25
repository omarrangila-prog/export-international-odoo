// The client's 24 Nov 2026 recordings, replayed (R01-R30): New Feeding Entry readable and reachable at the recorded 1364x590 window
// and 80-200% zoom, laptops and phones; the three parties asked once and inherited by the coil; codes chosen by name (or code),
// filled by themselves where a verified link exists; purchase / P&L codes that do not belong together are flagged with the matching
// code to choose; an item typed but not chosen is said beside the box and Save lists exactly what is missing; save, reopen,
// submit, a different person approves, ledgers; Save twice adds nothing; a DA number one letter off is flagged.
// DEMO parties, items and codes only; every outcome is read back from the database.
module.exports = {
  name: '31 Nov 24 recovery: zoom/scroll, parties once, codes by name, code pairs, item and Save messages',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const stamp = String(Date.now()).slice(-6), DA = `DEMO-40038934NOV-${stamp}`;
    const admin = await new Session(ctx, browser, 'admin', 'admin').start();
    await admin.rpc('ei.approval.policy', 'set_all', [true]);
    const one = async (model, domain, fields) => (await admin.rpc(model, 'search_read', [domain, fields], { limit: 1, order: 'id desc' }))[0];
    const count = async (model, domain) => admin.rpc(model, 'search_count', [domain]);

    // DEMO purchase and P&L codes of two families; the accountant approves the two pairs suggested from their names
    const batch = await admin.rpc('ei.import.batch', 'create', [{ name: `DEMO code pairs ${stamp}` }]);
    const code = async (c, sheet, name) => admin.rpc('ei.legacy.code', 'create', [{ legacy_code: c, source_sheet: sheet, source_sheet_key: sheet, source_row: 0, original_name: name, batch_id: batch }]);
    const ids = {
      ta: await code(`D7${stamp.slice(-2)}.01`, 'FOR PURCHASE', `DEMO ALPHA${stamp} EXPORT PUR & SLS`), pa: await code(`D8${stamp.slice(-2)}.84`, 'PROFIT & LOSS', `DEMO ALPHA${stamp} EXPORT P&L`),
      tb: await code(`D7${stamp.slice(-2)}.12`, 'FOR PURCHASE', `DEMO BETA${stamp} EXPORT NEW PUR & SLS`), pb: await code(`D8${stamp.slice(-2)}.99`, 'PROFIT & LOSS', `DEMO BETA${stamp} EXPORT NEW P&L`),
    };
    const C = { ta: `D7${stamp.slice(-2)}.01`, pa: `D8${stamp.slice(-2)}.84`, tb: `D7${stamp.slice(-2)}.12`, pb: `D8${stamp.slice(-2)}.99` };
    const acct = await new Session(ctx, browser, 'demo.mapper', 'demo').start();
    await acct.rpc('ei.code.pair', 'action_suggest', []);
    const pairs = await admin.rpc('ei.code.pair', 'search_read', [[['trade_code_id', 'in', [ids.ta, ids.tb]], ['state', '=', 'suggested']], ['id']]);
    await acct.rpc('ei.code.pair', 'action_approve', [pairs.map((x) => x.id)]);
    ctx.check(pairs.length === 2, 'setup: the accountant approves the two pairs suggested from the code names (suggestions alone change nothing)', String(pairs.length));
    await acct.close();

    const s = await new Session(ctx, browser, 'demo.contracts', 'demo', [1364, 590], { timeout: 30000 }).start();
    const p = s.page; const m0 = s.mark(); let m = m0;
    const typeEnter = async (text) => { await p.keyboard.type(text, { delay: 25 }); await p.waitForTimeout(800); await p.keyboard.press('Enter'); await p.waitForTimeout(1300); };
    const txt = async (sel) => (await p.locator(sel).allInnerTexts().catch(() => [])).join(' | ').replace(/\s+/g, ' ');
    const focused = () => p.evaluate(() => { const a = document.activeElement; return a ? (a.id || a.className || a.tagName) : ''; });
    const pick = async (f, term, enter = true) => {
      const b = p.locator(`.ei-fd-pick[data-f="${f}"] > button`);
      if (!(await b.count())) await p.locator(`.ei-fd-pick[data-f="${f}"] .ei-fd-picked`).getByRole('button', { name: /Change/ }).first().click(); else await b.click();
      await p.waitForSelector('#ei-fd-look'); await p.locator('#ei-fd-look').pressSequentially(term, { delay: 15 });
      if (enter) { await p.keyboard.press('Enter'); await p.waitForTimeout(1400); }
    };

    // R01: Home still works at the recorded window, and opens New Feeding Entry from the top bar
    await p.goto(`${ctx.base}/odoo/action-ei_ui_theme.action_ei_home`); await p.waitForSelector('.ei-home', { timeout: 60000 }); await p.waitForTimeout(800);
    const homeScroll = await p.evaluate(() => { const sc = [...document.querySelectorAll('.o_action_manager *')].find((e) => e.scrollHeight > e.clientHeight + 20 && /(auto|scroll)/.test(getComputedStyle(e).overflowY)); if (!sc) return 'none'; const b = sc.scrollTop; sc.scrollTop += 200; return sc.scrollTop > b; });
    await p.locator('.o_menu_sections .o_nav_entry, .o_menu_sections .dropdown-toggle', { hasText: 'New Feeding Entry' }).first().click(); await p.waitForSelector('#ei-fd-daname', { timeout: 30000 });
    ctx.check(homeScroll !== false, 'R01 Home scrolls at 1364x590 and opens New Feeding Entry from the top bar', String(homeScroll));

    // R05 + R06: the three parties once (Enter and Tab move on), the coil inherits Sold To and its sales code by itself
    await p.locator('#ei-fd-daname').click(); await typeEnter(DA);
    ctx.check(['ei-fd-supplier', 'ei-fd-pin', 'ei-fd-sold'].includes(await focused()) || /ei-fd-link/.test(await focused()), 'R05 Enter after the DA number moves to the parties', await focused());
    if (await p.locator('.ei-fd-supplier .ei-fd-picked').count()) await p.locator('.ei-fd-supplier .ei-fd-picked button').click();
    await p.locator('#ei-fd-supplier').click(); await typeEnter('DEMO Parent Steel');
    if (await p.locator('.ei-fd-pin .ei-fd-picked').count()) { await p.locator('.ei-fd-pin .ei-fd-picked button').click(); await p.waitForTimeout(300); }
    await p.locator('#ei-fd-pin').click(); await typeEnter('DEMO Buying');
    await typeEnter('Rehman');
    await p.waitForSelector('#ei-fd-item, #ei-fd-coil', { timeout: 20000 }); await p.waitForTimeout(900);
    const cust = await txt('.ei-fd-pick[data-f="customer"]');
    ctx.check(/Rehman/.test(cust) && /from the DA/.test(cust) && !(await p.locator('.ei-fd-pick[data-f="customer"] > button').count()),
      'R06 the coil shows Sold To from the DA ("from the DA", Change for this coil); no second empty customer picker', cust);
    ctx.check(/D\.01/.test(await txt('.ei-fd-pick[data-f="customer_code"]')), 'R08 the sales code D.01 is filled by itself from Rehman\'s verified code link (nothing typed)', await txt('.ei-fd-pick[data-f="customer_code"]'));
    await ctx.shot(p, '31_R06_inherited_sold_to');

    // R14 + R16: an item typed but not chosen is said beside the box; Save lists what is missing and goes to it
    const prodsBefore = await count('product.product', []);
    if (!(await p.locator('#ei-fd-item').count())) { await p.locator('.ei-fd-item .ei-fd-picked').getByRole('button', { name: 'Change' }).click(); await p.waitForTimeout(500); }
    await p.locator('#ei-fd-item').click(); await typeEnter(`DEMO GP 1.50X1219 (P${stamp})`);
    ctx.check(/is not in the item list yet/.test(await txt('.ei-fd-item .ei-fd-ferr')) && !(await p.locator('.ei-fd-editor .ei-fd-error').count()) && await count('product.product', []) === prodsBefore,
      'R14 an unknown item typed + Enter: a message beside the Item box, no new item made, no red error at the bottom', await txt('.ei-fd-item .ei-fd-ferr'));
    await p.fill('#ei-fd-qty', '5.724');
    await p.getByRole('button', { name: 'Save Entry' }).click(); await p.waitForTimeout(900);
    const miss = await txt('.ei-fd-missing');
    ctx.check(/Item: .* is typed but not chosen/.test(miss) && /Coil No/.test(miss) && /Method/.test(miss) && await focused() === 'ei-fd-item' && !/contract line/i.test(miss),
      'R17 Save lists exactly what is missing (item, coil no, method) beside Save, jumps to the first one, and never says "contract line"', miss + ' | focus ' + await focused());
    await ctx.shot(p, '31_R17_missing_list');
    await p.locator('#ei-fd-item').fill(''); await p.locator('#ei-fd-item').click(); await typeEnter('DEMO HR');
    ctx.check(/DEMO HR/.test(await txt('.ei-fd-item .ei-fd-picked')) && !(await p.locator('.ei-fd-item .ei-fd-ferr').count()) && await count('product.product', []) === prodsBefore,
      'R15/R16 an existing item chosen with Enter: linked, the old message is gone, no duplicate item', await txt('.ei-fd-item'));

    // R08-R13: codes by name or code; a pair that does not belong together is flagged with the matching code to use
    await pick('trade_code', `DEMO ALPHA${stamp} EXPORT`);
    ctx.check(new RegExp(C.ta.replace('.', '\\.')).test(await txt('.ei-fd-pick[data-f="trade_code"]')), 'R08 a purchase code found by its name only (no number typed)', await txt('.ei-fd-pick[data-f="trade_code"]'));
    await pick('pl_code', 'DEMO', true);
    ctx.check(/codes match: pick the right one/.test(await txt('.ei-fd-look')) && !/D8/.test(await txt('.ei-fd-pick[data-f="pl_code"] .ei-fd-picked')),
      'R10 a name that matches several codes is not guessed by Enter: the matches stay listed to pick from', await txt('.ei-fd-look .ei-fd-ambig'));
    await p.keyboard.press('Escape'); await p.waitForTimeout(300);
    await pick('pl_code', C.pb);
    ctx.check(new RegExp(C.pb.replace('.', '\\.')).test(await txt('.ei-fd-pick[data-f="pl_code"]')), 'R09 a code typed exactly is taken with its full name', await txt('.ei-fd-pick[data-f="pl_code"]'));
    await p.waitForTimeout(900);
    const warn = await txt('.ei-fd-codecheck');
    ctx.check(/Please check these codes/.test(warn) && new RegExp(`goes with P&L ${C.pa.replace('.', '\\.')}`).test(warn) && await p.locator('.ei-fd-usepl').count() === 1,
      'R11 purchase ALPHA EXPORT + P&L BETA EXPORT NEW: a plain warning naming the matching P&L, with one button to use it', warn.slice(0, 260));
    await ctx.shot(p, '31_R11_code_pair_warning');
    await pick('customer_code', 'D.02');
    await p.waitForTimeout(900);
    ctx.check(/belongs to DEMO Customer - Noor Steel, not to DEMO Customer - Rehman Traders/.test(await txt('.ei-fd-salescheck')), 'R13 sales code D.02 against Sold To Rehman: "belongs to Noor Steel, not to Rehman Traders"', await txt('.ei-fd-salescheck'));
    await pick('customer_code', 'D.01');
    await p.locator('.ei-fd-usepl').click(); await p.waitForTimeout(1000);
    ctx.check(/belong together/.test(await txt('.ei-fd-codecheck')) && new RegExp(C.pa.replace('.', '\\.')).test(await txt('.ei-fd-pick[data-f="pl_code"]')), 'R12 one click on the matching P&L: the warning becomes "These codes belong together"', await txt('.ei-fd-codecheck'));

    // R19 + R21: a complete coil saved (Save pressed twice), reopened with the same values
    await p.fill('#ei-fd-coil', `C-${stamp}`);
    await p.getByRole('radio', { name: /Direct \(no commission\)/ }).click(); await p.waitForTimeout(300);
    await p.locator('.ei-fd-editor .ei-fd-field:has-text("Purchase rate") input').fill('229500'); await p.locator('.ei-fd-editor .ei-fd-field:has-text("Sale rate") input').fill('230500'); await p.waitForTimeout(1200);
    const movesBefore = await count('account.move', []);
    await p.locator('.ei-fd-savebtn').dblclick(); await p.waitForTimeout(2500);
    const lines = await admin.rpc('ei.da.line', 'search_read', [[['da_id.name', '=', DA]], ['coil_no', 'mtl', 'customer_id', 'customer_code_id', 'trade_code_id', 'pl_code_id', 'purchase_rate', 'sale_rate', 'product_id']]);
    ctx.check(lines.length === 1 && lines[0].mtl === 5.724 && /Rehman/.test(lines[0].customer_id[1]) && lines[0].customer_code_id[1].includes('D.01') && lines[0].pl_code_id[0] === ids.pa && /DEMO HR/.test(lines[0].product_id[1]),
      'R19/R21 Save pressed twice: one coil, 5.724 MTL, the item, customer and codes as chosen', JSON.stringify(lines));
    ctx.check(await count('account.move', []) === movesBefore, 'R18 saving coils on a draft posts nothing to the books');
    await p.reload(); await p.waitForSelector('.ei-fd-darow'); await p.locator('.ei-fd-darow', { hasText: DA }).first().click(); await p.waitForSelector('.ei-fd-table');
    ctx.check(new RegExp(`C-${stamp}`).test(await txt('.ei-fd-table')) && /5\.724/.test(await txt('.ei-fd-table')), 'R19 reopened: the coil and its weight are there', await txt('.ei-fd-table tbody'));

    // R07: Sold To changed on the draft: the person chooses which coils follow
    await p.getByRole('button', { name: 'Copy Previous' }).click(); await p.waitForSelector('#ei-fd-coil'); await p.fill('#ei-fd-coil', `C2-${stamp}`); await p.fill('#ei-fd-qty', '4.574'); await p.waitForTimeout(1200);
    await p.getByRole('button', { name: 'Save Entry' }).click(); await p.waitForTimeout(1800);
    await p.locator('.ei-fd-soldchange').click(); await p.locator('#ei-fd-soldnew').click(); await typeEnter('Noor');
    const choice = await txt('.ei-fd-soldbox');
    ctx.check(/Which coils follow/.test(choice) && /Also the 2 coil\(s\) sold to DEMO Customer - Rehman Traders/.test(choice) && /Only coils added from now on/.test(choice), 'R07 changing Sold To asks: also the 2 coils sold to Rehman, or only new coils', choice);
    await p.locator('.ei-fd-soldnewonly').click(); await p.waitForTimeout(1500);
    const after7 = await admin.rpc('ei.da.line', 'search_read', [[['da_id.name', '=', DA]], ['customer_id']]);
    const head7 = await one('ei.da', [['name', '=', DA]], ['sold_out_id']);
    ctx.check(/Noor/.test(head7.sold_out_id[1]) && after7.every((l) => /Rehman/.test(l.customer_id[1])), '"Only coils added from now on": Sold To is Noor; the two saved coils keep Rehman (no silent rewrite)', JSON.stringify(after7));
    await p.locator('.ei-fd-soldchange').click(); await p.locator('#ei-fd-soldnew').click(); await typeEnter('Rehman'); await p.waitForTimeout(400);
    await p.locator('.ei-fd-soldall').click(); await p.waitForTimeout(1500);

    // R20 + R27: submitted, a different person approves, the From -> To trace shows it
    m = s.mark();
    await p.getByRole('button', { name: 'Submit for Approval' }).click(); await p.waitForSelector('.ei-fd-done.is-wait', { timeout: 30000 });
    const rec = await one('ei.da', [['name', '=', DA]], ['state', 'id']);
    const rq = await one('ei.approval.request', [['res_model', '=', 'ei.da'], ['res_id', '=', rec.id]], ['id']);
    const chk = await new Session(ctx, browser, 'demo.contractapprover', 'demo', [1364, 590], { timeout: 30000 }).start();
    await chk.rpc('ei.approval.request', 'decide', [rq.id, 'approve', 'Checked: codes belong together']);
    ctx.check(rec.state === 'under_review' && (await one('ei.da', [['id', '=', rec.id]], ['state'])).state === 'approved', 'R20 submitted by the maker, approved by a different person', rec.state);
    const cp = chk.page;
    await cp.goto(`${ctx.base}/odoo/action-ei_da_feeding.ei_ledger_trace_action`); await cp.waitForSelector('.o_list_view', { timeout: 30000 });
    await cp.locator('.o_searchview_input').fill(DA); await cp.keyboard.press('Enter'); await cp.waitForTimeout(1500);
    const tr = (await cp.locator('.o_list_view').innerText()).replace(/\s+/g, ' ');
    ctx.check(new RegExp(`C-${stamp}`).test(tr) && /DEMO Parent Steel Mill/.test(tr) && /Rehman/.test(tr), 'R27 From → IN → OUT trace lists the approved coils with supplier and customer', tr.slice(0, 220));
    await chk.close();

    // R22: a DA number one letter off is flagged before a second DA is made
    await p.goto(`${ctx.base}/odoo/action-ei_da_feeding.action_ei_new_feeding`); await p.waitForSelector('#ei-fd-daname', { timeout: 30000 }); await p.waitForTimeout(600);
    await p.locator('#ei-fd-daname').click(); await typeEnter(DA.replace('NOV', 'NV'));
    if (await p.locator('.ei-fd-supplier .ei-fd-picked').count()) await p.locator('.ei-fd-supplier .ei-fd-picked button').click();
    await p.locator('#ei-fd-supplier').click(); await typeEnter('DEMO Parent Steel');
    if (await p.locator('#ei-fd-pin').count()) { await p.locator('#ei-fd-pin').click(); await typeEnter('DEMO Buying'); }
    await p.locator('#ei-fd-gocoil').click(); await p.waitForTimeout(1500);
    ctx.check(/very similar DA number/.test(await txt('.ei-fd-warnbox')) && new RegExp(DA).test(await txt('.ei-fd-warnbox')) && await count('ei.da', [['name', '=', DA.replace('NOV', 'NV')]]) === 0,
      'R22 typing ...NV after ...NOV: "A very similar DA number is already in the system. A typing mistake?" and nothing is made yet', await txt('.ei-fd-warnbox'));
    await ctx.shot(p, '31_R22_similar_number');
    await s.clean('R01-R22 the feeding screens are clean (no console, page or server errors)', m0);
    await s.close();

    // R02-R04 + R28: the recorded window at 80-200% zoom, laptops, a tablet and phones: every coil box and Save reachable and
    // clickable, nothing covered by a pinned bar, the mouse wheel scrolls the form, no sideways page scroll
    const recA = await one('ei.da', [['name', '=', DA]], ['parent_partner_id', 'purchase_in_id', 'sold_out_id']);
    const SIZE_DA = `DEMO-SIZE-${stamp}`;
    const sda = await admin.rpc('ei.feeding.desk', 'da_create', [{ name: SIZE_DA, supplier_id: recA.parent_partner_id[0], purchase_in_id: recA.purchase_in_id[0], sold_out_id: recA.sold_out_id[0] }]);
    const prod = (await one('ei.da.line', [['da_id.name', '=', DA]], ['product_id'])).product_id[0];
    const scl = (await admin.rpc('ei.feeding.desk', 'ensure_line', [sda, prod])).contract_line_id;
    await admin.rpc('ei.feeding.desk', 'save_line', [sda, false, { contract_line_id: scl, coil_no: `S-${stamp}`, weight_kg: '4574', method: 'direct_no_commission', purchase_rate: '229500', sale_rate: '230500' }]);
    const sizes = [['1364x590 80%', 1705, 738], ['1364x590 90%', 1516, 656], ['1364x590 100%', 1364, 590], ['1364x604 100%', 1364, 604],
      ['1364x590 125%', 1091, 472], ['1364x590 150%', 909, 393], ['1364x590 175%', 779, 337], ['1364x590 200%', 682, 295],
      ['1280x576', 1280, 576], ['1366x768', 1366, 768], ['1280x720', 1280, 720], ['1024x768', 1024, 768], ['768x1024 tablet', 768, 1024],
      ['390x844 phone', 390, 844], ['320x568 phone', 320, 568],
      ['1366x768 150% (T03)', 911, 512], ['1280x720 175% (T04)', 731, 411], ['1024x768 200% (T05)', 512, 384], ['1360x610 100% (T01)', 1360, 610], ['1364x640 100% (T02)', 1364, 640], ['1364x720 100% (recording 6416)', 1364, 720]];
    for (const [label, w, h] of sizes) {
      const v = await new Session(ctx, browser, 'demo.contracts', 'demo', [w, h], { timeout: 30000 }).start();
      const q = v.page;
      try {
        await q.goto(`${ctx.base}/odoo/action-ei_da_feeding.action_ei_da_feeding`); await q.waitForSelector('.ei-fd-darow', { timeout: 30000 });
        await q.locator('.ei-fd-darow', { hasText: SIZE_DA }).first().click(); await q.waitForSelector('h2.ei-fd-daname'); await q.waitForTimeout(500);
        const add = q.getByRole('button', { name: 'Add Coil' });
        if (await add.count()) { await add.click(); } else { await q.locator('.ei-fd-table tbody tr').first().getByRole('button', { name: 'Edit' }).click(); }
        await q.waitForSelector('.ei-fd-savebtn'); await q.waitForTimeout(700);
        // the real mouse wheel, both ways (24 Nov root cause: the page had overflow hidden, so only focus could move it)
        const box = await q.locator('.ei-fd').boundingBox(), top = () => q.evaluate(() => document.querySelector('.ei-fd').scrollTop);
        await q.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
        const t0 = await top(); await q.mouse.wheel(0, -300); await q.waitForTimeout(500); const t1 = await top(); await q.mouse.wheel(0, 200); await q.waitForTimeout(500); const t2 = await top();
        const wheel = (t1 < t0 || t0 === 0) && t2 > t1 && (await q.evaluate(() => getComputedStyle(document.querySelector('.ei-fd')).overflowY)) === 'auto';
        const r = await q.evaluate(() => {
          const sc = document.querySelector('.ei-fd');
          const ok = (el) => { el.scrollIntoView({ block: 'center' }); const b = el.getBoundingClientRect(); const t = document.elementFromPoint(b.left + Math.min(10, b.width / 2), b.top + b.height / 2); return !!t && (t === el || el.contains(t)); };
          const inputs = [...document.querySelectorAll('.ei-fd-editor input:not([type=checkbox]):not([type=file]), .ei-fd-editor .ei-fd-pick > button, .ei-fd-editor .ei-fd-mpick')].filter((e) => e.offsetParent);
          const bad = inputs.filter((e) => !ok(e)).map((e) => e.id || e.className.split(' ').slice(-1)[0]);
          const save = document.querySelector('.ei-fd-savebtn'); const saveOk = ok(save);
          const fs = parseFloat(getComputedStyle(document.querySelector('.ei-fd-field > span')).fontSize);
          return { inputs: inputs.length, bad, saveOk, label: fs, overflow: document.documentElement.scrollWidth > innerWidth + 1, scrolls: sc.scrollHeight > sc.clientHeight };
        });
        ctx.check(r.saveOk && !r.bad.length && r.label >= 12 && !r.overflow && (wheel || !r.scrolls),
          `R02-R04 ${label}: all ${r.inputs} coil boxes and Save Entry reachable and clickable (none under a pinned bar), the wheel scrolls the form, labels ${r.label}px, no sideways scroll`, JSON.stringify({ ...r, wheel }));
        await ctx.shot(q, `31_size_${label.replace(/[^0-9a-z]+/gi, '_')}`);
        if (label === '1364x590 100%') {                     // R28: resize and zoom again, go Home and back: nothing lost, no errors
          const mm = v.mark();
          for (const [ww, hh] of [[682, 295], [1705, 738], [1364, 590]]) { await q.setViewportSize({ width: ww, height: hh }); await q.waitForTimeout(400); }
          const nav = (t) => q.locator('.o_menu_sections .o_nav_entry, .o_menu_sections .dropdown-toggle', { hasText: t }).first();
          await nav('Home').click(); await q.waitForSelector('.ei-home', { timeout: 30000 }); await nav('New Feeding Entry').click(); await q.waitForSelector('.ei-fd', { timeout: 30000 }); await q.waitForTimeout(800);
          ctx.check(await q.locator('.ei-fd-darow', { hasText: SIZE_DA }).count() === 1, 'R28 resized and zoomed back and forth, Home and back by the menu: the feeding screen and the open draft are there');
          await v.clean('R28 no missing assets or errors after resizing and navigating back', mm);
        }
      } catch (e) { ctx.check(false, `R02-R04 ${label}`, String(e.message).split('\n')[0]); }
      await v.close();
    }
    await admin.close();
  },
};
