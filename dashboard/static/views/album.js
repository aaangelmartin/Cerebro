/* View "album". Contract: see static/app.js (mount/render/onEvent/destroy). */
import * as core from "../app.js";
const { $, D, RAR, RAR_ES, buyTargets, col, cromoHTML, esc, fmt, num, ownedIndex, put, releaseEs, ring, setSym, state } = core;

export const needs = ["me", "catalog", "dealers"];

export function mount(root) {
  root.innerHTML = `<div class="wrap vhead"><div><h1>El álbum</h1><p>Cada barrio es una página de 10 cromos; el épico y el legendario son extra y no ocupan hueco. Los huecos en verde son nuestros mejores objetivos de compra. Toca un cromo para ver su ficha.</p></div><span class="muted" id="album-sum"></span></div>
      <section class="wrap"><div class="panel"><div class="legend" id="album-legend"></div><div id="album-pages"></div></div></section>`;
}

export function render(root, ctx) {
  const me = D("me"), clock = D("clock"), catalog = D("catalog"), lb = D("lb"), sched = D("sched");
  if (catalog?.currency_symbol) setSym(catalog.currency_symbol);

      if (!me || !catalog) return;
      const owned = ownedIndex(me), rar = catalog.rarities || {};
      const targets = new Set(buyTargets(me, catalog, owned).slice(0, 8).map(t => t.card.id));
      const first = state.seenAssets === null, seen = state.seenAssets || new Set(), fresh = new Set();
      for (const a of me.assets || []) if (!first && !seen.has(a.id)) fresh.add(a.ref);
      state.seenAssets = new Set((me.assets || []).map(a => a.id));
      const al = me.album || {};
      $("album-sum").textContent = `${al.filled ?? 0} de ${al.slots ?? 0} huecos · ${(me.assets || []).length} cromos`;
      put($("album-legend"), RAR.map(r => `<span><i class="gem" style="--rc:${col(rar[r]?.color, `var(--r-${r})`)}"></i>${esc(RAR_ES[r])} · ${esc(fmt(rar[r]?.book, 0))} ${esc(core.SYM)}</span>`).join("") + `<span>×n = repetidas</span>`);
      put($("album-pages"), (catalog.sets || []).map((set, si) => {
        const sc = col(set.color);
        const page = (al.pages || []).find(p => p.set === set.id);
        const have = page?.have ?? 0, of = page?.of ?? (set.cards || []).filter(c => c.page).length;
        const aff = num(me.affinity?.[set.id]);
        return `<article class="page ${set.released ? "" : "locked"}" style="--sc:${sc}">
          <div class="page-head">${ring(have, of, sc)}<div><h3 style="color:${sc}">${esc(set.name)}</h3><div class="theme">${esc(set.theme)}</div></div>
            <div class="tags">${aff == null ? "" : `<span class="tag ${aff >= 1.2 ? "hot" : aff < 1 ? "cold" : ""}">afinidad ×${esc(fmt(aff, 2))}</span>`}${set.released ? "" : `<span class="tag soon">Sale ${esc(releaseEs(set.release))}</span>`}${page?.complete ? `<span class="tag hot">Página completa${page.master ? " · maestra" : ""}</span>` : ""}</div></div>
          <div class="cromos">${(set.cards || []).map(c => cromoHTML(c, set, si, owned[c.id] || [], rar, { target: targets.has(c.id), fresh: fresh.has(c.id) })).join("")}</div></article>`;
      }).join(""));
    
}
