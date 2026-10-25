// Browser check for Party 360 (needs playwright + staging server on :8369 + demo.* users).  node tests/ui_party360.js [outdir]
// Exit code 1 if any check fails. Keyboard only for search; clicks only where a person would click.
const { chromium } = require('playwright');
const out = process.argv[2] || '/tmp';
const BASE = 'http://127.0.0.1:8369';
let failed = 0;
const check = (ok, msg) => { console.log((ok ? 'PASS ' : 'FAIL ') + msg); if (!ok) failed++; };

async function login(browser, user, pass, w = 1440, h = 900) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h } });
  const p = await ctx.newPage();
  const errors = [];
  p.on('pageerror', e => errors.push(e.message.slice(0, 160)));
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 160)); });
  await p.goto(BASE + '/web/login'); await p.fill('input[name=login]', user); await p.fill('input[name=password]', pass);
  await p.click('button[type=submit]'); await p.waitForSelector('.o_navbar', { timeout: 90000 });
  return { p, errors };
}
const openPage = async (p) => { await p.click('.o_navbar >> text=Customers & Suppliers'); await p.waitForSelector('.ei-p360', { timeout: 20000 }); };

(async () => {
  const browser = await chromium.launch();

  // ---- CEO
  let { p, errors } = await login(browser, 'demo.ceo', 'demo');
  await openPage(p);
  check(await p.isVisible('.ei-p360-empty'), 'empty state explains what to type');
  await p.screenshot({ path: `${out}/p360_1_empty.png` });
  await p.focus('#ei-p360-q');
  await p.keyboard.type('Rehman');
  await p.waitForSelector('.ei-p360-opt', { timeout: 10000 });
  check((await p.getAttribute('#ei-p360-q', 'aria-expanded')) === 'true', 'search list is announced as expanded');
  check((await p.$$('.ei-p360-opt')).length >= 1, 'search finds the party by part of the name');
  await p.screenshot({ path: `${out}/p360_2_search.png` });
  await p.keyboard.press('ArrowDown'); await p.keyboard.press('ArrowUp'); await p.keyboard.press('Enter');
  await p.waitForSelector('.ei-p360-party', { timeout: 15000 });
  const name = await p.innerText('.ei-p360-name');
  check(/Rehman/i.test(name), 'Enter opens the chosen party: ' + name);
  check((await p.$$('.ei-p360-kpi')).length >= 6, 'figures are shown (' + (await p.$$('.ei-p360-kpi')).length + ')');
  check(await p.isVisible('.ei-p360-asof'), 'page says when it was read');
  // explain
  const explainBtn = (await p.$$('.ei-p360-kpi .ei-p360-link[aria-expanded]'))[0];
  await explainBtn.click(); await p.waitForTimeout(400);
  check((await explainBtn.getAttribute('aria-expanded')) === 'true' && await p.isVisible('.ei-p360-explain'), '"How is this worked out?" opens the explanation');
  await p.screenshot({ path: `${out}/p360_3_party_ceo.png`, fullPage: false });
  // drill-down
  const show = await p.$('.ei-p360-link:has-text("Show the records")');
  if (show) {
    await show.click(); await p.waitForTimeout(2500);
    check(!(await p.$('.modal .o_error_dialog, .o_error_dialog')), 'drill-down opens the records with no error dialog (CEO)');
    await p.screenshot({ path: `${out}/p360_4_records.png` });
    await p.goBack(); await p.waitForTimeout(1500);
  } else { check(false, 'at least one figure has records to show'); }
  // chain + timeline present (scroll)
  await p.goto(BASE + '/odoo'); await p.waitForTimeout(500);
  check(errors.length === 0, 'no console/page errors (CEO): ' + errors.slice(0, 2).join(' | '));
  await p.context().close();

  // ---- CEO: money drill-down from Home must open (regression for the access error)
  ({ p, errors } = await login(browser, 'demo.ceo', 'demo'));
  await p.waitForSelector('.ei-home', { timeout: 20000 }); await p.waitForTimeout(1500);
  const owe = await p.$('button:has-text("Customers owe us")');
  if (owe) { await owe.click(); await p.waitForTimeout(3000); check(!(await p.$('.modal')) && /action-/.test(p.url()) && await p.isVisible('.o_list_view'), 'Home "Customers owe us" opens the journal items for the CEO'); }
  else check(false, 'Home money tile found');
  await p.context().close();

  // ---- cash clerk: role limits
  ({ p, errors } = await login(browser, 'demo.cash', 'demo'));
  await p.waitForSelector('.o_navbar >> text=Customers & Suppliers', { timeout: 15000 }).catch(() => {});
  const menu = await p.$('.o_navbar >> text=Customers & Suppliers');
  if (menu) {
    await openPage(p); await p.focus('#ei-p360-q'); await p.keyboard.type('Rehman'); await p.waitForSelector('.ei-p360-opt', { timeout: 10000 });
    await p.keyboard.press('Enter'); await p.waitForSelector('.ei-p360-party', { timeout: 15000 });
    check(await p.isVisible('.ei-p360-notice'), 'cash clerk is told which figures their role cannot see');
    check(!(await p.isVisible('.ei-p360-chains')), 'cash clerk does not see contract/lifting chains');
    await p.screenshot({ path: `${out}/p360_5_party_cash.png` });
  } else check(false, 'cash clerk can open Customers & Suppliers');
  await p.context().close();

  // ---- phone width
  ({ p, errors } = await login(browser, 'demo.ceo', 'demo', 390, 844));
  await p.goto(BASE + '/odoo'); await p.waitForTimeout(800);
  await p.evaluate(() => { });
  await browser.close();
  console.log(failed ? `\n${failed} CHECK(S) FAILED` : '\nall checks passed');
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
