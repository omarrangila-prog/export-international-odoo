// The standard screens (lists, cards, records, dialogs, menus) share the Overview's language: a white rounded card on a soft page, soft
// shadow instead of hard borders, a gutter that lines up with the floating top bar, boxed fields you can see, pill steps, round buttons.
// Every check reads what the browser actually drew (computed styles, boxes, the mouse wheel), in light, dark and on a phone.
const lum = (rgb) => { const m = String(rgb).match(/\d+(\.\d+)?/g); if (!m) return 1; const [r, g, b] = m.slice(0, 3).map(Number).map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };

module.exports = {
  name: '11 standard screens share the Overview design (lists, cards, records, dialogs; light, dark, phone)',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const style = (p, sel, props) => p.evaluate(([sel, props]) => { const e = document.querySelector(sel); if (!e) return null; const cs = getComputedStyle(e); const r = e.getBoundingClientRect(); const o = { left: Math.round(r.left), top: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height) }; for (const k of props) o[k] = cs[k]; return o; }, [sel, props]);
    const radius = (s) => s ? parseFloat(s.borderTopLeftRadius) : 0;
    const contrast = async (s, sel, label) => {
      const v = await s.axe(sel, ['wcag2aa']);
      const bad = (v || []).filter(x => ['serious', 'critical'].includes(x.impact) && x.id === 'color-contrast');
      ctx.check(v !== null && !bad.length, `${label}: text colours have enough contrast (axe)`, bad.map(x => `${x.id}(${x.n}): ${x.first}`).join(' | '));
    };

    // ================= light, desktop
    const s = await new Session(ctx, browser, 'admin', 'admin', [1440, 900], { timeout: 20000 }).start();
    const p = s.page;
    let m = s.mark();

    // ---- 1 a list
    await s.goto('/odoo/action-ei_legacy_master.ei_legacy_code_action'); await p.waitForSelector('.o_data_row', { timeout: 25000 }); await p.waitForTimeout(700);
    const nav = await style(p, '.o_main_navbar', ['borderTopLeftRadius']);
    const card = await style(p, '.o_list_renderer', ['borderTopLeftRadius', 'boxShadow', 'backgroundColor']);
    ctx.check(radius(card) >= 16 && card.boxShadow !== 'none' && lum(card.backgroundColor) > 0.9, '1 a list is one white rounded card with a soft shadow', JSON.stringify(card));
    ctx.check(Math.abs(card.left - nav.left) <= 2, '1 and its left edge lines up with the floating top bar', `${card.left} vs ${nav.left}`);
    const th = await style(p, '.o_list_table thead th:nth-child(2)', ['textTransform', 'fontSize', 'fontWeight']);
    ctx.check(th.textTransform === 'none' && parseFloat(th.fontSize) >= 12 && parseInt(th.fontWeight) >= 600, '1 column titles are calm sentence case, not shouting capitals', JSON.stringify(th));
    const title = await style(p, '.o_control_panel .o_last_breadcrumb_item', ['fontSize', 'fontWeight']);
    const panel = await style(p, '.o_control_panel', ['backgroundColor', 'borderBottomWidth']);
    ctx.check(parseFloat(title.fontSize) >= 24 && parseInt(title.fontWeight) >= 700, '1 the page title is large and bold', JSON.stringify(title));
    ctx.check(panel.backgroundColor === 'rgba(0, 0, 0, 0)' && parseFloat(panel.borderBottomWidth) === 0, '1 the strip above the list is part of the page (no band, no rule)', JSON.stringify(panel));
    const pager = await style(p, '.o_pager .btn', ['borderTopLeftRadius', 'width', 'height']);
    ctx.check(pager && parseFloat(pager.borderTopLeftRadius) >= 16 && pager.width === pager.height, '1 the pager buttons are round', JSON.stringify(pager));
    const search = await style(p, '.o_cp_searchview', ['borderTopLeftRadius', 'boxShadow']);
    ctx.check(radius(search) >= 14 && search.boxShadow !== 'none', '1 the search field is one rounded card', JSON.stringify(search));
    await contrast(s, '.o_action_manager', '1 the list');
    // a person scrolls with the wheel; the window itself must not move
    await p.mouse.move(700, 500); for (let i = 0; i < 6; i++) { await p.mouse.wheel(0, 700); await p.waitForTimeout(80); }
    const scrolled = await p.evaluate(() => { const els = [...document.querySelectorAll('.o_action_manager *')].filter(e => e.scrollTop > 0); return { moved: els.length, win: scrollY, top: els[0] ? Math.round(els[0].scrollTop) : 0 }; });
    ctx.check(scrolled.moved >= 1 && scrolled.win === 0, '1 the list scrolls with the mouse wheel and the window stays put', JSON.stringify(scrolled));
    await s.clean('1 the list screen is clean', m);
    await ctx.shot(p, 'screens_list');

    // ---- 2 cards (kanban)
    m = s.mark();
    await s.goto('/odoo/action-ei_contract_da.ei_contract_action'); await p.waitForSelector('.o_kanban_record', { timeout: 25000 }); await p.waitForTimeout(700);
    const rec = await style(p, '.o_kanban_record', ['borderTopLeftRadius', 'boxShadow']);
    ctx.check(radius(rec) >= 16 && rec.boxShadow !== 'none', '2 a card is rounded with a soft shadow', JSON.stringify(rec));
    await p.locator('.o_kanban_record').first().hover(); await p.waitForTimeout(450);
    const lifted = await p.locator('.o_kanban_record').first().evaluate(e => getComputedStyle(e).transform);
    ctx.check(lifted !== 'none' && /matrix/.test(lifted) && parseFloat(lifted.split(',')[5]) < 0, '2 and rises a little under the pointer', lifted);
    await s.clean('2 the cards screen is clean', m);

    // ---- 3 a record (read) and a new record (edit)
    m = s.mark();
    await p.locator('.o_kanban_record').first().click(); await p.waitForSelector('.o_form_sheet', { timeout: 20000 }); await p.waitForTimeout(700);
    const sheet = await style(p, '.o_form_sheet', ['borderTopLeftRadius', 'boxShadow']);
    ctx.check(radius(sheet) >= 16 && sheet.boxShadow !== 'none' && Math.abs(sheet.left - nav.left) <= 2, '3 a record is a white rounded sheet, lined up with the top bar', JSON.stringify(sheet) + ` nav ${nav.left}`);
    const cur = await style(p, '.o_statusbar_status .o_arrow_button_current', ['backgroundColor', 'borderTopLeftRadius']);
    ctx.check(cur && radius(cur) >= 12 && lum(cur.backgroundColor) < 0.25, '3 the step a record is at is a filled pill', JSON.stringify(cur));
    const chat = await style(p, '.o-mail-ChatterContainer', ['borderTopLeftRadius', 'boxShadow']);
    ctx.check(chat && radius(chat) >= 16, '3 the conversation beside it is its own rounded card', JSON.stringify(chat));
    const hs = await p.evaluate(() => { const e = document.querySelector('.o_form_sheet_bg'); return { sw: e.scrollWidth, cw: e.clientWidth }; });
    ctx.check(hs.sw <= hs.cw + 1, '3 the record has no sideways scrollbar of its own', JSON.stringify(hs));
    ctx.check(await p.locator('.ei-chatter-toggle').count() === 1 && !(await p.locator('.o-mail-ChatterContainer').isVisible()) && /Show activity/.test(await p.locator('.ei-chatter-toggle').innerText()), '3 the record comes first: the activity panel is closed until opened, and a button says so');
    const w1 = (await style(p, '.o_form_sheet', [])).width;
    await p.locator('.ei-chatter-toggle').click(); await p.waitForTimeout(500);
    const w2 = (await style(p, '.o_form_sheet', [])).width;
    ctx.check(await p.locator('.o-mail-ChatterContainer').isVisible() && (await style(p, '.o-mail-ChatterContainer', [])).width <= 392 && w2 < w1 - 200, '3 opening it gives a narrow side panel and the record gives up only that much width', `sheet ${w1} -> ${w2}`);
    await p.reload(); await p.waitForSelector('.o_form_sheet', { timeout: 20000 }); await p.waitForTimeout(800);
    ctx.check(await p.locator('.o-mail-ChatterContainer').isVisible(), '3 the choice is remembered when the page is opened again');
    await p.locator('.ei-chatter-toggle').click(); await p.waitForTimeout(400);
    ctx.check(!(await p.locator('.o-mail-ChatterContainer').isVisible()), '3 and the button closes it again');
    await contrast(s, '.o_action_manager', '3 the record');
    await ctx.shot(p, 'screens_form');
    await p.locator('.o_control_panel .btn', { hasText: 'New' }).first().click(); await p.waitForFunction(() => /^New$/.test((document.querySelector('.o_last_breadcrumb_item') || {}).innerText && document.querySelector('.o_last_breadcrumb_item').innerText.trim()), null, { timeout: 15000 }); await p.waitForSelector('.o_form_sheet .o_field_widget input', { timeout: 15000 }); await p.waitForTimeout(700);
    const box = await p.evaluate(() => { const e = [...document.querySelectorAll('.o_form_sheet .o_field_widget:not(.o_readonly_modifier) input:not([type=checkbox])')].find(i => i.offsetParent); if (!e) return null; const cs = getComputedStyle(e); return { border: cs.borderTopWidth + ' ' + cs.borderTopStyle, radius: parseFloat(cs.borderTopLeftRadius), h: Math.round(e.getBoundingClientRect().height) }; });
    ctx.check(box && box.border === '1px solid' && box.radius >= 10 && box.h >= 38, '3 an empty field is a visible box, so a person can see where to type', JSON.stringify(box));
    await p.locator('.o_field_many2one input').first().click(); await p.keyboard.type('DEMO'); await p.waitForSelector('.o-autocomplete--dropdown-menu', { timeout: 8000 }).catch(() => {});
    const dd = await style(p, '.o-autocomplete--dropdown-menu', ['borderTopLeftRadius', 'boxShadow']);
    ctx.check(dd && radius(dd) >= 12 && dd.boxShadow !== 'none', '3 a pick-list is a rounded floating card', JSON.stringify(dd));
    await p.keyboard.press('Escape');
    await p.locator('.o_form_sheet .o_field_widget:not(.o_readonly_modifier) input:not([type=checkbox])').nth(1).focus(); await p.waitForTimeout(250);
    const ring = await p.evaluate(() => getComputedStyle(document.activeElement).boxShadow);
    ctx.check(ring && ring !== 'none', '3 the field you are in shows a focus ring', ring);
    await s.discard(m); // leaving a half-made record is fine here

    // ---- 4 a dialog
    m = s.mark();
    await p.goto(ctx.base + '/odoo/action-ei_bank_operations.ei_bank_import_wizard_action'); await p.waitForSelector('.modal .modal-content', { timeout: 25000 }); await p.waitForTimeout(700);
    const mod = await style(p, '.modal-content', ['borderTopLeftRadius', 'boxShadow', 'backgroundColor']);
    ctx.check(radius(mod) >= 18 && mod.boxShadow !== 'none' && lum(mod.backgroundColor) > 0.9, '4 a dialog is a white rounded card that floats', JSON.stringify(mod));
    const mt = await style(p, '.modal-title', ['fontSize', 'fontWeight']);
    ctx.check(parseFloat(mt.fontSize) >= 19 && parseInt(mt.fontWeight) >= 700, '4 with a clear title', JSON.stringify(mt));
    const inputs = await p.evaluate(() => [...document.querySelectorAll('.modal .o_field_widget:not(.o_readonly_modifier) :is(input, select, textarea):not([type=file]):not([type=checkbox])')].filter(e => e.offsetParent).map(e => { const cs = getComputedStyle(e); return cs.borderTopWidth + ' ' + cs.borderTopStyle; }));
    ctx.check(inputs.length >= 2 && inputs.every(b => b === '1px solid'), '4 every field in it is a visible box (the journal used to be an invisible gap)', inputs.join(', '));
    const cancel = await style(p, '.modal-footer .btn-secondary', ['borderTopWidth', 'borderTopLeftRadius']);
    ctx.check(cancel && parseFloat(cancel.borderTopWidth) >= 1 && radius(cancel) >= 10, '4 Cancel is a visible rounded button, not white on white', JSON.stringify(cancel));
    await contrast(s, '.modal-content', '4 the dialog');
    await ctx.shot(p, 'screens_dialog');
    await s.discard(m);
    await s.close();

    // ================= the data grid, second pass
    const g = await new Session(ctx, browser, 'admin', 'admin', [1280, 800], { timeout: 25000 }).start();
    const gp = g.page; m = g.mark();
    await g.goto('/odoo/action-ei_legacy_master.ei_legacy_code_action'); await gp.waitForSelector('.o_data_row', { timeout: 25000 }); await gp.waitForTimeout(800);
    const cut = await gp.evaluate(() => [...document.querySelectorAll('thead th .text-truncate')].filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.innerText));
    ctx.check(!cut.length, '7 no column title is cut off ("Approved u..." now wraps onto a second line)', cut.join(' | '));
    const chip = await gp.evaluate(() => { const b = document.querySelector('.o_list_table .badge'); if (!b) return null; const a = getComputedStyle(b, '::before'); return { content: a.content, w: a.width }; });
    ctx.check(chip && chip.content !== 'none' && chip.w === '7px', '7 a status chip carries a dot as well as its word', JSON.stringify(chip));
    const rowH = async () => gp.evaluate(() => Math.round(document.querySelectorAll('.o_data_row')[3].getBoundingClientRect().height));
    const comfy = await rowH();
    await gp.locator('.ei-density-toggle').click(); await gp.waitForTimeout(300);
    const compact = await rowH();
    ctx.check(comfy - compact >= 10 && /Comfortable/.test(await gp.locator('.ei-density-toggle').innerText()), '7 the density switch makes rows compact, so more of the list fits on the screen', `${comfy}px -> ${compact}px`);
    await gp.reload(); await gp.waitForSelector('.o_data_row', { timeout: 20000 }); await gp.waitForTimeout(600);
    ctx.check(await rowH() === compact, '7 and the choice is remembered');
    await gp.locator('.ei-density-toggle').click();
    await gp.setViewportSize({ width: 1024, height: 768 }); await gp.waitForTimeout(500);
    const sticky = await gp.evaluate(async () => {
      const r = document.querySelector('.o_list_renderer'); const first = () => document.querySelector('.o_data_row td:nth-child(2)').getBoundingClientRect().left;
      const before = first(); r.scrollLeft = 400; await new Promise(res => setTimeout(res, 200)); return { before: Math.round(before), after: Math.round(first()), scrolled: r.scrollLeft > 0 };
    });
    ctx.check(!sticky.scrolled || Math.abs(sticky.after - sticky.before) <= 2, '7 the identifying column stays in view when a wide list scrolls sideways', JSON.stringify(sticky));
    await g.goto('/odoo/action-ei_reports.action_report_ar_aging'); await gp.waitForSelector('.o_cp_switch_buttons', { timeout: 25000 });
    await gp.locator('.o_cp_switch_buttons button.o_list').click(); await gp.waitForSelector('.o_data_row', { timeout: 15000 });
    const fig = await gp.evaluate(() => { const td = document.querySelector('.o_data_row td.o_list_number, .o_data_row td.o_monetary_cell'); if (!td) return null; const cs = getComputedStyle(td); return { align: cs.textAlign, nums: cs.fontVariantNumeric }; });
    ctx.check(fig && /end|right/.test(fig.align) && /tabular/.test(fig.nums), '7 figures are right-aligned with tabular digits', JSON.stringify(fig));
    await g.clean('7 the grid screens are clean', m);
    await g.close();

    // ================= a record on a phone, and a record header that stays
    const rp = await new Session(ctx, browser, 'admin', 'admin', [390, 844], { timeout: 25000 }).start();
    const q2 = rp.page; m = rp.mark();
    await rp.goto('/odoo/action-ei_contract_da.ei_contract_action'); await q2.waitForSelector('.o_kanban_record', { timeout: 25000 });
    await q2.locator('.o_kanban_record').first().click(); await q2.waitForSelector('.o_form_sheet', { timeout: 20000 }); await q2.waitForTimeout(900);
    const emptyShown = await q2.evaluate(() => [...document.querySelectorAll('.o_form_view .o_form_label_empty')].filter(l => l.offsetParent !== null).length);
    ctx.check(emptyShown === 0, '8 on a phone the empty read-only rows are not listed', `${emptyShown} still shown`);
    const cards = await q2.evaluate(() => { const tr = document.querySelector('.o_field_x2many .o_data_row'); if (!tr) return null; const td = tr.querySelector('td[data-label]'); return { display: getComputedStyle(tr).display, labelled: !!td, label: td && td.dataset.label, before: td && getComputedStyle(td, '::before').content }; });
    ctx.check(cards && cards.display === 'block' && cards.labelled && cards.before !== 'none', '8 the line items are cards, each value captioned with its column title', JSON.stringify(cards));
    const lay2 = await rp.layout();
    ctx.check(!lay2.overflow && !lay2.wide.length && !lay2.clipped.length, '8 the phone record has no sideways scrolling and nothing clipped', JSON.stringify(lay2.wide.concat(lay2.clipped)));
    const stick = await q2.evaluate(async () => {
      const sc = document.querySelector('.o_form_sheet_bg'); const bar = document.querySelector('.o_form_sheet_bg > .o_form_statusbar');
      sc.scrollTop = 300; await new Promise(r => setTimeout(r, 250)); const a = bar.getBoundingClientRect().top, c = sc.getBoundingClientRect().top; return { moved: sc.scrollTop, gap: Math.round(a - c) };
    });
    ctx.check(stick.moved === 0 || stick.gap <= 2, '8 the record header (steps and actions) stays in view while the record scrolls', JSON.stringify(stick));
    const btn = await q2.evaluate(() => [...document.querySelectorAll('.o_form_statusbar .o_statusbar_buttons .btn')].filter(b => b.offsetParent).map(b => Math.round(b.getBoundingClientRect().height)));
    ctx.check(btn.length === 0 || btn.every(h => h >= 40), '8 the action buttons are touch-sized', btn.join(','));
    await rp.clean('8 the phone record is clean', m);
    await ctx.shot(q2, 'screens_phone_record_compact');
    await rp.close();

    // ================= the sign-in page and the environment badge
    {
      const lc = await browser.newContext({ viewport: { width: 1440, height: 900 } }); const lpage = await lc.newPage();
      await lpage.goto(ctx.base + '/web/login'); await lpage.waitForSelector('input[name=login]', { timeout: 30000 }); await lpage.waitForTimeout(500);
      const look = await lpage.evaluate(() => { const card = document.querySelector('.card.o_database_list'); const btn = document.querySelector('.oe_login_form .btn-primary'); const env = document.querySelector('.ei-login-env'); return { radius: parseFloat(getComputedStyle(card).borderTopLeftRadius), btn: getComputedStyle(btn).backgroundColor, brand: !!document.querySelector('.ei-login-brand'), env: env ? env.innerText : '', form: !!document.querySelector('form.oe_login_form'), reset: [...document.querySelectorAll('a')].some(a => /Reset Password/i.test(a.innerText)) }; });
      ctx.check(look.brand && look.radius >= 18 && look.btn === 'rgb(29, 78, 216)', '9 the sign-in page carries the brand and the blue action of the application', JSON.stringify(look));
      ctx.check(/STAGING|DEMO/i.test(look.env), '9 and says which system it is, so live and staging are never confused', look.env);
      ctx.check(look.form && look.reset, '9 Odoo\'s own form and password recovery are untouched');
      await lpage.setViewportSize({ width: 390, height: 844 });
      const ov = await lpage.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
      ctx.check(!ov, '9 the sign-in page fits a phone');
      await lc.close();
      const sb = await new Session(ctx, browser, 'admin', 'admin', [1440, 900], { timeout: 25000 }).start();
      ctx.check(await sb.page.locator('.o_main_navbar .ei-env-badge').count() === 1 && /STAGING|DEMO/i.test(await sb.page.locator('.ei-env-badge').innerText()), '9 the top bar wears an environment badge when this is not the live system', await sb.page.locator('.ei-env-badge').count() ? await sb.page.locator('.ei-env-badge').innerText() : 'none');
      await sb.close();
    }

    // ================= dark
    const dk = await new Session(ctx, browser, 'admin', 'admin', [1440, 900], { cookies: [{ name: 'color_scheme', value: 'dark', path: '/' }], timeout: 20000 }).start();
    const d = dk.page; m = dk.mark();
    await dk.goto('/odoo/action-ei_legacy_master.ei_legacy_code_action'); await d.waitForSelector('.o_data_row', { timeout: 25000 }); await d.waitForTimeout(700);
    const dcard = await style(d, '.o_list_renderer', ['borderTopLeftRadius', 'backgroundColor']);
    const dpanel = await style(d, '.o_control_panel', ['backgroundColor']);
    ctx.check(radius(dcard) >= 16 && lum(dcard.backgroundColor) < 0.05, '5 dark: the list is the same rounded card, on a dark surface', JSON.stringify(dcard));
    ctx.check(dpanel.backgroundColor === 'rgba(0, 0, 0, 0)', '5 dark: the strip above it is part of the page', JSON.stringify(dpanel));
    const dnav = await style(d, '.o_main_navbar', ['backgroundColor']);
    ctx.check(lum(dnav.backgroundColor) < 0.05, '5 dark: the floating top bar is a dark card', JSON.stringify(dnav));
    await contrast(dk, '.o_action_manager', '5 dark list');
    await dk.goto('/odoo/action-ei_contract_da.ei_contract_action'); await d.waitForSelector('.o_kanban_record', { timeout: 25000 });
    await d.locator('.o_kanban_record').first().click(); await d.waitForSelector('.o_form_sheet', { timeout: 20000 }); await d.waitForTimeout(600);
    const dsheet = await style(d, '.o_form_sheet', ['backgroundColor']);
    ctx.check(lum(dsheet.backgroundColor) < 0.05, '5 dark: a record is a dark sheet', JSON.stringify(dsheet));
    const tile = await d.evaluate(() => { const b = document.querySelector('.o_cp_action_menus button'); if (!b) return null; const a = getComputedStyle(b, '::before'); return { disc: a.backgroundColor, bg: getComputedStyle(b).backgroundColor }; });
    ctx.check(tile && (lum(tile.disc) < 0.05 || tile.disc === 'rgba(0, 0, 0, 0)') && lum(tile.bg) < 0.05, '5 dark: the small buttons by the title have no white disc behind them', JSON.stringify(tile));
    await dk.clean('5 the dark screens are clean', m);
    await ctx.shot(d, 'screens_form_dark');
    await dk.close();

    // ================= phone
    const ph = await new Session(ctx, browser, 'admin', 'admin', [390, 844], { timeout: 20000 }).start();
    const q = ph.page;
    for (const [url, wait, label] of [['/odoo/action-ei_legacy_master.ei_legacy_code_action', '.o_data_row', 'list'], ['/odoo/action-ei_contract_da.ei_contract_action', '.o_kanban_record', 'cards']]) {
      await ph.goto(url); await q.waitForSelector(wait, { timeout: 25000 }); await q.waitForTimeout(600);
      const l = await ph.layout();
      ctx.check(!l.overflow && !l.wide.length, `6 phone ${label}: no horizontal overflow`, JSON.stringify(l.wide));
    }
    await q.locator('.o_kanban_record').first().click(); await q.waitForSelector('.o_form_sheet', { timeout: 20000 }); await q.waitForTimeout(600);
    const lf = await ph.layout();
    ctx.check(!lf.overflow && !lf.wide.length && !lf.clipped.length, '6 phone record: no horizontal overflow or clipped buttons', JSON.stringify(lf));
    await ctx.shot(q, 'screens_form_phone');
    await ph.close();
  },
};
