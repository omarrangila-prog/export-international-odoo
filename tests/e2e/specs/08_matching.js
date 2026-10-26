// "Match bank payments": a bank officer takes a staged statement from "who paid" to "which invoices", the way a person
// does it: menu -> line -> button -> result. Every check asserts on what is on the screen AND on the real records behind
// it, because the promise of this screen is that a suggestion never becomes a fact by itself and that nothing reaches
// the books from it.
const stamp = Date.now();
const today = new Date();
const iso = (days) => new Date(today.getTime() + days * 86400000).toISOString().slice(0, 10);
const dmy = (d) => `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`;

module.exports = {
  name: '08 match bank payments (who paid -> which invoices)',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const admin = await new Session(ctx, browser, 'admin', 'admin').start();

    // ---- arrangement, as real data: a customer with a known bank name, three open invoices, and a staged statement
    const name = `E2E Match Traders ${stamp}`;
    const [partnerId] = [await admin.rpc('res.partner', 'create', [[{ name }]]).then(r => r[0])];
    await admin.rpc('ei.partner.alias', 'create', [[{ partner_id: partnerId, alias: `E2EMATCH${stamp}`, state: 'approved' }]]);
    const invoice = async (amount, due) => {
      const [id] = await admin.rpc('account.move', 'create', [[{ move_type: 'out_invoice', partner_id: partnerId, invoice_date: iso(-30), invoice_date_due: due,
        invoice_line_ids: [[0, 0, { name: 'E2E steel', quantity: 1, price_unit: amount, tax_ids: [[6, 0, []]] }]] }]]);
      await admin.rpc('account.move', 'action_post', [[id]]);
      return id;
    };
    const inv1 = await invoice(100000, iso(-10)), inv2 = await invoice(320000, iso(5)), inv3 = await invoice(50000, iso(20));
    const [journal] = await admin.rpc('account.journal', 'search_read', [[['name', '=', 'DEMO Meezan Bank']], ['id']]);
    const d = dmy(today);
    const csv = `Date,Description,Reference,Debit,Credit,Balance\n` +
      `${d},RAAST FROM E2EMATCH${stamp} KHI,TXA${stamp},,420000,420000\n` +
      `${d},UNKNOWN DEPOSIT E2EB${stamp},,,75000,495000\n` +
      `${d},UNKNOWN DEPOSIT E2EC${stamp},,,75000,570000\n` +
      `${d},CHEQUE COLLECTED E2ED${stamp},,,10000,580000\n`;
    const bank = await new Session(ctx, browser, 'demo.bank', 'demo').start();
    const [wid] = await bank.rpc('ei.bank.import.wizard', 'create', [[{ journal_id: journal.id, filename: `e2e_match_${stamp}.csv`, file: Buffer.from(csv).toString('base64'), opening_balance: 0, closing_balance: 580000 }]]);
    const act = await bank.rpc('ei.bank.import.wizard', 'action_import', [[wid]]);
    await bank.rpc('ei.bank.import', 'action_suggest', [[act.res_id]]);
    const line = async (frag) => (await bank.rpc('ei.bank.import.line', 'search_read', [[['narration', 'ilike', frag]], ['id', 'state', 'partner_id', 'allocated', 'statement_line_id', 'verified_by']]))[0];
    const moves = () => admin.rpc('account.move', 'search_count', [[]]);
    ctx.check(act.res_id > 0 && (await line(`E2EMATCH${stamp}`)).state === 'proposed', 'arranged: a staged statement with a suggestion on the first line');

    const p = bank.page;
    // a toast from the step before may still be on screen: wait for the one that matches this step (CSS may upper-case, so ignore case)
    const toast = async (re, label) => {
      await p.waitForFunction(([src]) => new RegExp(src, 'i').test((document.querySelector('.ei-mt-toast') || { innerText: '' }).innerText), [re.source], { timeout: 8000 }).catch(() => {});
      const t = await p.locator('.ei-mt-toast').first().innerText().catch(() => '');
      ctx.check(new RegExp(re.source, 'i').test(t), label, t); return t;
    };
    const rows = () => p.locator('.ei-mt-row');
    const search = async (q) => { await p.fill('#ei-mt-q', q); await p.waitForTimeout(900); };
    const pick = async (frag) => { await rows().filter({ hasText: frag }).first().click(); await p.waitForSelector('.ei-mt-bigamt', { timeout: 8000 }); await p.waitForTimeout(500); };
    const tab = (label) => p.locator('.ei-mt-tab', { hasText: label });
    const decide = () => p.locator('.ei-mt-decide');
    const evidence = () => p.locator('.ei-mt-evidence');

    // ---- 1 the screen opens from the Money menu, with the real lines
    let m = bank.mark();
    await bank.menu('Money', 'Match bank payments');
    await p.waitForSelector('.ei-mt .ei-mt-cols', { timeout: 15000 });
    await p.waitForTimeout(800);
    ctx.check(await tab('To check').count() === 1 && await tab('Waiting for allocation').count() === 1 && await tab('Unidentified').count() === 1 && await tab('Duplicates').count() === 1, '1 the four lists are there');
    ctx.check(await rows().count() >= 4, '1 the staged lines are listed', String(await rows().count()));
    await bank.clean('1 opening the screen is clean', m);
    await ctx.shot(p, 'matching_open');

    // ---- 2 a suggestion is only a suggestion
    await search(String(stamp));
    ctx.check(await rows().count() === 4, '2 searching finds exactly the four lines of this statement', String(await rows().count()));
    const rowA = rows().filter({ hasText: `E2EMATCH${stamp}` });
    ctx.check(/Suggested: E2E Match Traders .* 90%/.test(await rowA.innerText()), '2 the row says "Suggested", with how sure it is');
    await pick(`E2EMATCH${stamp}`);
    ctx.check(/suggestion, not confirmed/i.test(await decide().innerText()), '2 the decision shows it as a suggestion, not confirmed');
    ctx.check(/approved for this party/.test(await decide().innerText()), '2 it says why it was suggested');
    ctx.check(await decide().locator('.ei-mt-item').count() === 3 && await decide().locator('.ei-mt-input.is-amt').count() === 0, '2 the party\'s open invoices are only previewed: nothing can be allocated yet');
    ctx.check(/Confirm the party above to allocate/.test(await decide().innerText()), '2 the preview says what to do first');
    let a = await line(`E2EMATCH${stamp}`);
    ctx.check(a.state === 'proposed' && !a.partner_id && a.allocated === 0, '2 in the database nothing was confirmed or allocated by looking at it', JSON.stringify(a));

    // ---- 3 confirming is a deliberate click, recorded on the line
    await p.getByRole('button', { name: 'Use this party' }).click(); await p.waitForTimeout(400);
    ctx.check(/Note \(optional\)/.test(await decide().locator('.ei-mt-pick').innerText()), '3 an approved name needs no evidence note');
    m = bank.mark();
    await p.getByRole('button', { name: new RegExp(`Confirm that E2E Match Traders .* paid`) }).click();
    await toast(/Confirmed/, '3 the screen says the party is confirmed');
    await p.waitForTimeout(800);
    ctx.check(/Confirmed/.test(await decide().locator('.ei-mt-confirmed').innerText()), '3 the decision now shows the party as Confirmed');
    ctx.check(await tab('Waiting for allocation').getAttribute('aria-selected') === 'true', '3 the screen followed the line to "Waiting for allocation"');
    a = await line(`E2EMATCH${stamp}`);
    ctx.check(a.state === 'verified' && a.partner_id && a.partner_id[1] === name && a.verified_by && /bank/i.test(a.verified_by[1]), '3 the database holds the confirmation and who made it', JSON.stringify(a));
    await bank.clean('3 confirming is clean', m);

    // ---- 4 invoices: a proposal is not saved; a bad amount is stopped; saving changes no books
    const amtInputs = () => decide().locator('.ei-mt-input.is-amt');
    ctx.check(await amtInputs().count() === 3, '4 each open invoice has an amount box');
    await p.getByRole('button', { name: 'Suggest invoices' }).click(); await p.waitForTimeout(900);
    ctx.check(/Suggestion, not saved/.test(await decide().innerText()), '4 the proposal is labelled as not saved');
    ctx.check(/add up exactly/.test(await decide().innerText()), '4 it explains it found an exact match');
    ctx.check([await amtInputs().nth(0).inputValue(), await amtInputs().nth(1).inputValue(), await amtInputs().nth(2).inputValue()].join(',') === '100000,320000,', '4 it filled 100,000 and 320,000, leaving the third invoice alone');
    a = await line(`E2EMATCH${stamp}`);
    ctx.check(a.allocated === 0, '4 asking for a proposal saved nothing', String(a.allocated));
    await amtInputs().nth(2).fill('60000'); await p.waitForTimeout(400);
    ctx.check(/more than the payment/.test(await decide().innerText()) || /Only .* is open/.test(await decide().innerText()), '4 more than the payment, or more than an invoice has open, is stopped on screen');
    ctx.check(await p.getByRole('button', { name: 'Save allocation' }).isDisabled(), '4 and Save allocation is disabled while it is wrong');
    await amtInputs().nth(2).fill(''); await p.waitForTimeout(400);
    const movesBefore = await moves();
    m = bank.mark();
    await p.getByRole('button', { name: 'Save allocation' }).click();
    await toast(/Allocation saved/, '4 saving says so');
    await p.waitForTimeout(900);
    a = await line(`E2EMATCH${stamp}`);
    ctx.check(a.allocated === 420000 && !a.statement_line_id, '4 420,000 is allocated in the database and nothing is posted', JSON.stringify(a));
    ctx.check(await moves() === movesBefore, '4 saving created no journal entry: the books are untouched');
    ctx.check(/left the list/.test(await decide().innerText()), '4 a finished line stays on screen with its effect, and says it left the list');
    const impact = (await evidence().locator('.ei-mt-impact').innerText()).replace(/\s+/g, ' ');
    ctx.check(/preview/i.test(await evidence().innerText()) && /Nothing is posted from this screen/.test(await evidence().innerText()), '4 the effect is labelled a preview');
    ctx.check(/goes from .*100,000.* to .*0/.test(impact) && /goes from .*320,000.* to .*0/.test(impact), '4 the effect names each invoice and what it becomes', impact.slice(0, 200));
    ctx.check(/A bank approver checks the whole statement/.test(await evidence().innerText()), '4 it says who must approve and post next');
    ctx.check(/What the bank said/.test(await evidence().innerText()) && new RegExp(`E2EMATCH${stamp}`).test(await evidence().innerText()), '4 the bank\'s own words are beside the decision');
    await bank.clean('4 invoices step is clean', m);
    await ctx.shot(p, 'matching_allocated');

    // ---- 5 unidentified, reject, evidence
    await p.getByRole('button', { name: /Go to the next payment/ }).click(); await p.waitForTimeout(600);
    await tab('To check').click(); await p.waitForTimeout(900);
    await search(String(stamp));
    await pick(`E2EB${stamp}`);
    ctx.check(/Same amount nearby/.test(await rows().filter({ hasText: `E2EB${stamp}` }).innerText()), '5 two 75,000 lines on the same day carry a "same amount nearby" tag');
    ctx.check(/Another line has the same amount/.test(await evidence().innerText()) && new RegExp(`E2EC${stamp}`).test(await evidence().innerText()), '5 the evidence names the other line and says to check it');
    let b = await line(`E2EB${stamp}`);
    ctx.check(b.state === 'new' || b.state === 'proposed', '5 the warning changed nothing', b.state);
    await p.getByRole('button', { name: 'Nobody knows who paid' }).click(); await p.waitForTimeout(500);
    ctx.check(await p.locator('.ei-mt-dialog').count() === 1 && await p.evaluate(() => !!document.activeElement && !!document.activeElement.closest('.ei-mt-dialog')), '5 the dialog opens with the keyboard focus inside it');
    await p.keyboard.type('Called the branch: no name on the slip');
    m = bank.mark();
    await p.locator('.ei-mt-dialog').getByRole('button', { name: 'Mark unidentified' }).click();
    await toast(/unidentified/i, '5 marking unidentified is confirmed');
    await p.waitForTimeout(800);
    b = await line(`E2EB${stamp}`);
    ctx.check(b.state === 'unidentified', '5 the line is unidentified in the database', b.state);
    ctx.check(new RegExp(`E2EC${stamp}`).test(await decide().innerText()), '5 the screen moved on to the next line');
    // reject needs a reason
    await p.getByRole('button', { name: 'Reject this line' }).click(); await p.waitForTimeout(400);
    await p.locator('.ei-mt-dialog').getByRole('button', { name: 'Reject line' }).click(); await p.waitForTimeout(400);
    ctx.check(await p.locator('.ei-mt-dialog').count() === 1 && /needs a reason/.test(await p.locator('.ei-mt-toast').innerText()), '5 a rejection without a reason is refused and the dialog stays');
    await p.keyboard.press('Escape'); await p.waitForTimeout(300);
    ctx.check(await p.locator('.ei-mt-dialog').count() === 0, '5 Escape closes the dialog');
    await p.getByRole('button', { name: 'Reject this line' }).click(); await p.waitForTimeout(400);
    await p.keyboard.type('E2E: not ours');
    await p.locator('.ei-mt-dialog').getByRole('button', { name: 'Reject line' }).click(); await p.waitForTimeout(1200);
    ctx.check((await line(`E2EC${stamp}`)).state === 'rejected', '5 the rejected line is rejected in the database');
    await bank.clean('5 unidentified and reject are clean', m);

    // the unidentified line is found later: a name that is not approved needs evidence
    await tab('Unidentified').click(); await p.waitForTimeout(900);
    await search(String(stamp));
    await pick(`E2EB${stamp}`);
    await p.fill('#ei-mt-party', name.slice(0, 14)); await p.waitForTimeout(900);
    await p.locator('.ei-mt-result', { hasText: name }).first().click(); await p.waitForTimeout(300);
    ctx.check(/How do you know\? \(required\)/.test(await decide().locator('.ei-mt-pick').innerText()), '5 a party found by search needs an evidence note');
    await p.getByRole('button', { name: /Confirm that .* paid/ }).click(); await p.waitForTimeout(600);
    ctx.check(/Write how you know/.test(await p.locator('.ei-mt-toast').innerText()) && (await line(`E2EB${stamp}`)).state === 'unidentified', '5 without a note nothing is saved');
    await p.fill('#ei-mt-note', 'Slip received on WhatsApp'); await p.waitForTimeout(200);
    await p.getByRole('button', { name: /Confirm that .* paid/ }).click(); await p.waitForTimeout(1500);
    b = await line(`E2EB${stamp}`);
    ctx.check(b.state === 'verified' && b.partner_id && b.partner_id[1] === name, '5 with a note the party is confirmed', JSON.stringify(b));
    // part of a payment: 50,000 of 75,000, the rest stays unallocated and is said so
    await p.getByRole('button', { name: 'Suggest invoices' }).click(); await p.waitForTimeout(900);
    ctx.check(/oldest invoices first|No invoice/.test(await decide().innerText()), '5 with no exact match the proposal says it is only "oldest first"');
    await p.getByRole('button', { name: 'Save allocation' }).click(); await p.waitForTimeout(1500);
    ctx.check(/stays unallocated/.test(await evidence().innerText()), '5 the effect says the remaining 25,000 stays unallocated, nothing guessed');
    b = await line(`E2EB${stamp}`);
    ctx.check(b.allocated === 50000, '5 50,000 is allocated', String(b.allocated));

    // ask a colleague, put aside
    await tab('To check').click(); await p.waitForTimeout(900);
    await search(`E2ED${stamp}`);
    await pick(`E2ED${stamp}`);
    await p.getByRole('button', { name: 'Ask a colleague for evidence' }).click(); await p.waitForTimeout(500);
    const people = p.locator('.ei-mt-dialog select option');
    ctx.check(await people.count() >= 2, '5 the colleagues who can open the line are offered', String(await people.count()));
    const who = await people.nth(1).getAttribute('value');
    await p.locator('.ei-mt-dialog select').selectOption(who);
    await p.locator('.ei-mt-dialog textarea').fill('Please send the payment slip for this cheque');
    await p.locator('.ei-mt-dialog').getByRole('button', { name: 'Write it on the line' }).click();
    await toast(/Noted on the line/, '5 asking for evidence is confirmed');
    const d1 = await line(`E2ED${stamp}`);
    const acts = await bank.rpc('mail.activity', 'search_read', [[['res_model', '=', 'ei.bank.import.line'], ['res_id', '=', d1.id]], ['user_id', 'summary']]);
    ctx.check(acts.length === 1 && acts[0].user_id[0] === Number(who) && d1.state !== 'unidentified', '5 the colleague got a reminder and the line itself did not change', JSON.stringify(acts));
    await p.getByRole('button', { name: 'Put it aside' }).click(); await p.waitForTimeout(300);
    await p.getByRole('menuitem', { name: 'Until tomorrow' }).click(); await p.waitForTimeout(1200);
    ctx.check(await rows().filter({ hasText: `E2ED${stamp}` }).count() === 0, '5 a line put aside leaves the list');
    ctx.check(/Put aside\s*[1-9]/.test(await p.locator('.ei-mt-tab.is-aside').innerText()), '5 "Put aside" shows how many');
    await p.locator('.ei-mt-tab.is-aside').click(); await p.waitForTimeout(900);
    await pick(`E2ED${stamp}`);
    await p.getByRole('button', { name: 'Put it back on my list' }).click(); await p.waitForTimeout(1200);
    ctx.check((await line(`E2ED${stamp}`)).state !== 'rejected', '5 putting aside never changed the line itself');

    // ---- 6 keyboard
    await tab('To check').click(); await p.waitForTimeout(900);
    await search('');
    const first = rows().first(); await first.focus(); await first.click(); await p.waitForTimeout(700);
    const before = await p.locator('.ei-mt-row[aria-current=true]').getAttribute('id');
    await p.keyboard.press('ArrowDown'); await p.waitForTimeout(900);
    const after = await p.locator('.ei-mt-row[aria-current=true]').getAttribute('id');
    ctx.check(before !== after, '6 the Down arrow chooses the next line', `${before} -> ${after}`);
    await p.keyboard.press('/'); await p.waitForTimeout(200);
    ctx.check(await p.evaluate(() => document.activeElement && document.activeElement.id) === 'ei-mt-q', '6 "/" jumps to the search box');

    // ---- 7 who may do what
    const approver = await new Session(ctx, browser, 'demo.bankapprover', 'demo').start();
    m = approver.mark();
    await approver.menu('Money', 'Match bank payments');
    await approver.page.waitForSelector('.ei-mt .ei-mt-row', { timeout: 15000 });
    await approver.page.locator('.ei-mt-row').first().click(); await approver.page.waitForTimeout(900);
    const at = await approver.page.locator('.ei-mt-decide').innerText();
    ctx.check(/only bank officers can decide/.test(at), '7 a bank approver sees the line and is told only officers decide');
    ctx.check(!/Use this party|Reject this line|Ask a colleague/.test(at) && await approver.page.locator('.ei-mt-input.is-amt').count() === 0, '7 and has no decision buttons or amount boxes');
    await approver.clean('7 the approver view is clean', m);
    await approver.close();
    const other = await new Session(ctx, browser, 'demo.contracts', 'demo').start();
    const q = await other.rpc('ei.matching', 'queue', ['check']);
    ctx.check(q.items.length === 0 && !q.can_review, '7 a colleague with no bank role gets an empty list from the server');
    let refused = false;
    try { await other.rpc('ei.matching', 'confirm_party', [d1.id, partnerId, 'x']); } catch { refused = true; }
    ctx.check(refused, '7 and cannot confirm a party by calling the server directly');
    await other.close();

    // ---- 8 phone: one section at a time; tablet and desktop: no overflow; accessibility in light and dark
    const lay = async (label) => {
      const l = await bank.layout();
      ctx.check(!l.overflow && !l.wide.length, `${label}: no horizontal overflow`, JSON.stringify(l.wide));
      ctx.check(!l.clipped.length, `${label}: no clipped buttons or badges`, l.clipped.join(' | '));
    };
    await p.setViewportSize({ width: 390, height: 844 });
    await bank.goto('/odoo/action-ei_matching.action_ei_matching'); await p.waitForSelector('.ei-mt .ei-mt-row', { timeout: 15000 });
    ctx.check(await p.locator('.ei-mt-queue').isVisible() && !(await p.locator('.ei-mt-decide').isVisible()), '8 on a phone the list shows first and the decision is out of the way');
    await lay('8 phone list');
    await ctx.shot(p, 'matching_phone_list');
    await p.locator('.ei-mt-row').first().click(); await p.waitForTimeout(1000);
    ctx.check(await p.locator('.ei-mt-decide').isVisible() && !(await p.locator('.ei-mt-queue').isVisible()), '8 choosing a line opens its decision');
    await lay('8 phone decision');
    await ctx.shot(p, 'matching_phone_decision');
    await p.locator('.ei-mt-steps button', { hasText: 'Evidence' }).click(); await p.waitForTimeout(500);
    ctx.check(await p.locator('.ei-mt-evidence').isVisible() && /What posting would do/.test(await p.locator('.ei-mt-evidence').innerText()), '8 the bottom bar opens the evidence and the effect');
    await lay('8 phone evidence');
    for (const [w, h] of [[375, 812], [768, 1024], [1024, 768], [1440, 900]]) {
      await p.setViewportSize({ width: w, height: h });
      await bank.goto('/odoo/action-ei_matching.action_ei_matching'); await p.waitForSelector('.ei-mt .ei-mt-row', { timeout: 15000 });
      await p.locator('.ei-mt-row').first().click(); await p.waitForTimeout(900);
      await lay(`8 ${w}px`);
      if ([375, 768, 1440].includes(w)) {
        const v = await bank.axe('.ei-mt');
        const bad = (v || []).filter(x => ['serious', 'critical'].includes(x.impact));
        ctx.check(v !== null && !bad.length, `8 ${w}px light: no serious accessibility findings (axe)`, bad.map(x => `${x.id}(${x.n}): ${x.first}`).join(' | '));
      }
      if (w === 1440) await ctx.shot(p, 'matching_desktop_1440');
    }
    await bank.close();
    const dark = await new Session(ctx, browser, 'demo.bank', 'demo', [1440, 900], { cookies: [{ name: 'color_scheme', value: 'dark', path: '/' }] }).start();
    await dark.goto('/odoo/action-ei_matching.action_ei_matching'); await dark.page.waitForSelector('.ei-mt .ei-mt-row', { timeout: 15000 });
    await dark.page.locator('.ei-mt-row').first().click(); await dark.page.waitForTimeout(900);
    const dv = await dark.axe('.ei-mt');
    const dbad = (dv || []).filter(x => ['serious', 'critical'].includes(x.impact));
    ctx.check(dv !== null && !dbad.length, '8 dark mode 1440px: no serious accessibility findings (axe)', dbad.map(x => `${x.id}(${x.n}): ${x.first}`).join(' | '));
    await ctx.shot(dark.page, 'matching_desktop_dark');
    await dark.close();
    await admin.close();
  },
};
