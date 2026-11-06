// The theme choice through real page loads, one browser per person, and the head of the app on a phone. Screenshots are kept as evidence.
const PHONE = [390, 844];
const HOME = '/odoo/action-ei_ui_theme.action_ei_home';
const colour = (p) => p.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--ei-bg').trim().toUpperCase());
const bar = (p) => p.evaluate(() => [...document.querySelectorAll('meta[name=theme-color]')].map((m) => m.content).join(','));

module.exports = {
  name: '19 theme and phone head (dark and light through navigation and refresh, each browser on its own)',
  async run(ctx, browser) {
    const { Session } = require('../lib');
    const a = await new Session(ctx, browser, 'demo.finance', 'demo', [1366, 768], { timeout: 30000 }).start();
    const b = await new Session(ctx, browser, 'demo.ceo', 'demo', [1366, 768], { timeout: 30000 }).start();
    const url = new URL(ctx.base);
    await a.bctx.addCookies([{ name: 'color_scheme', value: 'dark', domain: url.hostname, path: '/' }]);
    await a.goto(HOME); await a.page.waitForSelector('.ei-home-inner', { timeout: 30000 });
    ctx.check(await colour(a.page) === '#0E1626', '1 dark cookie: dark colours are applied', await colour(a.page));
    ctx.check(await bar(a.page) === '#0E1626', '1 dark cookie: the browser bar colour follows', await bar(a.page));
    await ctx.shot(a.page, 'theme_dark_desktop');
    await a.goto('/odoo/action-ei_close.ei_recon_centre_action'); await a.page.waitForSelector('.ei-rx-card', { timeout: 30000 });
    ctx.check(await colour(a.page) === '#0E1626', '2 dark stays after moving to another screen');
    await a.page.reload(); await a.page.waitForSelector('.ei-rx-card', { timeout: 30000 });
    ctx.check(await colour(a.page) === '#0E1626', '2 dark stays after a refresh');
    await b.goto(HOME); await b.page.waitForSelector('.ei-home-inner', { timeout: 30000 });
    ctx.check(await colour(b.page) === '#F4F6FA', '3 another person in another browser stays light', await colour(b.page));
    await a.bctx.addCookies([{ name: 'color_scheme', value: 'light', domain: url.hostname, path: '/' }]);
    await a.page.reload(); await a.page.waitForSelector('.ei-rx-card', { timeout: 30000 });
    ctx.check(await colour(a.page) === '#F4F6FA' && await bar(a.page) === '#F4F6FA', '4 choosing light comes back after a refresh');
    await a.close(); await b.close();

    const anon = await browser.newContext({ viewport: { width: PHONE[0], height: PHONE[1] }, hasTouch: true });
    const page = await anon.newPage();
    await page.goto(`${ctx.base}/web/login`); await page.waitForSelector('input[name=login]');
    ctx.check(await bar(page) === '#F4F6FA', '5 sign-in page on a phone: one theme colour, ours', await bar(page));
    ctx.check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), '5 sign-in page fits the phone');
    await ctx.shot(page, 'phone_sign_in');
    await anon.close();
    for (const scheme of ['light', 'dark']) {
      const s = await new Session(ctx, browser, 'demo.ceo', 'demo', PHONE, { timeout: 30000 }).start();
      await s.bctx.addCookies([{ name: 'color_scheme', value: scheme, domain: url.hostname, path: '/' }]);
      await s.goto(HOME); await s.page.waitForSelector('.ei-home-inner', { timeout: 30000 }); await s.page.waitForSelector('.ei-bn');
      const lay = await s.layout();
      ctx.check(!lay.overflow && !lay.wide.length, `6 phone, ${scheme}: Home fits and the bottom bar is there`, JSON.stringify(lay));
      await ctx.shot(s.page, `phone_home_${scheme}`);
      await s.close();
    }
  },
};
