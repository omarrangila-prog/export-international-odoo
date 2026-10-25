// Page-load timing on the staging site (demo-sized data - NOT a scale test). usage: node tests/ui_timing.js [runs]
const { chromium } = require('playwright');
const runs = +(process.argv[2] || 3);
const PAGES = { home: '/odoo', bank_lines: '/odoo/action-329', contracts: '/odoo/action-344', orders: '/odoo/action-352', lifting: '/odoo/action-354', parent: '/odoo/action-363' };
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
  await p.goto('http://127.0.0.1:8369/web/login'); await p.fill('input[name=login]', process.env.EI_LOGIN || 'admin'); await p.fill('input[name=password]', process.env.EI_PASS || 'admin');
  await p.click('button[type=submit]'); await p.waitForSelector('.o_navbar', { timeout: 90000 });
  for (const [name, url] of Object.entries(PAGES)) {
    const t = [];
    for (let i = 0; i < runs; i++) { const s = Date.now(); await p.goto('http://127.0.0.1:8369' + url); await p.waitForSelector('.o_list_view, .o_kanban_view, .o_form_view, .ei-home-inner, .ei-p360', { timeout: 30000 }).catch(() => {}); t.push(Date.now() - s); }
    t.sort((a, c) => a - c); console.log(name.padEnd(12), 'median', t[Math.floor(t.length / 2)], 'ms   all', t.join(','));
  }
  await b.close();
})();
