const { chromium } = require('playwright-core');
const BASE = process.argv[2];
const ROUTES = ['home','cerebro','noticias','coleccion','mercado','broker','duelos','competicion','rivales','supervision','laboratorio','bot'];
(async () => {
  const b = await chromium.launch({ channel: 'chrome' });
  const ctx = await b.newContext({ viewport: { width: 1600, height: 1000 } });
  const p = await ctx.newPage();
  const errs = [], outside = [], writes = [], bad = [];
  p.on('pageerror', e => errs.push('pageerror ' + String(e).slice(0, 160)));
  p.on('console', m => { if (m.type() === 'error') errs.push('console ' + m.text().slice(0, 160)); });
  p.on('request', r => { const u = new URL(r.url()); if (u.origin !== new URL(BASE).origin && !/fonts\.(googleapis|gstatic)\.com$/.test(u.hostname)) outside.push(r.url()); if (r.method() !== 'GET') writes.push(r.method() + ' ' + r.url()); });
  p.on('response', r => { if (r.status() >= 400) bad.push(r.status() + ' ' + r.url().slice(-80)); });
  await p.goto(BASE + '#home', { waitUntil: 'networkidle' });
  const out = {};
  for (const r of ROUTES) {
    await p.evaluate((h) => { location.hash = '#' + h; }, r);
    await p.waitForTimeout(r === 'rivales' || r === 'competicion' ? 6000 : 3500);
    out[r] = await p.evaluate(() => ({ len: document.getElementById('screen').innerText.length, err: !!document.querySelector('#screen .error, #screen .state-error'), nav: [...document.querySelectorAll('#nav-list a')].filter(a => getComputedStyle(a).display !== 'none').length, banners: document.getElementById('banners').innerText.slice(0, 120) }));
    await p.screenshot({ path: __dirname + '/shot-' + r + '.png' });
  }
  // try to press controls on the Bot screen
  await p.evaluate(() => { location.hash = '#bot'; }); await p.waitForTimeout(2500);
  const btns = await p.locator('#screen button').all(); let clicked = 0;
  for (const x of btns.slice(0, 12)) { try { await x.click({ timeout: 500 }); clicked++; await p.waitForTimeout(150); } catch (e) {} }
  await p.waitForTimeout(1200);
  console.log(JSON.stringify({ out, errs: errs.slice(0, 12), nerr: errs.length, outside, writes, bad: [...new Set(bad)].slice(0, 12), clicked, lang: await p.evaluate(() => document.documentElement.lang + ' ' + localStorage.getItem('bazaar.lang')) }, null, 1));
  await b.close();
})();
