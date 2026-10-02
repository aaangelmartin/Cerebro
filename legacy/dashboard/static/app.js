/* The Bazaar team dashboard: core (store, API, SSE hub, router, shared components). Views live in ./views/<id>.js */
import * as self from "./app.js";


/* =====================================================================
   Read-only team dashboard. Only same-origin GETs to the local proxy.
   ===================================================================== */
export const CYCLE_MS = 15000;
export const RAR = ["common", "uncommon", "rare", "epic", "legendary"];
export const RAR_ES = { common: "Común", uncommon: "Poco común", rare: "Rara", epic: "Épica", legendary: "Legendaria" };
export const DAY_ES = { fri: "Viernes", sat: "Sábado", sun: "Domingo" };
export const $ = id => document.getElementById(id);
export const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const col = (c, fb = "#8E99B8") => /^#[0-9a-f]{3,8}$/i.test(String(c || "")) ? c : fb;
export const num = v => (typeof v === "number" && isFinite(v)) ? v : (v !== null && v !== "" && v !== undefined && isFinite(Number(v)) ? Number(v) : null);
export const fmt = (n, d = 1) => num(n) == null ? "–" : num(n).toLocaleString("es-ES", { maximumFractionDigits: d });
export const pct = (a, b) => b > 0 ? Math.max(0, Math.min(100, 100 * a / b)) : 0;
export const rk = r => RAR.includes(r) ? r : "common";
export const tz = { hour: "2-digit", minute: "2-digit" };
export const enc = encodeURIComponent;

/* ---------- data layer: rate-limited queue + TTL cache ---------- */
/* Store keys -> [path, ttl]. Realtime comes from /events (SSE); these are fetched on demand with a TTL,
   and team events invalidate the team keys. "feed" is not here: it is the SSE store (feedEvents()). */
export const SRC = {
  me: ["/api/me", 30e3], clock: ["/api/clock", 30e3], health: ["/api/health", 120e3], catalog: ["/api/catalog", 600e3],
  lb: ["/api/leaderboard", 30e3], sched: ["/api/schedule", 120e3], dealers: ["/api/dealers", 120e3],
  offers: ["/api/me/offers", 60e3], threads: ["/api/me/threads", 60e3], duels: ["/api/duels", 60e3],
  levels: ["/api/levels", 120e3], venues: ["/api/venues", 60e3], log: ["/notes/LOG.md", 30e3], ref: ["/notes/BAZAAR.md", 120e3],
};
export const cache = new Map();
export const Q = []; let active = 0, lastStart = 0, pumpTimer = null;
export const MAX_CONC = 2, GAP_MS = 240;   // ≈ 4 req/s, under the 5 req/s team limit
export function pump() {
  if (pumpTimer) return;
  while (active < MAX_CONC && Q.length) {
    const wait = lastStart + GAP_MS - Date.now();
    if (wait > 0) { pumpTimer = setTimeout(() => { pumpTimer = null; pump(); }, wait); return; }
    const job = Q.shift(); active++; lastStart = Date.now();
    job().finally(() => { active--; pump(); });
  }
}
export function rawFetch(path) {
  return new Promise((resolve, reject) => {
    Q.push(async () => {
      try {
        const isText = path.startsWith("/notes/");
        const r = await fetch(path, { cache: "no-store", credentials: "same-origin", headers: { Accept: isText ? "text/markdown, text/plain" : "application/json" } });
        if (r.status === 401) { sessionExpired(); throw new Error("sesión caducada (401)"); }
        if (isText) {
          if (r.status === 404) return resolve(null);
          if (!r.ok) throw new Error(`${path} respondió ${r.status}`);
          return resolve(await r.text());
        }
        const j = await r.json().catch(() => null);
        if (!r.ok) throw new Error(`${path} respondió ${r.status}${j && (j.message || j.error || j.detail) ? ": " + (j.message || j.error || j.detail) : ""}`);
        resolve(j ?? {});
      } catch (e) { reject(e); }
    });
    pump();
  });
}
export function load(path, ttl = 20e3) {
  const c = cache.get(path) || {};
  if ("data" in c && Date.now() - c.at < ttl) return Promise.resolve(c.data);
  if (c.inflight) return c.inflight;
  const p = rawFetch(path).then(d => { cache.set(path, { data: d, at: Date.now(), err: null }); return d; },
    e => { const o = cache.get(path) || {}; cache.set(path, { ...o, inflight: null, err: e }); throw e; });
  cache.set(path, { ...c, inflight: p });
  return p;
}
export const D = key => SRC[key] ? cache.get(SRC[key][0])?.data : undefined;
export const loadKey = key => load(SRC[key][0], SRC[key][1]);

/* ---------- small helpers ---------- */
export const state = { prev: {}, seenAssets: null, seenFeed: null, lastOk: 0, clockAt: 0, lbSort: "score", lbDesc: true, catSet: "all", feedCat: "all", venue: null, seenLog: null };
export let SYM = "P";
export function setSym(s) { SYM = s; }
export function put(el, html) { if (el && el._html !== html) { el.innerHTML = html; el._html = html; } }
export function setVal(id, text) {
  const el = $(id); if (!el) return;
  if (el.textContent !== text) {
    const had = state.prev[id] !== undefined;
    el.textContent = text;
    if (had) { el.classList.remove("bump"); void el.offsetWidth; el.classList.add("bump"); }
    state.prev[id] = text;
  }
}
export function dur(ms) {
  if (ms == null || !isFinite(ms)) return "–";
  const s = Math.max(0, Math.round(ms / 1000));
  const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60), ss = s % 60;
  if (d) return `${d} d ${h} h`;
  if (h) return `${h} h ${String(m).padStart(2, "0")} min`;
  if (m) return `${m} min ${String(ss).padStart(2, "0")} s`;
  return `${ss} s`;
}
export const wallStr = (ms, opt = { weekday: "short", ...tz }) => ms ? new Date(ms).toLocaleString("es-ES", opt) : "";
export function rawBlock(obj) { return `<details class="raw"><summary>Ver datos completos</summary><pre class="json">${esc(JSON.stringify(obj, null, 2))}</pre></details>`; }
export function kv(obj, skip = []) {
  if (!obj || typeof obj !== "object") return "";
  const rows = Object.entries(obj).filter(([k, v]) => !skip.includes(k) && v !== null && v !== "" && typeof v !== "object");
  return rows.length ? `<dl class="kv">${rows.map(([k, v]) => `<dt>${esc(k.replace(/_/g, " "))}</dt><dd>${esc(typeof v === "number" ? fmt(v, 2) : v)}</dd>`).join("")}</dl>` : "";
}
export function ring(have, of, color, size = 56) {
  const C = 2 * Math.PI * 24, off = C * (1 - (of ? Math.min(1, have / of) : 0));
  return `<div class="ring" style="--sc:${color};width:${size}px;height:${size}px" role="img" aria-label="${esc(`${have} de ${of}`)}"><svg viewBox="0 0 56 56"><circle class="bg" cx="28" cy="28" r="24"/><circle class="fg" cx="28" cy="28" r="24" stroke-dasharray="${C.toFixed(2)}" stroke-dashoffset="${off.toFixed(2)}"/></svg><b>${esc(have)}/${esc(of)}</b></div>`;
}

/* ---------- names & indexes ---------- */
export function catIndex() {
  const cat = D("catalog") || {};
  const cards = {}, sets = {}, packs = {};
  for (const s of cat.sets || []) { sets[s.id] = s; for (const c of s.cards || []) cards[c.id] = { ...c, set: s }; }
  for (const p of cat.packs || []) packs[p.id] = p;
  return { cat, cards, sets, packs, rar: cat.rarities || {} };
}
export function nameOf(id) {
  if (id == null || id === "") return "";
  const s = String(id);
  const t = (D("lb")?.teams || []).find(x => x.team === s); if (t) return t.name;
  const me = D("me"); if (me && me.id === s) return me.name;
  const p = (D("dealers")?.personas || []).find(x => x.id === s); if (p) return p.name;
  const v = (D("venues")?.venues || D("lb")?.venues || []).find(x => x.venue === s); if (v) return v.name;
  return s;
}
export function itemName(it) {
  if (!it) return "";
  if (it.name) return it.name;
  const { cards, packs } = catIndex();
  if (it.kind === "pack") return packs[it.ref]?.name || it.ref;
  return cards[it.ref]?.name ? `${it.ref} ${cards[it.ref].name}` : (it.ref || it.card || it.id || "");
}
export function bundle(b) {
  if (!b) return "nada";
  if (typeof b !== "object") return String(b);
  const out = [];
  for (const a of b.assets || []) out.push(typeof a === "object" ? itemName(a) : `#${a}`);
  for (const t of b.types || []) {
    const ref = typeof t === "string" ? t : (t.ref || t.card || t.pack || t.rarity || "");
    const { cards, packs } = catIndex();
    out.push(packs[ref] ? packs[ref].name : cards[ref] ? `cualquier ${ref} ${cards[ref].name}` : `cualquier ${RAR_ES[ref] || ref}`);
  }
  for (const c of b.cards || []) { const ref = typeof c === "string" ? c : (c.ref || c.card || ""); const cc = catIndex().cards[ref]; out.push(cc ? `cualquier ${ref} ${cc.name}` : `cualquier ${ref}`); }
  if (b.cash) out.push(`${fmt(b.cash, 1)} ${SYM}`);
  if (b.card) out.push(itemName({ ref: b.card }));
  if (b.pack) out.push(itemName({ kind: "pack", ref: b.pack }));
  if (b.rarity) out.push(`una ${RAR_ES[b.rarity] || b.rarity}`);
  return out.length ? out.join(" + ") : "nada";
}

