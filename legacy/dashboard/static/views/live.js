/* View "live". Contract: see static/app.js (mount/render/onEvent/destroy). */
import * as core from "../app.js";
const { $, D, TONE, bundle, col, esc, eventsListHTML, feedEvents, feedText, fillHero, fmt, nameOf, num, pct, put, rk, setSym, state } = core;

export const needs = ["me", "clock", "lb", "catalog", "sched", "dealers", "venues", "offers", "threads", "feed"];

export function mount(root) {
  root.innerHTML = `<div class="wrap livegrid">
        <div class="col">
          <div class="plaque" style="margin:14px"><div class="rankbadge" id="rankbadge" hidden><small>puesto</small><b id="rank">–</b></div><div class="kicker">The Bazaar · Madrid</div><h1 id="team">Nuestro equipo</h1><div class="sub" id="team-sub"></div></div>
          <div class="panel"><div class="lvclock" data-cd="tick-big">–</div><div class="muted" data-cd="day-big" style="margin-top:10px"></div></div>
          <div class="panel"><h2>Nuestro equipo</h2><div id="lv-kpis"></div><ul class="lvfeed" id="lv-ours"></ul></div>
        </div>
        <div class="col"><div id="lv-ann"></div><div class="panel"><h2>En directo</h2><ul class="lvfeed" id="lv-feed"></ul></div></div>
        <div class="col"><div class="panel"><h2>Clasificación</h2><div class="lvlb" id="lv-lb"></div></div><div class="panel"><h2>Lo próximo</h2><ul class="nextev" id="lv-next" style="grid-template-columns:1fr"></ul></div></div>
      </div>`;
}

/* Live (projector): realtime feed from SSE, animated leaderboard, our own events */
const ANN_TYPES = /^(announcement|level\.announced|level\.activated|venue\.announcement|set\.released|round\.started|duels\.scheduled)$/;
function liveLi(e, enter) {
  const meId = D("me")?.id;
  let txt, tone, who;
  try { [txt, tone, who] = feedText(e); } catch { txt = String(e.type); tone = "muted"; who = []; }
  const us = meId && ((who || []).includes(meId) || e.actor === meId);
  return `<li class="${us ? "us" : ""} ${ANN_TYPES.test(e.type) ? "ann" : ""} ${enter ? "enter" : ""}" style="--c:${TONE[tone] || TONE.muted}" data-id="${esc(e.id)}"><span class="tk">t${esc(e.tick)}</span><i></i><span>${esc(txt)}</span></li>`;
}
function fillLive(fresh) {
  const ul = $("lv-feed"); if (!ul) return;
  const ls = state.live || (state.live = { ids: new Set(), events: [] });
  if (!ls.ids.size) {
    const evs = feedEvents();
    for (const e of evs) ls.ids.add(e.id);
    ls.events = [...evs].reverse();
    ul.innerHTML = evs.slice(0, 30).map(e => liveLi(e, false)).join("");
  } else if (fresh && !ls.ids.has(fresh.id)) {
    ls.ids.add(fresh.id); ls.events.push(fresh);
    ul.insertAdjacentHTML("afterbegin", liveLi(fresh, true));
    while (ul.children.length > 40) ul.lastElementChild.remove();
  }
  const ann = [...ls.events].reverse().find(e => ANN_TYPES.test(e.type));
  put($("lv-ann"), ann ? `<div class="lvann"><small>Último anuncio · t${esc(ann.tick)}</small>${esc(feedText(ann)[0])}</div>` : "");
}
function diffOurs() {
  const th = D("threads")?.threads, of = D("offers")?.offers, me = D("me");
  if (!th || !of || !me) return;
  const now = { threads: Object.fromEntries(th.map(t => [t.id, t.status || "open"])), offers: Object.fromEntries(of.map(o => [o.id, o])), cash: me.cash };
  const prev = state.oursPrev, add = (txt, tone) => state.ours.unshift({ at: Date.now(), txt, tone, tick: D("clock")?.tick });
  if (!prev) {
    for (const t of th) add(`Conversación #${t.id} con ${nameOf(t.with ?? t.persona ?? "")}: ${t.status || "abierta"}`, "info");
    for (const o of of) add(`Oferta #${o.id} en pie: ${bundle(o.give)} por ${bundle(o.want)}`, "info");
  } else {
    for (const t of th) {
      if (!(t.id in prev.threads)) add(`Abrimos conversación #${t.id} con ${nameOf(t.with ?? t.persona ?? "")}`, "gold");
      else if (prev.threads[t.id] !== now.threads[t.id]) add(`Conversación #${t.id}: ${prev.threads[t.id]} → ${now.threads[t.id]}`, now.threads[t.id] === "deal" ? "good" : "warn");
    }
    for (const id in prev.threads) if (!(id in now.threads)) add(`La conversación #${id} ya no está abierta`, "muted");
    for (const o of of) if (!(o.id in prev.offers)) add(`Publicamos la oferta #${o.id}: ${bundle(o.give)} por ${bundle(o.want)}`, "gold");
    for (const id in prev.offers) if (!(id in now.offers)) add(`La oferta #${id} ya no está (aceptada, retirada o caducada)`, "good");
    if (prev.cash !== now.cash) add(`Caja: ${fmt(prev.cash, 0)} → ${fmt(now.cash, 0)} ${core.SYM}`, now.cash > prev.cash ? "good" : "warn");
  }
  state.ours = state.ours.slice(0, 14);
  state.oursPrev = now;
}


