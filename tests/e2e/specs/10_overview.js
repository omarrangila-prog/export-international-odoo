// The Overview on Home: a real title, this period against the one before, the contract-to-payment pipeline, what customers owe, who owes
// most, recent invoices and the question box. Every number is checked against the records behind it, read straight from the database,
// and a role that may not see money must not be shown any.
const digits = (t) => parseFloat((String(t).match(/-?\d[\d,]*(?:\.\d+)?/) || ['0'])[0].replace(/,/g, ''));
const addDays = (iso, n) => new Date(Date.parse(iso + 'T00:00:00Z') + n * 86400000).toISOString().slice(0, 10);

module.exports = {
  name: '10 overview (period comparison, flows, pipeline, who owes most, question box)',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const admin = await new Session(ctx, browser, 'admin', 'admin').start();
    const ceo = await new Session(ctx, browser, 'demo.ceo', 'demo').start();
    const p = ceo.page;
    const card = (title) => p.locator('.ei-flow', { has: p.locator('.ei-hcard-title', { hasText: new RegExp(`^${title}$`) }) });
    const sumInvoiced = async (from, to) => (await admin.rpc('account.move', 'search_read', [[['move_type', '=', 'out_invoice'], ['state', '=', 'posted'], ['invoice_date', '>=', from], ['invoice_date', '<=', to]], ['amount_total_signed']])).reduce((t, r) => t + r.amount_total_signed, 0);
    const sumReceived = async (from, to) => (await admin.rpc('ei.bank.import.line', 'search_read', [[['state', '=', 'posted'], ['amount', '>', 0], ['date', '>=', from], ['date', '<=', to]], ['amount']])).reduce((t, r) => t + r.amount, 0);
    const deltaText = (cur, prev) => prev > 0 ? (Math.round((cur - prev) / prev * 100) > 0 ? '+' : '') + Math.round((cur - prev) / prev * 100) + '%' : (cur > 0 ? 'New' : 'No activity');

    // ---- 1 the header and the period choice
    let m = ceo.mark();
    await ceo.home();
    ctx.check(/^Overview$/.test(await p.locator('h1.ei-top-title').innerText()), '1 the page has a real title: Overview');
    const opts = await p.locator('.ei-period select option').allInnerTexts();
    ctx.check(opts.join('|') === 'Last 7 days|Last 14 days|Last 30 days|This month', '1 four periods are offered', opts.join('|'));
    ctx.check(await p.locator('.ei-period select').inputValue() === '14d' && /compared to/.test(await p.locator('.ei-period').innerText()), '1 it starts on the last 14 days and says what it is compared to');
    await ceo.clean('1 the Overview opens clean', m);
    await ctx.shot(p, 'overview_ceo');

    // ---- 2 the flow cards equal the records, and the change is worked out against the days just before
    const flows = await ceo.rpc('ei.home', 'get_data', ['14d']).then(d => d.flows);
    const inv = flows.find(f => f.key === 'invoiced');
    const first = inv.series[0].iso, last = inv.series[inv.series.length - 1].iso;
    const cur = await sumInvoiced(first, last), prev = await sumInvoiced(addDays(first, -14), addDays(first, -1));
    const shown = await card('Invoiced').locator('.ei-bignum').innerText();
    ctx.check(Math.abs(digits(shown) - cur) < 0.01 && cur > 0, '2 "Invoiced" equals the posted customer invoices of the period', `${shown} vs ${cur}`);
    const chip = (await card('Invoiced').locator('.ei-dchip').innerText()).replace(/\s+/g, ' ');
    ctx.check(chip.includes(deltaText(cur, prev)), '2 its change is worked out against the 14 days before', `${chip} vs ${deltaText(cur, prev)} (before ${prev})`);
    ctx.check(/Before:/.test(await card('Invoiced').innerText()) && digits(await card('Invoiced').locator('.ei-hcard-sub').innerText()) === prev, '2 and the card says what the earlier figure was', String(prev));
    const rec = await sumReceived(first, last);
    ctx.check(Math.abs(digits(await card('Received in the bank').locator('.ei-bignum').innerText()) - rec) < 0.01, '2 "Received in the bank" equals the posted bank receipts of the period');
    ctx.check(await card('Material lifted').count() === 1, '2 the lifted material card is there for this role');

    // ---- 3 changing the period changes the cards, from the server
    await p.locator('.ei-period select').selectOption('30d'); await p.waitForTimeout(1800);
    const f30 = (await ceo.rpc('ei.home', 'get_data', ['30d'])).flows.find(f => f.key === 'invoiced');
    const cur30 = await sumInvoiced(f30.series[0].iso, f30.series[f30.series.length - 1].iso);
    ctx.check(f30.series.length === 30 && Math.abs(digits(await card('Invoiced').locator('.ei-bignum').innerText()) - cur30) < 0.01, '3 "Last 30 days" re-reads the cards: 30 days, and the figure equals the records', String(cur30));
    ctx.check(/compared to/.test(await p.locator('.ei-h2-note').first().innerText()), '3 the section says which days it shows and which days it is compared to');
    await p.locator('.ei-period select').selectOption('7d'); await p.waitForTimeout(1500);
    ctx.check((await card('Invoiced').locator('.ei-fx span').first().innerText()).length > 0 && await card('Invoiced').count() === 1, '3 "Last 7 days" works too');
    await p.locator('.ei-period select').selectOption('14d'); await p.waitForTimeout(1500);

    // ---- 4 charts: hover, table alternative, open the records
    const chart = card('Invoiced').locator('.ei-fchart');
    await chart.scrollIntoViewIfNeeded(); await p.waitForTimeout(300);
    const box = await chart.boundingBox();
    await p.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5); await p.waitForTimeout(400);
    ctx.check(await card('Invoiced').locator('.ei-ftip').count() === 1 && /\d/.test(await card('Invoiced').locator('.ei-ftip').innerText()), '4 hovering a chart shows that day and its figure');
    await card('Invoiced').getByRole('button', { name: 'Show as table' }).click(); await p.waitForTimeout(400);
    const rows = card('Invoiced').locator('tbody tr');
    let total = 0; for (let i = 0; i < await rows.count(); i++) total += digits(await rows.nth(i).locator('td').innerText());
    ctx.check(await rows.count() === 14 && Math.abs(total - cur) < 0.01, '4 the table has one row per day and adds up to the card', `${await rows.count()} rows, ${total}`);
    await card('Invoiced').getByRole('button', { name: 'Show chart' }).click();
    m = ceo.mark();
    await card('Invoiced').locator('.ei-flow-open').click(); await p.waitForSelector('.o_list_view, .o_kanban_view', { timeout: 15000 });
    await p.waitForSelector('.o_data_row', { timeout: 15000 }).catch(() => {});
    ctx.check(await p.locator('.o_data_row').count() >= 1, '4 the arrow opens the invoices that were added up');
    await ceo.clean('4 the flow card and its records are clean', m);

    // ---- 5 what customers owe, and who owes most
    await ceo.home();
    const owedBooks = (await admin.rpc('account.move.line', 'search_read', [[['parent_state', '=', 'posted'], ['reconciled', '=', false], ['account_type', '=', 'asset_receivable']], ['amount_residual', 'partner_id']]));
    const owedTotal = owedBooks.reduce((t, r) => t + r.amount_residual, 0);
    // the receivable appears twice for the executive (summary tile + ageing card): both must equal the books
    const owedCard = p.locator('.ei-hero-money:has(.ei-agerows)').first();
    const owedOnCard = (await owedCard.locator('.ei-bignum, .ei-agesum b').first().innerText());
    ctx.check(Math.abs(digits(owedOnCard) - owedTotal) < 0.01, '5 "Customers owe us" equals the open receivable items in the books', String(owedTotal));
    const sumTile = p.locator('.ei-sum:has(.ei-sum-label:text-is("Customers owe us")) .ei-sum-value');
    ctx.check(await sumTile.count() === 0 || Math.abs(digits(await sumTile.innerText()) - owedTotal) < 0.01, '5 and the summary tile at the top says the same amount', await sumTile.count() ? await sumTile.innerText() : 'no summary for this role');
    const ageRows = await p.locator('.ei-agerows li').count();
    const pcts = (await p.locator('.ei-agepct').allInnerTexts()).map(t => parseInt(t, 10));
    ctx.check(ageRows === 5 && Math.abs(pcts.reduce((a, b) => a + b, 0) - 100) <= 3, '5 five ageing rows whose shares add up to the whole', pcts.join('+'));
    await p.locator('.ei-hero-money').getByRole('button', { name: 'Show as table' }).click(); await p.waitForTimeout(300);
    ctx.check(await p.locator('.ei-hero-money table').count() === 1, '5 the ageing can be read as a table');
    await p.locator('.ei-hero-money').getByRole('button', { name: 'Show chart' }).click();
    const byPartner = {}; for (const r of owedBooks) if (r.partner_id) byPartner[r.partner_id[1]] = (byPartner[r.partner_id[1]] || 0) + r.amount_residual;
    const top = Object.entries(byPartner).sort((a, b) => b[1] - a[1])[0];
    const topRow = p.locator('.ei-owelist .ei-owe').first();
    ctx.check((await topRow.locator('.ei-owe-name').innerText()) === top[0] && Math.abs(digits(await topRow.locator('.ei-owe-val').innerText()) - top[1]) < 0.01, '5 the biggest debtor on screen is the biggest in the books', `${top[0]} ${top[1]}`);
    m = ceo.mark();
    await topRow.click(); await p.waitForSelector('.ei-p360', { timeout: 15000 });
    ctx.check(await p.locator('.ei-p360-name').innerText().then(t => t.includes(top[0].replace(/^DEMO Customer - /, '')) || t === top[0]), '5 clicking a debtor opens that party');
    await ceo.clean('5 who owes most opens the party cleanly', m);

    // ---- 6 the pipeline and the latest invoices
    await ceo.home();
    const stages = (await ceo.rpc('ei.home', 'get_data', ['14d'])).pipeline;
    ctx.check(await p.locator('.ei-pcol').count() === stages.length, '6 one column per step of the pipeline', `${await p.locator('.ei-pcol').count()} vs ${stages.length}`);
    const counts = await p.locator('.ei-stage-count').allInnerTexts();
    ctx.check(counts.join(',') === stages.map(s => String(s.count)).join(','), '6 each column shows the real count', counts.join(','));
    const recent = await admin.rpc('account.move', 'search_read', [[['move_type', '=', 'out_invoice'], ['state', '=', 'posted']], ['name']], { order: 'invoice_date desc, id desc', limit: 6 });
    const names = await p.locator('.ei-rtable tbody th').allInnerTexts();
    ctx.check(names.map(n => n.trim()).join(',') === recent.map(r => r.name).join(','), '6 the recent invoices are the six latest posted', names.join(','));
    const labels = await p.locator('.ei-rtable .ei-statechip').allInnerTexts();
    ctx.check(labels.length === 6 && labels.every(l => /Paid|Not Paid|Overdue|Partially|In Payment/i.test(l)), '6 each has a status in words, not only a colour', labels.join(','));
    m = ceo.mark();
    await p.locator('.ei-rtable tbody th button').first().click(); await p.waitForSelector('.o_form_view', { timeout: 15000 });
    ctx.check((await p.locator('.o_form_view').first().innerText()).includes(recent[0].name), '6 an invoice number opens that invoice');
    await ceo.clean('6 the recent invoice opens cleanly', m);

    // ---- 7 the question box on Home
    await ceo.home();
    m = ceo.mark();
    await p.fill('#ei-ask-home', 'Who owes us money?'); await p.keyboard.press('Enter');
    await p.waitForSelector('.ei-ask .ei-ask-bot', { timeout: 20000 });
    ctx.check(/Customers owe us/.test(await p.locator('.ei-ask-bot').last().innerText()) && await p.locator('.ei-ask-me').count() === 1, '7 a question typed on Home lands on Ask and is answered at once');
    await ceo.home();
    await p.locator('.ei-askbar-chips button').first().click(); await p.waitForSelector('.ei-ask .ei-ask-bot', { timeout: 20000 });
    ctx.check(await p.locator('.ei-ask-bot').count() === 1, '7 a suggested question on Home does the same');
    await ceo.clean('7 the question box is clean', m);

    // ---- 8 a role without finance never sees money on the Overview
    const ops = await new Session(ctx, browser, 'demo.contracts', 'demo').start();
    const op = ops.page;
    m = ops.mark();
    await ops.home();
    const text = (await op.locator('.ei-home').innerText()).replace(/\s+/g, ' ');
    ctx.check(await op.locator('.ei-flow:has(.ei-hcard-title:text-is("Invoiced"))').count() === 0 && await op.locator('.ei-hero-money:has(.ei-hcard-title:text-is("Customers owe us"))').count() === 0, '8 an operator has no invoiced card and no "Customers owe us" card');
    ctx.check(await op.locator('.ei-flow:has(.ei-hcard-title:text-is("Material lifted"))').count() === 1, '8 but does have the material lifted card');
    ctx.check(!/Rs\.\s?[\d,]{7,}/.test(text), '8 and no large money figure appears anywhere on the page');
    const opAsk = await op.locator('.ei-askbar-chips button').allInnerTexts();
    ctx.check(!opAsk.some(c => /owes us|overdue|we owe/i.test(c)) && opAsk.length >= 1, '8 the question box offers this role only questions it can have answered', opAsk.join(' | '));
    await ops.clean('8 the operator Overview is clean', m);
    await ctx.shot(op, 'overview_operator');
    await ops.close();

    // ---- 8b a person can reach everything: the mouse wheel moves the page and its scrollbar is not hidden
    await p.setViewportSize({ width: 1440, height: 900 });
    await ceo.home();
    const wheel = await ceo.wheelScroll('.ei-home');
    ctx.check(wheel.max > 900 && wheel.top > 0 && wheel.top >= wheel.max - 2, '10 the mouse wheel alone takes a person to the very end of the Home', JSON.stringify(wheel));
    ctx.check(wheel.overflowY === 'auto' && wheel.scrollbarWidth !== 'none' && wheel.win === 0, '10 the Home scrolls inside itself (one scrollbar, not hidden)', JSON.stringify(wheel));
    const endSeen = await p.evaluate(() => { const secs = [...document.querySelectorAll('.ei-home section.ei-section')]; const r = secs[secs.length - 1].getBoundingClientRect(); return { bottom: Math.round(r.bottom), vh: innerHeight }; });
    ctx.check(endSeen.bottom <= endSeen.vh + 2, '10 and the last section is then fully on screen', JSON.stringify(endSeen));

    // ---- 8c the picture: a light floating top bar with the open screen as a filled pill, the question box inside the pipeline card
    await ceo.home();
    const bar = await p.evaluate(() => {
      const nav = document.querySelector('.o_main_navbar'); const cs = getComputedStyle(nav); const r = nav.getBoundingClientRect();
      const um = document.querySelector('.o_main_navbar .o_user_menu'); const ur = um ? um.getBoundingClientRect() : null;
      const cur = document.querySelector('.o_main_navbar [aria-current]'); const cc = cur && getComputedStyle(cur);
      return { bg: cs.backgroundColor, radius: parseFloat(cs.borderTopLeftRadius), top: Math.round(r.top), left: Math.round(r.left), right: Math.round(r.right), vw: innerWidth,
               userRight: ur ? Math.round(ur.right) : null, cur: cur ? cur.textContent.trim() : null, curBg: cc ? cc.backgroundColor : null };
    });
    ctx.check(bar.bg === 'rgb(255, 255, 255)' && bar.radius >= 16 && bar.top >= 8 && bar.left >= 8 && bar.right <= bar.vw - 8, '11 the top bar is light, rounded and floats clear of the window edges', JSON.stringify(bar));
    ctx.check(bar.userRight !== null && bar.userRight <= bar.right, '11 nothing in the top bar spills out of it', JSON.stringify(bar));
    ctx.check(bar.cur === 'Home' && bar.curBg !== 'rgba(0, 0, 0, 0)', '11 the entry you are in (Home) is the filled pill', JSON.stringify(bar));
    await ceo.menu('Customers & Suppliers'); await p.waitForSelector('.ei-p360');
    ctx.check(await p.locator('.o_main_navbar [aria-current]').innerText().then(t => t.trim() === 'Customers & Suppliers'), '11 and the pill moves with you to Customers & Suppliers');
    await ceo.home();
    ctx.check(await p.locator('.ei-hero-pipe .ei-askbar').count() === 1 && await p.locator('.ei-hero > .ei-askbar').count() === 0, '11 the question box sits inside the pipeline card, as in the design');
    ctx.check(await p.locator('.ei-title-row .ei-title-btn[aria-label="Refresh this page"]').count() === 1, '11 the title has its refresh button beside it');
    const pills = await p.locator('.ei-datepill').allInnerTexts();
    const info = await ceo.rpc('ei.home', 'get_data', ['14d']).then(d => d.period);
    ctx.check(pills.length === 2 && pills[0].replace(/\s+/g, ' ').includes(info.range) && pills[1].replace(/\s+/g, ' ').includes(info.compare), '11 the period and the period it is compared to are two date pills', pills.join(' / '));
    // the steps count different kinds of record, so they are cards, never a line or one shared axis
    ctx.check(await p.locator('.ei-stages').count() === 1 && await p.locator('.ei-hero-pipe path[stroke-dasharray], .ei-hero-pipe svg[preserveAspectRatio]').count() === 0 && await p.locator('.ei-pplot, .ei-pplot-axis').count() === 0, '11 the pipeline is a row of step cards: no connecting line, no shared axis');
    const labelled = await p.locator('.ei-stage').evaluateAll(els => els.map(e => e.getAttribute('aria-label')));
    ctx.check(labelled.length === stages.length && labelled.every((t, i) => t.includes(stages[i].definition)), '11 every step says in words what it counts (read by screen readers too)', labelled[0]);
    await p.locator('.ei-stage').nth(3).hover(); await p.waitForTimeout(250);
    ctx.check((await p.locator('.ei-stage-def').innerText()).includes(stages[3].definition), '11 pointing at a step shows exactly what it counts', await p.locator('.ei-stage-def').innerText());
    const splits = await p.locator('.ei-stage').evaluateAll(els => els.map(e => ({ wait: !!e.querySelector('.is-wait'), done: e.querySelector('.is-done') && e.querySelector('.is-done').style.flexGrow })));
    ctx.check(splits.every((x, i) => x.wait === (stages[i].waiting > 0) && Math.abs(parseFloat(x.done) - Math.round(stages[i].count / (stages[i].count + stages[i].waiting || 1) * 100)) < 1 || (!stages[i].count && !stages[i].waiting)), '11 each step has its own done-versus-waiting bar from its own two numbers', JSON.stringify(splits));
    // the review round: one place per figure, exceptions you can act on, book versus bank, additive material, a digest, a New menu
    const tiles = (await p.locator('.ei-kpi .ei-kpi-label').allInnerTexts()).map(t => t.trim());
    ctx.check(!tiles.includes('Customers owe us') && !tiles.includes('Bank balances') && tiles.includes('Cash in hand'), '12 a figure has one place: what customers owe and the bank balances are not repeated as tiles', tiles.join(' | '));
    const home = await ceo.rpc('ei.home', 'get_data', ['14d']);
    const cashK = home.kpis.find(k => k.key === 'cash');
    ctx.check(cashK && (cashK.tone === 'danger') === (await p.locator('.ei-kpi.ei-tone-danger', { hasText: 'Cash in hand' }).count() === 1), '12 a negative cash balance is drawn as an exception, a positive one is not', cashK && cashK.value + ' ' + cashK.tone);
    ctx.check(/Book balance/.test(await p.locator('.ei-banks').innerText()), '12 bank balances are labelled as BOOK balances');
    const staleN = home.banks.filter(b => b.stale).length;
    ctx.check(await p.locator('.ei-bank-act').count() === staleN && (staleN === 0 || /not confirmed|Never confirmed/i.test(await p.locator('.ei-banklist').innerText())), '12 a bank without today\'s confirmation says so and offers "Confirm the balance"', `${staleN} stale`);
    ctx.check(await p.locator('.ei-alert').count() > 0 && await p.locator('.ei-alert').evaluateAll(els => els.every(e => e.querySelector('.ei-alert-cta'))), '12 every exception names its next step ("Review the mismatch", "Confirm the balances")');
    const ranks = (await p.locator('.ei-owelist .ei-rank').allInnerTexts()).join(',');
    ctx.check(ranks === home.top_owing.rows.map(r => r.rank).join(',') && /overdue, oldest|Nothing overdue/.test(await p.locator('.ei-owelist').innerText()), '12 who owes most is ranked and splits overdue from outstanding', ranks);
    const agedBtn = await p.locator('.ei-agerows li button').count();
    ctx.check(agedBtn === home.charts.aging.rows.length && await p.locator('.ei-agerows li.is-zero').count() === home.charts.aging.rows.filter(r => !r.value).length, '12 each ageing band is clickable, and a band with nothing in it is a slim row', `${agedBtn} bands`);
    await p.locator('.ei-agerows li button').nth(1).click(); await p.waitForSelector('.o_cp_searchview .o_searchview_facet', { timeout: 15000 });
    ctx.check(/1-30 days late/.test(await p.locator('.o_searchview_facet').first().innerText()), '12 a band opens the receivables report already filtered to that band', await p.locator('.o_searchview_facet').first().innerText());
    await ceo.home();
    const m5 = home.charts.material;
    const legend = (await p.locator('.ei-meter-legend').first().innerText()).replace(/\s+/g, ' ');
    const nums = [...legend.matchAll(/(\d[\d,]*(?:\.\d+)?) MTL/g)].map(x => parseFloat(x[1].replace(/,/g, '')));
    ctx.check(m5 && nums.length >= 3 && Math.abs(nums[0] + nums[1] + nums[2] - m5.ordered) < 0.01 && /promised, not yet lifted/.test(legend), '12 lifted + promised-not-lifted + not-promised add up to what contracts ordered', `${nums.slice(0, 3).join(' + ')} vs ${m5 && m5.ordered}`);
    const grp = {}; home.activity.forEach(a => { const k = a.when.slice(0, 6) + '|' + a.who + '|' + a.text; grp[k] = (grp[k] || 0) + 1; });
    const folded = Object.values(grp).filter(n => n >= 3).length;
    ctx.check(await p.locator('.ei-feed-group').count() === folded, '12 repeated events by one person on one day fold into one digest line', `${folded} groups`);
    if (folded) { await p.locator('.ei-feed-group').first().click(); await p.waitForTimeout(250); ctx.check(await p.locator('.ei-feed-sub li').count() >= 3, '12 and the line opens to show every record'); }
    const quickN = home.quick.reduce((t, g) => t + g.items.length, 0);
    await p.locator('.ei-newbtn').click(); await p.waitForTimeout(250);
    ctx.check(await p.locator('.ei-newitem').count() === quickN && quickN > 0, '12 the New menu lists every starting point this role may use', `${await p.locator('.ei-newitem').count()} vs ${quickN}`);
    await p.keyboard.press('Escape'); await p.waitForTimeout(200);
    ctx.check(await p.locator('.ei-newmenu').count() === 0, '12 Escape closes it');
    const chips = await p.locator('.ei-chips .ei-chip').allInnerTexts();
    ctx.check(['Needs my action', 'Team queue', 'Assigned to me'].every(t => chips.some(c => c.startsWith(t))), '12 My Work says who owns what: needs my action, team queue, assigned to me', chips.join(' | '));
    const meter = await p.locator('.ei-agemeter').getAttribute('aria-label');
    ctx.check(/Share of what customers owe/.test(meter || '') && await p.locator('.ei-agemeter span').count() >= 1, '11 "Customers owe us" has a one-bar picture of how late, with the same in words', meter);
    ctx.check(!(await p.locator('.ei-feed-item:has-text("Journal Item")').count()), '11 the recent-activity list shows no journal-line noise');

    // ---- 9 phone, tablet, desktop, dark
    const lay = async (s, label) => {
      const l = await s.layout();
      ctx.check(!l.overflow && !l.wide.length, `${label}: no horizontal overflow`, JSON.stringify(l.wide));
      ctx.check(!l.clipped.length, `${label}: no clipped buttons or badges`, l.clipped.join(' | '));
    };
    for (const [w, h] of [[390, 844], [768, 1024], [1440, 900]]) {
      await p.setViewportSize({ width: w, height: h });
      await ceo.home();
      await lay(ceo, `9 ${w}px`);
      if (w === 390) await ctx.shot(p, 'overview_phone');
      if (w === 1440) await ctx.shot(p, 'overview_desktop');
    }
    await ceo.close();
    const dark = await new Session(ctx, browser, 'demo.ceo', 'demo', [1440, 900], { cookies: [{ name: 'color_scheme', value: 'dark', path: '/' }] }).start();
    await dark.home();
    await ctx.shot(dark.page, 'overview_dark');
    const dv = await dark.axe('.ei-home');
    const bad = (dv || []).filter(x => ['serious', 'critical'].includes(x.impact));
    ctx.check(dv !== null && !bad.length, '9 dark mode: no serious accessibility findings (axe)', bad.map(x => `${x.id}(${x.n}): ${x.first}`).join(' | '));
    await dark.close();
    await admin.close();
  },
};
