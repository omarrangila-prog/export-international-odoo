// Shared helpers for the real-browser end-to-end suite (Playwright + axe-core, headless Chromium).
// A check that cannot fail proves nothing: every spec asserts on what the user actually sees.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const VIEWPORTS = [[375, 812], [390, 844], [768, 1024], [1024, 768], [1440, 900], [1920, 1080]];
const AXE = (() => { try { return fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8'); } catch { return null; } })();

class Ctx {
  constructor(base, outDir) { this.base = base; this.outDir = outDir; this.rows = []; this.spec = ''; fs.mkdirSync(outDir, { recursive: true }); }
  check(ok, msg, detail) { this.rows.push({ spec: this.spec, status: ok ? 'PASS' : 'FAIL', msg, detail: detail || '' }); console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${msg}${!ok && detail ? '  -> ' + detail : ''}`); return ok; }
  skip(msg) { this.rows.push({ spec: this.spec, status: 'SKIP', msg, detail: '' }); console.log(`  SKIP  ${msg}`); }
  shot(page, name) { return page.screenshot({ path: path.join(this.outDir, name + '.png') }); }
  get failed() { return this.rows.filter(r => r.status === 'FAIL').length; }
}

// ---- one signed-in browser context that remembers every console / page / server error
class Session {
  constructor(ctx, browser, user, pass, vp = [1440, 900], opts = {}) { Object.assign(this, { ctx, browser, user, pass, vp, opts, problems: [] }); }
  async start() {
    const [w, h] = this.vp;
    this.bctx = await this.browser.newContext({ viewport: { width: w, height: h }, locale: this.opts.locale || 'en-US', colorScheme: 'light' });
    if (this.opts.cookies) await this.bctx.addCookies(this.opts.cookies.map(c => ({ name: c.name, value: c.value, url: this.ctx.base })));
    const p = this.page = await this.bctx.newPage();
    p.setDefaultTimeout(this.opts.timeout || 10000);
    p.on('pageerror', e => this.problems.push({ kind: 'pageerror', text: e.message.slice(0, 200) }));
    p.on('console', m => { if (m.type() === 'error') this.problems.push({ kind: 'console', text: m.text().slice(0, 200) }); });
    p.on('response', async r => {
      const u = r.url();
      if (r.status() >= 500) this.problems.push({ kind: 'http' + r.status(), text: u.slice(-90) });
      else if (/call_kw|\/web\/action\/load|web_search_read|web_read/.test(u) && r.status() === 200) {
        try { const j = await r.json(); if (j && j.error) this.problems.push({ kind: 'rpc', text: ((j.error.data && j.error.data.message) || j.error.message || '').slice(0, 160) + ' @' + u.slice(-50) }); } catch { /* not json */ }
      }
    });
    await p.goto(this.ctx.base + '/web/login');
    await p.fill('input[name=login]', this.user); await p.fill('input[name=password]', this.pass);
    await p.click('button[type=submit]');
    await p.waitForSelector('.o_navbar', { timeout: 90000 });
    await p.waitForTimeout(1200);
    return this;
  }
  mark() { return this.problems.length; }
  // forget problems recorded since mark(): for errors the test provokes on purpose (a refused action is not a defect)
  discard(i) { this.problems.splice(i); }
  // call a model method as the signed-in user (arrangement and assertions on real data)
  async rpc(model, method, args = [], kwargs = {}) {
    const r = await this.bctx.request.post(`${this.ctx.base}/web/dataset/call_kw/${model}/${method}`, { data: { jsonrpc: '2.0', method: 'call', params: { model, method, args, kwargs } } });
    const j = await r.json();
    if (j.error) throw new Error((j.error.data && j.error.data.message) || j.error.message);
    return j.result;
  }
  since(i) { return this.problems.slice(i); }
  async dialog() { const d = await this.page.$('.modal .o_error_dialog, .o_error_dialog, .modal:has-text("Something went wrong")'); return d ? (await d.innerText()).replace(/\s+/g, ' ').slice(0, 160) : null; }
  // assert nothing went wrong since mark(): no error dialog, no console/page/server/RPC error
  async clean(label, since) {
    const dlg = await this.dialog(); const errs = this.since(since || 0);
    return this.ctx.check(!dlg && !errs.length, label, dlg ? `dialog: ${dlg}` : errs.map(e => `${e.kind}: ${e.text}`).slice(0, 2).join(' | '));
  }
  async goto(p) { await this.page.goto(this.ctx.base + p); await this.page.waitForTimeout(900); }
  async home() { await this.page.goto(this.ctx.base + '/odoo'); await this.page.waitForSelector('.ei-home .ei-top-tools, .ei-home .ei-banner-bad', { timeout: 30000 }); await this.page.waitForTimeout(600); }
  // scroll the way a person does, with the mouse wheel. (scrollIntoViewIfNeeded scrolls a container the user cannot reach, which
  // hid for weeks that Odoo's "overflow: hidden" action wrapper stopped the Home and Party 360 from scrolling at all)
  async wheelScroll(root) {
    const p = this.page; const vp = p.viewportSize();
    await p.mouse.move(vp.width / 2, vp.height / 2);
    for (let i = 0; i < 40; i++) { await p.mouse.wheel(0, 900); await p.waitForTimeout(50); }
    await p.waitForTimeout(250);
    return p.evaluate((sel) => {
      const el = document.querySelector(sel); const cs = getComputedStyle(el);
      return { top: Math.round(el.scrollTop), max: Math.round(el.scrollHeight - el.clientHeight), win: Math.round(scrollY), overflowY: cs.overflowY, scrollbarWidth: cs.scrollbarWidth };
    }, root);
  }
  // top bar -> (optional) dropdown item, by visible text, like a person would
  async menu(top, item) {
    const p = this.page;
    const entry = p.locator('.o_menu_sections .dropdown-toggle:not(.d-none), .o_menu_sections .o_nav_entry', { hasText: top }).first();
    if (await entry.count() && await entry.isVisible()) {
      await entry.click();
    } else {                                   // squeezed into the "+" overflow menu on narrower screens
      await p.locator('.o_menu_sections_more').click();             // the overflow list already shows the section's items
      await p.locator('.o-dropdown--menu, .dropdown-menu').getByText(item || top, { exact: true }).first().click();
      await p.waitForTimeout(1200);
      return;
    }
    if (item) await p.locator('.o-dropdown--menu, .dropdown-menu').getByText(item, { exact: true }).first().click();
    await p.waitForTimeout(1200);
  }
  async button(text) { await this.page.locator('button:visible', { hasText: text }).first().click(); await this.page.waitForTimeout(1500); }
  async firstRow(text) {
    const rows = this.page.locator('.o_data_row, .o_kanban_record:not(.o_kanban_ghost)');
    const row = text ? rows.filter({ hasText: text }).first() : rows.first();
    await row.click(); await this.page.waitForTimeout(1500);
  }
  async url() { return this.page.url(); }
  // ---- layout audit: page overflow, content past the viewport edge, clipped badges/buttons
  async layout() {
    return this.page.evaluate(() => {
      const vw = window.innerWidth, out = { overflow: document.documentElement.scrollWidth > vw + 1, wide: [], clipped: [] };
      const sig = el => (el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '') + ' "' + (el.innerText || '').trim().slice(0, 24) + '"');
      const scrollable = el => { for (let p = el.parentElement; p; p = p.parentElement) { const cs = getComputedStyle(p); if (/(auto|scroll)/.test(cs.overflowX) && p.scrollWidth > p.clientWidth) return true; } return false; };
      for (const el of document.querySelectorAll('.o_action_manager *, .o_navbar *')) {
        if (out.wide.length >= 5) break;
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.right > vw + 1 && getComputedStyle(el).visibility !== 'hidden' && el.offsetParent && !scrollable(el)) out.wide.push(sig(el));
      }
      for (const el of document.querySelectorAll('.badge, .o_field_badge, .ei-pill, .ei-chip, .btn, button')) {
        if (out.clipped.length >= 5) break;
        const cs = getComputedStyle(el);
        if (el.offsetParent && el.scrollWidth > el.clientWidth + 1 && /hidden|clip/.test(cs.overflowX) && el.innerText.trim()) out.clipped.push(sig(el));
      }
      return out;
    });
  }
  async axe(selector, tags = ['wcag2a', 'wcag2aa']) {
    if (!AXE) return null;
    await this.page.evaluate(src => { if (!window.axe) { const s = document.createElement('script'); s.textContent = src; document.head.appendChild(s); } }, AXE);
    return this.page.evaluate(async ([sel, tags]) => {
      const r = await window.axe.run(sel ? document.querySelector(sel) : document, { runOnly: { type: 'tag', values: tags } });
      return r.violations.map(v => ({ id: v.id, impact: v.impact, n: v.nodes.length, help: v.help, first: (v.nodes[0] && v.nodes[0].target.join(' ')) || '' }));
    }, [selector || null, tags]);
  }
  // Odoo swallows a stylesheet compile error and shows an unstyled app; read each bundle and report the error text, if any
  async cssErrors() {
    return this.page.evaluate(async () => {
      const out = [];
      for (const l of document.querySelectorAll('link[rel=stylesheet]')) {
        const t = await (await fetch(l.href)).text();
        const m = t.match(/css_error_message[\s\S]{0,260}/);
        if (m) out.push(l.href.split('/').pop() + ': ' + m[0].replace(/\\A/g, ' ').slice(0, 220));
      }
      return out;
    });
  }
  async close() { await this.bctx.close(); }
}

async function launch() { return chromium.launch(); }
module.exports = { Ctx, Session, launch, VIEWPORTS };