export function render(root, ctx) {
  const me = D("me"), clock = D("clock"), catalog = D("catalog"), lb = D("lb"), sched = D("sched");
  if (catalog?.currency_symbol) setSym(catalog.currency_symbol);

  if (!state.live) state.live = { ids: new Set(), events: [] };
  fillHero(me, lb);
  if (me) {
    const s = me.score || {}, al = me.album || {};
    put($("lv-kpis"), `<div class="comp"><div><b>${esc(fmt(s.score, 2))}</b><span>Puntos</span></div><div><b>${esc(fmt(me.cash, 0))} ${esc(core.SYM)}</b><span>Caja</span></div><div><b>${esc(al.filled)}/${esc(al.slots)}</b><span>Álbum</span></div><div><b>${esc(fmt(s.deals, 0))}</b><span>Tratos</span></div></div>`);
  }
  diffOurs();
  put($("lv-ours"), state.ours.map(o => `<li style="--c:${TONE[o.tone] || TONE.muted}"><span class="tk">${o.tick != null ? "t" + esc(o.tick) : ""}</span><i></i><span>${esc(o.txt)}</span></li>`).join("") || `<li class="empty" style="display:block">Sin movimientos nuestros todavía.</li>`);
  if (clock && sched) put($("lv-next"), eventsListHTML(clock, sched, { limit: 3 }));
  if (lb && me) {
    const box = $("lv-lb");
    const teams = [...(lb.teams || [])].sort((a, b) => (a.rank || 99) - (b.rank || 99));
    const ranks = Object.fromEntries(teams.map(t => [t.team, t.rank]));
    const moved = {};
    if (state.rankPrev) for (const t of teams) { const p = state.rankPrev[t.team]; if (p != null && p !== t.rank) { state.rankDelta[t.team] = p - t.rank; moved[t.team] = p > t.rank ? "up" : "down"; } }
    state.rankPrev = ranks;
    const max = Math.max(1e-9, ...teams.map(t => num(t.score) || 0));
    const html = teams.map(t => { const d = state.rankDelta[t.team] || 0;
      return `<div class="lvrow ${t.team === me.id ? "me" : ""} ${moved[t.team] ? "moved-" + moved[t.team] : ""}" data-team="${esc(t.team)}"><span class="rk">${esc(t.rank)}</span>
        <span><span class="nm" style="display:block">${esc(t.name)}${t.frozen ? " (congelado)" : ""}</span><span class="bar" style="display:block"><i style="width:${max > 1e-9 ? pct(num(t.score) || 0, max) : 0}%"></i></span></span>
        <span class="dl ${d > 0 ? "up" : d < 0 ? "down" : ""}">${d > 0 ? "▲" + d : d < 0 ? "▼" + -d : ""}</span><span>${esc(fmt(t.score, 2))}</span></div>`; }).join("");
    if (box && box._html !== html) {
      const old = {}; box.querySelectorAll(".lvrow").forEach(r => { old[r.dataset.team] = r.getBoundingClientRect().top; });
      box.innerHTML = html; box._html = html;
      box.querySelectorAll(".lvrow").forEach(r => {
        const o = old[r.dataset.team]; if (o == null) return;
        const dy = o - r.getBoundingClientRect().top; if (!dy) return;
        r.style.transition = "none"; r.style.transform = `translateY(${dy}px)`;
        requestAnimationFrame(() => requestAnimationFrame(() => { r.style.transition = ""; r.style.transform = ""; }));
      });
    }
  }
  fillLive();

}

export function onEvent(ev, ctx) {
  if (ev.source === "public") fillLive(ev.data);
}
export function destroy() { state.live = null; }
