#!/usr/bin/env node
// A gallery of every screen of the staging copy, so someone who cannot run the system can still see what it looks like.
//   NODE_PATH=$HOME/tfmsg-website/node_modules node tests/ui_gallery.js [outDir] [baseUrl]
// Walks every menu entry the demo users can open (list/cards, the first record, a new record, the second tab), then the Home of each
// role, the interactive states (tooltips, menus, dialogs, the assistant, matching, Party 360), dark theme and a phone. Writes PNGs and
// INDEX.md (what each file is, who is signed in, theme and size). Read-only: nothing is saved (new records are left unsaved).
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const OUT = path.resolve(process.argv[2] || path.join(__dirname, '..', 'docs', 'ui', 'gallery'));
const BASE = process.argv[3] || 'http://127.0.0.1:8369';
const PASS = { admin: 'admin' };
const SECTIONS = (process.argv[4] || 'menus,homes,states,dark,phone,login').split(',');
const on = (k) => SECTIONS.includes(k);
const entries = [];
const problems = [];
const PREV = path.join(OUT, 'index.json');
const previous = fs.existsSync(PREV) && process.argv[4] ? JSON.parse(fs.readFileSync(PREV, 'utf8')).entries : [];
fs.mkdirSync(OUT, { recursive: true });

const slug = (s) => String(s).toLowerCase().replace(/&/g, 'and').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60);

async function open(browser, user, { scheme = 'light', vp = [1440, 900] } = {}) {
  const ctx = await browser.newContext({ viewport: { width: vp[0], height: vp[1] }, colorScheme: scheme });
  await ctx.addCookies([{ name: 'color_scheme', value: scheme, url: BASE }]);
  const page = await ctx.newPage();
  page.setDefaultTimeout(20000);
  await page.goto(BASE + '/web/login');
  await page.fill('input[name=login]', user); await page.fill('input[name=password]', PASS[user] || 'demo');
  await page.click('button[type=submit]');
  await page.waitForSelector('.o_navbar', { timeout: 60000 });
  await page.waitForTimeout(800);
  return { ctx, page, user, scheme, vp };
}

// one screenshot; a tall page is captured whole (the page scrolls inside itself, so the window is made as tall as its content)
async function shot(s, file, what, { full = true, cap = 3000, note = '' } = {}) {
  const { page } = s;
  await page.waitForTimeout(1300);
  const vp = page.viewportSize();
  let extra = 0;
  if (full) {
    extra = await page.evaluate(() => {
      let max = 0;
      for (const e of document.querySelectorAll('.o_action_manager, .o_action_manager *')) {
        if (e.scrollHeight > e.clientHeight + 4 && ['auto', 'scroll'].includes(getComputedStyle(e).overflowY)) max = Math.max(max, e.scrollHeight - e.clientHeight);
      }
      return max;
    });
  }
  const tall = extra > 40;
  if (tall) { await page.setViewportSize({ width: vp.width, height: Math.min(vp.height + extra + 24, cap) }); await page.waitForTimeout(800); }
  const name = file.endsWith('.png') ? file : file + '.png';
  await page.screenshot({ path: path.join(OUT, name) });
  const size = tall ? `${vp.width}x${Math.min(vp.height + extra + 24, cap)} (whole page)` : `${vp.width}x${vp.height}`;
  if (tall) await page.setViewportSize(vp);
  entries.push({ file: name, what, user: s.user, scheme: s.scheme, size, note });
  console.log('  ' + name);
}
const attempt = async (label, fn) => { try { await fn(); } catch (e) { problems.push(`${label}: ${String(e.message).split('\n')[0].slice(0, 140)}`); console.log('  !! ' + label + ': ' + String(e.message).split('\n')[0].slice(0, 100)); } };

async function menuTree(page) {
  return page.evaluate(async () => {
    const j = await (await fetch('/web/webclient/load_menus')).json();
    const out = [];
    const walk = (id, trail) => {
      const m = j[id]; if (!m) return;
      const t = id === 'root' ? [] : [...trail, m.name];
      if (m.actionID && id !== 'root') out.push({ id: m.id, actionID: m.actionID, path: t.join(' > '), app: m.appID });
      for (const c of m.children || []) walk(c, t);
    };
    walk('root', []);
    return out;
  });
}

