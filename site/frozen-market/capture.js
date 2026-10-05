const { chromium } = require('playwright-core');
const fs = require('fs'), path = require('path');
const ORIGIN = 'http://127.0.0.1:8793';
const OUT = path.join(__dirname, 'raw');
const ROUTES = ['/plaza/', '/plaza/how', '/plaza/agents', '/plaza/connect', '/plaza/board', '/plaza/collections', '/plaza/auctions', '/plaza/docs', '/plaza/market', '/plaza/activity'];
(async () => {
  fs.rmSync(OUT, { recursive: true, force: true }); fs.mkdirSync(OUT, { recursive: true });
  const b = await chromium.launch({ channel: 'chrome' });
  const ctx = await b.newContext({ viewport: { width: 1600, height: 1000 } });
  const p = await ctx.newPage();
  const api = {}, statics = {};
  await p.route('**/*', (r) => { const q = r.request(); const u = new URL(q.url());
    if (q.method() !== 'GET') return r.abort();
    if (u.origin === ORIGIN && (u.pathname.startsWith('/plaza/admin') || u.pathname.includes('/stream'))) return r.abort();
    r.continue(); });
  p.on('response', async (res) => {
    try {
      const u = new URL(res.url());
      if (u.origin !== ORIGIN || res.request().method() !== 'GET') return;
      const st = res.status(); if (st >= 300 && st < 400) return;
      const body = await res.body();
      if (u.pathname.startsWith('/plaza/api/')) {
        const rel = u.pathname.slice('/plaza/'.length);
        (api[rel] = api[rel] || []).push({ q: u.search.replace(/^\?/, ''), status: st, body: body.toString('utf8') });
      } else if (st === 200) statics[u.pathname] = body;
    } catch (e) {}
  });
  const get = async (pth) => { try { await p.evaluate(async (x) => { await fetch(x).then((r) => r.text()); }, pth); } catch (e) { console.log('ERR', pth, String(e).slice(0, 80)); } };
  await p.goto(ORIGIN + '/plaza/?lang=en', { waitUntil: 'networkidle' });
  for (const r of ROUTES) {
    await p.goto(ORIGIN + r, { waitUntil: 'networkidle' }).catch(() => {});
    await p.waitForTimeout(2500);
    const tabs = await p.locator('main [role=tab], main .tabs button, main .seg button, main .tab').all();
    for (const t of tabs.slice(0, 8)) { try { await t.click({ timeout: 700 }); await p.waitForTimeout(900); } catch (e) {} }
    await p.evaluate(() => { const m = document.querySelector('main') || document.scrollingElement; m.scrollTop = 1e6; window.scrollTo(0, 1e6); });
    await p.waitForTimeout(1500);
    console.log(r, Object.keys(api).length, Object.keys(statics).length);
  }
  // explicit public reads
  const j = async (pth) => p.evaluate(async (x) => { try { return await (await fetch(x)).json(); } catch (e) { return null; } }, pth);
  for (const x of ['/plaza/api/health', '/plaza/api/status', '/plaza/api/stats', '/plaza/api/teams', '/plaza/api/market', '/plaza/api/board', '/plaza/api/board/history', '/plaza/api/board/live', '/plaza/api/collections', '/plaza/api/lots', '/plaza/api/offers', '/plaza/api/matches', '/plaza/api/wall', '/plaza/api/floor', '/plaza/api/openapi.json', '/plaza/api/opportunities', '/plaza/api/quick', '/plaza/api/me', '/plaza/api/connect/status',
    '/plaza/AGENTS.md', '/plaza/AGENTS-AUCTIONS.md', '/plaza/agent.py.txt', '/plaza/agent.py', '/plaza/cards.json', '/plaza/i18n.json', '/plaza/board.json', '/plaza/board/live.json', '/plaza/board/history.json', '/plaza/live.json', '/plaza/history.json', '/plaza/collections.json', '/plaza/lots.json']) await get(x);
  const teams = ((await j('/plaza/api/teams')) || {}).teams || [];
  for (const t of teams) await get('/plaza/api/team/' + t.team);
  const cards = (await j('/plaza/api/collections')) || {};
  const refs = new Set(); JSON.stringify(cards).replace(/"([A-Z]{3}-\d{2})"/g, (m, r) => { refs.add(r); return m; });
  const mk = (await j('/plaza/api/market')) || {}; JSON.stringify(mk).replace(/"([A-Z]{3}-\d{2})"/g, (m, r) => { refs.add(r); return m; });
  console.log('teams', teams.length, 'refs', refs.size);
  const R = [...refs].sort();
  for (let i = 0; i < R.length; i += 6) await Promise.all(R.slice(i, i + 6).flatMap((r) => [get('/plaza/api/card/' + r), get('/plaza/art/' + r + '.svg')]));
  const lots = (await j('/plaza/api/lots')) || {}; for (const l of [...(lots.lots || []), ...(lots.recent || [])]) if (l.id || l.lot) await get('/plaza/api/lot/' + (l.id || l.lot));
  // one card page and one team page, to pull any lazy static
  await p.goto(ORIGIN + '/plaza/card/' + (R[0] || 'LAV-01'), { waitUntil: 'networkidle' }).catch(() => {}); await p.waitForTimeout(1500);
  await p.goto(ORIGIN + '/plaza/team/t01', { waitUntil: 'networkidle' }).catch(() => {}); await p.waitForTimeout(1500);
  await p.waitForTimeout(1000);
  for (const [rel, buf] of Object.entries(statics)) { const f = path.join(OUT, 'site', rel); if (rel.endsWith('/') || !/\.[a-z0-9]+$/i.test(rel)) continue; fs.mkdirSync(path.dirname(f), { recursive: true }); try { fs.writeFileSync(f, buf); } catch (e) { fs.writeFileSync(f + '.__page', buf); } }
  fs.writeFileSync(path.join(OUT, 'index.html'), statics['/plaza/'] || '');
  fs.writeFileSync(path.join(OUT, 'api.json'), JSON.stringify(api));
  fs.writeFileSync(path.join(OUT, 'refs.json'), JSON.stringify({ refs: R, teams: teams.map((t) => t.team) }));
  console.log('static', Object.keys(statics).length, 'api paths', Object.keys(api).length, 'bytes', fs.statSync(path.join(OUT, 'api.json')).size);
  console.log(Object.keys(statics).filter((k) => !k.startsWith('/plaza/static/') && !k.startsWith('/plaza/art/')).join(' '));
  await b.close();
})();
