// UI smoke/screenshot script (needs playwright + a running staging server on :8369). usage: node tests/ui_smoke.js outdir w h name=actionid|home ...   env EI_LOGIN / EI_PASS
const { chromium } = require('playwright');
const [outdir, w, h, ...pairs] = process.argv.slice(2);
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: +w, height: +h } });
  const problems = [];
  p.on('pageerror', e => problems.push('pageerror: ' + e.message));
  p.on('console', m => { if (m.type() === 'error') problems.push('console: ' + m.text().slice(0, 160)); });
  await p.goto('http://127.0.0.1:8369/web/login');
  await p.fill('input[name=login]', process.env.EI_LOGIN || 'admin'); await p.fill('input[name=password]', process.env.EI_PASS || 'admin');
  await p.click('button[type=submit]');
  await p.waitForSelector('.o_navbar', { timeout: 40000 });
  for (const pr of pairs) {
    const [name, x] = pr.split('=');
    problems.length = 0;
    await p.goto(x === 'home' ? 'http://127.0.0.1:8369/odoo' : `http://127.0.0.1:8369/odoo/action-${x}`);
    await p.waitForTimeout(3000);
    if (name.includes('first')) { const r = await p.$('.o_data_row, .o_kanban_record'); if (r) { await r.click(); await p.waitForTimeout(2500); } }
    const dlg = await p.$('.o_error_dialog, .modal .o_dialog_error');
    await p.screenshot({ path: `${outdir}/${name}.png` });
    console.log((dlg || problems.length ? 'PROBLEM ' : 'ok ') + name, dlg ? (await dlg.innerText()).slice(0, 200).replace(/\n/g, ' ') : '', problems.slice(0, 2).join(' | '));
  }
  await b.close();
})();
