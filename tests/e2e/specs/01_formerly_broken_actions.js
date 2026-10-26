// Every action and wizard that returns a window action from Python, driven the way a person does it:
// menu -> record -> button -> result. A flow passes only when the RESULT screen opens with no error dialog, no console
// error and no failed server call.
// Verified against the untouched pre-upgrade code (docs/e2e_baseline_reproduction.md): flows 1-4b, 10 and 11 already worked
// there (Odoo's button controller normalises the actions); flows 5b (cancel wizard), 6 (invoice wizard) and 7-9 (the three
// import wizards) were broken on screen. The Home money-tile crash is covered by specs 02 and 03.
const fs = require('fs');
const path = require('path');

const stamp = Date.now();
const REPO = path.join(__dirname, '../../..');

module.exports = {
  name: '01 formerly broken actions (12)',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const s = await new Session(ctx, browser, 'admin', 'admin').start();
    const p = s.page;
    // close dialogs from the TOP one down: a refusal dialog can sit on top of the wizard that raised it
    const closeDialogs = async () => {
      for (let i = 0; i < 6 && await p.locator('.modal').count(); i++) {
        const top = p.locator('.modal').last();
        const btn = top.locator('button', { hasText: /^(Close|Discard|Cancel)$/ }).first();
        if (await btn.count()) await btn.click({ timeout: 3000 }).catch(() => {}); else await p.keyboard.press('Escape');
        await p.waitForTimeout(400);
      }
    };
    const flow = async (label, fn) => {
      const m = s.mark();
      try { await fn(); } catch (e) {
        const dlg = await s.dialog();
        ctx.check(false, label, 'exception: ' + String(e.message).split('\n')[0].slice(0, 120) + (dlg ? ' | dialog: ' + dlg : ''));
        await ctx.shot(p, 'FAIL_' + label.replace(/\W+/g, '_').slice(0, 40)).catch(() => {});
        await closeDialogs(); return;
      }
      await s.clean(label, m);
      await closeDialogs();
    };
    const resultIsForm = async (model) => { await p.waitForSelector('.o_form_view', { timeout: 8000 }); return new RegExp(model.replace('.', '\\.')).test(p.url()); };
    const pickM2O = async (name, text) => {
      const f = p.locator(`.modal .o_field_widget[name=${name}] input`);
      await f.fill(text); await p.locator('.o-autocomplete--dropdown-item', { hasText: text }).first().click(); await p.waitForTimeout(300);
    };
    const upload = async (filename, content) => p.locator('.modal input[type=file]').setInputFiles({ name: filename, mimeType: 'text/csv', buffer: Buffer.from(content) });
    const fillNum = async (name, v) => { const f = p.locator(`.modal .o_field_widget[name=${name}] input`); await f.fill(String(v)); };

    // 1 contract -> Revise
    await flow('1 Contract > Revise opens the new revision', async () => {
      await s.menu('Orders & Trucks', 'Contracts'); await s.firstRow('CT/2026/0001'); await s.button('Revise');
      ctx.check(await resultIsForm('ei.contract'), '1 ... and shows a contract form');
    });
    // 2 DA -> Amend
    await flow('2 Delivery advice > Amend opens the amendment', async () => {
      await s.menu('Orders & Trucks', 'Delivery advices'); await s.firstRow('DA-DEMO-5502'); await s.button('Amend');
      ctx.check(await resultIsForm('ei.da'), '2 ... and shows a delivery advice form');
    });
    // 3 formula -> New version
    await flow('3 Formula > New version opens the new version', async () => {
      await s.menu('Setup', 'Formula register'); await s.firstRow(); await s.button('New version');
      ctx.check(await resultIsForm('ei.formula.definition'), '3 ... and shows a formula form');
    });
    // 4 daily order -> Send by email (composer with the PDF attached)
    await flow('4 Daily order > Send by email opens the composer with the PDF', async () => {
      await s.menu('Orders & Trucks', 'Daily orders'); await s.firstRow(); await s.button('Send by email');
      const modal = p.locator('.modal').first(); await modal.waitFor({ timeout: 8000 });
      const text = (await modal.innerText()).replace(/\s+/g, ' ');
      ctx.check(/Daily Order Request .*\.pdf/.test(text) && /Send/.test(text), '4 ... composer shows the attached Daily Order PDF', text.slice(0, 120));
    });
    // 4b the print button really produces a PDF file
    await flow('4b Daily order > Print downloads a real PDF', async () => {
      await s.menu('Orders & Trucks', 'Daily orders'); await s.firstRow();
      const [dl] = await Promise.all([p.waitForEvent('download', { timeout: 30000 }), p.locator('button:visible', { hasText: 'Print' }).first().click()]);
      const file = await dl.path(); const bytes = fs.readFileSync(file);
      ctx.check(bytes.slice(0, 5).toString() === '%PDF-' && bytes.length > 2000, `4b ... file is a PDF (${bytes.length} bytes)`);
    });
    // 5 DA -> Generate Daily Order (a second supplier's approved DA has no order yet)
    await flow('5 Delivery advice > Generate Daily Order opens the new order', async () => {
      await s.menu('Orders & Trucks', 'Delivery advices'); await s.firstRow('DA-DEMO-6601'); await s.button('Generate Daily Order');
      ctx.check(await resultIsForm('ei.daily.order'), '5 ... and shows the daily order form');
    });
    // 5b the order that is already approved cannot be cancelled once a supplier invoice is on it: the wizard must say WHY
    await flow('5b Cancel order request wizard works and the business rule speaks plainly', async () => {
      const mm = s.mark();
      await s.menu('Orders & Trucks', 'Daily orders'); await s.firstRow('DOR/2026/00001');
      await p.locator('button:visible', { hasText: /^Cancel$/ }).first().click(); await p.waitForTimeout(800);
      await p.locator('.modal .o_field_widget input, .modal textarea').first().fill('E2E: checking the wizard');
      await p.locator('.modal button', { hasText: 'Confirm' }).click(); await p.waitForTimeout(1500);
      const dlg = await s.dialog();
      ctx.check(!!dlg && /supplier invoice is already recorded/.test(dlg) && !/Action not allowed/.test(dlg), '5b ... the reason shown is the real rule, not "Action not allowed"', dlg || 'no dialog');
      s.discard(mm); // the refusal is the expected outcome here
      await closeDialogs();
    });
    // 6 invoice wizard
    await flow('6 Invoice delivered material > Create invoices opens the invoices', async () => {
      await s.menu('Bills & Invoices', 'Invoice delivered material');
      await p.locator('.o_data_row', { hasText: 'To invoice' }).first().locator('input[type=checkbox]').check();
      await p.locator('.o_cp_action_menus button').first().click(); await p.getByText('Invoice verified liftings', { exact: true }).click(); await p.waitForTimeout(1200);
      await p.locator('.modal button', { hasText: 'Create invoices' }).click(); await p.waitForSelector('.modal', { state: 'detached', timeout: 20000 }).catch(() => {}); await p.waitForSelector('.o_list_view, .o_form_view', { timeout: 20000 }); await p.waitForTimeout(500);
      const after = { url: p.url(), views: await p.locator('.o_list_view, .o_form_view').count(), modal: await p.locator('.modal').count() ? (await p.locator('.modal').first().innerText()).replace(/\s+/g, ' ').slice(0, 160) : '' };
      ctx.check(/account\.move|action-/.test(after.url) && after.views > 0 && !after.modal, '6 ... and shows the new customer invoice', JSON.stringify(after));
    });
    // 7 bank statement import wizard
    await flow('7 Import a bank statement opens the imported statement', async () => {
      await s.menu('Money', 'Import a bank statement');
      await pickM2O('journal_id', 'DEMO Meezan');
      const csv = `Date,Description,Reference,Debit,Credit,Balance\n25/10/2026,RAAST FROM E2E PAYER,E2E-${stamp},,1000,1000\n`;
      await upload('e2e.csv', csv); await fillNum('opening_balance', 0); await fillNum('closing_balance', 1000);
      await p.locator('.modal button', { hasText: 'Import' }).first().click(); await p.waitForTimeout(2500);
      ctx.check(/ei\.bank\.import/.test(p.url()) || (await p.locator('.o_form_view').count()) > 0, '7 ... and shows the statement form', p.url());
    });
    // 8 parent statement import wizard
    await flow('8 Import parent statement opens the matched statement', async () => {
      await s.menu('Month-end', 'Import parent statement');
      await pickM2O('partner_id', 'DEMO Parent');
      await p.locator('.modal .o_field_widget[name=date_from] input').fill('10/01/2026'); await p.keyboard.press('Enter');
      await p.locator('.modal .o_field_widget[name=date_to] input').fill('10/31/2026'); await p.keyboard.press('Enter');
      await upload('parent.csv', `Invoice No,Date,Amount,Tax\nE2E-INV-${stamp},06/10/2026,1000,0\n`);
      await p.locator('.modal button', { hasText: 'Import and match' }).click(); await p.waitForTimeout(2500);
      ctx.check(/ei\.parent\.statement/.test(p.url()) || (await p.locator('.o_form_view').count()) > 0, '8 ... and shows the statement form', p.url());
    });
    // 9 legacy code import wizard (re-import is idempotent: nothing new is created)
    await flow('9 Import old codes opens the import batch', async () => {
      const src = path.join(REPO, 'migration/source/EXI_legacy_codes.csv');
      if (!fs.existsSync(src)) { ctx.skip('9 legacy code file not present (migration/source is not in git)'); return; }
      await s.menu('Setup', 'Import old codes');
      await upload('EXI_legacy_codes.csv', fs.readFileSync(src, 'utf8'));
      await p.locator('.modal button', { hasText: 'Import' }).first().click(); await p.waitForTimeout(3500);
      ctx.check(/ei\.import\.batch/.test(p.url()), '9 ... and shows the batch form', p.url());
    });
    // 10 + 11 management dashboard and its KPI drill-downs
    await flow('10 Detailed report opens the management dashboard', async () => {
      await s.menu('Setup', 'Detailed report');
      ctx.check(/ei\.dashboard/.test(p.url()), '10 ... and shows the dashboard', p.url());
    });
    await flow('11 Each KPI magnifier opens the records behind it', async () => {
      const n = await p.locator('[name="action_open_kpi"]').count();
      ctx.check(n >= 6, `11 ... dashboard offers ${n} drill-down buttons`);
      for (let i = 0; i < Math.min(n, 6); i++) {
        await p.locator('[name="action_open_kpi"]').nth(i).click(); await p.waitForTimeout(1300);
        if (!(await p.locator('.o_list_view, .o_kanban_view, .o_form_view').count())) ctx.check(false, `11 ... drill-down ${i + 1} shows records`);
        await p.goBack(); await p.waitForTimeout(900);
      }
    });
    // 12 has no button: the approvals table on that dashboard is plain text
    ctx.skip('12 action_open_queue: no button in the product calls it (the dashboard approval counts are plain text); covered by Home task tiles instead');
    await s.close();
  },
};
