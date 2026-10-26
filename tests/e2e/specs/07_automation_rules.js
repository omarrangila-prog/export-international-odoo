// Automation rules: a manager previews, switches on and runs a rule; the colleague finds the reminder on their own Home.
// Nothing is created by a preview; running twice does not duplicate; people without the management role cannot see or change rules.
module.exports = {
  name: '07 automation rules (Rules & Controls)',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const ceo = await new Session(ctx, browser, 'demo.ceo', 'demo').start();
    const p = ceo.page, m = ceo.mark();
    await ceo.menu('Setup', 'Automation rules');
    await p.waitForSelector('.o_list_view');
    const text = await p.locator('.o_list_view').innerText();
    ctx.check(await p.locator('.o_data_row').count() === 4, 'the Rules & Controls list shows the four automations');
    ctx.check(/Supplier invoice missing/.test(text) && /Customer invoice overdue/.test(text) && /Problems that need a manager/.test(text) && /not lifted/.test(text), 'each automation is named in plain words');
    const on = await ceo.rpc('ei.rule', 'search_count', [[['enabled', '=', true]]]);
    ctx.check(on === 0, 'every automation ships switched off', String(on));
    await ceo.clean('opening the list is clean', m);

    // open the supplier-invoice rule, explain, set days to 0 and switch it on
    await p.locator('.o_data_row', { hasText: 'Supplier invoice missing' }).first().click(); await p.waitForSelector('.o_form_view');
    const info = await p.locator('.o_form_view').innerText();
    ctx.check(/switched off/i.test(info) && /What it never does/i.test(info) && /only leaves an internal reminder/.test(info), 'the form says it is off and what it will never do');
    ctx.check(await p.locator('button', { hasText: 'Run now' }).count() === 0, 'Run now is not offered while the rule is off');
    const m2 = ceo.mark();
    await p.locator('.o_field_widget[name=days] input').fill('0');
    await p.locator('.o_field_widget[name=enabled] input').check();
    await p.locator('.o_form_button_save').click(); await p.waitForTimeout(1200);

    // PREVIEW creates nothing
    const beforeActs = await ceo.rpc('mail.activity', 'search_count', [[['summary', '=like', 'Auto reminder%']]]);
    await p.locator('button', { hasText: 'Show what it finds now' }).click(); await p.waitForSelector('.o_form_view .alert-info', { timeout: 8000 });
    ctx.check(/Nothing was created/.test(await p.locator('.o_form_view').innerText()), 'the preview says nothing was created');
    ctx.check(await p.locator('.o_data_row').count() >= 1, 'the preview lists the real records it would remind about');
    ctx.check(await ceo.rpc('mail.activity', 'search_count', [[['summary', '=like', 'Auto reminder%']]]) === beforeActs, 'a preview created no reminder');
    await ctx.shot(p, 'automation_preview');

    // RUN creates exactly the reminders previewed, for the colleague who prepared the order
    await p.goBack(); await p.waitForSelector('.o_form_view');
    await p.locator('button', { hasText: 'Run now' }).click(); await p.waitForTimeout(600);
    await p.locator('.modal button.btn-primary').click(); await p.waitForSelector('.o_form_view', { timeout: 10000 }); await p.waitForTimeout(800);
    const runText = await p.locator('.o_form_view').innerText();
    ctx.check(/Run by a manager/.test(runText), 'a live run is recorded as run by a manager');
    const made = await ceo.rpc('mail.activity', 'search_read', [[['summary', '=like', 'Auto reminder%']], ['summary', 'user_id', 'res_model']]);
    ctx.check(made.length === 1 && /Supplier invoice still missing/.test(made[0].summary), 'exactly one reminder was created', JSON.stringify(made.map(x => x.summary)));
    await ceo.clean('preview and run on the screen are clean', m2);

    // running again does NOT duplicate
    await p.goBack(); await p.waitForSelector('.o_form_view');
    await p.locator('button', { hasText: 'Run now' }).click(); await p.waitForTimeout(500); await p.locator('.modal button.btn-primary').click(); await p.waitForTimeout(1500);
    ctx.check(await ceo.rpc('mail.activity', 'search_count', [[['summary', '=like', 'Auto reminder%']]]) === 1, 'running again does not create a second reminder');
    ctx.check(/Skipped: reminder still open/.test(await p.locator('.o_form_view').innerText()), 'the run log says why it skipped');
    await ceo.close();

    // the colleague who prepared the order finds it on Home and can open it
    const maker = await new Session(ctx, browser, 'demo.contracts', 'demo').start();
    await maker.home();
    const tools = (await maker.page.locator('.ei-top-tools').innerText()).replace(/\s+/g, ' ');
    ctx.check(/\b1 reminder\b/.test(tools), 'the colleague sees "1 reminder" on their Home', tools);
    await maker.page.locator('.ei-pill-info').click(); await maker.page.waitForTimeout(2000);
    await maker.clean('the reminders pill opens the reminders with no error', 0);
    ctx.check(/Supplier invoice still missing/.test(await maker.page.locator('.o_action_manager').innerText()), 'the reminder text is there');
    await ctx.shot(maker.page, 'automation_reminder_for_colleague');
    // people without the management role cannot read or change rules
    let denied = false;
    try { await maker.rpc('ei.rule', 'search_count', [[]]); } catch (e) { denied = /not allowed|access/i.test(String(e.message)); }
    ctx.check(denied, 'a colleague without the management role cannot read the rules');
    ctx.check(await maker.page.locator('.o_navbar', { hasText: 'Automation rules' }).count() === 0, 'and the menu entry is not offered');
    await maker.close();
  },
};
