/* View "catalogue". Contract: see static/app.js (mount/render/onEvent/destroy). */
import * as core from "../app.js";
const { $, D, RAR_ES, col, cromoHTML, esc, fmt, num, ownedIndex, pct, put, releaseEs, rk, setSym, state } = core;

export const needs = ["me", "catalog"];

export function mount(root) {
  root.innerHTML = `<div class="wrap vhead"><div><h1>Catálogo completo</h1><p>Los 6 barrios y sus 12 cromos, con rareza, valor de catálogo, tirada y cuántos se han acuñado ya. En color, los que tenemos.</p></div></div>
      <section class="wrap"><div class="filters" id="cat-filters"></div><div id="cat-body"></div></section>`;
}

export function render(root, ctx) {
  const me = D("me"), clock = D("clock"), catalog = D("catalog"), lb = D("lb"), sched = D("sched");
  if (catalog?.currency_symbol) setSym(catalog.currency_symbol);

      if (!catalog) return;
      const owned = ownedIndex(me), rar = catalog.rarities || {};
      put($("cat-filters"), [{ id: "all", name: "Todos", color: "#E8ECF6" }, ...(catalog.sets || [])].map(s => `<button type="button" data-catset="${esc(s.id)}" aria-pressed="${state.catSet === s.id}" style="--c:${col(s.color)}"><i></i>${esc(s.name)}${s.released === false ? " · pronto" : ""}</button>`).join("") + `<button type="button" data-catset="packs" aria-pressed="${state.catSet === "packs"}" style="--c:#E0A458"><i></i>Sobres</button>`);
      const sets = (catalog.sets || []).map((s, i) => [s, i]).filter(([s]) => state.catSet === "all" || state.catSet === s.id);
      const setsHtml = state.catSet === "packs" ? "" : sets.map(([set, si]) => {
        const sc = col(set.color);
        const mintedTot = (set.cards || []).reduce((a, c) => a + (num(c.minted) || 0), 0), runTot = (set.cards || []).reduce((a, c) => a + (num(c.print_run) || 0), 0);
        return `<div class="panel" style="margin-bottom:20px"><div class="page-head" style="grid-template-columns:minmax(0,1fr) auto"><div><h3 style="color:${sc};font-size:26px">${esc(set.name)} <span class="muted" style="font-size:15px">${esc(set.id)}</span></h3><div class="theme">${esc(set.theme)}</div></div>
          <div class="tags">${set.released ? `<span class="tag hot">Publicado</span>` : `<span class="tag soon">Sale ${esc(releaseEs(set.release))}</span>`}<span class="muted" style="font-size:12px">${esc(fmt(mintedTot, 0))} de ${esc(fmt(runTot, 0))} acuñados</span></div></div>
          <div class="cromos big">${(set.cards || []).map(c => {
            const mine = owned[c.id] || [], r = rk(c.rarity);
            return `<div class="slot">${cromoHTML(c, set, si, mine, rar, { mode: "catalogue" })}
              <div class="scarce" style="--rc:${col(rar[r]?.color, `var(--r-${r})`)}">${esc(fmt(c.minted, 0))}/${esc(fmt(c.print_run, 0))} acuñados${mine.length ? ` · <span class="ours">tenemos ${mine.length}</span>` : ""}<div class="bar"><i style="width:${pct(num(c.minted) || 0, num(c.print_run) || 0)}%"></i></div></div></div>`;
          }).join("")}</div></div>`;
      }).join("");
      const packsHtml = (state.catSet === "all" || state.catSet === "packs") ? `<div class="panel"><h2>Sobres</h2><p class="lede">Probabilidad de rareza en cada hueco del sobre, y el valor de catálogo esperado.</p><div class="packs">${(catalog.packs || []).map(p => `<div class="pack" style="--pc:${col(p.color)}"><h3>${esc(p.name)}</h3><div class="muted" style="font-size:13px">${(p.slots || []).length} cromos · valor esperado <b style="color:var(--text)">${esc(fmt(p.expected_book, 1))} ${esc(core.SYM)}</b></div>
          ${(p.slots || []).map((sl, i) => `<div class="slotrow"><span>hueco ${i + 1}</span><div class="seg" style="height:12px">${Object.entries(sl).map(([r, pr]) => `<i style="width:${100 * (num(pr) || 0)}%;background:${col(rar[r]?.color, `var(--r-${rk(r)})`)}" title="${esc(`${RAR_ES[r] || r}: ${fmt(100 * pr, 0)}%`)}"></i>`).join("")}</div></div>`).join("")}</div>`).join("")}</div></div>` : "";
      put($("cat-body"), setsHtml + packsHtml);
    
}
