// Opens every page of the market in a headless browser: EN and ES, desktop and 390 px, mock mode and against the
// simulator started by `python -m bazaar.plaza.e2e.serve`. Uses the Playwright that lives in video/.
//
//   node bazaar/plaza/e2e/browser.js '<the JSON line serve.py printed>' [outDir] [--quick]
//
// Hard failures (exit 1): a page error, a blocked or failed script, a 5xx, hostile text that runs, a nav link
// that leads nowhere. Findings (listed, exit 0): console errors, missing i18n keys, sideways scroll, cut text.
const path = require("path");
const fs = require("fs");
const { chromium } = require(path.join(__dirname, "..", "..", "..", "video", "node_modules", "playwright-core"));

const info = JSON.parse(process.argv[2] || "{}");
const OUT = process.argv[3] && !process.argv[3].startsWith("--") ? process.argv[3]
  : path.join(__dirname, "..", "..", "..", "design", "plaza", "build");
const QUICK = process.argv.includes("--quick");
const BASE = info.base;
const MATCH = info.match || "m-0000000000";

const USER = [
  ["landing", "/plaza/"], ["connect", "/plaza/connect"], ["how", "/plaza/how"], ["agents", "/plaza/agents"],
  ["home", "/plaza/home"], ["activity", "/plaza/activity"], ["offers", "/plaza/offers"],
  ["offers-match", "/plaza/offers/" + MATCH], ["cards", "/plaza/cards"], ["market", "/plaza/market"],
  ["card", "/plaza/card/SAL-10"], ["settings", "/plaza/settings"], ["suggest", "/plaza/suggest"],
  ["docs", "/plaza/docs"], ["kit", "/plaza/_kit"],
];
const ADMIN = ["overview", "performance", "matchmaker", "trades", "teams", "activity", "suggestions", "venue", "docs"]
  .map((n) => ["admin-" + n, "/plaza/admin/" + n]);
const VIEWS = { desktop: { width: 1600, height: 1000 }, mobile: { width: 390, height: 844 } };
const STATES = ["closed", "paused", "offline", "empty", "error"];
const STATE_SCREENS = [["home", "/plaza/home"], ["offers", "/plaza/offers"], ["market", "/plaza/market"],
  ["activity", "/plaza/activity"], ["cards", "/plaza/cards"]];
