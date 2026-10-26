// "Ask": the read-only assistant, used the way a person uses it: top-bar button -> question -> answer -> source. Every check asserts on
// what is on the screen AND on the real records behind it, because the promises of this feature are that answers equal the product's own
// figures, that every answer shows where it comes from, that a role never sees what it may not see, and that nothing can be changed.
const stamp = Date.now();
const today = new Date();
const iso = (days) => new Date(today.getTime() + days * 86400000).toISOString().slice(0, 10);
const digits = (t) => (String(t).match(/-?\d[\d,]*(?:\.\d+)?/) || ['0'])[0].replace(/,/g, '');

module.exports = {
  name: '09 ask (read-only assistant)',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const admin = await new Session(ctx, browser, 'admin', 'admin').start();

    // ---- arrangement: a customer who is 40 days late, and two parties with similar names
    const ledger = async () => {            // what the books say customers owe, straight from the journal items
      const rows = await admin.rpc('account.move.line', 'search_read', [[['parent_state', '=', 'posted'], ['reconciled', '=', false], ['account_type', '=', 'asset_receivable']], ['amount_residual']]);
      return rows.reduce((t, r) => t + r.amount_residual, 0);
    };
    const owedBefore = await ledger();
    const slowName = `E2E Slow Payer ${stamp}`;
    const [slowId] = await admin.rpc('res.partner', 'create', [[{ name: slowName }]]);
    const [invId] = await admin.rpc('account.move', 'create', [[{ move_type: 'out_invoice', partner_id: slowId, invoice_date: iso(-60), invoice_date_due: iso(-40),
      invoice_line_ids: [[0, 0, { name: 'E2E steel', quantity: 1, price_unit: 250000, tax_ids: [[6, 0, []]] }]] }]]);
    await admin.rpc('account.move', 'action_post', [[invId]]);
    const [{ name: invName }] = await admin.rpc('account.move', 'read', [[invId], ['name']]);
    await admin.rpc('res.partner', 'create', [[{ name: `Zed ${stamp} Twin Alpha` }, { name: `Zed ${stamp} Twin Beta` }]]);
    const counts = async () => ({ moves: await admin.rpc('account.move', 'search_count', [[]]), lines: await admin.rpc('ei.bank.import.line', 'search_count', [[]]),
      contracts: await admin.rpc('ei.contract', 'search_count', [[]]), inv: (await admin.rpc('account.move', 'read', [[invId], ['payment_state', 'write_date']]))[0] });

    const ceo = await new Session(ctx, browser, 'demo.ceo', 'demo').start();
    const p = ceo.page;
    const bots = () => p.locator('.ei-ask-bot');
    const ask = async (text) => {
      const n = await bots().count();
      await p.fill('#ei-ask-q', text); await p.keyboard.press('Enter');
      await p.waitForFunction((k) => document.querySelectorAll('.ei-ask-bot').length > k, n, { timeout: 15000 });
      await p.waitForTimeout(400);
      return bots().last();
    };

    // ---- 1 the button is in the top bar, on every screen
    let m = ceo.mark();
    await ceo.home();
    ctx.check(await p.locator('.o_navbar .ei-ask-btn').count() === 1, '1 the Ask button is in the top bar of Home');
    await p.locator('.o_navbar .ei-ask-btn').click();
    await p.waitForSelector('.ei-ask .ei-ask-welcome', { timeout: 15000 });
    ctx.check(/I cannot change anything and I do not guess/.test(await p.locator('.ei-ask').innerText()), '1 the screen says what it is and what it cannot do');
    ctx.check(await p.evaluate(() => document.activeElement && document.activeElement.id) === 'ei-ask-q', '1 the cursor is already in the question box');
    const chips = await p.locator('.ei-ask-welcome .ei-ask-chip').allInnerTexts();
    ctx.check(chips.includes('Who owes us money?') && chips.includes('What is waiting for me?'), '1 the CEO is offered money questions and the work question', chips.join(' | '));
    await ceo.clean('1 opening Ask is clean', m);
    await ctx.shot(p, 'ask_open');

    // ---- 2 an answer carries its sources and how it was worked out
    m = ceo.mark();
    await p.locator('.ei-ask-welcome .ei-ask-chip', { hasText: 'What is waiting for me?' }).click();
    await p.waitForSelector('.ei-ask-bot', { timeout: 15000 }); await p.waitForTimeout(500);
    let card = bots().last();
    ctx.check(/What is waiting for you/.test(await card.innerText()), '2 a chip asks the question and the answer appears');
    ctx.check(await card.locator('.ei-ask-source').count() >= 1, '2 the answer lists where it comes from');
    const how = card.locator('.ei-ask-how');
    ctx.check(!(await how.evaluate(el => el.open)), '2 "How this was worked out" starts closed');
    await how.locator('summary').click();
    ctx.check(/real records/.test(await how.innerText()) && /As of/.test(await card.innerText()), '2 it opens to a plain explanation, and the answer says when it was read');
    await ceo.clean('2 the first answer is clean', m);

    // ---- 3 money answers equal the books
    m = ceo.mark();
    card = await ask('Who owes us money?');
    const owedNow = await ledger();
    const figure = await card.locator('.ei-ask-figure', { hasText: 'Customers owe us' }).locator('.ei-ask-figure-value').innerText();
    ctx.check(Math.abs(parseFloat(digits(figure)) - owedNow) < 0.01, '3 "Customers owe us" equals the open receivable items in the books', `${figure} vs ${owedNow}`);
    ctx.check(owedNow - owedBefore === 250000, '3 the books moved by exactly the arranged invoice (250,000)', String(owedNow - owedBefore));
    const row = card.locator('tr', { hasText: slowName });
    ctx.check(await row.count() === 1 && /250,000/.test(await row.innerText()), '3 the late customer is in the table with its 250,000', await row.count() ? (await row.innerText()).replace(/\s+/g, ' ') : 'missing');
    await row.locator('.ei-ask-link').click();
    await p.waitForSelector('.o_list_view, .o_form_view', { timeout: 15000 });
    ctx.check(/Slow Payer/.test(await p.locator('.o_action_manager').innerText()) || await p.locator('.o_data_row').count() >= 1, '3 clicking the customer opens the open items behind the figure');
    await ceo.clean('3 money answer and its source are clean', m);

    // ---- 4 overdue: the invoice, how late, and the invoice itself opens
    m = ceo.mark();
    await ceo.home(); await p.locator('.o_navbar .ei-ask-btn').click(); await p.waitForSelector('.ei-ask .ei-ask-welcome');
    card = await ask('What is overdue?');
    const late = card.locator('tr', { hasText: invName });
    ctx.check(await late.count() === 1 && /\b40\b/.test(await late.innerText()), '4 the overdue invoice is listed, 40 days late', await late.count() ? (await late.innerText()).replace(/\s+/g, ' ') : 'missing');
    const lateLines = await admin.rpc('account.move.line', 'search_read', [[['parent_state', '=', 'posted'], ['reconciled', '=', false], ['account_type', '=', 'asset_receivable'], ['date_maturity', '<', iso(0)]], ['amount_residual']]);
    const lateBooks = lateLines.reduce((t, r) => t + r.amount_residual, 0);
    const lateShown = await card.locator('.ei-ask-figure', { hasText: 'Overdue in total' }).locator('.ei-ask-figure-value').innerText();
    ctx.check(Math.abs(parseFloat(digits(lateShown)) - lateBooks) < 0.01 && lateBooks >= 250000, '4 the overdue total equals the overdue items in the books', `${lateShown} vs ${lateBooks}`);
    await late.locator('.ei-ask-link').click();
    await p.waitForSelector('.o_form_view', { timeout: 15000 });
    ctx.check((await p.locator('.o_form_view').first().innerText()).includes(invName), '4 the invoice opens', invName);
    await ceo.clean('4 overdue answer and the invoice are clean', m);

    // ---- 5 choosing between parties, and not understanding
    m = ceo.mark();
    await ceo.home(); await p.locator('.o_navbar .ei-ask-btn').click(); await p.waitForSelector('.ei-ask .ei-ask-welcome');
    card = await ask(`Zed ${stamp} Twin`);
    ctx.check(/Which one do you mean/.test(await card.innerText()) && await card.locator('.ei-ask-option').count() === 2, '5 two parties fit, so it asks which one');
    await card.locator('.ei-ask-option', { hasText: 'Alpha' }).click();
    await p.waitForFunction(() => document.querySelectorAll('.ei-ask-bot').length > 1, null, { timeout: 15000 }); await p.waitForTimeout(400);
    ctx.check(new RegExp(`Zed ${stamp} Twin Alpha`).test(await bots().last().locator('.ei-ask-answer-title').innerText()), '5 picking one shows that party');
    card = await ask('Qqqq Zzzz');
    ctx.check(/did not understand/.test(await card.innerText()) && await card.locator('.ei-ask-suggest .ei-ask-chip').count() >= 3, '5 a question it cannot answer says so and offers questions that work');
    await card.locator('.ei-ask-suggest .ei-ask-chip').first().click();
    await p.waitForFunction(() => document.querySelectorAll('.ei-ask-bot').length > 3, null, { timeout: 15000 });
    ctx.check(await bots().count() === 4 && !/did not understand/.test(await bots().last().innerText()), '5 a suggested question gets a real answer');
    await ceo.clean('5 choosing and not understanding are clean', m);

    // ---- 6 it only reads: a request to change something is refused and nothing moves
    m = ceo.mark();
    const before = await counts();
    card = await ask('approve the invoice');
    ctx.check(/I can only look things up/.test(await card.innerText()) && /cannot approve, post, pay/.test(await card.innerText()), '6 a request to approve is refused in plain words');
    card = await ask('please post the bank statement and pay the bill');
    ctx.check(/I can only look things up/.test(await card.innerText()), '6 so is posting and paying');
    const after = await counts();
    ctx.check(JSON.stringify(before) === JSON.stringify(after), '6 no invoice, bank line or contract changed, and the invoice is still unpaid', JSON.stringify(after.inv));
    ctx.check(await ledger() === owedNow, '6 the books are exactly as they were');
    await ceo.clean('6 refusals are clean', m);
    await ctx.shot(p, 'ask_answers');

    // ---- 7 the questions are recorded for management
    const log = await ceo.rpc('ei.assistant.log', 'search_read', [[['question', 'in', ['approve the invoice', 'Qqqq Zzzz', 'Who owes us money?']]], ['question', 'outcome', 'user_id']], { order: 'id desc' });
    const outcomes = Object.fromEntries(log.map(r => [r.question, r.outcome]));
    ctx.check(outcomes['approve the invoice'] === 'refused' && outcomes['Qqqq Zzzz'] === 'unknown' && outcomes['Who owes us money?'] === 'answered', '7 management can read what was asked and whether it was answered', JSON.stringify(outcomes));

    // ---- 8 a role without finance never sees money
    const ops = await new Session(ctx, browser, 'demo.contracts', 'demo').start();
    const op = ops.page;
    m = ops.mark();
    await ops.home(); await op.locator('.o_navbar .ei-ask-btn').click(); await op.waitForSelector('.ei-ask .ei-ask-welcome', { timeout: 15000 });
    const opChips = await op.locator('.ei-ask-welcome .ei-ask-chip').allInnerTexts();
    ctx.check(!opChips.some(c => /owes us|overdue|we owe/i.test(c)) && opChips.includes('What is waiting for me?'), '8 a contracts clerk is not offered money questions', opChips.join(' | '));
    await op.fill('#ei-ask-q', 'Who owes us money?'); await op.keyboard.press('Enter');
    await op.waitForSelector('.ei-ask-bot', { timeout: 15000 }); await op.waitForTimeout(400);
    const denied = await op.locator('.ei-ask-bot').last().innerText();
    ctx.check(/Money in the books is shown to finance and management only/.test(denied) && !/250,000/.test(denied) && !new RegExp(slowName).test(denied), '8 asking for money is answered with why not, and shows no figure');
    await op.fill('#ei-ask-q', `Tell me about ${slowName}`); await op.keyboard.press('Enter');
    await op.waitForFunction(() => document.querySelectorAll('.ei-ask-bot').length > 1, null, { timeout: 15000 }); await op.waitForTimeout(400);
    const partyText = await op.locator('.ei-ask-bot').last().innerText();
    ctx.check(/Not shown to your role/.test(partyText) && !/250,000/.test(partyText), '8 a party page hides the ledger from this role and says so');
    let refused = false;
    try { await ops.rpc('ei.assistant.log', 'search_read', [[], ['question']]); } catch { refused = true; }
    ctx.check(refused, '8 and this role cannot read the log of questions');
    await ops.clean('8 the operator view is clean', m);
    await ops.close();

    // ---- 9 phone, tablet, desktop, dark: layout and accessibility
    const lay = async (s, label) => {
      const l = await s.layout();
      ctx.check(!l.overflow && !l.wide.length, `${label}: no horizontal overflow`, JSON.stringify(l.wide));
      ctx.check(!l.clipped.length, `${label}: no clipped buttons or badges`, l.clipped.join(' | '));
    };
    for (const [w, h] of [[390, 844], [768, 1024], [1440, 900]]) {
      await p.setViewportSize({ width: w, height: h });
      await ceo.goto('/odoo/action-ei_assistant.action_ei_assistant'); await p.waitForSelector('.ei-ask .ei-ask-welcome', { timeout: 15000 });
      await ask('What is overdue?'); await ask('Who owes us money?');
      await lay(ceo, `9 ${w}px`);
      if (w === 390) ctx.check(!(await p.locator('.o_navbar .ei-ask-btn-label').isVisible()), '9 on a phone the top-bar button shows only its icon');
      const v = await ceo.axe('.ei-ask');
      const bad = (v || []).filter(x => ['serious', 'critical'].includes(x.impact));
      ctx.check(v !== null && !bad.length, `9 ${w}px light: no serious accessibility findings (axe)`, bad.map(x => `${x.id}(${x.n}): ${x.first}`).join(' | '));
      if (w === 390 || w === 1440) await ctx.shot(p, `ask_${w}`);
    }
    await ceo.close();
    const dark = await new Session(ctx, browser, 'demo.ceo', 'demo', [1440, 900], { cookies: [{ name: 'color_scheme', value: 'dark', path: '/' }] }).start();
    await dark.goto('/odoo/action-ei_assistant.action_ei_assistant'); await dark.page.waitForSelector('.ei-ask .ei-ask-welcome', { timeout: 15000 });
    await dark.page.fill('#ei-ask-q', 'Who owes us money?'); await dark.page.keyboard.press('Enter');
    await dark.page.waitForSelector('.ei-ask-bot', { timeout: 15000 }); await dark.page.waitForTimeout(500);
    const dv = await dark.axe('.ei-ask');
    const dbad = (dv || []).filter(x => ['serious', 'critical'].includes(x.impact));
    ctx.check(dv !== null && !dbad.length, '9 dark mode 1440px: no serious accessibility findings (axe)', dbad.map(x => `${x.id}(${x.n}): ${x.first}`).join(' | '));
    await ctx.shot(dark.page, 'ask_dark');
    await dark.close();
    await admin.close();
  },
};