async function describe(page) {
  return page.evaluate(() => {
    const kind = document.querySelector('.modal .modal-content') ? 'dialog' : document.querySelector('.o_form_view') ? 'record' : document.querySelector('.o_list_view') ? 'list' : document.querySelector('.o_kanban_view') ? 'cards' : document.querySelector('.ei-home') ? 'home' : 'page';
    const title = (document.querySelector('.modal-title') || document.querySelector('.o_last_breadcrumb_item') || document.querySelector('h1') || {}).innerText || '';
    const rows = document.querySelectorAll('.o_data_row, .o_kanban_record:not(.o_kanban_ghost)').length;
    const pager = (document.querySelector('.o_pager_counter') || {}).innerText || '';
    return { kind, title: title.trim().replace(/\s+/g, ' ').slice(0, 80), rows, pager: pager.trim() };
  });
}

(async () => {
  const browser = await chromium.launch({ ignoreDefaultArgs: ['--hide-scrollbars'] });   // real scrollbars, as a person sees them
  console.log('gallery ->', OUT);

  // ============================================================ 1 every menu entry (the first user who can open it)
  console.log('\n[1] menu entries');
  const users = !on('menus') ? ['demo.ceo', 'admin'] : ['demo.ceo', 'demo.sysadmin', 'admin', 'demo.bank', 'demo.cash', 'demo.contracts', 'demo.dispatch', 'demo.accountant'];
  const sessions = {}; const seen = new Set(); let n = 0;
  for (const u of users) {
    const s = sessions[u] = await open(browser, u).catch(() => null);
    if (!s) { problems.push('could not sign in as ' + u); continue; }
    const tree = on('menus') ? await menuTree(s.page) : [];
    for (const m0 of tree) {
      if (!m0.path.startsWith('Export International')) continue;        // our application only (not Odoo's Discuss and the like)
      const m = { ...m0, path: m0.path.replace(/^Export International( > )?/, '') || 'Export International' };
      if (seen.has(m.actionID)) continue;
      seen.add(m.actionID); n++;
      const base = `menu-${String(n).padStart(2, '0')}-${slug(m.path)}`;
      await attempt(base, async () => {
        const { page } = s;
        await page.goto(`${BASE}/odoo/action-${m.actionID}`);
        await page.waitForSelector('.o_action_manager .o_action, .modal .modal-content', { timeout: 30000 });
        await page.waitForTimeout(700);
        const d = await describe(page);
        const isDialog = d.kind === 'dialog';
        await shot(s, base, `Menu "${m.path}": ${d.kind}${d.title ? ' "' + d.title + '"' : ''}${d.pager ? ', ' + d.pager : d.rows ? ', ' + d.rows + ' shown' : ''}`, { full: !(d.kind === 'list' || d.kind === 'cards'), cap: 2800 });
        if (isDialog) return;
        // the first record
        const first = page.locator('.o_data_row, .o_kanban_record:not(.o_kanban_ghost)').first();
        if (await first.count() && await first.isVisible()) {
          await first.click();
          await page.waitForSelector('.o_form_view .o_form_sheet', { timeout: 12000 });
          const r = await describe(page);
          await shot(s, base + '-record', `The first record of "${m.path}": ${r.title}`);
          const tabs = page.locator('.o_notebook .nav-link');
          if (await tabs.count() > 1) { await tabs.nth(1).click(); await shot(s, base + '-record-tab2', `The same record, second tab "${(await tabs.nth(1).innerText()).trim()}"`); }
        }
      });
      // a new record (left unsaved)
      await attempt(base + '-new', async () => {
        const { page } = s;
        await page.goto(`${BASE}/odoo/action-${m.actionID}`);
        await page.waitForSelector('.o_action_manager .o_action', { timeout: 30000 });
        const add = page.locator('.o_control_panel .o_list_button_add, .o_control_panel .o_form_button_create, .o_control_panel .o-kanban-button-new').first();
        if (!(await add.count()) || !(await add.isVisible())) return;
        await add.click();
        await page.waitForSelector('.o_form_view .o_form_sheet, .modal .modal-content', { timeout: 12000 });
        await page.waitForTimeout(500);
        await shot(s, base + '-new', `Making a new record in "${m.path}" (nothing is saved): fields are visible boxes`);
      });
    }
    // keep the signed-in pages for later states: only the first two are needed
    if (!['demo.ceo', 'admin'].includes(u)) { await s.ctx.close(); delete sessions[u]; }
  }

  // ============================================================ 2 the Home of every role
  console.log('\n[2] Home of each role');
  const roles = [['demo.ceo', 'executive'], ['demo.finance', 'finance manager'], ['demo.accountant', 'accountant'], ['demo.contractapprover', 'contract desk'], ['demo.bank', 'data entry (bank)'], ['demo.cash', 'data entry (cash)'], ['demo.dispatch', 'logistics'], ['demo.sysadmin', 'system administrator']];
  for (const [u, label] of (on('homes') ? roles : [])) {
    await attempt('home ' + u, async () => {
      const s = await open(browser, u);
      await s.page.goto(BASE + '/odoo'); await s.page.waitForSelector('.ei-home .ei-top-tools', { timeout: 40000 });
      await shot(s, `home-${slug(label)}`, `Home (the "Overview") as ${label}: what this role may see, nothing more`, { cap: 5200 });
      await s.ctx.close();
    });
  }

  // ============================================================ 3 interactive states (CEO)
  console.log('\n[3] states');
  const ceo = sessions['demo.ceo'];
  const P = ceo.page;
  if (on('states')) {
  await attempt('home states', async () => {
    await P.goto(BASE + '/odoo'); await P.waitForSelector('.ei-home .ei-top-tools'); await P.waitForTimeout(1800);
    await P.locator('.ei-stage').nth(3).hover(); await P.waitForTimeout(400);
    await shot(ceo, 'state-home-pipeline-tooltip', 'Home: pointing at a step of the contract-to-payment pipeline shows exactly what that step counts', { full: false });
    await P.mouse.move(5, 400);
    await P.locator('.ei-period select').selectOption('30d'); await P.waitForTimeout(1500);
    await shot(ceo, 'state-home-last-30-days', 'Home: the period set to "Last 30 days"; every card and its comparison re-read from the server', { full: false });
    await P.locator('.ei-period select').selectOption('14d'); await P.waitForTimeout(1200);
    const chart = P.locator('.ei-flow .ei-fchart').first(); await chart.scrollIntoViewIfNeeded(); const b = await chart.boundingBox();
    await P.mouse.move(b.x + b.width * 0.5, b.y + b.height * 0.5); await P.waitForTimeout(400);
    await shot(ceo, 'state-home-chart-hover', 'Home: hovering the Invoiced chart shows that day and its figure', { full: false });
    await P.locator('.ei-flow .ei-flow-table').first().click(); await P.waitForTimeout(400);
    await shot(ceo, 'state-home-table-view', 'Home: "Show as table" gives every chart a table with the same numbers', { full: false });
    await P.locator('.ei-flow .ei-flow-table').first().click();
  });
  await attempt('search', async () => {
    await P.goto(BASE + '/odoo'); await P.waitForSelector('.ei-home .ei-top-tools'); await P.waitForTimeout(1200);
    await P.locator('.ei-top input[type=search]').fill('Rehman'); await P.waitForSelector('.ei-search-hit', { timeout: 10000 }); await P.waitForTimeout(500);
    await shot(ceo, 'state-home-search-results', 'Home: the universal search (also Ctrl+K) finds customers, contracts, invoices and bank references in one list', { full: false });
  });
  await attempt('my work menu', async () => {
    await P.goto(BASE + '/odoo'); await P.waitForSelector('.ei-home .ei-top-tools'); await P.waitForTimeout(1200);
    const more = P.locator('.ei-task .ei-more').first(); await more.scrollIntoViewIfNeeded(); await more.click(); await P.waitForTimeout(400);
    await shot(ceo, 'state-home-work-menu', 'Home: a task in "What is stuck across the company" with its menu (put aside, assign, escalate)', { full: false });
    await P.keyboard.press('Escape'); await P.mouse.click(5, 500);
  });
  await attempt('top bar menus', async () => {
    await P.goto(BASE + '/odoo/action-' + (await menuTree(P)).find(m => /Old codes|Contracts/.test(m.path)).actionID); await P.waitForSelector('.o_list_view, .o_kanban_view'); await P.waitForTimeout(1000);
    await P.locator('.o_menu_sections .dropdown-toggle', { hasText: 'Money' }).click(); await shot(ceo, 'state-menu-money', 'Top bar: the Money menu opened (menus keep the plain labels)', { full: false });
    await P.keyboard.press('Escape');
    await P.locator('.o_user_menu').click(); await shot(ceo, 'state-menu-user', 'Top bar: the person menu', { full: false }); await P.keyboard.press('Escape');
    await P.locator('.o_searchview_dropdown_toggler').click(); await shot(ceo, 'state-list-filters', 'A list with its filter / group / favourites panel open', { full: false }); await P.keyboard.press('Escape');
    await P.locator('.o_searchview_input').click(); await P.keyboard.type('bank'); await P.waitForTimeout(600);
    await shot(ceo, 'state-list-search-typing', 'A list while typing in the search field', { full: false });
  });
  await attempt('ask', async () => {
    await P.goto(BASE + '/odoo/action-ei_assistant.action_ei_assistant'); await P.waitForSelector('.ei-ask .ei-ask-welcome');
    await shot(ceo, 'ask-welcome', 'Ask (read-only assistant): the welcome with suggested questions');
    await P.fill('#ei-ask-q', 'Who owes us money?'); await P.keyboard.press('Enter'); await P.waitForSelector('.ei-ask .ei-ask-bot', { timeout: 20000 }); await P.waitForTimeout(800);
    await shot(ceo, 'ask-answer', 'Ask: an answer with its figures, the sources it came from and how it was worked out');
  });
  await attempt('match', async () => {
    const bank = await open(browser, 'demo.bank');
    await bank.page.goto(BASE + '/odoo/action-ei_matching.action_ei_matching'); await bank.page.waitForSelector('.ei-mt .ei-mt-row', { timeout: 20000 });
    await shot(bank, 'match-queue', 'Match bank payments: the queue of bank lines (four tabs) before one is chosen', { full: false });
    await bank.page.locator('.ei-mt-row').first().click(); await bank.page.waitForTimeout(1500);
    await shot(bank, 'match-line-chosen', 'Match bank payments: three columns - the line, the decision (who paid, which invoices) and the evidence with the effect on the books', { full: false });
  });
  await attempt('party360', async () => {
    await P.goto(BASE + '/odoo/action-ei_party360.action_ei_party360'); await P.waitForSelector('.ei-p360');
    await shot(ceo, 'party360-empty', 'Customers & Suppliers (Party 360): the empty state tells what to type', { full: false });
    await P.focus('#ei-p360-q'); await P.keyboard.type('Rehman'); await P.waitForSelector('.ei-p360-opt'); await P.keyboard.press('Enter'); await P.waitForSelector('.ei-p360-party'); await P.waitForTimeout(1200);
    await shot(ceo, 'party360-party', 'Party 360 for one customer: every figure with its basis, the open items, the documents and the history on one page', { cap: 4200 });
    const link = P.locator('.ei-p360-kpi .ei-p360-link[aria-expanded]').first(); await link.scrollIntoViewIfNeeded(); await link.click(); await P.waitForTimeout(500);
    await shot(ceo, 'party360-explain', 'Party 360: "How is this worked out?" opened on a figure', { cap: 4200 });
  });
  await attempt('dialogs', async () => {
    await P.goto(BASE + '/odoo/action-ei_bank_operations.ei_bank_import_wizard_action'); await P.waitForSelector('.modal .modal-content'); await P.waitForTimeout(500);
    await shot(ceo, 'state-dialog-bank-import', 'A dialog (Import bank statement): rounded card, visible fields, Import and Cancel buttons', { full: false });
  });
  await attempt('pick-list', async () => {
    const adm = sessions['admin'], A = adm.page;        // the executive reads contracts; the administrator can start one
    await A.goto(BASE + '/odoo/action-ei_contract_da.ei_contract_action'); await A.waitForSelector('.o_kanban_record');
    await A.locator('.o_control_panel .btn', { hasText: 'New' }).first().click(); await A.waitForFunction(() => /^New$/.test(((document.querySelector('.o_last_breadcrumb_item') || {}).innerText || '').trim()));
    await A.waitForTimeout(700);
    await A.locator('.o_field_many2one input').first().click(); await A.keyboard.type('DEMO'); await A.waitForSelector('.o-autocomplete--dropdown-menu'); await A.waitForTimeout(500);
    await shot(adm, 'state-pick-list', 'A new contract with the "Parent company" pick-list open (type to search)', { full: false });
  });
  await attempt('reports', async () => {
    await P.goto(BASE + '/odoo/action-ei_reports.action_report_catalog'); await P.waitForSelector('.ei-rc-card'); await P.locator('.ei-rc-check input').check(); await P.waitForTimeout(400);
    await shot(ceo, 'reports-catalog', 'Reports: the catalog of every report asked for, with what it answers, how it is worked out and whether it is delivered, partly there, blocked or not built (a reason is given for each that is not ready)');
    await P.goto(BASE + '/odoo/action-ei_reports.action_report_ar_aging'); await P.waitForSelector('.o_graph_view canvas, .o_graph_renderer canvas'); await P.waitForTimeout(1500);
    await shot(ceo, 'reports-ar-chart', 'Aged receivables as a chart (how much is owed, by how late), with the table and list one click away', { full: false });
    await P.locator('.o_cp_switch_buttons button.o_pivot').click(); await P.waitForSelector('.o_pivot'); await P.waitForTimeout(800);
    await shot(ceo, 'reports-ar-pivot', 'Aged receivables as a pivot: customer by how-late band; totals equal the Home figure', { full: false });
    await P.locator('.o_cp_switch_buttons button.o_list').click(); await P.waitForSelector('.o_data_row'); await P.waitForTimeout(600);
    await shot(ceo, 'reports-ar-list', 'Aged receivables as a list ("view rows"): one row per open invoice, a row opens the invoice behind it', { full: false });
    await P.locator('thead .o_list_record_selector input').check(); await P.locator('.o_cp_action_menus button, .o_cp_action_menus .dropdown-toggle').first().click(); await P.waitForTimeout(500);
    await shot(ceo, 'reports-ar-actions', 'The report list with rows selected and the Actions menu open (Export is here for the roles allowed to export)', { full: false });
    await P.keyboard.press('Escape');
  });
  await attempt('record actions', async () => {
    await P.goto(BASE + '/odoo/action-ei_contract_da.ei_contract_action'); await P.waitForSelector('.o_kanban_record');
    await P.locator('.o_kanban_record').first().hover(); await P.waitForTimeout(500);
    await shot(ceo, 'state-cards-hover', 'Cards: the card under the pointer rises a little', { full: false });
  });

  }
  // ============================================================ 4 dark theme
  console.log('\n[4] dark');
  if (on('dark')) await attempt('dark', async () => {
    const d = await open(browser, 'demo.ceo', { scheme: 'dark' });
    const pg = d.page;
    await pg.goto(BASE + '/odoo'); await pg.waitForSelector('.ei-home .ei-top-tools'); await shot(d, 'dark-home-executive', 'Home (executive), dark theme', { cap: 5200 });
    const tree = await menuTree(pg);
    const pick = (re) => tree.find(m => re.test(m.path));
    for (const [re, name, label] of [[/Old codes/, 'dark-list', 'A list'], [/Contracts/, 'dark-cards', 'Cards']]) {
      const m = pick(re); if (!m) continue;
      await pg.goto(`${BASE}/odoo/action-${m.actionID}`); await pg.waitForSelector('.o_action_manager .o_action'); await shot(d, name, `${label} (${m.path}), dark theme`, { full: false });
    }
    const c = pick(/Contracts/);
    await pg.goto(`${BASE}/odoo/action-${c.actionID}`); await pg.waitForSelector('.o_kanban_record'); await pg.locator('.o_kanban_record').first().click(); await pg.waitForSelector('.o_form_sheet');
    await shot(d, 'dark-record', 'A contract record, dark theme');
    await pg.goto(BASE + '/odoo/action-ei_bank_operations.ei_bank_import_wizard_action'); await pg.waitForSelector('.modal .modal-content'); await shot(d, 'dark-dialog', 'A dialog, dark theme', { full: false });
    await pg.goto(BASE + '/odoo/action-ei_assistant.action_ei_assistant'); await pg.waitForSelector('.ei-ask'); await shot(d, 'dark-ask', 'Ask, dark theme', { full: false });
    await pg.goto(BASE + '/odoo/action-ei_party360.action_ei_party360'); await pg.waitForSelector('.ei-p360'); await pg.focus('#ei-p360-q'); await pg.keyboard.type('Rehman'); await pg.waitForSelector('.ei-p360-opt'); await pg.keyboard.press('Enter'); await pg.waitForSelector('.ei-p360-party'); await pg.waitForTimeout(1000);
    await shot(d, 'dark-party360', 'Party 360, dark theme', { cap: 4200 });
    await d.ctx.close();
  });

  // ============================================================ 5 a phone
  console.log('\n[5] phone');
  if (on('phone')) await attempt('phone', async () => {
    const ph = await open(browser, 'demo.ceo', { vp: [390, 844] });
    const pg = ph.page;
    await pg.goto(BASE + '/odoo'); await pg.waitForSelector('.ei-home .ei-top-tools'); await shot(ph, 'phone-home', 'Home on a phone (390px wide): one column, the same cards', { cap: 7000 });
    const tree = await menuTree(pg);
    const c = tree.find(m => /Contracts/.test(m.path)), l = tree.find(m => /Old codes/.test(m.path));
    await pg.goto(`${BASE}/odoo/action-${l.actionID}`); await pg.waitForSelector('.o_data_row'); await shot(ph, 'phone-list', 'A list on a phone', { full: false });
    await pg.goto(`${BASE}/odoo/action-${c.actionID}`); await pg.waitForSelector('.o_kanban_record'); await shot(ph, 'phone-cards', 'Cards on a phone', { full: false });
    await pg.locator('.o_kanban_record').first().click(); await pg.waitForSelector('.o_form_sheet'); await shot(ph, 'phone-record', 'A record on a phone', { cap: 4200 });
    await pg.goto(BASE + '/odoo/action-ei_assistant.action_ei_assistant'); await pg.waitForSelector('.ei-ask'); await shot(ph, 'phone-ask', 'Ask on a phone', { full: false });
    await pg.goto(BASE + '/odoo/action-ei_party360.action_ei_party360'); await pg.waitForSelector('.ei-p360'); await pg.focus('#ei-p360-q'); await pg.keyboard.type('Rehman'); await pg.waitForSelector('.ei-p360-opt'); await pg.keyboard.press('Enter'); await pg.waitForSelector('.ei-p360-party'); await pg.waitForTimeout(1000);
    await shot(ph, 'phone-party360', 'Party 360 on a phone (compact)', { cap: 5200 });
    await ph.ctx.close();
  });

  // ============================================================ 6 the sign-in page
  if (on('login')) await attempt('login', async () => {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } }); const page = await ctx.newPage();
    await page.goto(BASE + '/web/login'); await page.waitForSelector('input[name=login]'); await page.waitForTimeout(600);
    await page.screenshot({ path: path.join(OUT, 'login.png') });
    entries.push({ file: 'login.png', what: 'The sign-in page (Odoo\'s own, not restyled yet)', user: '-', scheme: 'light', size: '1440x900', note: '' });
    await ctx.close();
  });

  await browser.close();
  const merged = [...previous.filter(p => !entries.some(e => e.file === p.file)), ...entries];
  fs.writeFileSync(path.join(OUT, 'index.json'), JSON.stringify({ entries: merged, problems }, null, 1));
  console.log(`\n${entries.length} screenshots taken now (${merged.length} in the gallery), ${problems.length} problems`);
  problems.forEach(p => console.log('  - ' + p));
})().catch(e => { console.error(e); process.exit(2); });
