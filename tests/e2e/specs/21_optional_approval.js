// The client's final decision (9 Nov 2026): routine approval is OFF by default. The person entering a DA confirms it with
// "Save & Continue" and goes straight on to the daily order; "Send for review" on one DA (or the policy switched on) sends it
// to a second person. Only PKR and USD are offered for new entries. Staging copy, DEMO data.
module.exports = {
  name: '21 approval switched off by an administrator, and PKR/USD only',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const admin = await new Session(ctx, browser, 'admin', 'admin').start();
    await admin.rpc('ei.approval.policy', 'set_all', [false]);
    try {
      const s = await new Session(ctx, browser, 'demo.contracts', 'demo', [1440, 900], { timeout: 30000 }).start();
      const p = s.page;
      const m = s.mark();
      const act = (await admin.rpc('ir.model.data', 'search_read', [[['module', '=', 'ei_da_feeding'], ['name', '=', 'action_ei_da_feeding']], ['res_id']]))[0].res_id;
      await s.goto(`/odoo/action-${act}`); await p.waitForSelector('.ei-fd-method', { timeout: 30000 });
      await p.getByRole('tab', { name: /Real entry/ }).click();
      await p.getByRole('button', { name: 'New DA' }).click();
      await p.waitForSelector('.ei-fd-curseg [role="radio"]', { timeout: 15000 });
      const curs = await p.locator('.ei-fd-curseg [role="radio"]').allInnerTexts();
      ctx.check(curs.join('|') === 'PKR|USD', '1 a new DA offers exactly two currencies: PKR and USD', curs.join('|'));
      await p.waitForSelector('.ei-fd-main select option:nth-child(2)', { state: 'attached', timeout: 15000 });
      const opts = await p.locator('.ei-fd-main select option').evaluateAll((os) => os.map((o) => [o.value, o.textContent]));
      ctx.check(opts.slice(1).every(([, t]) => /PKR$/.test(t.trim())), '1 with PKR chosen, only PKR contracts are listed', opts.map((o) => o[1]).join(' / '));
      const feed = async (name, review, contractRe = /DEMO\/ISL\/001/, direct = false) => {
        if (!(await p.locator('#ei-fd-daname').count())) await p.getByRole('button', { name: 'New DA' }).click();
        await p.waitForSelector('.ei-fd-main select option:nth-child(2)', { state: 'attached', timeout: 15000 });
        const o = await p.locator('.ei-fd-main select option').evaluateAll((os) => os.map((x) => [x.value, x.textContent]));
        await p.locator('.ei-fd-main select').first().selectOption(o.find(([, t]) => contractRe.test(t))[0]);
        await p.fill('#ei-fd-daname', name);
        await p.locator('.ei-fd-main .ei-fd-field.is-wide input').last().fill('M/S DEMO CUSTOMER - REHMAN TRADERS');
        await p.getByRole('button', { name: 'Create draft DA' }).click(); await p.waitForSelector('.ei-fd-daname', { timeout: 15000 });
        await p.locator('.ei-fd-paper input[type="file"]').setInputFiles(require('../lib').synthPdf());
        await p.waitForTimeout(900);
        await p.getByRole('button', { name: 'Add Coil' }).click();
        await p.fill('#ei-fd-coil', name + '-C1');
        await p.locator('.ei-fd-editor .ei-fd-field:has-text("Weight") input').fill('4574');
        for (const [label, term] of [['Customer', 'Rehman'], ['Customer code', 'D.01']]) {
          await p.locator('.ei-fd-pick', { hasText: label }).getByRole('button', { name: /Choose|Change/ }).first().click();
          await p.fill('#ei-fd-look', term); await p.waitForTimeout(700); await p.locator('.ei-fd-lookrows button').first().click(); await p.waitForTimeout(300);
        }
        if (direct) {
          await p.getByRole('radio', { name: /Direct purchase/ }).click();
          await p.locator('.ei-fd-editor .ei-fd-field:has-text("Purchase rate") input').fill('200000');
          await p.locator('.ei-fd-editor .ei-fd-field:has-text("Sale rate") input').fill('201000');
        } else {
          await p.getByRole('radio', { name: /Normal sale/ }).click();
          await p.locator('.ei-fd-editor .ei-fd-field:has-text("Sale = mill rate") input').fill('-1000');
        }
        await p.waitForTimeout(900);
        await p.getByRole('button', { name: 'Save & Add Coil' }).click(); await p.waitForTimeout(1200);
        // Duplicate Row: the next coil keeps the customer, codes and method; its coil number and weight start empty
        const coilVal = await p.locator('#ei-fd-coil').inputValue();
        const custShown = await p.locator('.ei-fd-pick', { hasText: 'Customer code' }).innerText();
        ctx.check(coilVal === '' && /D\.01/.test(custShown), `2 ${name}: the next coil keeps the customer and code, with an empty coil number`);
        await p.locator('.ei-fd-editor').getByRole('button', { name: 'Close', exact: true }).click();
        await p.locator('.ei-fd-table tbody tr').first().getByRole('button', { name: /Duplicate/ }).click(); await p.waitForTimeout(600);
        ctx.check(await p.locator('#ei-fd-coil').inputValue() === '' && await p.locator('.ei-fd-mpick.is-on', { hasText: direct ? 'Direct purchase' : 'Normal sale' }).count() === 1,
          `2 ${name}: Duplicate Row copies the method and codes but not the coil number`);
        await p.fill('#ei-fd-coil', name + '-C2');
        await p.locator('.ei-fd-editor .ei-fd-field:has-text("Weight") input').fill('3980'); await p.waitForTimeout(900);
        await p.getByRole('button', { name: 'Save Draft' }).click(); await p.waitForTimeout(1200);
        const foot = (await p.locator('.ei-fd-table tfoot').innerText()).replace(/\s+/g, ' ');
        ctx.check(/2 coil/.test(foot) && foot.includes('8.554'), `2 ${name}: the totals row shows 2 coils and 8.554 MTL`, foot);
        if (review) await p.locator('.ei-fd-review input').check();
        await p.getByRole('button', { name: 'Save & Continue' }).click(); await p.waitForTimeout(1800);
        return (await admin.rpc('ei.da', 'search_read', [[['name', '=', name]], ['state', 'approved_by']]))[0];
      };
      const stamp = Date.now().toString().slice(-6);
      const direct = await feed('DA-E2E-OFF-' + stamp, false, /DEMO\/ISL\/002/, true);
      ctx.check(direct.state === 'approved' && /Contracts/.test(direct.approved_by[1]), '3 approval off: Save & Continue confirms the DA at once, by the person entering it', JSON.stringify(direct));
      ctx.check(/Next task: daily order request/.test(await p.locator('.ei-fd-done').innerText()), '3 and the next task (the daily order request) is ready');
      await p.getByRole('button', { name: 'Open the daily order' }).click(); await p.waitForSelector('.o_form_view', { timeout: 15000 });
      ctx.check(await p.locator('.o_form_view').innerText().then((t) => t.includes('DA-E2E-OFF-' + stamp)), '3 "Open the daily order" opens the order made from this DA');
      await s.goto(`/odoo/action-${act}`); await p.waitForSelector('.ei-fd-method', { timeout: 30000 });
      await p.getByRole('tab', { name: /Real entry/ }).click();
      const reviewed = await feed('DA-E2E-REV-' + stamp, true);
      ctx.check(reviewed.state === 'under_review', '4 "Send for review" ticked: the DA waits for a second person', reviewed.state);
      ctx.check(/Pending approval|Waiting for review/.test(await p.locator('.ei-fd-done').innerText()), '4 and the desk says it is waiting for a checker');
      let selfApprove = '';
      try { await s.rpc('ei.da', 'action_approve', [[(await admin.rpc('ei.da', 'search', [[['name', '=', 'DA-E2E-REV-' + stamp]]]))[0]]]); } catch (e) { selfApprove = String(e.message); }
      ctx.check(/approver|Maker-checker/.test(selfApprove), '4 the person who entered it cannot approve it themselves', selfApprove.slice(0, 120));
      await s.clean('5 the approval-off flow is clean', m);
      await ctx.shot(p, 'approval_off_desk');
      await s.close();
      // the settings page: only an administrator sees the switches
      const ad = admin.page;
      await admin.goto('/odoo/settings'); await ad.waitForTimeout(2500);
      await ad.getByText('Export International', { exact: true }).first().click(); await ad.waitForTimeout(1000);
      const txt = await ad.locator('body').innerText();
      ctx.check(/Maker-checker approval/.test(txt) && /Require approval: delivery advices/.test(txt), '6 the administrator finds "Require approval" per workflow in Settings');
    } finally {
      await admin.rpc('ei.approval.policy', 'set_all', [true]);
      await admin.close();
    }
  },
};
