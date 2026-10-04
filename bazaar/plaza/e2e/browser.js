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

async function finalChecks(browser) {
  // The landing at four sizes: nothing spills, no console error, and it stands still when asked to.
  for (const [w, h] of [[1600, 1000], [1440, 900], [1280, 720], [390, 844]]) {
    for (const reduce of [false, true]) {
      const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion: reduce ? "reduce" : "no-preference" });
      await ctx.route(BASE + "/**", (route) => route.continue({ headers: { ...route.request().headers(), "x-plaza-client": `10.90.${w % 250}.${reduce ? 2 : 1}` } }));
      const page = await ctx.newPage();
      const tag = `landing ${w}x${h}${reduce ? " reduced-motion" : ""}`;
      const errs = [];
      page.on("pageerror", (e) => hard.push(`${tag}: page error: ${String(e.message).slice(0, 160)}`));
      page.on("console", (m) => { if (m.type() === "error" && !/401/.test(m.text())) errs.push(m.text().slice(0, 160)); });
      await page.goto(`${BASE}/plaza/?lang=en&mock=0`, { waitUntil: "load" }).catch(() => null);
      await page.waitForTimeout(1500);
      const f = await page.evaluate(() => {
        const vw = window.innerWidth, out = [];
        for (const el of document.querySelectorAll("#app *")) {
          const r = el.getBoundingClientRect();
          if (r.width && (r.right > vw + 2 || r.left < -2) && getComputedStyle(el).position !== "fixed") {
            let p = el.parentElement, clipped = false;
            for (; p && p !== document.body; p = p.parentElement) if (/hidden|clip|auto|scroll/.test(getComputedStyle(p).overflowX)) { clipped = true; break; }
            if (!clipped) out.push((el.className || el.tagName) + "");
          }
        }
        const running = document.getAnimations().filter((a) => a.playState === "running" && (a.effect.getComputedTiming().duration || 0) > 50).length;
        return { sideways: document.documentElement.scrollWidth - vw, spill: [...new Set(out)].slice(0, 5), running,
          foldCta: (() => { const b = document.querySelector("#app button.primary, #app .btn.primary"); return b ? b.getBoundingClientRect().bottom <= window.innerHeight : null; })() };
      });
      if (f.sideways > 2 || f.spill.length) findings.push(`${tag}: spills sideways (${f.sideways}px): ${f.spill.join(", ")}`);
      if (errs.length) findings.push(`${tag}: console errors: ${[...new Set(errs)].slice(0, 2).join(" | ")}`);
      if (reduce && f.running) findings.push(`${tag}: ${f.running} animations still run with prefers-reduced-motion`);
      if (f.foldCta === false) findings.push(`${tag}: the main button is below the fold`);
      fs.mkdirSync(path.join(OUT, "final"), { recursive: true });
      await page.screenshot({ path: path.join(OUT, "final", `landing-${w}x${h}${reduce ? "-reduced" : ""}.png`) });
      pages += 1;
      await ctx.close();
    }
  }
  // A visitor: no side nav anywhere, a way back to the landing, and no price of a trade that is not settled.
  for (const [name, route] of [["market", "/plaza/market"], ["activity", "/plaza/activity"], ["card", "/plaza/card/" + (info.live_ref || "SAL-10")], ["agents", "/plaza/agents"], ["docs", "/plaza/docs"], ["how", "/plaza/how"]]) {
    for (const view of ["desktop", "mobile"]) {
      const v = await visit(browser, { name: "visitor-" + name, route, lang: "en", view, mode: "final", mock: "0" });
      if (!v) continue;
      const f = await v.page.evaluate(() => {
        const nav = document.querySelector(".sidenav");
        return { nav: !!(nav && nav.offsetParent !== null && nav.getBoundingClientRect().width > 0), back: !!document.querySelector(".pubbar-back"),
          text: document.body.innerText };
      });
      if (f.nav) hard.push(`visitor ${name} (${view}): the side nav of the app is shown to a visitor`);
      if (!f.back && name !== "how") findings.push(`visitor ${name} (${view}): no Back to the landing`);
      if (info.live_price && ["market", "activity", "card"].includes(name) && new RegExp(`(^|[^\\d.])${info.live_price}\\s*P`).test(f.text))
        hard.push(`visitor ${name} (${view}): shows ${info.live_price} P, the price of a trade that is not settled`);
      if (f.back && view === "desktop" && name === "market") {
        await v.page.click(".pubbar-back");
        await v.page.waitForTimeout(300);
        const at = await v.page.evaluate(() => location.pathname);
        if (at !== "/plaza/") hard.push(`visitor: Back from Market leads to ${at}`);
      }
      await close(v);
    }
  }
  { // a team's screen opened by a visitor goes to the landing, never to an empty app
    const v = await visit(browser, { name: "visitor-home", route: "/plaza/home", lang: "en", view: "desktop", mode: "final", mock: "0" });
    if (v) {
      const at = await v.page.evaluate(() => ({ path: location.pathname, nav: !!document.querySelector(".sidenav") && document.querySelector(".sidenav").offsetParent !== null }));
      if (at.nav) hard.push(`visitor: /plaza/home shows the app to nobody (${at.path})`);
      await close(v);
    }
  }
  // A warned team: the overlay in the middle, the mark in the top bar, the Standing row. A banned one: told so.
  for (const [who, session] of [["warned", info.warned_session], ["banned", info.banned_session]]) {
    if (!session) { findings.push(`the scene has no ${who} team`); continue; }
    for (const view of ["desktop", "mobile"]) {
      const v = await visit(browser, { name: who + "-home", route: "/plaza/home", lang: view === "mobile" ? "es" : "en", view, mode: "final", session, mock: "0" });
      if (!v) continue;
      await v.page.waitForTimeout(700);
      const f = await v.page.evaluate(() => {
        const o = document.querySelector(".standing-overlay"), b = document.querySelector(".tb-standing");
        const card = o && (o.firstElementChild || o).getBoundingClientRect();
        const area = o && o.getBoundingClientRect();           // centred in the area it covers (the screen, beside the nav)
        return { overlay: !!o, centred: card ? Math.abs((card.left + card.right) / 2 - (area.left + area.right) / 2) < 24 : null,
          bar: !!(b && !b.hidden && b.getBoundingClientRect().width > 0), text: document.body.innerText };
      });
      if (!f.overlay) hard.push(`${who} team (${view}): no warning overlay`);
      else if (f.centred === false) findings.push(`${who} team (${view}): the warning is not centred`);
      if (!f.bar) findings.push(`${who} team (${view}): no mark in the top bar`);
      await v.page.screenshot({ path: path.join(OUT, "final", `${who}-${view}.png`) });
      await close(v);
    }
  }
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
  await finalChecks(browser);
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
