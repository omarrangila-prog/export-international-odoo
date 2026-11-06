// The first screen of Home leads with the figures and charts (the owner's decision, 6 Nov 2026). For the three roles that carry money
// (executive, finance manager, accountant) a laptop (1366x768) must show the tiles and both charts whole, and a phone (390x844) the tiles and
// the start of the chart. What needs a person is one press away: a button in the header says how much there is and goes straight to it.
// Money figures must never wrap onto two lines, and on a phone the secondary sections start folded.
const ROLES = [['demo.ceo', 'executive'], ['demo.finance', 'finance manager'], ['demo.accountant', 'accountant']];
const FIRST = '.ei-decide .ei-dalerts .ei-alert, .ei-decide .ei-dtask, .ei-decide .ei-allclear';

async function measure(p) {
  return p.evaluate((first) => {
    const rect = (e) => { const r = e.getBoundingClientRect(); return { top: Math.round(r.top), bottom: Math.round(r.bottom) }; };
    const sumEl = document.querySelector('.ei-sum-grid');
    const firstEl = [...document.querySelectorAll(first)].find((e) => e.offsetParent);
    const values = [...document.querySelectorAll('.ei-sum-value')].map((e) => ({ text: e.textContent.trim(), fits: e.scrollWidth <= e.clientWidth + 1, oneLine: e.getBoundingClientRect().height < parseFloat(getComputedStyle(e).fontSize) * 1.6 }));
    const cta = firstEl && firstEl.querySelector('.ei-alert-cta');
    const nav = document.querySelector('.ei-bn');
    const strip = document.querySelector('.ei-sum-grid'), tiles = [...document.querySelectorAll('.ei-sum')];
    return {
      navTop: nav ? Math.round(nav.getBoundingClientRect().top) : window.innerHeight,
      swipes: !!strip && strip.scrollWidth > strip.clientWidth + 1, peek: tiles.length > 1 && tiles[1].getBoundingClientRect().left < window.innerWidth - 12,
      sum: sumEl && rect(sumEl), first: firstEl && rect(firstEl), cta: cta && rect(cta), values,
      folds: [...document.querySelectorAll('.ei-foldbar')].map((e) => e.getAttribute('aria-expanded')),
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      heroShown: !!document.querySelector('.ei-hero-money'),
      pulse: (() => { const e = document.querySelector('.ei-pulse'); return e && rect(e); })(),
      plot: (() => { const e = document.querySelector('.ei-plot-area'); return e && rect(e); })(),
      attn: (() => { const e = document.querySelector('.ei-attn'); return e && rect(e); })(),
    };
  }, FIRST);
}