const KEY_RX = /\b(?:common|shell|closed|landing|connect|how|agents|home|activity|offers|cards|market|card|settings|suggest|docs|kit|admin|overview|performance|matchmaker|trades|teams|suggestions|venue)\.[a-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*\b/g;
const NOT_A_KEY = /\.(?:json|js|css|md|py|html|svg|png)$/;

const hard = [], findings = [], shots = [];
let pages = 0, visits = 0, perLoad = 0;

async function visit(browser, { name, route, lang, view, mode, session, admin, mock }) {
  const context = await browser.newContext({ viewport: VIEWS[view], deviceScaleFactor: 1 });
  // Its own client address, as the gateway would forward it, so every visit has its own request budget; the
  // headers go only to the market, never to the font host.
  const extra = { "x-plaza-client": `10.77.${Math.floor(visits / 250) % 250}.${visits % 250 + 1}`, ...(admin ? { "x-plaza-admin": info.admin_token } : {}) };
  await context.route(BASE + "/**", (route) => route.continue({ headers: { ...route.request().headers(), ...extra } }));
  visits += 1;
  let requests = 0;
  if (session) await context.addCookies([{ name: "plaza_session", value: session, url: BASE + "/plaza" }]);
  const page = await context.newPage();
  const tag = `${mode}/${lang}-${view}-${name}`;
  const errs = [], warns = [];
  page.on("pageerror", (e) => hard.push(`${tag}: page error: ${String(e.message || e).slice(0, 200)}`));
  page.on("console", (m) => {
    const text = m.text();
    if (m.type() === "error") errs.push(text.slice(0, 200));
    if (/i18n: missing key/.test(text)) warns.push(text.replace("i18n: missing key ", ""));
  });
  page.on("request", () => { requests += 1; });
  page.on("response", (r) => {
    const s = r.status(), u = r.url().replace(BASE, "");
    if (s >= 500 && !(mock === "error")) hard.push(`${tag}: ${s} on ${u}`);
    else if (s >= 400 && /\.(js|css)(\?|$)/.test(u)) hard.push(`${tag}: ${s} on ${u} (a script or a style is missing)`);
  });
  const url = `${BASE}${route}?lang=${lang}&mock=${mock || "0"}`;
  try {
    const res = await page.goto(url, { waitUntil: "load", timeout: 15000 });
    if (!res || res.status() >= 400) hard.push(`${tag}: the page answers ${res ? res.status() : "nothing"}`);
    await page.waitForTimeout(QUICK ? 500 : 1100);
    const facts = await page.evaluate(() => {
      const app = document.querySelector("#app");
      const text = document.body.innerText || "";
      const cut = [];
      for (const el of document.querySelectorAll("#app *")) {
        if (el.children.length || !el.textContent.trim()) continue;
        const cs = getComputedStyle(el);
        if (cs.overflowX === "visible" || cs.textOverflow === "ellipsis" || cs.overflowX === "auto" || cs.overflowX === "scroll") continue;
        if (el.scrollWidth > el.clientWidth + 2) cut.push((el.className || el.tagName) + ": " + el.textContent.trim().slice(0, 40));
      }
      return { text, empty: !app || !app.children.length || text.trim().length < 20,
        sideways: document.documentElement.scrollWidth - window.innerWidth,
        lang: document.documentElement.lang, xss: window.__xss || null,
        injected: document.querySelectorAll('img[src="x"], #app script').length, cut: cut.slice(0, 5) };
    });
    if (facts.xss || facts.injected) hard.push(`${tag}: hostile text became markup (xss=${facts.xss}, nodes=${facts.injected})`);
    if (facts.empty) hard.push(`${tag}: the page is empty`);
    if (facts.sideways > 2) findings.push(`${tag}: scrolls sideways by ${facts.sideways}px`);
    if (facts.lang && facts.lang !== lang) findings.push(`${tag}: <html lang> is ${facts.lang}`);
    const keys = [...new Set((facts.text.match(KEY_RX) || []).filter((k) => !NOT_A_KEY.test(k)))];
    if (keys.length && name !== "docs" && name !== "agents" && name !== "admin-docs") findings.push(`${tag}: raw i18n keys on screen: ${keys.slice(0, 6).join(", ")}`);
    if (warns.length) findings.push(`${tag}: missing i18n keys: ${[...new Set(warns)].slice(0, 8).join(", ")}`);
    if (errs.length && mock !== "error") findings.push(`${tag}: console errors: ${[...new Set(errs)].slice(0, 3).join(" | ")}`);
    if (facts.cut.length) findings.push(`${tag}: cut text: ${facts.cut.join(" ; ")}`);
    fs.mkdirSync(path.join(OUT, mode), { recursive: true });
    const file = path.join(OUT, mode, `${lang}-${view}-${name}.png`);
    await page.screenshot({ path: file, fullPage: false });
    shots.push(path.relative(path.join(__dirname, "..", "..", ".."), file));
    pages += 1;
    perLoad = Math.max(perLoad, requests);
    return { page, context, facts };
  } catch (e) {
    hard.push(`${tag}: ${String(e.message || e).split("\n")[0].slice(0, 200)}`);
    await context.close();
    return null;
  }
}

async function launch() {
  // The browser Playwright downloaded for its own version, else whichever one is in its cache, else Chrome.
  const tries = [{ headless: true }];
  const cache = path.join(process.env.HOME || "", "Library", "Caches", "ms-playwright");
  try {
    for (const dir of fs.readdirSync(cache).filter((d) => d.startsWith("chromium_headless_shell-")).sort().reverse()) {
      for (const sub of fs.readdirSync(path.join(cache, dir))) {
        const exe = path.join(cache, dir, sub, "chrome-headless-shell");
        if (fs.existsSync(exe)) tries.push({ headless: true, executablePath: exe });
      }
    }
  } catch (e) { /* no cache */ }
  tries.push({ headless: true, channel: "chrome" });
  let last = null;
  for (const opts of tries) {
    try { return await chromium.launch(opts); } catch (e) { last = e; }
  }
  throw new Error("no browser to launch: " + String(last && last.message).split("\n")[0]);
}

async function close(v) { if (v) await v.context.close(); }

async function navigation(browser, mode, session) {
  // Every entry of the side nav leads to a screen that draws, and the landing leads to Connect and on to Home.
  const v = await visit(browser, { name: "nav-home", route: "/plaza/home", lang: "en", view: "desktop", mode, session, mock: mode === "mock" ? "1" : "0" });
  if (!v) return;
  const links = await v.page.$$eval(".sidenav a.nav-item", (as) => as.map((a) => a.getAttribute("href")));
  if (links.length < 5) hard.push(`${mode}: the side nav has ${links.length} entries`);
  for (const href of links) {
    try {
      await v.page.click(`.sidenav a.nav-item[href="${href}"]`);
      await v.page.waitForTimeout(350);
      const at = await v.page.evaluate(() => ({ path: location.pathname, active: (document.querySelector(".sidenav a.nav-item.active") || {}).getAttribute?.("href") || null,
        filled: (document.querySelector("#app").innerText || "").trim().length > 40 }));
      if (at.path !== href.split("?")[0]) hard.push(`${mode}: nav ${href} leads to ${at.path}`);
      if (!at.filled) hard.push(`${mode}: nav ${href} draws nothing`);
      if (at.active !== href) findings.push(`${mode}: nav ${href} is not marked active (active: ${at.active})`);
    } catch (e) { hard.push(`${mode}: nav ${href}: ${String(e.message).split("\n")[0].slice(0, 160)}`); }
  }
  await close(v);
  const flow = await visit(browser, { name: "flow-landing", route: "/plaza/", lang: "en", view: "desktop", mode, mock: mode === "mock" ? "1" : "0" });
  if (!flow) return;
  try {
    const cta = await flow.page.$('#app a[href^="/plaza/connect"], #app main button.primary, #app button.btn.primary, #app .landing-hero button');
    if (!cta) hard.push(`${mode}: the landing has no link to Connect`);
    else {
      await cta.click();
      await flow.page.waitForTimeout(400);
      const at = await flow.page.evaluate(() => location.pathname);     // Connect, or Home when a team is already in
      if (!/^\/plaza\/(connect|home)/.test(at)) hard.push(`${mode}: the landing's main button leads to ${at}`);
    }
    await flow.page.goto(`${BASE}/plaza/how?lang=en`, { waitUntil: "load" });
    await flow.page.waitForTimeout(400);
    const how = await flow.page.evaluate(() => {
      const nav = document.querySelector(".sidenav");
      return { shell: !!(nav && nav.offsetParent !== null && nav.getBoundingClientRect().width > 0),
        enter: [...document.querySelectorAll('#app a[href^="/plaza/home"], #app button')].length };
    });
    if (how.shell) findings.push(`${mode}: How it works shows the app's side nav (it is a full page without the shell)`);
    if (!how.enter) hard.push(`${mode}: How it works has no "Enter the market" button`);
    else {
      const enter = (await flow.page.$('#app .how-enter')) || (await flow.page.$$('#app a[href^="/plaza/home"], #app button')).pop();
      await enter.click();
      await flow.page.waitForTimeout(400);
      const at = await flow.page.evaluate(() => location.pathname);
      if (!/^\/plaza\/(home|connect)/.test(at)) findings.push(`${mode}: the last button of How it works leads to ${at}, not to Home (or to Connect when no team is connected)`);
    }
  } catch (e) { hard.push(`${mode}: flow: ${String(e.message).split("\n")[0].slice(0, 160)}`); }
  await close(flow);
}

(async () => {
  if (!BASE) { console.error("usage: node browser.js '<json from serve.py>' [outDir] [--quick]"); process.exit(2); }
  const browser = await launch();
  const langs = ["en", "es"], views = QUICK ? ["desktop"] : ["desktop", "mobile"];
  for (const mode of ["mock", "real"]) {
    const session = mode === "real" ? info.session : null;
    for (const lang of langs) for (const view of views) {
      for (const [name, route] of USER) await close(await visit(browser, { name, route, lang, view, mode, session, mock: mode === "mock" ? "1" : "0" }));
      if (view === "desktop") for (const [name, route] of ADMIN) await close(await visit(browser, { name, route, lang, view, mode, admin: true, mock: mode === "mock" ? "1" : "0" }));
    }
    await navigation(browser, mode, session);
  }
  for (const state of STATES) for (const [name, route] of STATE_SCREENS) {
    const v = await visit(browser, { name: `${name}-${state}`, route, lang: "en", view: "desktop", mode: "states", mock: state });
    if (v && (state === "closed" || state === "paused")) {
      const overlay = await v.page.$(".closed-overlay");
      if (!overlay) findings.push(`states/${name}-${state}: no closed or paused overlay`);
    }
    await close(v);
  }
  { // the panel does not exist without the admin proof
    const ctx = await browser.newContext();
    const res = await (await ctx.newPage()).goto(`${BASE}/plaza/admin/`, { waitUntil: "load" }).catch(() => null);
    if (!res || res.status() !== 404) hard.push(`the panel answers ${res ? res.status() : "nothing"} without the admin header`);
    await ctx.close();
  }
  { // one client, one address: how many times can a person reload before the budget (240 reads a minute) stops the page
    const ctx = await browser.newContext();
    await ctx.route(BASE + "/**", (route) => route.continue({ headers: { ...route.request().headers(), "x-plaza-client": "10.88.0.1" } }));
    const page = await ctx.newPage();
    let loads = 0, blocked = false;
    page.on("response", (r) => { if (r.status() === 429) blocked = true; });
    for (; loads < 8 && !blocked; loads += 1) await page.goto(`${BASE}/plaza/home?mock=1`, { waitUntil: "load" }).catch(() => null);
    if (blocked) findings.push(`budget: one client address is refused (429) on page load ${loads} within a minute; a page load makes about ${perLoad} requests and every static file counts against the 240 reads. Teams behind one shared address (the venue's wifi) share that budget`);
    await ctx.close();
  }
  await browser.close();
  const report = { pages, hard, findings, shots: shots.length, out: OUT };
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(path.join(OUT, "report.json"), JSON.stringify(report, null, 1));
  console.log(JSON.stringify({ pages, hard: hard.length, findings: findings.length, out: OUT }));
  for (const h of hard) console.log("HARD  " + h);
  for (const f of findings.slice(0, 80)) console.log("note  " + f);
  process.exit(hard.length ? 1 : 0);
})();
