const { chromium } = require('playwright-core');
const ORIGIN = process.argv[2], BASE = ORIGIN + '/Cerebro/market';
const ROUTES = ['/', '/how', '/agents', '/connect', '/board', '/collections', '/auctions', '/docs', '/market', '/activity', '/card/LAV-12', '/team/t01', '/home'];
(async () => {
  const b = await chromium.launch({ channel: 'chrome' });
  const ctx = await b.newContext({ viewport: { width: 1600, height: 1000 } });
  const p = await ctx.newPage();
  const errs = [], outside = [], writes = [], bad = [];
  p.on('pageerror', e => errs.push('pageerror ' + String(e).slice(0, 200)));
  p.on('console', m => { if (m.type() === 'error') errs.push('console ' + m.text().slice(0, 200)); });
  p.on('request', r => { const u = new URL(r.url()); if (u.origin !== ORIGIN && !/fonts\.(googleapis|gstatic)\.com$/.test(u.hostname) && u.protocol !== 'data:') outside.push(r.url()); if (r.method() !== 'GET') writes.push(r.method() + ' ' + r.url()); });
  p.on('response', r => { if (r.status() >= 400) bad.push(r.status() + ' ' + r.url().replace(ORIGIN, '')); });
  const out = {};
  for (const r of ROUTES) {
    await p.goto(BASE + r, { waitUntil: 'networkidle' }).catch((e) => errs.push('goto ' + r + ' ' + String(e).slice(0, 80)));
    await p.waitForTimeout(r === '/' ? 3500 : 2200);
    out[r] = await p.evaluate(() => ({ path: location.pathname, title: document.title, len: (document.querySelector('main') || document.body).innerText.length, err: [...document.querySelectorAll('.state-error, .state.error, .is-error')].map(e => e.innerText.slice(0, 80)), overlay: !!document.querySelector('.closed-overlay'), ribbon: (document.getElementById('frozen-ribbon') || {}).innerText }));
    await p.screenshot({ path: __dirname + '/shot' + (process.argv[3] || '') + r.replace(/\//g, '_') + '.png' });
  }
  // in-app navigation and a write attempt
  await p.goto(BASE + '/', { waitUntil: 'networkidle' }); await p.waitForTimeout(1500);
  const nav = await p.evaluate(async () => { const a = [...document.querySelectorAll('a[href]')].map(x => x.getAttribute('href')); const w = await fetch('/Cerebro/market/api/connect/start', { method: 'POST', body: '{}' }).then(r => r.status); const es = typeof window.EventSource; return { links: [...new Set(a)].slice(0, 40), write: w, es, lang: document.documentElement.lang }; });
  // language toggle
  let toggled = null;
  await p.goto(BASE + '/board', { waitUntil: 'networkidle' }); await p.waitForTimeout(1500);
  try { const btn = p.locator('.lang-switch button', { hasText: 'ES' }).first(); await btn.click({ timeout: 1500 }); await p.waitForTimeout(800); toggled = await p.evaluate(() => document.documentElement.lang + ' | ' + document.title); await p.screenshot({ path: __dirname + '/shot' + (process.argv[3] || '') + '_board_es.png' }); } catch (e) { toggled = 'no-toggle ' + String(e).slice(0, 60); }
  console.log(JSON.stringify({ out, errs: [...new Set(errs)].slice(0, 15), nerr: errs.length, outside: [...new Set(outside)], writes, bad: [...new Set(bad)].slice(0, 20), nav, toggled }, null, 1));
  await b.close();
})();