/* ---------- time model: game hours run only while doors are open ---------- */
export function dayModel(clock) {
  let cum = 0;
  return (clock?.days || []).map(d => {
    const o = Date.parse(d.opens), c = Date.parse(d.closes);
    const h = isFinite(o) && isFinite(c) ? (c - o) / 3600000 : 0;
    const m = { ...d, o, c, h, start: cum }; cum += h; return m;
  });
}
export function hoursToWall(days, hrs) {
  for (const d of days) if (hrs <= d.start + d.h + 1e-9) return d.o + Math.max(0, hrs - d.start) * 3600000;
  return null;
}
export const EV = {
  duels: { c: "#FF6B6B", es: "Duelos" }, bench: { c: "#4C8DFF", es: "Prueba de mercado" }, round: { c: "#FFC44D", es: "Nueva ronda" },
  end_round: { c: "#FFC44D", es: "Fin de ronda" }, set_release: { c: "#3BB273", es: "Sale un barrio" }, grant_all: { c: "#3DDC97", es: "Reparto para todos" },
  announce: { c: "#8E99B8", es: "Anuncio" }, persona: { c: "#E07A5F", es: "Nuevo vendedor" }, day_opens: { c: "#5D688A", es: "Abre" }, day_closes: { c: "#5D688A", es: "Cierra" },
};
export const evInfo = a => EV[a] || { c: "#8E99B8", es: String(a || "Evento").replace(/_/g, " ") };
export function evLabel(e, sets) {
  const inf = evInfo(e.action);
  if (e.action === "set_release" && sets[e.params?.set]) return `Sale ${sets[e.params.set].name}`;
  if ((e.action === "duels" || e.action === "round") && e.params?.name) return e.params.name;
  if (e.action === "day_opens") return `Abre ${DAY_ES[e.params?.day] || ""}`;
  if (e.action === "day_closes") return `Cierra ${DAY_ES[e.params?.day] || ""}`;
  return inf.es;
}
export function timelineHTML(clock, sched) {
  const days = dayModel(clock);
  const total = days.reduce((a, d) => a + d.h, 0);
  if (!days.length || !total) return `<div class="empty">El servidor no ha publicado el calendario.</div>`;
  const nowH = num(sched?.now_hours) ?? num(clock.t_hours) ?? 0;
  const ups = (sched?.upcoming || []).filter(e => num(e.at_hours) != null);
  const gap = 6, n = days.length;
  const pos = h => {
    let i = days.findIndex(d => h <= d.start + d.h + 1e-9); if (i < 0) i = n - 1;
    const d = days[i], f = (d.start + (d.h ? Math.min(1, Math.max(0, (h - d.start) / d.h)) : 0) * d.h) / total;
    return `calc(${(100 * f).toFixed(3)}% + ${(gap * i - gap * (n - 1) * f).toFixed(2)}px)`;
  };
  const dayEls = days.map(d => {
    const f = Math.min(1, Math.max(0, (nowH - d.start) / (d.h || 1)));
    return `<div class="tl-day" style="flex:${d.h} 1 0"><div class="fill" style="width:${(f * 100).toFixed(2)}%"></div>
      <div class="lbl">${esc(DAY_ES[d.day] || d.name)} <span>${esc(wallStr(d.o, tz))}–${esc(wallStr(d.c, tz))}</span></div></div>`;
  }).join("");
  const evs = ups.filter(e => !/^day_/.test(e.action)).map(e => {
    const inf = evInfo(e.action), w = hoursToWall(days, e.at_hours);
    const tip = `${inf.es}: ${e.note || ""}${w ? " · ≈ " + wallStr(w) : ""}`;
    return `<span class="tl-ev ${e.at_hours < nowH ? "past" : ""}" style="left:${pos(e.at_hours)};--c:${inf.c}" title="${esc(tip)}"></span>`;
  }).join("");
  const hours = days.map(d => `<div style="flex:${d.h} 1 0"><span>${esc(new Date(d.o).getHours())}h</span><span>${esc(new Date(d.c).getHours())}h</span></div>`).join("");
  return `<div class="tl">${evs}<div class="tl-days">${dayEls}</div><div class="tl-now" style="left:${pos(nowH)}"></div><div class="tl-hours">${hours}</div></div>`;
}
export function eventsListHTML(clock, sched, { limit = 6, includePast = false } = {}) {
  const days = dayModel(clock), sets = catIndex().sets;
  const nowH = num(sched?.now_hours) ?? 0;
  let ups = (sched?.upcoming || []).filter(e => num(e.at_hours) != null && e.action !== "day_opens");
  if (!includePast) ups = ups.filter(e => e.at_hours >= nowH);
  return ups.slice(0, limit).map(e => {
    const inf = evInfo(e.action), w = hoursToWall(days, e.at_hours);
    const rel = e.at_hours >= nowH ? `en ${fmt(e.at_hours - nowH, 1)} h de juego` : "ya pasó";
    return `<li class="${e.at_hours < nowH ? "past" : ""}" style="--c:${inf.c}"><i></i><div><span class="when">${esc(w ? "≈ " + wallStr(w, { weekday: "long", ...tz }) + " · " : "")}${esc(rel)}</span><b>${esc(evLabel(e, sets))}</b><span class="note">${esc(e.note || "")}</span></div></li>`;
  }).join("") || `<li class="empty">No queda nada programado.</li>`;
}

