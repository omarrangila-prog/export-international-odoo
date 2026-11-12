// Maker-checker in the real browser (client requirement, 10 Nov 2026). Each person signs in on the login page and uses the screens:
// maker feeds a DA and presses "Submit for Approval" -> signs out; checker signs in, sees "Approvals (n)" and the bell, opens the request
// from the notification, reviews rates and the paper, approves -> the DA is approved and its daily order prepared; the maker sees the result.
// Then: return for correction -> corrected and resubmitted -> approved; reject with a reason; a person without the role; the maker trying to
// approve their own; the counter updating live; the whole review on a phone. Every outcome is read back from the database. DEMO data only.
module.exports = {
  name: '25 maker-checker: submit, notify, review, approve / return / reject, live counter, phone',
  async run(ctx, browser) {
    const { Session, synthPdf } = require('../lib');
    const stamp = String(Date.now()).slice(-6);
    const admin = await new Session(ctx, browser, 'admin', 'admin').start();
    await admin.rpc('ei.approval.policy', 'set_all', [true]);
    const one = async (model, domain, fields) => (await admin.rpc(model, 'search_read', [domain, fields], { limit: 1, order: 'id desc' }))[0];
    const reqOf = async (da) => one('ei.approval.request', [['res_model', '=', 'ei.da'], ['name', 'ilike', da]], ['state', 'approver_id', 'maker_id', 'round', 'decided_by', 'decision_note', 'id']);
    const daOf = (da) => one('ei.da', [['name', '=', da]], ['state', 'id']);

    // the maker feeds one coil in the desk and submits it
    const feed = async (s, da, kg = '4000') => {
      const p = s.page;
      await p.goto(`${ctx.base}/odoo/action-ei_da_feeding.action_ei_da_feeding`); await p.waitForSelector('.ei-fd-tabs', { timeout: 30000 });
      await p.getByRole('tab', { name: /Real entry/ }).click(); await p.getByRole('button', { name: 'New DA' }).click(); await p.waitForSelector('.ei-fd-more', { state: 'attached', timeout: 15000 }); await p.evaluate(() => { document.querySelector('.ei-fd-more').open = true; });
      await p.waitForFunction(() => [...document.querySelectorAll('#ei-fd-contract option')].some((o) => /DEMO\/ISL\/002/.test(o.textContent)));
      const opts = await p.locator('#ei-fd-contract option').evaluateAll((os) => os.map((o) => [o.value, o.textContent]));
      await p.locator('#ei-fd-contract').selectOption(opts.find(([, t]) => /DEMO\/ISL\/002/.test(t))[0]);
      await p.fill('#ei-fd-daname', da); await p.locator('.ei-fd-main .ei-fd-field.is-wide input').last().fill('M/S DEMO CUSTOMER - REHMAN TRADERS');
      await p.getByRole('button', { name: 'Create draft DA' }).click(); await p.waitForSelector('.ei-fd-daname');
      await p.locator('.ei-fd-paper input[type="file"]').setInputFiles(synthPdf()); await p.waitForTimeout(1500);
      await p.getByRole('button', { name: 'Add Coil' }).click();
      await p.fill('#ei-fd-coil', 'MC-1'); await p.locator('.ei-fd-editor .ei-fd-field', { hasText: 'Weight' }).locator('input').fill(kg);
      for (const [label, term, row] of [['Sold (OUT)', 'Rehman', null], ['Sales code', 'D.01', 'D.01']]) {
        await p.locator('.ei-fd-pick', { hasText: label }).getByRole('button', { name: /Choose|Change/ }).first().click();
        await p.locator('#ei-fd-look').pressSequentially(term, { delay: 40 }); await p.waitForTimeout(1200);
        await p.locator('.ei-fd-lookrows button', row ? { hasText: row } : {}).first().click(); await p.waitForTimeout(400);
      }
      await p.locator('.ei-fd-mpick', { hasText: /^Direct purchase and sale/ }).click();
      await p.locator('.ei-fd-editor .ei-fd-field', { hasText: 'Purchase rate / MTL' }).locator('input').fill('200000');
      await p.locator('.ei-fd-editor .ei-fd-field', { hasText: 'Sale rate / MTL' }).locator('input').fill('201000');
      await p.waitForSelector('.ei-fd-answer', { timeout: 40000 });
      await p.getByRole('button', { name: 'Save Draft' }).click(); await p.waitForTimeout(1500);
      await p.getByRole('button', { name: 'Submit for Approval' }).click(); await p.waitForSelector('.ei-fd-done.is-wait', { timeout: 30000 });
    };
    const pillCount = async (p) => parseInt((await p.locator('.o_menu_systray .ei-ap-pill .ei-ap-pill-count').innerText().catch(() => '0')).trim() || '0', 10);
    const decideInCenter = async (p, kind, reason) => {
      const btn = { approve: 'Approve', return: 'Return for correction', reject: 'Reject' }[kind];
      await p.locator('.ei-ap-actions').getByRole('button', { name: btn, exact: true }).click();
      await p.waitForSelector('.ei-ap-ask');
      if (reason !== undefined) await p.locator('.ei-ap-ask textarea').fill(reason);
      await p.locator('.ei-ap-ask .ei-ap-btn.is-primary').click(); await p.waitForTimeout(2000);
    };

    // ---------------------------------------------------------------- A: submit -> notify -> open from the notification -> approve
    const daA = `DA-MC-A-${stamp}`;
    let s = await new Session(ctx, browser, 'demo.contracts', 'demo', [1440, 900], { timeout: 30000 }).start();
    let m = s.mark();
    await feed(s, daA);
    const banner = await s.page.locator('.ei-fd-done.is-wait').innerText();
    let rq = await reqOf(daA);
    ctx.check(rq && rq.state === 'pending' && /Contractapprover/.test(rq.approver_id[1]) && /Pending approval/.test(banner) && banner.includes(rq.approver_id[1]),
      'A1 maker feeds a DA and submits it: pending, assigned to a checker who is not the maker, the desk names the checker', `${JSON.stringify(rq)} | ${banner.replace(/\s+/g, ' ')}`);
    ctx.check((await daOf(daA)).state === 'under_review', 'A1 the DA waits (under review); nothing is approved by the maker');
    await ctx.shot(s.page, '25_A1_maker_submitted');
    await s.clean('A1 maker screens are clean', m);
    await s.close();

    let c = await new Session(ctx, browser, 'demo.contractapprover', 'demo', [1440, 900], { timeout: 30000 }).start();
    let p = c.page; m = c.mark();
    await p.waitForSelector('.ei-ap-pill', { timeout: 20000 });
    const counts0 = await c.rpc('ei.approval.request', 'counts', []);
    const pill0 = await pillCount(p);
    ctx.check(pill0 === counts0.pending_for_me && pill0 >= 1, 'A2 the checker sees "Approvals (n)" in the top bar, equal to what waits for them', `${pill0} vs ${counts0.pending_for_me}`);
    ctx.check(await p.locator('.ei-ap-bell .ei-ap-bell-count').count() === 1, 'A2 the bell shows unread notifications');
    await p.locator('.ei-ap-bell').click(); await p.waitForSelector('.ei-ap-panel');
    const item = p.locator('.ei-ap-item', { hasText: daA }).first();
    await item.waitFor({ timeout: 15000 }).catch(() => {});
    ctx.check(await item.count() === 1 && /New request for you/.test(await item.innerText()) && /DEMO Contracts/.test(await item.innerText()),
      'A3 the notification names the request, the document type and the maker', (await item.innerText().catch(() => '')).replace(/\s+/g, ' '));
    await ctx.shot(p, '25_A3_checker_bell');
    await item.click(); await p.waitForSelector('.ei-ap-review', { timeout: 20000 }); await p.waitForTimeout(1200);
    const rv = await p.locator('.ei-ap-review').innerText();
    ctx.check(rv.includes(daA) && /200,000\.00/.test(rv) && /201,000\.00/.test(rv) && /paper\.pdf/.test(rv) && /4\.000/.test(rv),
      'A4 clicking it opens that DA: rates, quantity and the attached paper are on the review', rv.replace(/\s+/g, ' ').slice(0, 240));
    ctx.check(/Submitted/.test(rv) && /Assigned/.test(rv), 'A4 the timeline shows the submission and the assignment');
    await ctx.shot(p, '25_A4_checker_review');
    await decideInCenter(p, 'approve', 'Checked against the paper');
    rq = await reqOf(daA);
    const daStA = (await daOf(daA)).state;
    ctx.check(rq.state === 'approved' && daStA === 'approved' && /Contractapprover/.test(rq.decided_by[1]), 'A5 approved: the request and the DA are approved, by the checker', `${rq.state} ${daStA}`);
    const order = await one('ei.daily.order', [['line_ids.da_line_id.da_id.name', '=', daA]], ['name', 'state']);
    ctx.check(!!order, 'A6 the approved DA moved on: its daily order request was prepared', JSON.stringify(order));
    ctx.check(/Approved/.test(await p.locator('.ei-ap-review .ei-ap-rv-title').innerText()), 'A6 the review now says Approved');
    await ctx.shot(p, '25_A6_checker_approved');
    await p.reload(); await p.waitForSelector('.o_menu_systray .ei-ap-pill', { timeout: 20000 }); await p.waitForTimeout(1500);
    const counts1 = await c.rpc('ei.approval.request', 'counts', []);
    ctx.check(await pillCount(p) === counts1.pending_for_me, 'A7 after a reload the counter still equals what waits (no stale count)', `${await pillCount(p)} vs ${counts1.pending_for_me}`);
    const stillListed = await c.rpc('ei.approval.request', 'center_data', [], { tab: 'pending' });
    ctx.check(!stillListed.rows.some((r) => r.name.includes(daA)), 'A7 the approved DA left "Pending for me"');
    await c.clean('A checker screens are clean', m);
    await c.close();

    s = await new Session(ctx, browser, 'demo.contracts', 'demo', [1440, 900], { timeout: 30000 }).start();
    p = s.page;
    await p.locator('.ei-ap-bell').click(); await p.waitForSelector('.ei-ap-panel');
    const told = p.locator('.ei-ap-item', { hasText: daA }).first();
    await told.waitFor({ timeout: 15000 }).catch(() => {});
    ctx.check(await told.count() === 1 && /approved/i.test(await told.innerText()), 'A8 the maker is told it was approved', (await told.innerText().catch(() => '')).replace(/\s+/g, ' '));
    await ctx.shot(p, '25_A8_maker_told');
    await s.close();

    // ---------------------------------------------------------------- B: return for correction -> corrected -> resubmitted -> approved
    const daB = `DA-MC-B-${stamp}`;
    s = await new Session(ctx, browser, 'demo.contracts', 'demo', [1440, 900], { timeout: 30000 }).start();
    await feed(s, daB, '5000'); await s.close();
    c = await new Session(ctx, browser, 'demo.contractapprover', 'demo', [1440, 900], { timeout: 30000 }).start();
    p = c.page;
    await p.locator('.ei-ap-pill').click(); await p.waitForSelector('.ei-ap-page');
    await p.locator('.ei-ap-table tbody tr', { hasText: daB }).first().click(); await p.waitForSelector('.ei-ap-review');
    await decideInCenter(p, 'return', '');
    ctx.check(/Write the reason/.test(await p.locator('.ei-ap-ask').innerText()), 'B1 returning without a reason is refused on the screen');
    await p.locator('.ei-ap-ask textarea').fill('The paper says 4,800 kg, not 5,000'); await p.locator('.ei-ap-ask .ei-ap-btn.is-primary').click(); await p.waitForTimeout(2000);
    rq = await reqOf(daB);
    ctx.check(rq.state === 'returned' && (await daOf(daB)).state === 'draft' && /4,800/.test(rq.decision_note), 'B2 returned with the reason: the DA is a draft again', JSON.stringify(rq));
    await c.close();
    s = await new Session(ctx, browser, 'demo.contracts', 'demo', [1440, 900], { timeout: 30000 }).start();
    p = s.page;
    await p.goto(`${ctx.base}/odoo/action-ei_da_feeding.action_ei_da_feeding`); await p.waitForSelector('.ei-fd-tabs');
    await p.getByRole('tab', { name: /Real entry/ }).click(); await p.locator('.ei-fd-darow', { hasText: daB }).click(); await p.waitForSelector('.ei-fd-daname');
    const why = await p.locator('.ei-fd-warnbox').first().innerText().catch(() => '');
    ctx.check(/Returned for correction/.test(why) && /4,800/.test(why), 'B3 the maker opens the DA and reads why it came back', why.replace(/\s+/g, ' '));
    await ctx.shot(p, '25_B3_maker_returned');
    await p.locator('.ei-fd-table tbody tr').first().getByRole('button', { name: 'Edit' }).click();
    await p.locator('.ei-fd-editor .ei-fd-field', { hasText: 'Weight' }).locator('input').fill('4800'); await p.waitForTimeout(1500);
    await p.getByRole('button', { name: 'Save Draft' }).click(); await p.waitForTimeout(1500);
    await p.getByRole('button', { name: 'Submit for Approval' }).click(); await p.waitForSelector('.ei-fd-done.is-wait', { timeout: 30000 });
    rq = await reqOf(daB);
    ctx.check(rq.state === 'pending' && rq.round === 2, 'B4 corrected and resubmitted: round 2 is pending', JSON.stringify(rq));
    await s.close();
    c = await new Session(ctx, browser, 'demo.contractapprover', 'demo', [1440, 900], { timeout: 30000 }).start();
    p = c.page;
    await p.goto(`${ctx.base}/odoo/action-ei_approvals.ei_approvals_center_action`); await p.waitForSelector('.ei-ap-page');
    await p.locator('.ei-ap-table tbody tr', { hasText: daB }).first().click(); await p.waitForSelector('.ei-ap-review'); await p.waitForTimeout(800);
    ctx.check(/Earlier submissions/.test(await p.locator('.ei-ap-review').innerText()), 'B5 the checker sees the earlier round and its reason');
    await decideInCenter(p, 'approve', 'Corrected');
    ctx.check((await daOf(daB)).state === 'approved', 'B5 the corrected DA is approved');
    await c.close();

    // ---------------------------------------------------------------- C: reject with a reason
    const daC = `DA-MC-C-${stamp}`;
    s = await new Session(ctx, browser, 'demo.contracts', 'demo', [1440, 900], { timeout: 30000 }).start();
    await feed(s, daC); await s.close();
    c = await new Session(ctx, browser, 'demo.contractapprover', 'demo', [1440, 900], { timeout: 30000 }).start();
    p = c.page;
    await p.goto(`${ctx.base}/odoo/action-ei_approvals.ei_approvals_center_action`); await p.waitForSelector('.ei-ap-page');
    await p.locator('.ei-ap-table tbody tr', { hasText: daC }).first().click(); await p.waitForSelector('.ei-ap-review');
    await decideInCenter(p, 'reject', 'Duplicate of an earlier DA');
    rq = await reqOf(daC);
    ctx.check(rq.state === 'rejected' && (await daOf(daC)).state === 'cancelled' && /Duplicate/.test(rq.decision_note), 'C1 rejected with a reason: the DA is cancelled', JSON.stringify(rq));
    await ctx.shot(p, '25_C1_rejected');
    await c.close();

    // ---------------------------------------------------------------- D: a person without the role; E: the maker approving their own
    const daE = `DA-MC-E-${stamp}`;
    s = await new Session(ctx, browser, 'demo.contracts', 'demo', [1440, 900], { timeout: 30000 }).start();
    await feed(s, daE);
    const rqE = await reqOf(daE);
    let refused = '';
    try { await s.rpc('ei.approval.request', 'decide', [rqE.id, 'approve', '']); } catch (e) { refused = String(e.message); }
    ctx.check(/Maker-checker|different person|not an authorised/i.test(refused), 'E1 the maker cannot approve their own DA (server refuses)', refused.slice(0, 120));
    try { refused = ''; const [d] = await admin.rpc('ei.da', 'search_read', [[['name', '=', daE]], ['id']]); await s.rpc('ei.da', 'action_approve', [[d.id]]); } catch (e) { refused = String(e.message); }
    ctx.check(!!refused, 'E2 nor through the old Approve button of the document', refused.slice(0, 120));
    await s.page.goto(`${ctx.base}/odoo/action-ei_approvals.ei_approvals_center_action`); await s.page.waitForSelector('.ei-ap-page');
    await s.page.locator('.ei-ap-tab', { hasText: 'My submissions' }).click(); await s.page.waitForTimeout(1200);
    await s.page.locator('.ei-ap-table tbody tr', { hasText: daE }).first().click(); await s.page.waitForSelector('.ei-ap-review');
    const own = await s.page.locator('.ei-ap-actions').innerText();
    ctx.check(!/\bApprove\b/.test(own.replace('Approvals', '')) && /Withdraw/.test(own), 'E3 the maker sees no Approve button on their own request, only Withdraw', own.replace(/\s+/g, ' '));
    await s.close();
    const d = await new Session(ctx, browser, 'demo.dispatch', 'demo', [1440, 900], { timeout: 30000 }).start();
    refused = '';
    try { await d.rpc('ei.approval.request', 'decide', [rqE.id, 'approve', '']); } catch (e) { refused = String(e.message); }
    ctx.check(!!refused, 'D1 someone without the approver role cannot approve it', refused.slice(0, 120));
    const theirs = await d.rpc('ei.approval.request', 'center_data', [], { tab: 'all' });
    ctx.check(!theirs.rows.some((r) => r.name.includes(daE)) && !(await d.page.locator('.ei-ap-pill').count()),
      'D2 and does not even see it, nor an approvals counter', String(theirs.total));
    await d.close();
    ctx.check((await daOf(daE)).state === 'under_review', 'E4 after both attempts the DA still waits for a real checker');

    // ---------------------------------------------------------------- F: the counter updates live (no reload)
    c = await new Session(ctx, browser, 'demo.contractapprover', 'demo', [1440, 900], { timeout: 30000 }).start();
    p = c.page; await p.waitForSelector('.ei-ap-pill'); await p.waitForTimeout(1500);
    const before = await pillCount(p);
    const daF = `DA-MC-F-${stamp}`;
    s = await new Session(ctx, browser, 'demo.contracts', 'demo', [1440, 900], { timeout: 30000 }).start();
    await feed(s, daF); await s.close();
    let live = before;
    for (let i = 0; i < 30 && live <= before; i++) { await p.waitForTimeout(1000); live = await pillCount(p); }
    ctx.check(live === before + 1, 'F1 a new request raises the checker\'s counter without reloading the page', `${before} -> ${live}`);
    const toast = await p.locator('.o_notification').allInnerTexts();
    ctx.check(toast.some((t) => /New request for you/.test(t) && t.includes(daF)), 'F1 with one quiet toast naming it', toast.join(' | ').slice(0, 160));
    await c.close();

    // ---------------------------------------------------------------- G: on a phone
    c = await new Session(ctx, browser, 'demo.contractapprover', 'demo', [390, 844], { timeout: 30000 }).start();
    p = c.page; m = c.mark(); await p.waitForTimeout(2000);
    const badge = await p.locator('.ei-bn-item', { hasText: 'Approvals' }).locator('.ei-bn-badge').innerText().catch(() => '');
    const cnt = (await c.rpc('ei.approval.request', 'counts', [])).pending_for_me;
    ctx.check(parseInt(badge, 10) === cnt, 'G1 on a phone the bottom bar\'s Approvals shows the count', `${badge} vs ${cnt}`);
    ctx.check(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'G1 the phone top bar fits (no sideways scrolling)');
    await p.locator('.ei-bn-item', { hasText: 'Approvals' }).click(); await p.locator('.ei-sheet').getByText('Approvals centre').click();
    await p.waitForSelector('.ei-ap-page'); await p.waitForTimeout(1000);
    await p.locator('.ei-ap-card', { hasText: daF }).first().click(); await p.waitForSelector('.ei-ap-review'); await p.waitForTimeout(800);
    const fits = await p.evaluate(() => {
      const vw = innerWidth, vh = innerHeight;
      const btns = [...document.querySelectorAll('.ei-ap-actions .ei-ap-btn')].map((b) => b.getBoundingClientRect());
      return { overflow: document.documentElement.scrollWidth > vw, buttons: btns.length, inside: btns.every((r) => r.left >= 0 && r.right <= vw + 0.5 && r.bottom <= vh + 0.5 && r.width > 40) };
    });
    ctx.check(!fits.overflow && fits.buttons >= 3 && fits.inside, 'G2 the review fills the phone; Approve, Return and Reject are on screen and not clipped', JSON.stringify(fits));
    const scrolled = await p.evaluate(() => { const el = document.querySelector('.ei-ap-rv-scroll'); el.scrollTop = 600; return el.scrollTop > 0; });
    ctx.check(scrolled, 'G2 the review scrolls on a phone');
    await ctx.shot(p, '25_G2_phone_review');
    await decideInCenter(p, 'approve');
    ctx.check((await daOf(daF)).state === 'approved', 'G3 approved from the phone');
    await c.clean('G phone screens are clean', m);
    await c.close();
    await admin.close();
  },
};
