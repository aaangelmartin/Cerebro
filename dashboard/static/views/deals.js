/* View "deals". Contract: see static/app.js (mount/render/onEvent/destroy). */
import * as core from "../app.js";
const { $, D, bundle, col, esc, fmt, nameOf, offerRow, put, rawBlock, setSym } = core;

export const needs = ["me", "catalog", "offers", "threads", "duels", "lb", "dealers", "clock"];

export function mount(root) {
  root.innerHTML = `<div class="wrap vhead"><div><h1>Nuestros tratos</h1><p>Negociaciones, ofertas y duelos del equipo. Toca una conversación para leerla entera.</p></div></div>
      <section class="wrap"><div id="dl-acts"></div><div class="board even" style="padding-top:12px"><div class="panel"><h2>Conversaciones</h2><div id="dl-threads"></div></div><div class="col"><div class="panel"><h2>Ofertas</h2><div id="dl-offers"></div></div><div class="panel"><h2>Duelos</h2><div id="dl-duels"></div></div></div></div></section>`;
}

export function render(root, ctx) {
  const me = D("me"), clock = D("clock"), catalog = D("catalog"), lb = D("lb"), sched = D("sched");
  if (catalog?.currency_symbol) setSym(catalog.currency_symbol);

      const o = D("offers")?.offers || [], t = D("threads")?.threads || [], d = D("duels")?.duels || [], lim = clock?.limits || {};
      put($("dl-acts"), `<div class="acts" style="max-width:640px"><div><b>${o.length}</b><span>Ofertas${lim.max_open_offers_per_team ? ` de ${esc(lim.max_open_offers_per_team)}` : ""}</span></div><div><b>${t.length}</b><span>Conversaciones${lim.max_open_threads_per_team ? ` de ${esc(lim.max_open_threads_per_team)}` : ""}</span></div><div><b>${d.length}</b><span>Duelos</span></div></div>`);
      put($("dl-threads"), t.length ? t.map(x => `<button type="button" class="rowlink" data-thread="${esc(x.id)}"><span class="tag">#${esc(x.id)}</span><span><b>${esc(nameOf(x.with ?? x.persona ?? ""))}</b>${x.topic ? ` <span class="muted">· ${esc(x.topic.buy ? "comprar " + bundle(x.topic.buy) : x.topic.sell ? "vender" : "")}</span>` : ""}<br><small class="muted">${esc(x.status ?? "")}${x.last_tick != null ? ` · último t${esc(x.last_tick)}` : ""}${x.messages != null ? ` · ${esc(Array.isArray(x.messages) ? x.messages.length : x.messages)} mensajes` : ""}</small></span><span class="muted">Leer</span></button>`).join("") : `<div class="empty">No hay conversaciones abiertas. Se abren desde el SDK o la web oficial.</div>`);
      put($("dl-offers"), o.length ? o.map(x => offerRow(x, me?.id)).join("") : `<div class="empty">No tenemos ofertas publicadas.</div>`);
      put($("dl-duels"), d.length ? d.map(x => `<div class="rowlink" style="cursor:default"><span class="tag">#${esc(x.id ?? x.duel ?? "")}</span><span><b>${esc(x.item ?? x.name ?? "Duelo")}</b> <span class="muted">${esc(x.role ? (x.role === "buyer" ? "· compramos" : x.role === "seller" ? "· vendemos" : "· " + x.role) : "")}</span><br><small class="muted">${esc([x.status, x.opponent ? "contra " + nameOf(x.opponent) : "", x.price != null ? `precio ${fmt(x.price, 1)}` : ""].filter(Boolean).join(" · "))}</small></span><span></span></div>`).join("") + rawBlock(d) : `<div class="empty">Sin duelos ahora mismo.</div>`);
    
}