/* ---------- markdown (escape first, then a small safe subset) ---------- */
export const slug = s => String(s).toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/<[^>]+>/g, "").replace(/&[a-z#0-9]+;/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "s";
export function mdInline(s) {
  const codes = [];
  s = s.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, t, u) => {
    const url = u.replace(/&amp;/g, "&");
    if (/^https?:\/\//i.test(url)) return `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${t}</a>`;
    if (url.startsWith("#")) return `<a href="#intel" data-anchor="${esc(slug(url.slice(1)))}">${t}</a>`;
    return t;
  });
  s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, (m, p, u) => `${p}<a href="${u}" target="_blank" rel="noopener noreferrer">${u}</a>`);
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/__([^_]+)__/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>").replace(/(^|[\s(])_([^_\s][^_]*)_(?=[\s.,;:)!?]|$)/g, "$1<em>$2</em>");
  s = s.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[+i]}</code>`);
}
export function md(src, { headingIds = true } = {}) {
  const lines = esc(String(src || "").replace(/\r\n?/g, "\n")).split("\n");
  const out = [], toc = [];
  const used = {};
  let i = 0;
  const isTableSep = l => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);
  const cells = l => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(c => mdInline(c.trim()));
  while (i < lines.length) {
    const l = lines[i];
    if (/^\s*```/.test(l)) {
      const buf = []; i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) buf.push(lines[i++]);
      i++; out.push(`<pre><code>${buf.join("\n")}</code></pre>`); continue;
    }
    let m;
    if ((m = l.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/))) {
      const lvl = m[1].length, html = mdInline(m[2]);
      let id = slug(m[2]); used[id] = (used[id] || 0) + 1; if (used[id] > 1) id += "-" + used[id];
      if (lvl <= 3) toc.push({ lvl, id, html });
      out.push(`<h${lvl}${headingIds ? ` id="md-${id}"` : ""}>${html}</h${lvl}>`); i++; continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(l)) { out.push("<hr>"); i++; continue; }
    if (l.includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      const head = cells(l); i += 2; const rows = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(cells(lines[i++]));
      out.push(`<table><thead><tr>${head.map(c => `<th>${c}</th>`).join("")}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
      continue;
    }
    if (/^\s*&gt;\s?/.test(l)) {
      const buf = [];
      while (i < lines.length && /^\s*&gt;\s?/.test(lines[i])) buf.push(lines[i++].replace(/^\s*&gt;\s?/, ""));
      out.push(`<blockquote>${md(buf.join("\n").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'"), { headingIds: false }).html}</blockquote>`);
      continue;
    }
    if (/^\s*([-*+]|\d+[.)])\s+/.test(l)) {
      /* nested lists by indentation */
      const stack = [];
      const open = (type, ind) => { out.push(type === "ol" ? "<ol>" : "<ul>"); stack.push({ type, ind }); };
      while (i < lines.length && (/^\s*([-*+]|\d+[.)])\s+/.test(lines[i]) || (/^\s{2,}\S/.test(lines[i]) && stack.length))) {
        const li = lines[i];
        const mm = li.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
        if (!mm) { out.push(" " + mdInline(li.trim())); i++; continue; }
        const ind = mm[1].length, type = /\d/.test(mm[2]) ? "ol" : "ul";
        while (stack.length && ind < stack[stack.length - 1].ind) { out.push("</li>" + (stack.pop().type === "ol" ? "</ol>" : "</ul>")); }
        if (!stack.length || ind > stack[stack.length - 1].ind) open(type, ind);
        else out.push("</li>");
        let body = mdInline(mm[3]).replace(/^\[ \]\s/, "☐ ").replace(/^\[x\]\s/i, "☑ ");
        out.push(`<li>${body}`); i++;
      }
      while (stack.length) out.push("</li>" + (stack.pop().type === "ol" ? "</ol>" : "</ul>"));
      continue;
    }
    if (!l.trim()) { i++; continue; }
    const buf = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\s*```|\s*([-*+]|\d+[.)])\s+|\s*&gt;)/.test(lines[i]) && !(lines[i].includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1]))) buf.push(lines[i++]);
    out.push(`<p>${mdInline(buf.join(" "))}</p>`);
  }
  return { html: out.join("\n"), toc };
}
export function parseLog(src) {
  if (!src) return { intro: "", entries: [] };
  const parts = String(src).replace(/\r\n?/g, "\n").split(/^(?=## )/m);
  const entries = [];
  let intro = "";
  for (const p of parts) {
    const m = p.match(/^## (.*)\n?([\s\S]*)$/);
    if (!m) { intro += p; continue; }
    const head = m[1].trim();
    const hm = head.match(/^(\d{4}-\d{2}-\d{2}(?:[ T]\d{1,2}:\d{2})?)\s*(?:[—–-]+\s*)?(.*)$/);
    entries.push({ when: hm ? hm[1] : "", title: hm ? (hm[2] || hm[1]) : head, body: m[2].trim(), key: head });
  }
  return { intro: intro.replace(/^#\s.*\n?/, "").trim(), entries };
}
export function logEntryHTML(e, isNew) {
  let when = e.when;
  const t = Date.parse(e.when.replace(" ", "T"));
  if (isFinite(t)) when = new Date(t).toLocaleString("es-ES", { weekday: "short", day: "numeric", ...tz });
  return `<article class="logentry ${isNew ? "new" : ""}"><time>${esc(when)}</time><h3>${mdInline(esc(e.title))}</h3><div class="md">${md(e.body, { headingIds: false }).html}</div></article>`;
}

/* ---------- feed formatting (mirrors the official event wording) ---------- */
export const TONE = { good: "var(--good)", gold: "var(--gold)", info: "var(--info)", warn: "var(--warn)", accent: "var(--bad)", muted: "var(--faint)", neutral: "var(--text)" };
export const FEED_CATS = [
  { k: "all", es: "Todo", c: "var(--text)" }, { k: "trade", es: "Tratos y mercado", c: "var(--good)" }, { k: "talk", es: "Negociaciones", c: "var(--info)" },
  { k: "duel", es: "Duelos", c: "var(--bad)" }, { k: "team", es: "Equipos", c: "var(--gold)" }, { k: "news", es: "Anuncios", c: "var(--warn)" }, { k: "clock", es: "Reloj y rondas", c: "var(--faint)" },
];
export function feedCat(t) {
  if (/^(settlement|offer\.|pack\.|venue\.|bench\.)/.test(t)) return "trade";
  if (/^thread\./.test(t)) return "talk";
  if (/^duel/.test(t)) return "duel";
  if (/^(team\.|level\.unlocked|badge\.|egg\.|gift\.|admin\.|persona\.)/.test(t)) return "team";
  if (/^(announcement|level\.announced|level\.activated|set\.released)/.test(t)) return "news";
  return "clock";
}
export function feedText(e) {
  const n = e.payload || {}, nm = nameOf, $s = v => `${fmt(v, 1)} ${SYM}`;
  const items = arr => (arr || []).map(itemName).join(", ");
  switch (e.type) {
    case "settlement": {
      const parties = n.parties || [], it = items(n.items) || "dinero";
      if (n.kind === "gift") return [`${nm(n.persona)} regala ${it} a ${nm(parties[0])}`, "gold", parties];
      if (n.kind === "egg" || n.kind === "grant") return [`${nm(parties[0])} recibe ${it}`, "gold", parties];
      return [`${nm(parties[0])} ⇄ ${nm(parties[1])}: ${it}${num(n.price) ? ` por ${$s(n.price)}` : ""}${n.venue && n.venue !== "rastro" ? ` en ${nm(n.venue)}` : ""}${num(n.fee) ? ` · comisión ${$s(n.fee)}` : ""}`, "good", parties];
    }
    case "pack.opened": return [`${n.name || nm(n.team)} abre ${itemName({ kind: "pack", ref: n.pack })}: ${(n.cards || []).length} cromos${n.best ? `, el mejor ${itemName(n.best)}` : ""}`, ["epic", "legendary"].includes(n.best?.rarity) ? "gold" : "neutral", [n.team]];
    case "thread.opened": return [`${nm(n.team)} abre una negociación con ${nm(n.with)}${n.topic?.buy ? ` para comprar ${bundle(n.topic.buy)}` : n.topic?.sell?.assets?.length ? ` para vender ${n.topic.sell.assets.length} cromo(s)` : ""}`, "muted", [n.team]];
    case "thread.message": return [`${nm(n.sender)}: ${n.text ? `“${String(n.text).slice(0, 140)}”` : "(sin palabras)"}${n.offer ? ` — ofrece ${bundle(n.offer.give)} por ${bundle(n.offer.want)}` : ""}`, "neutral", [n.team, n.sender]];
    case "offer.listed": return [`${nm(n.offer?.maker)} publica ${bundle(n.offer?.give)} por ${bundle(n.offer?.want)} en ${nm(n.venue)}`, "info", [n.offer?.maker]];
    case "offer.cancelled": return [`Oferta #${n.offer} retirada${n.venue ? ` de ${nm(n.venue)}` : ""}`, "muted", []];
    case "team.joined": return [`${n.name || nm(n.team)} entra en el Bazaar`, "info", [n.team]];
    case "team.granted": return [`${nm(n.team)} recibe ${n.cards} cromos iniciales`, "muted", [n.team]];
    case "level.unlocked": return [`${n.name || nm(n.team)} desbloquea a ${n.persona_name || nm(n.persona)} — ahora nivel ${n.level}`, "gold", [n.team]];
    case "persona.open_to_all": return [`${n.name || nm(n.persona)} (nivel ${n.level}) ya trata con todos`, "gold", []];
    case "persona.updated": return [`${n.name || nm(n.persona)} actualizado a v${n.version}${n.note ? ` — ${n.note}` : ""}`, "info", []];
    case "persona.strike": return [`${nm(n.persona)} da un aviso a ${nm(n.team)} (${(n.kinds || []).join(", ")}) — ${n.strikes} en total`, "warn", [n.team]];
    case "persona.cooloff": return [`${n.name || nm(n.persona)} echa a ${n.team_name || nm(n.team)} hasta T${n.until_tick}`, "warn", [n.team]];
    case "egg.found": return [`${n.name || nm(n.team)} encuentra un huevo de pascua en el puesto de ${nm(n.persona)}`, "gold", [n.team]];
    case "badge.awarded": return [`${n.name || nm(n.team)} gana la insignia “${n.badge}”`, "gold", [n.team]];
    case "gift.given": case "egg.given": case "admin.grant": {
      const r = [n.cash ? $s(n.cash) : "", ...(n.packs || []).map(p => itemName({ kind: "pack", ref: p })), ...(n.cards || []).map(c => itemName({ ref: c }))].filter(Boolean);
      return [`${n.name || nm(n.team)} recibe ${r.join(", ") || "un regalo"}${n.reason ? ` — ${n.reason}` : ""}`, e.type === "admin.grant" ? "info" : "gold", [n.team]];
    }
    case "admin.adjustment": return [`${nm(n.team)}: ${n.kind === "penalty_pct" ? `penalización del ${fmt(n.amount)}%` : `${num(n.amount) >= 0 ? "+" : ""}${fmt(n.amount)} puntos`} (${n.component})${n.reason ? ` — ${n.reason}` : ""}`, n.kind === "penalty_pct" ? "accent" : "good", [n.team]];
    case "admin.freeze": return [`${nm(n.team)} ${n.frozen ? "congelado" : "descongelado"} por la organización`, n.frozen ? "accent" : "info", [n.team]];
    case "admin.key_rotated": return [`${nm(n.team)} tiene una clave nueva`, "muted", [n.team]];
    case "announcement": return [n.text || "Anuncio", "info", []];
    case "level.announced": return [`Próximamente: ${n.name}${n.teaser ? ` — ${n.teaser}` : ""}`, "gold", []];
    case "level.activated": return [`${n.name} ya está abierto${num(n.opens_to_all_in_hours) > 0 ? `: para quien lo ganó; para todos en ${fmt(n.opens_to_all_in_hours, 1)} h` : ""}`, "gold", []];
    case "venue.opened": return [`${nm(n.owner)} abre el mercado “${n.name}” — comisión ${fmt((num(n.fee_bps) || 0) / 100, 2)}%${num(n.fee_per_card) ? ` + ${$s(n.fee_per_card)}/cromo` : ""}, fianza ${$s(n.bond)}`, "gold", [n.owner]];
    case "venue.fee_announced": return [`${nm(n.venue)} cobrará ${fmt((num(n.fee_bps) || 0) / 100, 2)}% desde T${n.effective_tick}`, "info", []];
    case "venue.fee_changed": return [`${nm(n.venue)} ahora cobra ${fmt((num(n.fee_bps) || 0) / 100, 2)}%`, "info", []];
    case "venue.closing": return [`${nm(n.venue)} cierra; la fianza vuelve en T${n.refund_at_tick}`, "muted", []];
    case "venue.closed": return [`${nm(n.venue)} cerrado; ${$s(n.refund)} de fianza devueltos`, "muted", []];
    case "venue.suspended": return [`${n.name || nm(n.venue)} suspendido: ${n.reason}${num(n.slashed) ? ` — pierde ${$s(n.slashed)} de fianza` : ""}`, "accent", []];
    case "venue.reopened": return [`${n.name || nm(n.venue)} reabre`, "good", []];
    case "venue.announcement": return [`${n.name || nm(n.venue)}: “${n.text}”`, "info", []];
    case "round.started": return [`Empieza la ronda ${n.round} “${n.name}”${num(n.weight) === 1 ? "" : ` (peso ${n.weight})`}${n.reset ? " — se reinician las colecciones" : ""}`, "gold", []];
    case "round.ended": return [`Termina la ronda ${n.round} “${n.name}”`, "info", []];
    case "round.voided": return [`Ronda ${n.round} “${n.name}” anulada: ya no cuenta`, "accent", []];
    case "round.weight": return [`La ronda ${n.round} ahora pesa ${n.weight}`, "info", []];
    case "set.released": return [`Nuevo barrio: ${n.name} (${n.cards} cromos)`, "gold", []];
    case "day.opened": return [`${DAY_ES[n.day] || n.name || "El Bazaar"} abre: un tick cada ${fmt(n.tick_seconds)} s`, "gold", []];
    case "day.closed": return [n.reopens ? `Cerrado hasta ${wallStr(Date.parse(n.reopens))}` : "El Bazaar ha cerrado", "info", []];
    case "calendar.switched": return [n.calendar_on ? "Vuelve el horario de apertura" : "Horario desactivado: el reloj corre hasta que lo paren", "warn", []];
    case "calendar.changed": return ["Ha cambiado el horario de apertura", "warn", []];
    case "clock.changed": return [n.paused ? "El reloj está en pausa" : `El reloj marca un tick cada ${fmt(n.tick_seconds)} s`, n.paused ? "warn" : "info", []];
    case "tick": return [`Tick ${n.tick ?? e.tick}`, "muted", []];
    case "flag.raised": return [`${nm(n.team)} denuncia el mensaje #${n.message}`, "warn", [n.team]];
    case "settlement.failed": return [`Falló una liquidación: ${n.reason}`, "accent", []];
    case "schedule.fired": return [n.note || `Programado: ${n.action}`, "info", []];
    case "schedule.failed": return [`Falló lo programado (${n.action}): ${n.error}`, "accent", []];
    case "duels.scheduled": return [`Duelos “${n.name}”: ${n.duels} negociaciones uno contra uno`, "gold", []];
    case "duels.finished": return [`Terminan los duelos “${n.name}”`, "info", []];
    case "duel.started": return [`Empieza el duelo #${n.duel} — somos ${n.role === "buyer" ? "compradores" : n.role === "seller" ? "vendedores" : n.role}`, "gold", []];
    case "duel.message": return [`${n.from}: “${String(n.text || "").slice(0, 140)}”${num(n.price) != null ? ` — ${$s(n.price)}` : ""}`, "neutral", []];
    case "duel.closed": return [`Duelo #${n.duel} por ${n.item}: ${n.status === "deal" ? "trato" : "sin trato"}`, n.status === "deal" ? "good" : "muted", []];
    case "duel.result": return [`Duelo #${n.duel}: ${n.status === "deal" ? `trato a ${$s(n.price)}, capturamos ${fmt(n.you_captured, 1)}` : "sin trato"}`, n.status === "deal" ? "good" : "muted", []];
    case "bench.started": return [`Prueba de mercado “${n.name}” en ${(n.venues || []).length} mercados`, "gold", []];
    case "bench.finished": return [`${nm(n.venue)} termina la prueba: eficiencia ${fmt(100 * (num(n.efficiency) || 0), 0)}%, ${n.matches} cruces`, "good", []];
    default: return [n.text ? String(n.text) : `${String(e.type || "evento").replace(/[._]/g, " ")}${e.actor ? ` · ${nm(e.actor)}` : ""}`, n.text ? "info" : "muted", []];
  }
}
export function feedHTML(events, { cat = "all", limit = 40, markFresh = false } = {}) {
  const meId = D("me")?.id;
  const seen = state.seenFeed;
  const list = [...(events || [])].sort((a, b) => (b.id ?? 0) - (a.id ?? 0)).filter(e => cat === "all" || feedCat(e.type) === cat).slice(0, limit);
  return list.map(e => {
    let txt, tone, who;
    try { [txt, tone, who] = feedText(e); } catch { txt = String(e.type); tone = "muted"; who = []; }
    const us = meId && (who || []).includes(meId) || (meId && e.actor === meId);
    const fresh = markFresh && seen && !seen.has(e.id);
    return `<li class="${us ? "us" : ""} ${fresh ? "fresh" : ""}" style="--c:${TONE[tone] || TONE.muted}"><span class="tk">t${esc(e.tick)}</span><i></i><span>${esc(txt)}</span></li>`;
  }).join("") || `<li class="empty" style="display:block">Aún no ha pasado nada aquí.</li>`;
}

