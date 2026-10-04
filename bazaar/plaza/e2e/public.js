// The public address, end to end, read only: what a team that was handed the link sees.
//
//   node bazaar/plaza/e2e/public.js [https://market.nglmrtn.com] [ip to resolve the host to] [outDir]
//
// It never starts a connection and never writes: pages, AGENTS.md, the public reads, the security headers, and
// that the panel, the component page, the dashboard and the private API do not exist from outside.
const path = require("path");
const fs = require("fs");
const { chromium } = require(path.join(__dirname, "..", "..", "..", "video", "node_modules", "playwright-core"));

const BASE = (process.argv[2] || "https://market.nglmrtn.com").replace(/\/$/, "");
const IP = process.argv[3] || "";
const OUT = process.argv[4] || path.join(__dirname, "..", "..", "..", "design", "plaza", "build", "e2e-final", "public");
const HOST = new URL(BASE).hostname;
const bad = [], notes = [], rows = [];

async function launch() {
  const args = IP ? [`--host-resolver-rules=MAP ${HOST} ${IP}`] : [];
  const tries = [{ headless: true, args }];
  const cache = path.join(process.env.HOME || "", "Library", "Caches", "ms-playwright");
  try {
    for (const dir of fs.readdirSync(cache).filter((d) => d.startsWith("chromium_headless_shell-")).sort().reverse())
      for (const sub of fs.readdirSync(path.join(cache, dir))) {
        const exe = path.join(cache, dir, sub, "chrome-headless-shell");
        if (fs.existsSync(exe)) tries.push({ headless: true, args, executablePath: exe });
      }
  } catch (e) { /* no cache */ }
  let last = null;
  for (const o of tries) { try { return await chromium.launch(o); } catch (e) { last = e; } }
  throw last;
}

