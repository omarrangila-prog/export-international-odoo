// The report catalog and the first real reports. Every figure on a report is compared with the records read straight from the database
// (and with Home), drill-through opens the document behind a row, the export really downloads, and a role without money cannot open a money report.
const digits = (t) => parseFloat((String(t).match(/-?\d[\d,]*(?:\.\d+)?/) || ['0'])[0].replace(/,/g, ''));

module.exports = {
  name: '12 reports (catalog, receivables ageing, bank, contracts, lifting, export, access)',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const ceo = await new Session(ctx, browser, 'demo.ceo', 'demo').start();
    const p = ceo.page;
    let m = ceo.mark();

    // ---- 1 the catalog
    ctx.check(await p.locator('.o_menu_sections').getByText('Reports', { exact: true }).count() > 0 || await p.locator('.o_menu_sections_more').count() > 0, '1 Reports is a top-level entry of the top bar');
    await ceo.goto('/odoo/action-ei_reports.action_report_catalog'); await p.waitForSelector('.ei-rc-card', { timeout: 25000 });
    const cat = await ceo.rpc('ei.report.catalog', 'get_catalog', []);
    const open = cat.filter(c => c.can_open);
    ctx.check(await p.locator('.ei-rc-card').count() === open.length && open.length >= 6, '1 the catalog lists the reports this role can open', `${await p.locator('.ei-rc-card').count()} vs ${open.length}`);
    const chips = (await p.locator('.ei-rc-sum').innerText()).replace(/\s+/g, ' ');
    const n = (s) => cat.filter(c => c.status === s).length;
    ctx.check(chips.includes(`${n('delivered')} delivered`) && chips.includes(`${n('partial')} partly there`) && chips.includes(`${n('pending_source')} blocked`) && chips.includes(`${n('not_built')} not built yet`), '1 the summary counts delivered, partly there, blocked and not built exactly as the server says', chips);
    await p.locator('.ei-rc-search input').fill('bank'); await p.waitForTimeout(300);
    const hits = await p.locator('.ei-rc-card-title').allInnerTexts();
    ctx.check(hits.length >= 2 && hits.every(t => /bank/i.test(t) || cat.find(c => c.title === t && /bank/i.test(c.question + c.definition + c.source))), '1 the search finds reports by what they answer', hits.join(' | '));
    await p.locator('.ei-rc-search input').fill('');
    await p.locator('.ei-rc-check input').check(); await p.waitForTimeout(300);
    ctx.check(await p.locator('.ei-rc-card').count() === cat.length && await p.locator('.ei-rc-card.is-warn .ei-rc-note').count() >= 3, '1 "also show" reveals the reports that are not built or blocked, each with its reason');
    ctx.check(await p.locator('.ei-rc-card .ei-rc-open').count() === open.length && await p.locator('.ei-rc-unavail').count() === cat.length - open.length, '1 a report that is not available has no button that leads nowhere');
    await p.locator('.ei-rc-check input').uncheck();
    const star = p.locator('.ei-rc-card', { hasText: 'Aged receivables' }).locator('.ei-rc-star');
    await star.click(); await p.waitForTimeout(500);
    ctx.check(await star.getAttribute('aria-pressed') === 'true' && (await ceo.rpc('ei.report.catalog', 'get_catalog', [])).find(c => c.key === 'ar_aging').favourite, '1 a favourite is saved for the person');
    await p.reload(); await p.waitForSelector('.ei-rc-card'); await p.locator('.ei-rc-pill', { hasText: 'Favourites' }).click(); await p.waitForTimeout(300);
    ctx.check(await p.locator('.ei-rc-card').count() === 1 && /Aged receivables/.test(await p.locator('.ei-rc-card').innerText()), '1 and it is still there after reloading, under Favourites');
    await p.locator('.ei-rc-card .ei-rc-star').click(); await p.waitForTimeout(400);
    await ceo.clean('1 the catalog is clean', m);
    await ctx.shot(p, 'reports_catalog');

    // ---- 2 aged receivables: equals the books, equals Home, opens the invoice behind a row, exports
    m = ceo.mark();
    const rows = await ceo.rpc('ei.report.ar.aging', 'search_read', [[], ['amount_residual', 'bucket', 'move_id']]);
    const dbTotal = rows.reduce((t, r) => t + r.amount_residual, 0);
    const home = await ceo.rpc('ei.home', 'get_data', ['14d']);
    const homeOwed = home.charts.aging.rows.reduce((t, r) => t + r.value, 0);
    ctx.check(Math.abs(dbTotal - homeOwed) < 0.01 && dbTotal > 0, '2 the ageing report adds up to the Home figure "Customers owe us"', `${dbTotal} vs ${homeOwed}`);
    await ceo.goto('/odoo/action-ei_reports.action_report_ar_aging'); await p.waitForSelector('.o_graph_renderer canvas, .o_graph_view canvas', { timeout: 25000 });
    ctx.check(await p.locator('.o_cp_switch_buttons button').count() >= 3, '2 it opens as a chart with the table and the list one click away');
    await p.locator('.o_cp_switch_buttons button.o_list').click(); await p.waitForSelector('.o_data_row', { timeout: 15000 });
    ctx.check(await p.locator('.o_data_row').count() === Math.min(rows.length, 80), '2 the list has one row per open item', `${await p.locator('.o_data_row').count()} vs ${rows.length}`);
    const foot = (await p.locator('.o_list_footer td, tfoot td').allInnerTexts()).join(' ');
    ctx.check(Math.abs(digits(foot) - dbTotal) < 0.01 && rows.length <= 80, '2 the list total equals the books', `${foot.trim()} vs ${dbTotal}`);
    await p.locator('.o_cp_switch_buttons button.o_pivot').click(); await p.waitForSelector('.o_pivot', { timeout: 15000 }); await p.waitForTimeout(800);
    const cells = (await p.locator('.o_pivot_cell_value').allInnerTexts()).map(digits).filter(x => x > 0);
    ctx.check(cells.length > 0 && Math.abs(Math.max(...cells) - dbTotal) < 0.01, '2 the pivot grand total equals the books too', `${Math.max(...cells)} vs ${dbTotal}`);
    await p.locator('.o_cp_switch_buttons button.o_list').click(); await p.waitForSelector('.o_data_row');
    await p.locator('.o_data_row').first().click(); await p.waitForSelector('.o_form_view', { timeout: 15000 });
    ctx.check(/INV|BNK|\//.test(await p.locator('.o_last_breadcrumb_item').innerText()), '2 a row opens the invoice behind it', await p.locator('.o_last_breadcrumb_item').innerText());
    await p.goBack(); await p.waitForSelector('.o_data_row', { timeout: 15000 });
    await p.locator('thead .o_list_record_selector input').check();
    await p.locator('.o_cp_action_menus button, .o_cp_action_menus .dropdown-toggle').first().click();
    await p.getByText('Export', { exact: true }).first().click(); await p.waitForSelector('.o_export_data_dialog, .modal .o_export_tree', { timeout: 15000 });
    const [dl] = await Promise.all([p.waitForEvent('download', { timeout: 30000 }), p.locator('.modal footer button', { hasText: /^Export$/ }).first().click()]);
    const name = dl.suggestedFilename();
    const size = require('fs').statSync(await dl.path()).size;
    ctx.check(/\.xlsx$/.test(name) && size > 2000, '2 the export downloads a real spreadsheet', `${name} ${size} bytes`);
    await ceo.clean('2 the ageing report is clean', m);
    await ctx.shot(p, 'reports_ar_list');

    // ---- 3 bank book against bank confirmation and the bank lines not yet in the books
    m = ceo.mark();
    const fresh = await ceo.rpc('ei.report.bank.freshness', 'search_read', [[], ['journal_id', 'freshness', 'book_balance']]);
    const banks = home.banks;
    ctx.check(fresh.length === banks.length && fresh.filter(f => ['stale', 'never'].includes(f.freshness)).length === banks.filter(b => b.stale).length, '3 the bank report and Home agree on which banks are not confirmed today', `${fresh.map(f => f.freshness).join(',')}`);
    ctx.check(Math.abs(fresh.reduce((t, f) => t + f.book_balance, 0) - banks.reduce((t, b) => t + b.amount, 0)) < 0.01, '3 and on the book balance');
    await ceo.goto('/odoo/action-ei_reports.action_report_bank_freshness'); await p.waitForSelector('.o_data_row', { timeout: 25000 });
    const badges = (await p.locator('.o_data_row .o_field_badge').allInnerTexts()).join('|');
    ctx.check(/Not confirmed today|Never confirmed/.test(badges), '3 a stale confirmation is written in words, not a dot', badges);
    const unm = await ceo.rpc('ei.report.bank.unmatched', 'search_read', [[], ['amount', 'state', 'direction']]);
    const waiting = home.kpis.find(k => k.key === 'waiting');
    const rcpt = unm.filter(u => u.direction === 'receipt' && u.state !== 'duplicate').reduce((t, u) => t + u.amount, 0);
    ctx.check(!waiting || Math.abs(digits(waiting.value) - rcpt) < 0.01, '3 the unmatched-lines report agrees with Home "Bank money to match"', `${waiting && waiting.value} vs ${rcpt}`);
    await ceo.goto('/odoo/action-ei_reports.action_report_bank_unmatched'); await p.waitForSelector('.o_graph_renderer canvas, .o_graph_view canvas', { timeout: 25000 });
    await ceo.clean('3 the bank reports are clean', m);

    // ---- 4 contracts and lifting
    m = ceo.mark();
    const dash = await ceo.rpc('ei.dashboard', 'create', [{}]);
    const dv = (await ceo.rpc('ei.dashboard', 'read', [[dash], ['gross_spread', 'mtl_lifted', 'mtl_ordered']]))[0];
    const spread = await ceo.rpc('ei.report.contract.spread', 'search_read', [[['state', 'in', ['active', 'fulfilled']]], ['gross_spread', 'lifted_mtl', 'ordered_mtl']]);
    ctx.check(Math.abs(spread.reduce((t, r) => t + r.gross_spread, 0) - dv.gross_spread) < 0.01 && Math.abs(spread.reduce((t, r) => t + r.lifted_mtl, 0) - dv.mtl_lifted) < 0.001, '4 contract spread and lifted material equal the dashboard figures', `${dv.gross_spread} / ${dv.mtl_lifted}`);
    await ceo.goto('/odoo/action-ei_reports.action_report_contract_spread'); await p.waitForSelector('.o_graph_renderer canvas, .o_graph_view canvas', { timeout: 25000 });
    await p.locator('.o_cp_switch_buttons button.o_list').click(); await p.waitForSelector('.o_data_row');
    ctx.check(/provisional/i.test(await p.locator('thead').innerText()) || /provisional/i.test(await p.locator('.o_list_view').innerText()), '4 the gross spread is labelled provisional on the report itself');
    const lift = await ceo.rpc('ei.report.lifting', 'search_read', [[], ['lifted_mtl', 'state']]);
    const verified = await ceo.rpc('ei.lifting', 'search_read', [[['state', '=', 'verified']], ['verified_mtl']]);
    ctx.check(Math.abs(lift.reduce((t, r) => t + r.lifted_mtl, 0) - verified.reduce((t, r) => t + r.verified_mtl, 0)) < 0.001, '4 the lifting report counts verified loadings only');
    await ceo.goto('/odoo/action-ei_reports.action_report_lifting'); await p.waitForSelector('.o_graph_renderer canvas, .o_graph_view canvas', { timeout: 25000 });
    await ceo.clean('4 the contract and lifting reports are clean', m);

    // ---- 5 a role without money
    const ops = await new Session(ctx, browser, 'demo.dispatch', 'demo').start();
    const op = ops.page; m = ops.mark();
    const opCat = await ops.rpc('ei.report.catalog', 'get_catalog', []);
    ctx.check(opCat.find(c => c.key === 'lifting').can_open && !opCat.find(c => c.key === 'ar_aging').can_open && !opCat.find(c => c.key === 'contract_spread').can_open, '5 logistics can open the lifting report and no money report');
    let blocked = false;
    try { await ops.rpc('ei.report.ar.aging', 'search_read', [[], ['amount_residual']]); } catch (e) { blocked = /access|allowed/i.test(String(e.message)); }
    ctx.check(blocked, '5 and the server refuses the receivables report to them, not just the menu');
    await ops.goto('/odoo/action-ei_reports.action_report_catalog'); await op.waitForSelector('.ei-rc-card');
    const opTitles = await op.locator('.ei-rc-card-title').allInnerTexts();
    ctx.check(opTitles.includes('Material lifting') && !opTitles.includes('Aged receivables'), '5 their catalog shows only what they may open', opTitles.join(' | '));
    await ops.clean('5 the operator catalog is clean', m);
    await ops.close();

    // ---- 6 layout: phone, dark, axe
    for (const [w, h] of [[390, 844], [1024, 768], [1440, 900]]) {
      await p.setViewportSize({ width: w, height: h });
      await ceo.goto('/odoo/action-ei_reports.action_report_catalog'); await p.waitForSelector('.ei-rc-card');
      const l = await ceo.layout();
      ctx.check(!l.overflow && !l.wide.length && !l.clipped.length, `6 ${w}px catalog: no horizontal overflow or clipped buttons`, JSON.stringify(l.wide.concat(l.clipped)));
    }
    const wheel = await ceo.wheelScroll('.ei-rc');
    ctx.check(wheel.max === 0 || (wheel.top >= wheel.max - 2 && wheel.win === 0), '6 the catalog scrolls with the mouse wheel', JSON.stringify(wheel));
    await p.setViewportSize({ width: 1440, height: 900 });
    await ceo.goto('/odoo/action-ei_reports.action_report_catalog'); await p.waitForSelector('.ei-rc-card');
    const v = await ceo.axe('.ei-rc');
    const bad = (v || []).filter(x => ['serious', 'critical'].includes(x.impact));
    ctx.check(v !== null && !bad.length, '6 catalog: no serious accessibility findings (axe)', bad.map(x => `${x.id}(${x.n}): ${x.first}`).join(' | '));
    await ceo.close();
    const dark = await new Session(ctx, browser, 'demo.ceo', 'demo', [1440, 900], { cookies: [{ name: 'color_scheme', value: 'dark', path: '/' }] }).start();
    await dark.goto('/odoo/action-ei_reports.action_report_catalog'); await dark.page.waitForSelector('.ei-rc-card');
    const dv2 = await dark.axe('.ei-rc');
    const dbad = (dv2 || []).filter(x => ['serious', 'critical'].includes(x.impact));
    ctx.check(dv2 !== null && !dbad.length, '6 catalog (dark): no serious accessibility findings (axe)', dbad.map(x => `${x.id}(${x.n}): ${x.first}`).join(' | '));
    await ctx.shot(dark.page, 'reports_catalog_dark');
    await dark.close();
  },
};