/* ---------- album helpers ---------- */
export function ownedIndex(me) {
  const by = {};
  for (const a of me?.assets || []) if (a.kind === "card" && a.ref) (by[a.ref] ||= []).push(a);
  for (const k in by) by[k].sort((a, b) => (a.serial ?? 1e9) - (b.serial ?? 1e9));
  return by;
}
export function buyTargets(me, catalog, owned) {
  const out = [];
  for (const set of catalog.sets || []) {
    if (!set.released) continue;
    const page = (me.album?.pages || []).find(p => p.set === set.id) || {};
    const aff = num(me.affinity?.[set.id]) ?? 1;
    for (const c of set.cards || []) {
      if (owned[c.id] || c.hidden || !c.page) continue;
      const est = (num(c.book) || 0) * aff;
      const closeness = page.of ? (page.have || 0) / page.of : 0;
      out.push({ set, card: c, aff, est, missing: (page.of || 0) - (page.have || 0), score: est * (1 + closeness) * (aff >= 1 ? 1.2 : 0.6) });
    }
  }
  return out.sort((a, b) => b.score - a.score);
}
export const patFor = i => `repeating-linear-gradient(${[135, 45, 90, 0, 60, 120][i % 6]}deg, rgba(255,255,255,.10) 0 3px, transparent 3px 9px)`;
export const releaseEs = r => String(r || "").startsWith("sat") ? "el sábado" : String(r || "").startsWith("sun") ? "el domingo" : String(r || "");
/* One cromo. mode: "album" (owned face or empty slot) or "catalogue" (always the face). */
export function cromoHTML(c, set, si, mine, rar, { mode = "album", target = false, fresh = false } = {}) {
  const r = rk(c.rarity), rc = col(rar[r]?.color, `var(--r-${r})`), sc = col(set.color);
  const no = String(c.id).split("-").pop();
  const name = c.hidden ? "???" : c.name;
  const minted = num(c.minted), run = num(c.print_run);
  const tip = `${c.id} · ${name} · ${RAR_ES[r]} · book ${c.book} ${SYM}${run ? ` · ${minted ?? 0}/${run} acuñados` : ""}`;
  if (mode === "album" && !mine.length) {
    return `<button type="button" data-card="${esc(c.id)}" class="cromo miss r-${r} ${c.page ? "" : "extra"} ${target ? "target" : ""}" style="--rc:${rc};--sc:${sc}" title="${esc(tip)}">
      <span class="num">${esc(no)}</span><span class="nm">${esc(name)}</span><i class="gem"></i><span class="bk">${esc(fmt(c.book, 0))} ${esc(SYM)}</span></button>`;
  }
  const best = mine[0], yv = num(best?.your_value), bk = num(c.book) || 0;
  const cls = yv == null ? "" : yv >= bk ? "up" : "down";
  const lock = mode === "catalogue" && !set.released ? `<span class="lockov">Sale ${esc(releaseEs(set.release))}</span>` : "";
  return `<button type="button" data-card="${esc(c.id)}" class="cromo face r-${r} ${mine.length > 1 ? "dup" : ""} ${mine.length > 2 ? "dup3" : ""} ${c.page ? "" : "extra"} ${c.hidden ? "hiddencard" : ""} ${mode === "catalogue" && !mine.length ? "notours" : ""} ${fresh ? "fresh" : ""}"
    style="--rc:${rc};--sc:${sc};--pat:${patFor(si)}" title="${esc(tip)}">
    ${mine.length > 1 ? `<span class="qty" aria-label="${mine.length} copias">×${mine.length}</span>` : ""}
    <span class="band"><span>${esc(set.id)}</span><span>${esc(no)}</span></span>
    <span class="art"><span class="num">${c.hidden ? "?" : esc(no)}</span></span>
    <span class="nm">${esc(name)}</span>
    <span class="foot"><span><i class="gem"></i></span><span>${best ? `#${esc(best.serial)}/${esc(best.print_run ?? run ?? "")}` : `${esc(fmt(run, 0))} ej.`}</span></span>
    ${run ? `<span class="mint"><i style="width:${pct(minted || 0, run)}%"></i></span>` : ""}
    <span class="vals">${best ? `<span>nos <b class="${cls}">${esc(fmt(yv, 1))}</b></span>` : `<span>${esc(RAR_ES[r])}</span>`}<span>bk ${esc(fmt(bk, 0))}</span></span>
    ${lock}
  </button>`;
}

/* ---------- shared panels ---------- */
export function heroHTML() {
  return `<header class="wrap hero">
    <div class="plaque">
      <div class="rankbadge" id="rankbadge" hidden><small>puesto</small><b id="rank">–</b></div>
      <div class="kicker">The Bazaar · Madrid</div>
      <h1 id="team">Nuestro equipo</h1>
      <div class="sub" id="team-sub">Cargando datos del juego…</div>
    </div>
    <div class="kpis">
      <div class="kpi k-score"><b id="k-score">–</b><span>Puntos</span><span class="spark"><i id="k-score-bar" style="width:0"></i></span></div>
      <div class="kpi k-cash"><b id="k-cash">–</b><span>Primas en caja</span></div>
      <div class="kpi k-val"><b id="k-val">–</b><span>Valor de la colección para nosotros</span></div>
      <div class="kpi k-album"><b id="k-album">–</b><span id="k-album-l">Huecos del álbum llenos</span><span class="spark"><i id="k-album-bar" style="width:0;background:var(--good)"></i></span></div>
    </div>
  </header>`;
}
export function fillHero(me, lb) {
  if (!me || !$("team")) return;
  const s = me.score || {};
  $("team").textContent = me.name || me.id || "Nuestro equipo";
  const unl = (me.unlocked || []).length;
  $("team-sub").textContent = `${me.id ?? ""} · nivel ${me.level ?? "–"} · ${unl} vendedor${unl === 1 ? "" : "es"} desbloqueado${unl === 1 ? "" : "s"}${me.frozen ? " · equipo congelado" : ""}`;
  if (s.rank) { $("rankbadge").hidden = false; setVal("rank", `${s.rank}º`); }
  setVal("k-score", fmt(s.score, 2));
  const top = Math.max(0, ...((lb?.teams) || []).map(t => num(t.score) || 0));
  if ($("k-score-bar")) $("k-score-bar").style.width = (top > 0 ? pct(s.score || 0, top) : 0) + "%";
  setVal("k-cash", `${fmt(me.cash, 0)} ${SYM}`);
  setVal("k-val", `${fmt(me.collection_value, 1)} ${SYM}`);
  const al = me.album || {};
  setVal("k-album", `${al.filled ?? "–"} / ${al.slots ?? "–"}`);
  if ($("k-album-l")) $("k-album-l").textContent = `Huecos del álbum llenos · ${s.pages_complete ?? 0} páginas completas`;
  if ($("k-album-bar")) $("k-album-bar").style.width = pct(al.filled || 0, al.slots || 0) + "%";
}
export function weekendHTML(clock, sched, { limit = 6 } = {}) {
  if (!clock) return `<div class="skeleton">Cargando calendario…</div>`;
  const rnd = (sched?.rounds || []).find(r => r.status === "active");
  return `<div class="wk-head"><h2>El fin de semana</h2><span class="count" data-cd="day"></span>
      ${rnd ? `<span class="count">Ronda <b>${esc(rnd.round)}</b> <span>${esc(rnd.name || "")} · peso ×${esc(fmt(rnd.weight, 2))}</span></span>` : ""}</div>
    ${timelineHTML(clock, sched)}<ul class="nextev">${eventsListHTML(clock, sched, { limit })}</ul>`;
}
export function tradeHTML(me, catalog, dealers) {
  const owned = ownedIndex(me);
  const { sets, cards: cardById, rar } = catIndex();
  const mini = (ref, rarity, ghost) => {
    const set = sets[String(ref).split("-")[0]]; const r = rk(rarity);
    return `<span class="mini ${ghost ? "ghost" : ""}" style="--sc:${col(set?.color)};--rc:${col(rar[r]?.color, `var(--r-${r})`)}">${esc(String(ref).split("-").pop())}</span>`;
  };
  const sell = [];
  for (const [ref, list] of Object.entries(owned)) if (list.length > 1) for (const a of list.slice(1))
    sell.push({ a, why: `Repetida (tenemos ${list.length}); nos quedamos la #${list[0].serial}`, ratio: (num(a.your_value) || 0) / (num(cardById[ref]?.book) || 1) });
  const ids = new Set(sell.map(x => x.a.id));
  for (const list of Object.values(owned)) for (const a of list) {
    if (ids.has(a.id)) continue;
    const bk = num(cardById[a.ref]?.book), yv = num(a.your_value);
    if (bk && yv != null && yv < 0.5 * bk) sell.push({ a, why: `Para nosotros vale el ${fmt(100 * yv / bk, 0)}% del book (afinidad ×${fmt(me.affinity?.[a.set], 2)})`, ratio: yv / bk });
  }
  sell.sort((x, y) => x.ratio - y.ratio);
  const dealerPrice = {};
  for (const p of dealers?.personas || []) for (const s of p.menu?.sells || []) {
    if (!s.rarity) continue;
    if (!dealerPrice[s.rarity] || s.list_price < dealerPrice[s.rarity].price) dealerPrice[s.rarity] = { price: s.list_price, who: p.name };
  }
  const buys = buyTargets(me, catalog, owned).slice(0, 8);
  const sellHtml = sell.slice(0, 10).map(({ a, why }) => `<button type="button" class="tc" data-card="${esc(a.ref)}">${mini(a.ref, a.rarity)}<span class="t"><b>${esc(a.ref)} ${esc(a.name)}</b> <span class="muted">#${esc(a.serial)}/${esc(a.print_run)}</span><small>${esc(why)}</small></span>
      <span class="n"><b>${esc(fmt(a.your_value, 1))} ${esc(SYM)}</b>book ${esc(fmt(cardById[a.ref]?.book, 0))}</span></button>`).join("") || `<div class="empty">Sin repetidas ni cromos de bajo valor ahora mismo.</div>`;
  const buyHtml = buys.map(t => {
    const dp = dealerPrice[t.card.rarity];
    return `<button type="button" class="tc" data-card="${esc(t.card.id)}">${mini(t.card.id, t.card.rarity, true)}<span class="t"><b>${esc(t.card.id)} ${esc(t.card.name)}</b><small>${esc(t.set.name)} · afinidad ×${esc(fmt(t.aff, 2))} · faltan ${esc(t.missing)} para la página${dp ? ` · ${esc(dp.who)} lo vende a ${esc(dp.price)} ${esc(SYM)}` : ""}</small></span>
      <span class="n"><b>≈ ${esc(fmt(t.est, 1))} ${esc(SYM)}</b>book ${esc(fmt(t.card.book, 0))}</span></button>`;
  }).join("") || `<div class="empty">No falta ningún cromo en los barrios publicados.</div>`;
  return `<div class="tc-group"><h3 style="--c:var(--bad)"><span class="dot"></span>Vender o cambiar · ${sell.length}</h3>${sellHtml}</div>
    <div class="tc-group"><h3 style="--c:var(--good)"><span class="dot"></span>Comprar · los ${buys.length} huecos que más nos valen</h3>${buyHtml}</div>`;
}
export function lbBarsHTML(lb, meId, key = "score", limit = 99) {
  const teams = [...(lb?.teams || [])].sort((a, b) => (num(b[key]) || 0) - (num(a[key]) || 0) || (a.rank || 99) - (b.rank || 99));
  const max = Math.max(1e-9, ...teams.map(t => num(t[key]) || 0));
  let shown = teams.slice(0, limit);
  const mine = teams.find(t => t.team === meId);
  if (mine && !shown.includes(mine)) shown = [...shown, mine];
  return shown.map(t => {
    const me = t.team === meId, v = num(t[key]) || 0;
    const label = key === "album_filled" ? `${t.album_filled}/${t.album_slots}` : key === "score" ? fmt(v, 2) : fmt(v, 1);
    return `<span class="lab ${me ? "me" : ""}">${esc(t.rank)}. ${esc(t.name)}${t.frozen ? " (congelado)" : ""}</span>
      <span class="tr"><i style="width:${max > 1e-9 ? pct(v, max) : 0}%;background:${me ? "var(--gold)" : "#3A4A7E"}"></i></span>
      <span class="v ${me ? "me" : ""}">${esc(label)}</span>`;
  }).join("") || `<div class="empty">Aún no hay clasificación.</div>`;
}
export function scoreHTML(me, sched) {
  const s = me.score || {}, w = sched?.weights || D("lb")?.weights || {};
  const parts = [
    { k: "neg_points", es: "Negociación", c: "#E4572E" }, { k: "mm_points", es: "Creador de mercado", c: "#4C8DFF" },
    { k: "duel_points", es: "Duelos", c: "#FF6B6B" }, { k: "ladder_points", es: "Escalera", c: "#B061FF" }, { k: "bench_points", es: "Prueba de mercado", c: "#3DDC97" },
  ];
  const tot = parts.reduce((a, p) => a + Math.max(0, num(s[p.k]) || 0), 0);
  return `<div class="comp">
      <div><b>${esc(fmt(s.negotiating, 2))}</b><span>Negociación${w.negotiating ? ` · peso ${esc(fmt(w.negotiating, 0))}` : ""}</span></div>
      <div><b>${esc(fmt(s.market, 2))}</b><span>Mercado${w.market ? ` · peso ${esc(fmt(w.market, 0))}` : ""}</span></div>
      <div><b>${esc(fmt(s.deals, 0))}</b><span>Tratos cerrados</span></div>
    </div>
    <div class="subh">Puntos por fuente</div>
    <div class="seg" role="img" aria-label="Reparto de puntos">${tot > 0 ? parts.map(p => `<i style="width:${pct(Math.max(0, num(s[p.k]) || 0), tot)}%;background:${p.c}" title="${esc(p.es)}"></i>`).join("") : ""}</div>
    <div class="seg-legend">${parts.map(p => `<span style="--c:${p.c}">${esc(p.es)} <b>${esc(fmt(s[p.k] ?? 0, 2))}</b></span>`).join("")}</div>
    ${tot > 0 ? "" : `<div class="empty" style="padding-top:0">Todavía no hemos sumado puntos: cerrar tratos y jugar duelos los mueve.</div>`}
    ${s.rarest ? `<div class="muted" style="font-size:13px">Nuestro cromo más raro: <b style="color:var(--text)">${esc(s.rarest.ref)} ${esc(s.rarest.name)}</b> #${esc(s.rarest.serial)}/${esc(s.rarest.print_run)}</div>` : ""}`;
}
export function valueHTML(me, catalog) {
  const { rar, cards } = catIndex();
  const bySet = {}, byRar = {}; let tot = 0, totBook = 0;
  for (const a of me.assets || []) {
    const v = Math.max(0, num(a.your_value) || 0); tot += v; totBook += num(cards[a.ref]?.book) || 0;
    bySet[a.set] = (bySet[a.set] || 0) + v; byRar[a.rarity] = (byRar[a.rarity] || 0) + v;
  }
  const cv = num(me.collection_value) ?? tot, bonus = cv - tot;
  const segs = items => `<div class="seg">${items.map(i => `<i style="width:${pct(i.v, tot)}%;background:${i.c}" title="${esc(`${i.l}: ${fmt(i.v)} ${SYM}`)}"></i>`).join("")}</div>
    <div class="seg-legend">${items.map(i => `<span style="--c:${i.c}">${esc(i.l)} <b>${esc(fmt(i.v, 1))}</b></span>`).join("")}</div>`;
  const setItems = (catalog.sets || []).filter(s => bySet[s.id]).map(s => ({ l: s.name, v: bySet[s.id], c: col(s.color) }));
  const rarItems = RAR.filter(r => byRar[r]).map(r => ({ l: RAR_ES[r], v: byRar[r], c: col(rar[r]?.color, `var(--r-${r})`) }));
  return `<div class="comp">
      <div><b>${esc(fmt(cv, 1))}</b><span>Para nosotros (${esc(SYM)})</span></div>
      <div><b>${esc(fmt(totBook, 0))}</b><span>Valor de catálogo</span></div>
      <div><b>${esc(fmt(bonus, 1))}</b><span>Extra por páginas y conjunto</span></div>
    </div>
    ${tot > 0 ? `<div class="subh">Por barrio (suma por cromo)</div>${segs(setItems)}<div class="subh">Por rareza</div>${segs(rarItems)}` : `<div class="empty">Aún no tenemos cromos.</div>`}`;
}
export function affinityHTML(me) {
  const { sets } = catIndex();
  const entries = Object.entries(me.affinity || {}).sort((a, b) => b[1] - a[1]);
  const max = Math.max(2, ...entries.map(e => num(e[1]) || 0));
  return entries.map(([k, v]) => {
    v = num(v) || 0; const s = sets[k];
    const one = 100 / max, x = 100 * v / max;
    return `<span class="lab" style="color:${col(s?.color, "#E8ECF6")}">${esc(s?.name || k)}</span>
      <span class="tr"><i style="left:${Math.min(x, one)}%;width:${Math.abs(x - one)}%;background:${v >= 1 ? "var(--good)" : "var(--bad)"}"></i><span class="one" style="left:${one}%"></span></span>
      <span class="v" style="color:${v >= 1 ? "var(--good)" : "var(--bad)"}">×${esc(fmt(v, 2))}</span>`;
  }).join("") || `<div class="empty">Sin datos de afinidad.</div>`;
}
export function miniSetsHTML(me, catalog) {
  const owned = ownedIndex(me);
  return (catalog.sets || []).map(set => {
    const sc = col(set.color);
    const page = (me.album?.pages || []).find(p => p.set === set.id);
    const have = page?.have ?? 0, of = page?.of ?? (set.cards || []).filter(c => c.page).length;
    const dots = (set.cards || []).map(c => `<i class="${owned[c.id] ? "on" : ""} ${c.page ? "" : "x"}" title="${esc(c.id)}"></i>`).join("");
    return `<a class="miniset" href="#album" style="--sc:${sc}">${ring(have, of, sc)}<span><h3 style="color:${sc}">${esc(set.name)}</h3>
      <small>${set.released ? `afinidad ×${esc(fmt(me.affinity?.[set.id], 2))}` : `sale ${esc(releaseEs(set.release))}`}</small><span class="dots">${dots}</span></span></a>`;
  }).join("");
}
export function logPanelHTML(log, { limit = 3, full = false } = {}) {
  if (log === undefined) return `<div class="skeleton">Cargando la bitácora…</div>`;
  if (log === null || !String(log).trim()) return `<div class="empty">La bitácora está vacía. Cuando alguien del equipo apunte algo en <b>LOG.md</b>, aparecerá aquí.</div>`;
  const { intro, entries } = parseLog(log);
  const prevSeen = state.seenLog;
  const isNew = e => prevSeen && !prevSeen.has(e.key);
  if (!entries.length) return `<div class="md">${md(log).html}</div>`;
  const top = entries.slice(0, limit), rest = entries.slice(limit);
  return `${full && intro ? `<div class="md" style="margin-bottom:14px">${md(intro, { headingIds: false }).html}</div>` : ""}
    <div class="logentries">${top.map(e => logEntryHTML(e, isNew(e))).join("")}</div>
    ${rest.length ? (full ? `<details class="older"><summary>Ver ${rest.length} entradas anteriores</summary>${rest.map(e => logEntryHTML(e, isNew(e))).join("")}</details>`
      : `<p style="margin:12px 0 0"><a href="#intel" style="font-size:13px;font-weight:600">Ver las ${entries.length} entradas de la bitácora</a></p>`) : ""}`;
}
export function rememberLog(log) { if (typeof log === "string") state.seenLog = new Set(parseLog(log).entries.map(e => e.key)); }
export function radarSVG(traits, color) {
  const keys = Object.keys(traits || {}); if (keys.length < 3) return "";
  const W = 200, cx = 100, cy = 92, R = 62, n = keys.length;
  const pt = (i, f) => { const a = -Math.PI / 2 + i / n * 2 * Math.PI; return [cx + Math.cos(a) * R * f, cy + Math.sin(a) * R * f]; };
  const poly = f => keys.map((k, i) => pt(i, typeof f === "function" ? f(k) : f).map(v => v.toFixed(1)).join(",")).join(" ");
  const ES = { patience: "paciencia", generosity: "generosidad", shrewdness: "astucia", memory: "memoria", strictness: "rigor", chattiness: "charla" };
  const labels = keys.map((k, i) => { const [x, y] = pt(i, 1.32); return `<text x="${x.toFixed(1)}" y="${(y + 3).toFixed(1)}" text-anchor="middle" font-size="10" fill="#8E99B8">${esc(ES[k] || k)}</text>`; }).join("");
  const c = col(color, "#FFC44D");
  return `<svg class="radar" viewBox="0 0 ${W} 190" role="img" aria-label="${esc(keys.map(k => `${ES[k] || k} ${fmt(traits[k], 2)}`).join(", "))}">
    ${[.25, .5, .75, 1].map(f => `<polygon points="${poly(f)}" fill="none" stroke="#27325A" stroke-width="1"/>`).join("")}
    <polygon points="${poly(k => Math.max(0, Math.min(1, num(traits[k]) || 0)))}" fill="${c}" fill-opacity=".3" stroke="${c}" stroke-width="2"/>${labels}</svg>`;
}
export function unlockText(p) {
  const u = p.unlock || {};
  if (u.always) return "Abierto desde el principio";
  if (p.open_to_all) return "Abierto a todos";
  const bits = [];
  if (u.early_deals_with) bits.push(`antes, con ${u.early_min_deals || "?"} tratos con ${nameOf(u.early_deals_with)}`);
  if (u.early_min_level) bits.push(`nivel ${u.early_min_level}`);
  if (u.open_to_all_at) bits.push(`para todos a las ${u.open_to_all_at}`);
  return bits.length ? `Se desbloquea: ${bits.join(" · ")}` : "Bloqueado";
}
export function dealerCardHTML(p, me) {
  const c = col(p.avatar?.color, "#3A4A7E");
  const unl = (me?.unlocked || []).includes(p.id);
  if (p.status === "announced") return `<article class="dcard teaser"><div class="dtop" style="--c:#FFC44D"><span class="avatar lg" style="--c:#2A2F45">?</span><div><h3>${esc(p.name || "Próximamente")}</h3><div class="muted">${esc(p.title || p.teaser || "Un vendedor nuevo llegará pronto")}</div></div></div></article>`;
  const sells = (p.menu?.sells || []).map(s => s.pack
    ? `<span class="chip">${esc(s.name)} · ${esc(s.list_price)} ${esc(SYM)} <span class="muted">(pide ${esc(s.opening_ask)}, máx ${esc(s.per_team_per_hour)}/h)</span></span>`
    : `<span class="chip">${esc(RAR_ES[s.rarity] || s.rarity)} · ${esc(s.list_price)} ${esc(SYM)}</span>`).join("");
  const buys = (p.menu?.buys || []).map(b => `<span class="chip buy">compra ${esc(RAR_ES[b.rarity] || b.rarity)}</span>`).join("");
  return `<article class="dcard"><div class="dtop" style="--c:${c}"><span class="avatar lg" style="--c:${c}">${esc(p.avatar?.initials || "")}<em>${esc(p.avatar?.emoji || "")}</em></span>
      <div><h3>${esc(p.name)}</h3><div class="muted" style="font-size:13px">${esc(p.title || "")}</div>
      <div class="chips" style="margin-top:6px"><span class="tag ${unl ? "hot" : "soon"}">${unl ? "Desbloqueado para nosotros" : "Aún no desbloqueado"}</span><span class="tag">nivel ${esc(p.level)}</span><span class="tag">${esc(p.status)}</span></div></div></div>
    <div class="dbody"><div><p class="bio">${esc(p.bio || "")}</p>
      <div class="subh">Vende</div><div class="chips">${sells || `<span class="muted">Nada</span>`}</div>
      <div class="subh" style="margin-top:8px">Compra</div><div class="chips">${buys || `<span class="muted">Nada</span>`}</div>
      <p class="muted" style="font-size:12px;margin:10px 0 0">${esc(unlockText(p))} · ${esc(p.menu?.deals_per_team_per_hour ?? "?")} tratos por hora</p>
      <button type="button" class="bigbtn" data-dealer="${esc(p.id)}" style="margin-top:10px;cursor:pointer">Ver ficha completa</button></div>
      <div>${radarSVG(p.traits, c)}</div></div></article>`;
}
export function offerRow(o, meId) {
  const give = o.give || o.sell || {}, want = o.want || o.buy || {};
  const gCash = !!give.cash && !(give.assets?.length || give.types?.length), wCash = !!want.cash && !(want.assets?.length || want.types?.length);
  const side = wCash ? ["sell", "Vende"] : gCash ? ["buy", "Compra"] : ["swap", "Cambia"];
  const mine = meId && (o.maker === meId || o.team === meId);
  return `<div class="offer ${mine ? "mine" : ""}"><span class="side ${side[0]}">${side[1]}</span>
    <span><b>${esc(bundle(give))}</b> <span class="muted">por</span> <b>${esc(bundle(want))}</b><br><small class="muted">${esc(mine ? "Nuestra oferta" : nameOf(o.maker || o.team || ""))}${o.id != null ? ` · #${esc(o.id)}` : ""}${o.tick != null ? ` · t${esc(o.tick)}` : ""}${o.status ? ` · ${esc(o.status)}` : ""}</small></span>
    <span class="muted" style="font-size:12px">${o.expires_tick != null ? `caduca t${esc(o.expires_tick)}` : ""}</span></div>`;
}

/* ---------- writes: every write goes through confirmWrite() (shows the exact JSON) ---------- */
state.writes = [];          // successful writes this session: {tick, kind, thread}
state.thread = null;        // selected thread id
state.duel = null;
state.bookVenue = null;
state.sending = false;
state.ours = []; state.oursPrev = null;
state.rankPrev = null; state.rankDelta = {};

export function send(method, path, body) {
  return new Promise(resolve => {
    Q.unshift(async () => {   // writes jump the read queue but still respect the pacing
      try {
        const headers = { Accept: "application/json", "Content-Type": "application/json", "X-Dashboard": "1" };
        const r = await fetch(path, { method, cache: "no-store", credentials: "same-origin", headers, body: body !== undefined ? JSON.stringify(body) : undefined });
        if (r.status === 401) sessionExpired();
        const txt = await r.text();
        let j; try { j = txt ? JSON.parse(txt) : {}; } catch { j = { raw: txt.slice(0, 2000) }; }
        resolve({ ok: r.ok, status: r.status, body: j });
      } catch (e) { resolve({ ok: false, status: 0, body: { error: "network", message: e.message } }); }
    });
    pump();
  });
}
export function invalidate(...paths) { for (const p of paths) { const c = cache.get(p); if (c) cache.set(p, { ...c, at: 0 }); } }
export function invalidateTeam() {
  invalidate(SRC.me[0], SRC.offers[0], SRC.threads[0], SRC.duels[0]);
  for (const k of [...cache.keys()]) if (/^\/api\/(threads\/|venues\/.+\/offers|me\/value)/.test(k)) invalidate(k);
}
export function closeModal() { document.querySelectorAll(".modal-scrim").forEach(m => { if (!m.dataset.busy) m.remove(); }); }
export function confirmWrite({ title, method, path, body, kind, thread, note }) {
  if (state.sending) return;
  closeModal();
  const tick = D("clock")?.tick;
  const scrim = document.createElement("div");
  scrim.className = "modal-scrim";
  scrim.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-labelledby="m-title">
    <h2 id="m-title">${esc(title)}</h2>
    <div class="route">${esc(method)} ${esc(path)}</div>
    <pre class="json">${esc(body === undefined ? "(sin cuerpo)" : JSON.stringify(body, null, 2))}</pre>
    ${note ? `<p style="font-size:13px">${note}</p>` : ""}
    <p class="muted" style="font-size:13px">Se envía al servidor del juego con la clave del equipo (tick actual ${esc(tick ?? "–")}). Si se acepta, se liquida en el siguiente tick.</p>
    <div class="actions"><button type="button" class="btn ghost" data-m="cancel">Cancelar</button><button type="button" class="btn" data-m="send">Confirmar y enviar</button></div>
    <div data-m="result"></div></div>`;
  document.body.appendChild(scrim);
  const sendBtn = scrim.querySelector('[data-m="send"]'), cancelBtn = scrim.querySelector('[data-m="cancel"]'), out = scrim.querySelector('[data-m="result"]');
  cancelBtn.focus();
  scrim.addEventListener("click", e => { if (e.target === scrim || e.target === cancelBtn) { if (!scrim.dataset.busy) scrim.remove(); } });
  sendBtn.addEventListener("click", async () => {
    if (state.sending || sendBtn.disabled) return;
    state.sending = true; scrim.dataset.busy = "1";
    sendBtn.disabled = true; cancelBtn.disabled = true; sendBtn.textContent = "Enviando…";
    const r = await send(method, path, body);
    state.sending = false; delete scrim.dataset.busy; cancelBtn.disabled = false; cancelBtn.textContent = "Cerrar";
    if (r.ok) {
      state.writes.push({ tick: D("clock")?.tick, kind, thread });
      if (kind === "thread" && r.body?.id != null) state.thread = r.body.id;
      sendBtn.textContent = "Enviado";
      out.innerHTML = `<div class="result ok"><b>Hecho (${esc(r.status)}).</b><pre class="json">${esc(JSON.stringify(r.body, null, 2))}</pre></div>`;
      invalidateTeam();
      cycle();
    } else {
      const code = r.body?.error || `http_${r.status}`, msg = r.body?.message || r.body?.detail || "";
      out.innerHTML = `<div class="result bad"><div class="code">${esc(code)}</div><div>${esc(typeof msg === "string" ? msg : JSON.stringify(msg))}</div>
        ${r.body?.next_tick != null ? `<div class="muted">Siguiente tick: ${esc(r.body.next_tick)}</div>` : ""}<pre class="json">${esc(JSON.stringify(r.body, null, 2))}</pre>
        ${r.status === 0 ? `<div class="muted">Sin respuesta: puede que el envío llegara. Comprueba el estado antes de repetir.</div>` : ""}</div>`;
      if (r.status !== 0) { sendBtn.disabled = false; sendBtn.textContent = "Reintentar"; } else sendBtn.textContent = "No enviado";
    }
  });
}