module.exports = {
  name: '14 Home first screen (figures and charts, one press to what needs a person, laptop and phone)',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    for (const [login, label] of ROLES) {
      // ---- laptop 1366x768
      let s = await new Session(ctx, browser, login, 'demo', [1366, 768], { timeout: 30000 }).start();
      let m = s.mark();
      await s.home();
      let r = await measure(s.page);
      ctx.check(!!r.sum && r.sum.bottom <= 768, `${label}: the summary strip is inside the first 1366x768 screen`, JSON.stringify(r.sum));
      ctx.check(!!r.pulse && r.pulse.bottom <= 768, `${label}: both charts are whole inside the first screen too`, JSON.stringify(r.pulse));
      ctx.check(!!r.attn && r.attn.bottom <= 768, `${label}: the button to what needs a person is on the first screen`, JSON.stringify(r.attn));
      await s.page.locator('.ei-attn').click(); await s.page.waitForTimeout(900);
      const seen = await measure(s.page);
      ctx.check(!!seen.first && seen.first.top >= 0 && seen.first.bottom <= 768, `${label}: and it brings the first alert or decision into view`, JSON.stringify(seen.first));
      await s.page.locator('.ei-home').evaluate((e) => e.scrollTo(0, 0));
      ctx.check(r.values.length >= 3 && r.values.every((v) => v.fits && v.oneLine), `${label}: every summary figure sits on one line (${r.values.length} figures)`, JSON.stringify(r.values.filter((v) => !v.fits || !v.oneLine)));
      ctx.check(r.overflow <= 0, `${label}: no sideways scroll at 1366`, String(r.overflow));
      ctx.check(r.folds.length === 0, `${label}: nothing is folded on a laptop`);
      await ctx.shot(s.page, `home_first_${login.split('.')[1]}_1366`);
      await s.clean(`${label}: the laptop first screen opens clean`, m);
      // 1280x720 and a 200%-zoom window (683 CSS px wide) keep the same promise
      for (const [w, h] of [[1280, 720], [683, 640]]) {
        await s.page.setViewportSize({ width: w, height: h }); await s.page.waitForTimeout(700);
        r = await measure(s.page);
        ctx.check(r.overflow <= 0 && r.values.every((v) => v.fits && v.oneLine), `${label}: ${w}px wide - no sideways scroll and figures stay on one line`, JSON.stringify({ overflow: r.overflow, bad: r.values.filter((v) => !v.fits || !v.oneLine) }));
      }
      await s.close();

      // ---- phone 390x844
      s = await new Session(ctx, browser, login, 'demo', [390, 844], { timeout: 30000 }).start();
      m = s.mark();
      await s.home();
      r = await measure(s.page);
      ctx.check(r.navTop < 844 && r.navTop >= 744, `${label}: the phone has its bottom bar`, String(r.navTop));
      ctx.check(!!r.plot && r.plot.top < r.navTop, `${label}: on a phone the chart starts on the first screen, above the bottom bar`, JSON.stringify(r.plot) + ' bar at ' + r.navTop);
      ctx.check(!!r.attn && r.attn.bottom <= r.navTop, `${label}: and so does the button to what needs a person`, JSON.stringify(r.attn));
      await s.page.locator('.ei-attn').click(); await s.page.waitForTimeout(900);
      const seenP = await measure(s.page);
      ctx.check(!!seenP.first && seenP.first.top >= 0 && seenP.first.bottom <= seenP.navTop, `${label}: it brings the first alert or decision into view`, JSON.stringify(seenP.first));
      ctx.check(!seenP.cta || seenP.cta.bottom <= seenP.navTop, `${label}: with its next-step button not cut off`, JSON.stringify(seenP.cta));
      await s.page.locator('.ei-home').evaluate((e) => e.scrollTo(0, 0));
      ctx.check(r.swipes && r.peek, `${label}: the figures are a swipe strip and the next one peeks out`, JSON.stringify({ swipes: r.swipes, peek: r.peek }));
      ctx.check(r.values.every((v) => v.fits && v.oneLine), `${label}: phone figures sit on one line`, JSON.stringify(r.values.filter((v) => !v.fits || !v.oneLine)));
      ctx.check(r.overflow <= 0, `${label}: no sideways scroll on a phone`, String(r.overflow));
      ctx.check(r.folds.length >= 3 && r.folds.every((x) => x === 'false') && !r.heroShown, `${label}: secondary sections start folded (${r.folds.length} bars)`, JSON.stringify(r.folds));
      // opening a fold shows its content and the bar says so
      const bar = s.page.locator('.ei-foldbar').first();
      await bar.click(); await s.page.waitForTimeout(500);
      ctx.check(await bar.getAttribute('aria-expanded') === 'true', `${label}: a fold bar opens when pressed`);
      // "All work" in the decisions block opens the folded list instead of doing nothing
      const all = s.page.locator('.ei-decide .ei-hcard-head .ei-link', { hasText: 'All work' });
      if (await all.count()) {
        await all.click(); await s.page.waitForTimeout(900);
        ctx.check(await s.page.locator('#ei-h-work').count() === 1, `${label}: "All work" opens the full list`);
      }
      await ctx.shot(s.page, `home_first_${login.split('.')[1]}_phone`);
      await s.clean(`${label}: the phone first screen opens clean`, m);
      await s.close();
    }
  },
};