(async () => {
  const browser = await launch();
  fs.mkdirSync(OUT, { recursive: true });
  for (const [name, route, view] of [["landing", "/plaza/", [1600, 1000]], ["landing-mobile", "/plaza/", [390, 844]], ["market", "/plaza/market", [1600, 1000]],
    ["activity", "/plaza/activity", [1600, 1000]], ["agents", "/plaza/agents", [1600, 1000]], ["how", "/plaza/how", [1600, 1000]], ["docs", "/plaza/docs", [1600, 1000]],
    ["home-as-visitor", "/plaza/home", [1600, 1000]]]) {
    const ctx = await browser.newContext({ viewport: { width: view[0], height: view[1] } });
    const page = await ctx.newPage();
    const errs = [];
    page.on("pageerror", (e) => bad.push(`${name}: page error: ${String(e.message).slice(0, 160)}`));
    page.on("console", (m) => { if (m.type() === "error") errs.push(m.text().slice(0, 140)); });
    page.on("response", (r) => { if (r.status() >= 500 || (r.status() >= 400 && /\.(js|css)(\?|$)/.test(r.url()))) bad.push(`${name}: ${r.status()} on ${r.url().replace(BASE, "")}`); });
    const res = await page.goto(BASE + route, { waitUntil: "load", timeout: 30000 }).catch((e) => { bad.push(`${name}: ${String(e.message).split("\n")[0]}`); return null; });
    if (res) {
      await page.waitForTimeout(2500);
      const f = await page.evaluate(() => { const nav = document.querySelector(".sidenav");
        return { len: (document.body.innerText || "").trim().length, nav: !!(nav && nav.offsetParent !== null), path: location.pathname,
          sideways: document.documentElement.scrollWidth - window.innerWidth, keys: (document.body.innerText.match(/\b(?:landing|shell|market|activity|how|docs|agents|common)\.[a-z][A-Za-z0-9.]+\b/g) || []).filter((k) => !/\.(md|json|js)$/.test(k)).slice(0, 5) }; });
      const h = res.headers();
      rows.push({ name, status: res.status(), at: f.path, text: f.len, console_errors: [...new Set(errs)] });
      if (res.status() !== 200) bad.push(`${name}: the page answers ${res.status()}`);
      if (f.len < 40) bad.push(`${name}: the page is empty`);
      if (f.nav) bad.push(`${name}: a visitor sees the app's side nav`);
      if (f.sideways > 2) notes.push(`${name}: scrolls sideways by ${f.sideways}px`);
      if (f.keys.length && !["docs", "agents"].includes(name)) notes.push(`${name}: raw text keys ${f.keys.join(", ")}`);
      const other = errs.filter((e) => !/40[13]/.test(e));
      if (other.length) notes.push(`${name}: console: ${[...new Set(other)].slice(0, 2).join(" | ")}`);
      if (name === "landing") for (const k of ["content-security-policy", "x-frame-options", "x-content-type-options", "referrer-policy"]) if (!h[k]) bad.push(`landing: no ${k} header`);
      if (name === "landing" && !h["strict-transport-security"]) notes.push("landing: no Strict-Transport-Security header");
      await page.screenshot({ path: path.join(OUT, name + ".png") });
      if (name === "landing") {                                 // the reads and the doors, from the page's own origin
        const probes = await page.evaluate(async () => {
          const out = {};
          for (const p of ["/plaza/AGENTS.md", "/AGENTS.md", "/plaza/api/status", "/plaza/api/openapi.json", "/plaza/api/health", "/plaza/api/market", "/plaza/api/floor", "/plaza/api/matches",
            "/plaza/api/teams", "/plaza/api/stats", "/plaza/admin/", "/plaza/admin/overview", "/plaza/admin/api/overview", "/plaza/admin/api/teams", "/plaza/_kit", "/plaza/static/fixtures/me.json",
            "/v2/", "/api/control", "/api/brain", "/plaza/api/me", "/plaza/api/me/cards", "/plaza/api/agent/next", "/plaza/../.env", "/.env", "/plaza/static/../server.py"]) {
            try { const r = await fetch(p, { headers: p.includes("admin") ? { "X-Plaza-Admin": "guess" } : {} }); const t = await r.text();
              out[p] = { s: r.status, n: t.length, veiled: p === "/plaza/api/matches" ? (JSON.parse(t).matches || []).every((m) => m.state === "settled" || (m.price === null && m.veiled === true)) : undefined,
                routes: p.endsWith("openapi.json") ? Object.keys(JSON.parse(t).paths || {}).length : undefined, status: p.endsWith("/status") ? JSON.parse(t) : undefined,
                v07: p.endsWith("AGENTS.md") ? /v07/.test(t) && /never/i.test(t) : undefined }; } catch (e) { out[p] = { s: 0, err: String(e).slice(0, 80) }; }
          }
          return out;
        });
        const open = ["/plaza/AGENTS.md", "/AGENTS.md", "/plaza/api/status", "/plaza/api/openapi.json", "/plaza/api/health", "/plaza/api/market", "/plaza/api/floor", "/plaza/api/matches", "/plaza/api/teams", "/plaza/api/stats"];
        for (const [p, r] of Object.entries(probes)) {
          rows.push({ path: p, ...r, status: undefined });
          if (open.includes(p) ? r.s !== 200 : p.startsWith("/plaza/api/me") || p.endsWith("/next") ? r.s !== 401 : r.s !== 404 && !(p === "/plaza/static/fixtures/me.json")) bad.push(`${p} answers ${r.s}`);
        }
        if (probes["/plaza/api/matches"].veiled === false) bad.push("a live match shows its price to a visitor");
        const st = probes["/plaza/api/status"].status || {};
        rows.push({ status: { game: st.game, market: st.market, matchmaker: st.matchmaker, feed: st.feed, tick: st.tick, name: st.name } });
        if (probes["/plaza/static/fixtures/me.json"].s === 200) notes.push("the mock fixtures are served on the public address (example data, no real team)");
      }
    }
    await ctx.close();
  }
  await browser.close();
  fs.writeFileSync(path.join(OUT, "report.json"), JSON.stringify({ base: BASE, bad, notes, rows }, null, 1));
  console.log(JSON.stringify({ base: BASE, pages: rows.filter((r) => r.name).length, bad: bad.length, notes: notes.length, out: OUT }));
  for (const b of bad) console.log("HARD  " + b);
  for (const n of notes) console.log("note  " + n);
  for (const r of rows) console.log("      " + JSON.stringify(r).slice(0, 230));
  process.exit(bad.length ? 1 : 0);
})();