/* ---------- strip + countdowns ---------- */
export function renderStrip() {
  const clock = D("clock"), h = D("health");
  if (clock) {
    const open = clock.doors === "open";
    $("live").className = "live " + (!open ? "closed" : clock.paused ? "paused" : "on");
    $("live-txt").textContent = `${!open ? "Cerrado" : clock.paused ? "En pausa" : "En juego"} · ${clock.round_name || ""}`;
  }
  const hc = $("health");
  if (h) {
    const ok = h.ok ?? h.healthy ?? (typeof h.status === "string" ? /ok|healthy|up/i.test(h.status) : undefined);
    hc.hidden = false; hc.className = "hchip " + (ok === false ? "bad" : "ok");
    hc.textContent = ok === false ? "Servidor con problemas" : "Servidor OK";
    hc.title = JSON.stringify(h).slice(0, 300);
  }
}
export function tickCountdowns() {
  const c = D("clock"); const now = Date.now();
  if (c) {
    const elapsed = (now - state.clockAt) / 1000, open = c.doors === "open";
    /* local estimate between clock fetches: ticks keep coming every tick_seconds */
    let nextTick = null, estTick = num(c.tick) ?? 0;
    if (open && !c.paused && num(c.next_tick_in) != null) {
      const ts = num(c.tick_seconds) || 60, over = elapsed - c.next_tick_in;
      if (over < 0) nextTick = -over * 1000;
      else { estTick += 1 + Math.floor(over / ts); nextTick = (ts - (over % ts)) * 1000; }
    }
    state.estTick = estTick;
    $("tick-cd").textContent = `Tick ${fmt(estTick, 0)}${nextTick != null ? ` · siguiente en ${dur(nextTick)}` : c.paused ? " · reloj detenido" : ""}`;
    const closes = Date.parse(c.closes), opens = Date.parse(c.next_opens);
    const nextName = DAY_ES[(c.days || []).find(x => x.opens === c.next_opens)?.day] || c.next_name || "";
    const dayTxt = open && isFinite(closes) ? `Cierra hoy en <b>${esc(dur(closes - now))}</b> <span>(${esc(wallStr(closes, tz))})</span>`
      : isFinite(opens) ? `${esc(nextName)} abre en <b>${esc(dur(opens - now))}</b>` : "";
    document.querySelectorAll('[data-cd="day"],[data-cd="day-big"]').forEach(el => { if (el.innerHTML !== dayTxt) el.innerHTML = dayTxt; });
    document.querySelectorAll('[data-cd="tick-big"],[data-cd="tick-trade"]').forEach(el => { el.textContent = nextTick != null ? `Tick ${estTick} · ${dur(nextTick)}` : c.paused ? `Tick ${estTick} · en pausa` : open ? `Tick ${estTick}` : "Cerrado"; });
  }
  if (state.lastOk) {
    $("upd-ring").style.strokeDashoffset = String(37.7 * Math.min(1, (now - state.lastOk) / CYCLE_MS));
    const ago = Math.round((now - state.lastOk) / 1000);
    $("updated").textContent = `Actualizado hace ${ago < 2 ? "un momento" : ago + " s"}`;
  }
}
export function showErrors(errs) {
  const b = $("err");
  if (!errs.length) { b.classList.remove("show"); return; }
  const when = state.lastOk ? ` Mostrando datos de las ${new Date(state.lastOk).toLocaleTimeString("es-ES")}.` : "";
  $("err-txt").textContent = `No se pudieron cargar ${errs.length} fuente${errs.length > 1 ? "s" : ""} (${errs.slice(0, 3).join("; ")}).${when} Se reintenta en ${CYCLE_MS / 1000} s.`;
  b.classList.add("show");
}

