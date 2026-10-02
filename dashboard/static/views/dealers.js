/* View "dealers". Contract: see static/app.js (mount/render/onEvent/destroy). */
import * as core from "../app.js";
const { $, D, dealerCardHTML, put, setSym } = core;

export const needs = ["me", "catalog", "dealers"];

export function mount(root) {
  root.innerHTML = `<div class="wrap vhead"><div><h1>Vendedores</h1><p>Quién vende y compra en el Bazaar, cómo negocia cada uno y cuándo se desbloquea.</p></div></div>
      <section class="wrap"><div class="dealers" id="dl-cards"></div></section>`;
}

export function render(root, ctx) {
  const me = D("me"), clock = D("clock"), catalog = D("catalog"), lb = D("lb"), sched = D("sched");
  if (catalog?.currency_symbol) setSym(catalog.currency_symbol);

      const ps = D("dealers")?.personas || [];
      put($("dl-cards"), ps.map(p => dealerCardHTML(p, me)).join("") || `<div class="empty">No hay vendedores visibles todavía.</div>`);
    
}
