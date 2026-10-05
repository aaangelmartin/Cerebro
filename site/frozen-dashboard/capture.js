const { chromium } = require('playwright-core');
const fs = require('fs'), path = require('path');
const BASE = 'http://127.0.0.1:8791/';
const OUT = path.join(__dirname, 'raw');
const ROUTES = ['home','cerebro','noticias','coleccion','mercado','broker','duelos','competicion','rivales','supervision','laboratorio','bot'];
(async () => {
  fs.rmSync(OUT, { recursive: true, force: true }); fs.mkdirSync(OUT, { recursive: true });
  const b = await chromium.launch({ channel: 'chrome' });
  const ctx = await b.newContext({ viewport: { width: 1600, height: 1000 } });
  const p = await ctx.newPage();
  const api = {};   // path -> [{q, body}]
  const statics = {};
  await p.route('**/*', (r) => {
    const req = r.request();
    if (req.method() !== 'GET') return r.abort();          // capture can never write
    r.continue();
  });
  p.on('response', async (res) => {
    try {
      const u = new URL(res.url());
      if (u.origin !== new URL(BASE).origin) return;
      if (res.request().method() !== 'GET' || res.status() !== 200) return;
      const rel = u.pathname.replace(/^\//, '');
      const body = await res.body();
      if (rel.startsWith('api/')) {
        (api[rel] = api[rel] || []).push({ q: u.search.replace(/^\?/, ''), body: body.toString('utf8') });
      } else {
        statics[rel || 'index.html'] = body;
      }
    } catch (e) {}
  });
  await p.goto(BASE + 'index.html?lang=en#home', { waitUntil: 'networkidle' });
  for (const r of ROUTES) {
    await p.evaluate((h) => { location.hash = '#' + h; }, r);
    await p.waitForTimeout(4500);
    // read-only tab clicks (writes are aborted above)
    const tabs = await p.locator('#screen [role=tab], #screen .tabs button, #screen .tab, #screen .seg button, #screen .subnav button, #screen .subnav a').all();
    for (const t of tabs.slice(0, 10)) { try { await t.click({ timeout: 800 }); await p.waitForTimeout(1200); } catch (e) {} }
    await p.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await p.waitForTimeout(3500);
    console.log(r, Object.keys(api).length);
  }
  // details for duels (public game data about our own duels)
  const ids = await p.evaluate(async () => {
    try { const d = await (await fetch('api/rec/duels')).json(); const a = d.duels || d.items || d; return (Array.isArray(a) ? a : []).map((x) => x.id || x.duel || x.duel_id).filter(Boolean); } catch (e) { return []; }
  });
  console.log('duels', ids.length);
  for (let i = 0; i < ids.length; i += 8) {
    await p.evaluate(async (chunk) => { await Promise.all(chunk.map((id) => fetch('api/rec/duels/' + encodeURIComponent(id)).then((r) => r.text()).catch(() => null))); }, ids.slice(i, i + 8));
  }
  await p.waitForTimeout(1500);
  for (const [rel, buf] of Object.entries(statics)) {
    const f = path.join(OUT, 'site', rel); fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, buf);
  }
  fs.writeFileSync(path.join(OUT, 'api.json'), JSON.stringify(api));
  console.log('static', Object.keys(statics).length, 'api paths', Object.keys(api).length, 'bytes', fs.statSync(path.join(OUT, 'api.json')).size);
  await b.close();
})();