/* ---------- drawer (card / thread / dealer detail) ---------- */
export function openDrawer(html) {
  const root = $("drawer-root");
  root.innerHTML = `<div class="scrim" data-close></div><aside class="drawer" role="dialog" aria-modal="true" aria-label="Detalle"><button type="button" class="close" data-close>Cerrar</button><div id="drawer-body">${html}</div></aside>`;
  root.querySelector(".close").focus();
}
export function closeDrawer() { $("drawer-root").innerHTML = ""; }
export const drawerBody = html => { const b = $("drawer-body"); if (b) b.innerHTML = html; };
export function historyHTML(d) {
  if (!d || typeof d !== "object") return `<div class="empty">Sin historial.</div>`;
  const arr = Array.isArray(d) ? d : (d.history || d.events || d.provenance || d.moves || Object.values(d).find(Array.isArray) || []);
  const head = Array.isArray(d) ? "" : kv(d.card || d);
  const rows = arr.map(h => `<li style="--c:var(--info)"><span class="tk">${h.tick != null ? "t" + esc(h.tick) : ""}</span><i></i><span>${esc(h.type || h.kind || h.event || "")} ${esc(Object.entries(h).filter(([k, v]) => !["tick", "type", "kind", "event"].includes(k) && v != null && typeof v !== "object").map(([k, v]) => `${k}: ${["from", "to", "team", "owner"].includes(k) ? nameOf(v) : v}`).join(" · "))}</span></li>`).join("");
  return `${head}${rows ? `<ul class="feed" style="margin-top:8px">${rows}</ul>` : `<div class="empty">No hay movimientos registrados.</div>`}`;
}
export function openCard(ref) {
  const { cards, rar } = catIndex(); const c = cards[ref]; if (!c) return;
  const me = D("me"), mine = ownedIndex(me)[ref] || [], set = c.set, si = (D("catalog")?.sets || []).indexOf(set);
  const r = rk(c.rarity);
  openDrawer(`<div class="muted" style="font-size:13px">${esc(set.name)} · ${esc(c.id)}</div><h2>${esc(c.hidden ? "???" : c.name)}</h2>
    <div class="cardhero"><div class="cromos" style="grid-template-columns:1fr">${cromoHTML(c, set, si, mine, rar, { mode: "catalogue" })}</div>
      <div>${c.flavour && !c.hidden ? `<p class="flav">“${esc(c.flavour)}”</p>` : ""}
        <dl class="kv"><dt>Rareza</dt><dd><span style="--rc:${col(rar[r]?.color, `var(--r-${r})`)}"><i class="gem"></i></span> ${esc(RAR_ES[r])}</dd><dt>Book</dt><dd>${esc(fmt(c.book, 0))} ${esc(SYM)}</dd>
        <dt>Tirada</dt><dd>${esc(fmt(c.print_run, 0))}</dd><dt>Acuñados</dt><dd>${esc(fmt(c.minted, 0))} (${esc(fmt(pct(num(c.minted) || 0, num(c.print_run) || 0), 1))}%)</dd>
        <dt>Página</dt><dd>${c.page ? "Ocupa hueco en el álbum" : "Extra, no ocupa hueco"}</dd><dt>Afinidad</dt><dd>×${esc(fmt(me?.affinity?.[set.id], 2))}</dd><dt>Tenemos</dt><dd>${mine.length}</dd></dl></div></div>
    <h3>Cuánto vale para nosotros</h3><div id="dv-value"><button type="button" class="btn ghost small" data-dv="value" data-ref="${esc(ref)}">Consultar nuestro valor de una copia más</button></div>
    <h3>Nuestras copias</h3>${mine.length ? mine.map(a => `<div class="panel" style="margin-bottom:10px;padding:12px 14px"><b>#${esc(a.serial)}/${esc(a.print_run)}</b> <span class="muted">· id ${esc(a.id)} · nos vale ${esc(fmt(a.your_value, 1))} ${esc(SYM)}</span><div id="dv-h-${esc(a.id)}"><button type="button" class="btn ghost small" data-dv="history" data-aid="${esc(a.id)}" style="margin-top:6px">Ver historial</button></div></div>`).join("") : `<div class="empty">No tenemos este cromo.</div>`}`);
}
export function drawerFetch(btn) {
  if (btn.dataset.dv === "value") {
    const el = $("dv-value"); el.innerHTML = `<div class="skeleton" style="padding:8px 0">Consultando…</div>`;
    load(`/api/me/value?card=${enc(btn.dataset.ref)}`, 60e3).then(d => { el.innerHTML = (typeof d === "object" ? kv(d) || "" : esc(d)) + rawBlock(d); })
      .catch(e => { el.innerHTML = `<div class="empty">No disponible: ${esc(e.message)}</div>`; });
  } else if (btn.dataset.dv === "history") {
    const id = btn.dataset.aid, el = $(`dv-h-${id}`); el.innerHTML = `<div class="skeleton" style="padding:8px 0">Cargando historial…</div>`;
    load(`/api/cards/${enc(id)}`, 60e3).then(d => { el.innerHTML = historyHTML(d) + rawBlock(d); })
      .catch(e => { el.innerHTML = `<div class="empty">No disponible: ${esc(e.message)}</div>`; });
  }
}
export function openThread(id) {
  openDrawer(`<div class="muted">Conversación #${esc(id)}</div><h2>Cargando…</h2>`);
  load(`/api/threads/${enc(id)}`, 10e3).then(t => {
    const th = t.thread || t, meId = D("me")?.id;
    const msgs = th.messages || t.messages || [];
    drawerBody(`<div class="muted">Conversación #${esc(id)} · ${esc(th.status || "")}</div><h2>Con ${esc(nameOf(th.with ?? th.persona ?? ""))}</h2>
      ${th.topic ? `<p class="muted">Tema: ${esc(th.topic.buy ? "comprar " + bundle(th.topic.buy) : th.topic.sell ? "vender " + bundle(th.topic.sell) : JSON.stringify(th.topic))}</p>` : ""}
      ${msgs.map(m => { const ours = m.sender === meId || m.from === meId || m.side === "team"; return `<div class="msg ${ours ? "ours" : ""}"><div class="who">${esc(ours ? "Nosotros" : nameOf(m.sender ?? m.from ?? m.side ?? ""))}${m.tick != null ? ` · t${esc(m.tick)}` : ""}</div>${esc(m.text || "")}${m.offer ? `<div class="offerbox">Ofrece <b>${esc(bundle(m.offer.give))}</b> por <b>${esc(bundle(m.offer.want))}</b></div>` : ""}</div>`; }).join("") || `<div class="empty">Sin mensajes.</div>`}
      ${rawBlock(t)}`);
  }).catch(e => drawerBody(`<h2>Conversación #${esc(id)}</h2><div class="empty">No se pudo cargar: ${esc(e.message)}</div>`));
}
export function openDealer(pid) {
  const base = (D("dealers")?.personas || []).find(p => p.id === pid);
  openDrawer(base ? `<div class="dealers">${dealerCardHTML(base, D("me"))}</div><div id="dv-dealer"></div>` : `<h2>Cargando…</h2><div id="dv-dealer"></div>`);
  load(`/api/dealers/${enc(pid)}`, 60e3).then(p => {
    const el = $("dv-dealer"); if (!el) return;
    const extra = kv(p, ["id", "name", "status", "level", "title", "kind", "bio", "enabled", "open_to_all"]);
    el.innerHTML = `${base ? "" : `<div class="dealers">${dealerCardHTML(p, D("me"))}</div>`}${extra ? `<h3>Más datos</h3>${extra}` : ""}${rawBlock(p)}`;
  }).catch(e => { const el = $("dv-dealer"); if (el) el.innerHTML = `<div class="empty">Ficha ampliada no disponible: ${esc(e.message)}</div>`; });
}


/* =====================================================================
   View registry and module contract
   ---------------------------------------------------------------------
   Each view is static/views/<id>.js and may export:
     needs: string[]                 store keys to keep fresh while active (keys of SRC, plus "feed" = SSE store)
     mount(root, ctx)                build the static shell once (root = <div class="view">)
     render(root, ctx)               (re)draw from the store; called after mount, after every refresh and on demand
     onEvent(evt, ctx)               realtime event {seq, source: "public"|"team"|"gateway", type, data}
     destroy()                       leaving the view
   ctx = { core, id, state, store: { get, load, path, invalidate, feed }, rerender }
   ===================================================================== */
export const VIEWS = [
  { id: "home", es: "Inicio" },
  { id: "intel", es: "Bitácora" },
  { id: "trade", es: "Consola" },
  { id: "live", es: "En directo" },
  { id: "album", es: "Álbum" },
  { id: "catalogue", es: "Catálogo" },
  { id: "market", es: "Mercados" },
  { id: "deals", es: "Nuestros tratos" },
  { id: "dealers", es: "Vendedores" },
  { id: "leaderboard", es: "Clasificación" },
  { id: "feed", es: "Feed" },
  { id: "schedule", es: "Calendario" },
];
export function registerView(v) { if (!VIEWS.some(x => x.id === v.id)) VIEWS.push(v); renderTabs(current || VIEWS[0]); }
export const GLOBAL = ["me", "clock", "lb"];
export let current = null, mod = null;
export const mods = {}, viewState = {};

export function route() {
  let h = (location.hash || "#home").slice(1).split("/")[0];
  if (h === "big") h = "live";
  return VIEWS.find(v => v.id === h) || VIEWS[0];
}
export function renderTabs(v) {
  const log = D("log");
  const newCount = typeof log === "string" && state.seenLog ? parseLog(log).entries.filter(e => !state.seenLog.has(e.key)).length : 0;
  put($("tabs"), VIEWS.filter(x => !x.hidden).map(x => `<a href="#${x.id}" ${x.id === v?.id ? 'aria-current="page"' : ""}>${esc(x.es)}${x.id === "intel" && newCount ? `<span class="badge">${newCount}</span>` : ""}</a>`).join(""));
}
export function makeCtx(v) {
  return { core: self, id: v?.id, state: (viewState[v?.id] ||= {}),
    store: { get: D, load: loadKey, path: load, invalidate, feed: feedEvents }, rerender };
}
export const viewRoot = () => $("app").firstElementChild;
export async function mountView(v) {
  try { mod?.destroy?.(); } catch (e) { console.error(e); }
  mod = null;
  document.body.classList.toggle("big", v.id === "live");
  $("bigbtn").textContent = v.id === "live" ? "Salir de pantalla grande" : "Pantalla grande";
  $("bigbtn").setAttribute("href", v.id === "live" ? "#home" : "#live");
  $("app").innerHTML = `<div class="view" id="view-${esc(v.id)}"><div class="wrap skeleton">Cargando…</div></div>`;
  let m;
  try { m = mods[v.id] || (mods[v.id] = await import(`./views/${v.id}.js`)); }
  catch (e) { console.error(e); viewRoot().innerHTML = `<div class="wrap vhead"><div><h1>${esc(v.es)}</h1><p>Esta sección todavía no está lista (${esc(e.message)}).</p></div></div>`; return; }
  if (current !== v) return;
  mod = m;
  try { m.mount?.(viewRoot(), makeCtx(v)); } catch (e) { console.error(e); showErrors([`Fallo al montar ${v.es}: ${e.message}`]); }
}
export function rerender() {
  if (!mod || !current || !viewRoot()) return;
  try { mod.render?.(viewRoot(), makeCtx(current)); } catch (e) { console.error("render", current.id, e); showErrors([`Fallo al dibujar ${current.es}: ${e.message}`]); }
}
export const renderView = () => rerender();   // compat for older call sites

/* ---------- refresh: the active view's keys (TTL-gated) plus a slow global poll ---------- */
export let cycleId = 0;
export async function cycle() {
  const my = ++cycleId, v = current; if (!v) return;
  const keys = [...new Set([...GLOBAL, ...((mod?.needs) || [])])].filter(k => SRC[k]);
  if (!D("catalog") && keys.includes("catalog")) await loadKey("catalog").catch(() => {});
  const res = await Promise.allSettled(keys.map(k => loadKey(k).then(d => { if (k === "clock") state.clockAt = cache.get(SRC.clock[0]).at; return d; })));
  if ((mod?.needs || []).includes("feed") && hub.status !== "ok" && !feedStore.size) await feedFallback();
  if (my !== cycleId || v !== current) return;
  const errs = [];
  res.forEach((r, i) => { if (r.status === "rejected") errs.push(r.reason?.message || keys[i]); });
  if (res.some(r => r.status === "fulfilled")) state.lastOk = Math.max(state.lastOk, ...keys.map(k => cache.get(SRC[k][0])?.at || 0));
  renderStrip(); renderTabs(v); rerender();
  if (v.id === "intel" || (v.id === "home" && state.seenLog === null)) rememberLog(D("log"));
  showErrors(errs);
  tickCountdowns();
}
export let teamTimer = null;
export function scheduleRefresh(ms = 700) { clearTimeout(teamTimer); teamTimer = setTimeout(cycle, ms); }
export async function go() {
  const v = route();
  if (current?.id !== v.id) { current = v; await mountView(v); window.scrollTo(0, 0); }
  renderStrip(); renderTabs(v); rerender(); tickCountdowns();
  cycle();
}

/* ---------- realtime hub: /events (SSE) ---------- */
export const feedStore = new Map();
export function feedEvents() { return [...feedStore.values()].sort((a, b) => (b.id ?? 0) - (a.id ?? 0)); }
export function addFeed(e) {
  if (!e || e.id == null || feedStore.has(e.id)) return false;
  feedStore.set(e.id, e);
  if (feedStore.size > 500) [...feedStore.keys()].sort((a, b) => a - b).slice(0, feedStore.size - 500).forEach(k => feedStore.delete(k));
  return true;
}
export async function feedFallback() {
  try { const d = await load("/api/feed?limit=150", 30e3); for (const e of d?.events || []) addFeed(e); } catch { /* shown by the error banner on next cycle */ }
}
export const hub = { status: "connecting", es: null, lastEvent: 0 };
export const GW_ES = { ok: "Tiempo real conectado", connecting: "Conectando tiempo real…", reconnecting: "Reconectando tiempo real…", error: "Pasarela con problemas", closed: "Tiempo real desconectado" };
export function setGw(s, detail = "") {
  hub.status = s;
  const c = $("gw"); if (!c) return;
  c.hidden = false; c.className = "hchip " + (s === "ok" ? "ok" : s === "connecting" ? "" : "bad");
  c.textContent = GW_ES[s] || s; c.title = detail;
}
export function connectSSE() {
  if (typeof EventSource === "undefined") { setGw("closed", "Este navegador no admite EventSource"); return; }
  setGw("connecting");
  const es = hub.es = new EventSource("/events");
  es.onopen = () => setGw("ok");
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) { setGw("closed"); setTimeout(connectSSE, 5000); }
    else setGw("reconnecting");
    feedFallback().then(() => { if ((mod?.needs || []).includes("feed")) rerender(); });
  };
  es.onmessage = m => { let ev; try { ev = JSON.parse(m.data); } catch { return; } onHubEvent(ev); };
}
export let pubTimer = null;
export function onHubEvent(ev) {
  if (!ev || typeof ev !== "object") return;
  hub.lastEvent = Date.now();
  if (ev.source === "public") {
    if (!addFeed(ev.data)) return;            // replayed or duplicate
    const t = String(ev.data?.type || "");
    if (/^(clock\.|day\.|calendar\.|round\.)/.test(t)) { invalidate(SRC.clock[0], SRC.sched[0]); scheduleRefresh(1500); }
    if (/^(round\.|admin\.adjust|admin\.freeze)/.test(t)) invalidate(SRC.lb[0]);
    if (/^venue\./.test(t)) invalidate(SRC.venues[0]);
    if (/^(level\.|persona\.)/.test(t)) invalidate(SRC.levels[0], SRC.dealers[0]);
    if (/^set\.released/.test(t)) invalidate(SRC.catalog[0]);
  } else if (ev.source === "team") {
    invalidateTeam(); scheduleRefresh();
  } else if (ev.source === "gateway") {
    const t = String(ev.type || "");
    if (/error|lost|down|fail|closed/.test(t)) setGw("error", JSON.stringify(ev.data ?? {}).slice(0, 200));
    else if (/ok|connected|up|ready|open/.test(t)) setGw("ok");
  }
  try { mod?.onEvent?.(ev, makeCtx(current)); } catch (e) { console.error(e); }
}
export function sessionExpired() {
  const b = $("err"); if (!b) return;
  $("err-txt").innerHTML = `La sesión ha caducado. <a href="" style="color:#fff;font-weight:700">Recarga la página</a> para volver a entrar.`;
  b.classList.add("show"); b.dataset.session = "1";
}

