/* View "feed". Contract: see static/app.js (mount/render/onEvent/destroy). */
import * as core from "../app.js";
const { $, D, FEED_CATS, esc, feedEvents, feedHTML, put, setSym, state } = core;

export const needs = ["me", "catalog", "lb", "dealers", "venues", "feed"];

export function mount(root) {
  root.innerHTML = `<div class="wrap vhead"><div><h1>Lo que pasa en el Bazaar</h1><p>Los últimos 150 eventos públicos. Lo que nos afecta va marcado en dorado.</p></div></div>
      <section class="wrap"><div class="filters" id="feed-filters"></div><div class="panel"><ul class="feed" id="feed-list"></ul></div></section>`;
}

export function render(root, ctx) {
  const me = D("me"), clock = D("clock"), catalog = D("catalog"), lb = D("lb"), sched = D("sched");
  if (catalog?.currency_symbol) setSym(catalog.currency_symbol);

      put($("feed-filters"), FEED_CATS.map(c => `<button type="button" data-feedcat="${c.k}" aria-pressed="${state.feedCat === c.k}" style="--c:${c.c}"><i></i>${esc(c.es)}</button>`).join(""));
      const evs = feedEvents();
      put($("feed-list"), feedHTML(evs, { cat: state.feedCat, limit: 150, markFresh: true }));
      state.seenFeed = new Set(evs.map(e => e.id));
    
}

export function onEvent(ev, ctx) { if (ev.source === "public") ctx.rerender(); }