/* ---------- global events ---------- */
document.addEventListener("click", e => {
  const t = e.target.closest("[data-close],[data-card],[data-thread],[data-dealer],[data-venue],[data-catset],[data-feedcat],[data-lbsort],[data-anchor],[data-dv]");
  if (!t) return;
  if (t.hasAttribute("data-close")) return closeDrawer();
  if (t.dataset.dv) return drawerFetch(t);
  if (t.dataset.card) { if (t.closest(".drawer") || t.closest("form")) return; return openCard(t.dataset.card); }
  if (t.dataset.thread) return openThread(t.dataset.thread);
  if (t.dataset.dealer) return openDealer(t.dataset.dealer);
  if (t.dataset.venue) { state.venue = t.dataset.venue; return rerender(); }
  if (t.dataset.catset) { state.catSet = t.dataset.catset; return rerender(); }
  if (t.dataset.feedcat) { state.feedCat = t.dataset.feedcat; return rerender(); }
  if (t.dataset.lbsort) { const k = t.dataset.lbsort; state.lbDesc = state.lbSort === k ? !state.lbDesc : !["name", "rank"].includes(k); state.lbSort = k; return rerender(); }
  if (t.dataset.anchor) { e.preventDefault(); const el = document.getElementById("md-" + t.dataset.anchor); if (el) el.scrollIntoView({ behavior: "smooth", block: "start" }); }
});
document.addEventListener("keydown", e => { if (e.key === "Escape") { if (document.querySelector(".modal-scrim")) return closeModal(); closeDrawer(); } });
window.addEventListener("hashchange", () => { closeDrawer(); go(); });

go();
connectSSE();
setTimeout(() => { if (!feedStore.size) feedFallback().then(() => { if ((mod?.needs || []).includes("feed")) rerender(); }); }, 4000);
setInterval(cycle, 30000);          // slow safety poll; realtime comes from /events
setInterval(tickCountdowns, 1000);
