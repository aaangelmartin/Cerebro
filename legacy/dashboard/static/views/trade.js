/* View "trade". Contract: see static/app.js (mount/render/onEvent/destroy). */
import * as core from "../app.js";
const { $, D, RAR, RAR_ES, bundle, cache, catIndex, col, confirmWrite, enc, esc, fmt, load, nameOf, num, put, renderView, rk, setSym, state } = core;

export const needs = ["me", "clock", "catalog", "dealers", "lb", "venues", "offers", "threads", "duels"];

export function mount(root) {
  root.innerHTML = `<div class="wrap vhead"><div><h1>Consola de trading</h1><p>Para operar a mano. Cada envío abre una confirmación con el método, la ruta y el JSON exactos que se mandan al servidor del juego.</p></div></div>
      <section class="wrap"><div class="warnbox">Estas acciones son reales: mueven cromos y primas del equipo y gastan el cupo por tick. Revisa el JSON antes de confirmar.</div><div class="tstatus" id="tr-status"></div></section>
      <div class="wrap board even">
        <div class="col">
          <section class="panel"><h2>Abrir conversación</h2>
            <form class="f" data-form="thread" autocomplete="off">
              <div class="row"><label>Con<select name="with" id="ft-with"></select></label><label>Mercado (solo entre equipos)<select name="venue" id="ft-venue"></select></label></div>
              <label>Tema<select name="kind" id="ft-kind"><option value="buy_pack">Comprar un sobre</option><option value="buy_card">Comprar un cromo concreto</option><option value="buy_rarity">Comprar una rareza de un barrio</option><option value="sell">Vender cromos nuestros</option><option value="none">Sin tema</option></select></label>
              <div class="row" data-show="buy_pack"><label>Sobre<select name="pack" id="ft-pack"></select></label></div>
              <div class="row" data-show="buy_card"><label>Cromo<select name="card" id="ft-card"></select></label></div>
              <div class="row" data-show="buy_rarity"><label>Rareza<select name="rarity" id="ft-rarity"></select></label><label>Barrio<select name="set" id="ft-set"></select></label></div>
              <div data-show="sell"><div class="fl">Cromos que vendemos</div><div class="checklist" id="ft-assets"></div></div>
              <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><button type="button" class="btn ghost small" data-act="preview">Ver nuestro valor</button><span class="vpill" id="ft-val"></span></div>
              <div class="formerr" data-err></div>
              <button class="btn" type="submit">Revisar y abrir</button>
            </form></section>
          <section class="panel"><h2>Conversaciones</h2><div id="tr-threads"></div><div id="tr-thread"></div>
            <form class="f" data-form="msg" id="f-msg" hidden autocomplete="off">
              <label>Mensaje<textarea name="text" maxlength="1200" placeholder="Hola, Abuela…"></textarea></label>
              <div class="row"><label>Precio (opcional, primas enteras)<input name="price" type="number" min="1" step="1" inputmode="numeric"></label></div>
              <label>Oferta estructurada entre equipos (JSON opcional)<textarea name="offer" placeholder='{"give":{"assets":[123]},"want":{"cash":30}}'></textarea></label>
              <div class="formerr" data-err></div>
              <div style="display:flex;gap:10px;flex-wrap:wrap"><button class="btn" type="submit">Revisar y enviar</button><button class="btn danger" type="button" data-act="close-thread">Cerrar conversación</button></div>
            </form></section>
          <section class="panel"><h2>Duelos</h2><div id="tr-duels"></div>
            <form class="f" data-form="duel" id="f-duel" hidden autocomplete="off">
              <label>Duelo<select name="duel" id="fd-duel"></select></label>
              <label>Mensaje<textarea name="text" maxlength="1200"></textarea></label>
              <div class="row"><label>Precio<input name="price" type="number" min="1" step="1" inputmode="numeric"></label><label>Días de entrega (0–10, si se negocian)<input name="days" type="number" min="0" max="10" step="1" inputmode="numeric"></label></div>
              <div class="formerr" data-err></div>
              <div style="display:flex;gap:10px;flex-wrap:wrap"><button class="btn" type="submit">Revisar y enviar</button><button class="btn ghost" type="button" data-act="duel-accept">Aceptar la oferta rival</button></div>
            </form></section>
        </div>
        <div class="col">
          <section class="panel"><h2>Publicar oferta</h2>
            <form class="f" data-form="offer" autocomplete="off">
              <div class="row"><label>Mercado<select name="venue" id="fo-venue"></select></label><label>Solo para (opcional)<select name="to" id="fo-to"></select></label></div>
              <div class="row"><label>Damos<select name="gk" id="fo-gk"><option value="assets">Cromos o sobres nuestros</option><option value="cash">Primas</option></select></label><label>Pedimos<select name="wk" id="fo-wk"><option value="cash">Primas</option><option value="cards">Cromos (cualquier copia)</option></select></label></div>
              <div data-gshow="assets"><div class="fl">Lo que damos</div><div class="checklist" id="fo-assets"></div></div>
              <div class="row" data-gshow="cash"><label>Primas que damos<input name="gcash" type="number" min="1" step="1" inputmode="numeric"></label></div>
              <div class="row" data-wshow="cash"><label>Primas que pedimos<input name="wcash" type="number" min="1" step="1" inputmode="numeric"></label></div>
              <div data-wshow="cards"><label>Cromos que pedimos (Ctrl o Cmd para varios)<select name="wcards" id="fo-wcards" multiple></select></label></div>
              <div class="row"><label>Caduca en (ticks)<input name="exp" type="number" min="1" step="1" value="40" inputmode="numeric"></label></div>
              <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><button type="button" class="btn ghost small" data-act="preview">Ver nuestro valor</button><span class="vpill" id="fo-val"></span></div>
              <div class="formerr" data-err></div>
              <button class="btn" type="submit">Revisar y publicar</button>
            </form></section>
          <section class="panel"><h2>Nuestras ofertas</h2><div id="tr-offers"></div></section>
          <section class="panel"><h2>Aceptar del libro</h2><label class="fl">Mercado<select id="tb-venue"></select></label><div id="tr-book" style="margin-top:8px"></div></section>
          <section class="panel"><h2>Abrir sobres</h2><div id="tr-packs"></div></section>
        </div>
      </div>`;
}

/* ---------- console helpers ---------- */
function fillSelect(el, opts, placeholder) {
  if (!el) return;
  const html = (placeholder != null ? `<option value="">${esc(placeholder)}</option>` : "") + opts.map(([v, l, dis]) => `<option value="${esc(v)}"${dis ? " disabled" : ""}>${esc(l)}</option>`).join("");
  if (el._html === html) return;
  const keep = el.multiple ? [...el.selectedOptions].map(o => o.value) : el.value;
  el.innerHTML = html; el._html = html;
  if (el.multiple) [...el.options].forEach(o => { o.selected = keep.includes(o.value); });
  else if ([...el.options].some(o => o.value === keep)) el.value = keep;
}
function checklist(el, assets) {
  if (!el) return;
  const checked = new Set([...el.querySelectorAll("input:checked")].map(i => i.value));
  const { cards } = catIndex();
  put(el, assets.map(a => `<label><input type="checkbox" value="${esc(a.id)}"${checked.has(String(a.id)) ? " checked" : ""}> <span>${esc(a.kind === "pack" ? "Sobre " + (a.name || a.ref) : `${a.ref} ${cards[a.ref]?.name || a.name || ""}`)}${a.serial != null ? ` #${esc(a.serial)}` : ""} <span class="vpill">nos vale ${esc(fmt(a.your_value, 1))}</span></span></label>`).join("") || `<span class="muted">No tenemos nada que dar.</span>`);
}
const checkedIds = el => [...(el?.querySelectorAll("input:checked") || [])].map(i => Number(i.value));
function valueFor(ref) { return load(`/api/me/value?card=${enc(ref)}`, 60e3).then(d => num(d?.your_value) ?? num(d?.value)).catch(() => null); }
const myAssets = () => (D("me")?.assets || []);
function used(kind, thread) { const t = D("clock")?.tick; return state.writes.filter(w => w.tick === t && w.kind === kind && (thread == null || w.thread === thread)).length; }
const teamOpts = () => (D("lb")?.teams || []).filter(t => t.team !== D("me")?.id).map(t => [t.team, `${t.name} (${t.team})`]);
const venueOpts = () => (D("venues")?.venues || []).filter(v => v.status === "open").map(v => [v.venue, `${v.name} · ${fmt((num(v.fee_bps) || 0) / 100, 2)}%`]);

async function previewValues() {
  const f = document.querySelector('form[data-form="thread"]');
  if (f) {
    const kind = f.kind.value, out = $("ft-val");
    if (kind === "buy_card" && f.card.value) { out.textContent = "Calculando nuestro valor…"; const v = await valueFor(f.card.value); out.textContent = v != null ? `Una copia más de ${f.card.value} nos vale ${fmt(v, 1)} ${core.SYM}` : ""; }
    else if (kind === "sell") { const ids = new Set(checkedIds($("ft-assets"))); const sum = myAssets().filter(a => ids.has(a.id)).reduce((x, a) => x + (num(a.your_value) || 0), 0); out.textContent = ids.size ? `Lo que vendemos nos vale ${fmt(sum, 1)} ${core.SYM}` : ""; }
    else if (kind === "buy_pack" && f.pack.value) { const p = catIndex().packs[f.pack.value]; out.textContent = p ? `Valor de catálogo esperado del sobre: ${fmt(p.expected_book, 1)} ${core.SYM}` : ""; }
    else out.textContent = "";
  }
  const o = document.querySelector('form[data-form="offer"]');
  if (o) {
    const parts = [];
    if (o.gk.value === "assets") { const ids = new Set(checkedIds($("fo-assets"))); if (ids.size) parts.push(`Damos algo que nos vale ${fmt(myAssets().filter(a => ids.has(a.id)).reduce((x, a) => x + (num(a.your_value) || 0), 0), 1)} ${core.SYM}`); }
    if (o.wk.value === "cards") {
      const refs = [...o.wcards.selectedOptions].map(x => x.value).slice(0, 3);
      if (refs.length) { const vals = await Promise.all(refs.map(valueFor)); parts.push(refs.map((r, i) => `${r}: nos vale ${vals[i] != null ? fmt(vals[i], 1) : "?"}`).join(" · ")); }
    }
    $("fo-val").textContent = parts.join(" · ");
  }
}
function syncForms() {
  const f = document.querySelector('form[data-form="thread"]');
  if (f) {
    f.querySelectorAll("[data-show]").forEach(el => { el.hidden = el.dataset.show !== f.kind.value; });
    const isTeam = (D("lb")?.teams || []).some(t => t.team === f.with.value);
    f.venue.disabled = !isTeam;
  }
  const o = document.querySelector('form[data-form="offer"]');
  if (o) {
    o.querySelectorAll("[data-gshow]").forEach(el => { el.hidden = el.dataset.gshow !== o.gk.value; });
    o.querySelectorAll("[data-wshow]").forEach(el => { el.hidden = el.dataset.wshow !== o.wk.value; });
  }
}

function threadDetailHTML(t, meId) {
  const th = t.thread || t;
  const msgs = th.messages || t.messages || [];
  const so = th.standing_offers || t.standing_offers || [];
  const openOthers = so.filter(o => o.status === "open" && o.maker !== meId);
  return `<div class="panel" style="background:var(--panel-2);margin:10px 0">
    <div class="muted" style="font-size:12px">#${esc(th.id)} · ${esc(th.status || "")}${th.closed_reason ? ` · ${esc(th.closed_reason)}` : ""}${th.until_tick != null ? ` hasta t${esc(th.until_tick)}` : ""}${th.venue ? ` · ${esc(nameOf(th.venue))}` : ""}</div>
    <h3 style="font-size:18px;margin:2px 0 6px">Con ${esc(nameOf(th.with ?? th.persona ?? ""))}${th.topic ? ` <span class="muted" style="font-size:13px">· ${esc(th.topic.buy ? "comprar " + bundle(th.topic.buy) : th.topic.sell ? "vender " + bundle(th.topic.sell) : "")}</span>` : ""}</h3>
    <div style="max-height:340px;overflow-y:auto">${msgs.map(m => {
      const ours = m.sender === meId || m.from === meId;
      return `<div class="msg ${ours ? "ours" : ""}"><div class="who">${esc(ours ? "Nosotros" : nameOf(m.sender ?? m.from ?? ""))}${m.tick != null ? ` · t${esc(m.tick)}` : ""}${m.price != null ? ` · precio ${esc(m.price)}` : ""}</div>${esc(m.text || "")}
        ${m.offer ? `<div class="offerbox">Ofrece <b>${esc(bundle(m.offer.give))}</b> por <b>${esc(bundle(m.offer.want))}</b></div>` : ""}
        ${!ours && m.id != null ? `<div style="margin-top:6px"><button type="button" class="btn danger small" data-act="flag" data-mid="${esc(m.id)}">Denunciar mala fe</button></div>` : ""}</div>`;
    }).join("") || `<div class="empty">Sin mensajes todavía.</div>`}</div>
    ${so.length ? `<div class="subh" style="margin-top:8px">Ofertas en pie</div>${so.map(o => `<div class="so ${o.final ? "final" : ""}"><span><b>${esc(o.maker === meId ? "Nuestra" : nameOf(o.maker))}</b> #${esc(o.id)} · da <b>${esc(bundle(o.give))}</b> por <b>${esc(bundle(o.want))}</b> · ${esc(o.status)}${o.final ? " · <b>oferta final</b>" : ""}</span>
      ${o.status === "open" && o.maker !== meId ? `<button type="button" class="btn small" data-act="accept-offer" data-id="${esc(o.id)}">Aceptar</button>` : "<span></span>"}</div>`).join("")}` : ""}
    ${openOthers.length ? "" : ""}</div>`;
}
function acceptControls(o, meId) {
  const wantCards = o.want?.cards || o.want?.types || [];
  const mine = myAssets().filter(a => wantCards.some(c => (typeof c === "string" ? c : c.ref || c.card) === a.ref));
  const sel = wantCards.length ? `<select data-acc-assets="${esc(o.id)}" style="max-width:220px"><option value="">Copia automática</option>${mine.map(a => `<option value="${esc(a.id)}">${esc(a.ref)} #${esc(a.serial)} · nos vale ${esc(fmt(a.your_value, 1))}</option>`).join("")}</select>` : "";
  return `<span style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">${sel}<button type="button" class="btn small" data-act="accept-offer" data-id="${esc(o.id)}">Aceptar</button></span>`;
}

function renderTrade() {
  const me = D("me"), clock = D("clock"), cat = D("catalog"), lim = clock?.limits || {};
  if (!me || !cat) return;
  const offersResp = D("offers") || {}, ours = offersResp.offers || [], threads = D("threads")?.threads || [], duels = D("duels")?.duels || [];
  const rem = (limit, n) => limit == null ? "–" : Math.max(0, limit - n);
  const acc = rem(lim.accepts_per_team_per_tick, used("accept")), lst = rem(lim.offers_per_team_per_tick, used("listing"));
  put($("tr-status"), `<div><b data-cd="tick-trade">–</b><span>Tick y siguiente</span></div>
    <div><b>${esc(fmt(me.cash, 0))} ${esc(core.SYM)}</b><span>En caja</span></div>
    <div class="${acc === 0 ? "low" : ""}"><b>${esc(acc)} / ${esc(lim.accepts_per_team_per_tick ?? "–")}</b><span>Aceptaciones que quedan este tick</span></div>
    <div class="${lst === 0 ? "low" : ""}"><b>${esc(lst)} / ${esc(lim.offers_per_team_per_tick ?? "–")}</b><span>Ofertas nuevas este tick</span></div>
    <div><b>${esc(threads.filter(t => (t.status || "open") === "open").length)} / ${esc(lim.max_open_threads_per_team ?? "–")}</b><span>Conversaciones abiertas</span></div>
    <div><b>${esc(ours.length)} / ${esc(lim.max_open_offers_per_team ?? "–")}</b><span>Ofertas abiertas</span></div>
    <div><b>${esc(lim.messages_per_side_per_tick ?? "–")}</b><span>Mensajes por conversación y tick</span></div>`);

  const { cards, sets } = catIndex();
  const personas = (D("dealers")?.personas || []).filter(p => p.status !== "announced");
  fillSelect($("ft-with"), [...personas.map(p => [p.id, `${p.name}${(me.unlocked || []).includes(p.id) ? "" : " (bloqueado)"}`]), ...teamOpts()]);
  fillSelect($("ft-venue"), venueOpts(), "Por defecto (El Rastro)");
  fillSelect($("ft-pack"), (cat.packs || []).map(p => [p.id, `${p.name} · esperado ${fmt(p.expected_book, 1)}`]));
  const cardOpts = Object.values(cards).filter(c => !c.hidden).map(c => [c.id, `${c.id} ${c.name} · ${RAR_ES[rk(c.rarity)]}${c.set.released ? "" : " (sin publicar)"}`]);
  fillSelect($("ft-card"), cardOpts);
  fillSelect($("ft-rarity"), RAR.map(r => [r, RAR_ES[r]]));
  fillSelect($("ft-set"), Object.values(sets).map(s => [s.id, `${s.name}${s.released ? "" : " (sin publicar)"}`]));
  fillSelect($("fo-venue"), venueOpts());
  fillSelect($("fo-to"), teamOpts(), "Cualquiera");
  fillSelect($("fo-wcards"), cardOpts);
  fillSelect($("tb-venue"), venueOpts());
  checklist($("ft-assets"), myAssets().filter(a => a.kind === "card").sort((a, b) => String(a.ref).localeCompare(b.ref)));
  checklist($("fo-assets"), [...myAssets()].sort((a, b) => String(a.ref).localeCompare(b.ref)));
  syncForms();

  // threads
  if (state.thread == null && threads.length) state.thread = threads[0].id;
  put($("tr-threads"), threads.length ? threads.map(t => `<button type="button" class="rowlink" data-tsel="${esc(t.id)}" ${String(t.id) === String(state.thread) ? 'style="background:rgba(255,196,77,.08)"' : ""}><span class="tag">#${esc(t.id)}</span><span><b>${esc(nameOf(t.with ?? t.persona ?? ""))}</b> <small class="muted">${esc(t.status || "")}</small><br><small class="muted">mensajes este tick: ${esc(used("message", t.id))} de ${esc(lim.messages_per_side_per_tick ?? "–")}</small></span><span class="muted">${String(t.id) === String(state.thread) ? "Abierta" : "Ver"}</span></button>`).join("") : `<div class="empty">No hay conversaciones. Abre una arriba.</div>`);
  $("f-msg").hidden = state.thread == null;
  if (state.thread != null) {
    const path = `/api/threads/${enc(state.thread)}`;
    const c = cache.get(path);
    if (c && "data" in c) put($("tr-thread"), threadDetailHTML(c.data, me.id));
    load(path, 5e3).then(d => { if (core.current?.id === "trade") put($("tr-thread"), threadDetailHTML(d, me.id)); })
      .catch(e => put($("tr-thread"), `<div class="empty">No se pudo cargar la conversación: ${esc(e.message)}</div>`));
  } else put($("tr-thread"), "");

  // duels
  if (state.duel == null && duels.length) state.duel = duels[0].id;
  fillSelect($("fd-duel"), duels.map(d => [d.id, `#${d.id} · ${d.item ?? d.name ?? ""} · ${d.role === "buyer" ? "compramos" : d.role === "seller" ? "vendemos" : d.role ?? ""}`]));
  $("f-duel").hidden = !duels.length;
  put($("tr-duels"), duels.length ? duels.map(d => `<div class="so"><span><b>#${esc(d.id)} ${esc(d.item ?? d.name ?? "")}</b> · ${esc(d.role === "buyer" ? "compramos" : d.role === "seller" ? "vendemos" : d.role ?? "")} · ${esc(d.status ?? "")}<br>
    <small class="muted">nuestro límite ${esc(fmt(d.your_limit, 1))}${d.rival_offer != null ? ` · oferta rival ${esc(typeof d.rival_offer === "object" ? JSON.stringify(d.rival_offer) : d.rival_offer)}` : ""}${d.deadline != null ? ` · cierra t${esc(d.deadline)}` : ""}${d.issues ? ` · negocia ${esc([].concat(d.issues).join(", "))}` : ""}${d.your_days_weight != null ? ` · peso por día ${esc(fmt(d.your_days_weight, 2))}` : ""}</small></span><span></span></div>`).join("") : `<div class="empty">Sin duelos en curso. Salen según el calendario.</div>`);

  // our offers (+ anything else the endpoint returns, e.g. offers addressed to us)
  const extra = Object.entries(offersResp).filter(([k, v]) => k !== "offers" && Array.isArray(v) && v.length);
  put($("tr-offers"), (ours.length ? ours.map(o => `<div class="so"><span>#${esc(o.id)} · da <b>${esc(bundle(o.give))}</b> por <b>${esc(bundle(o.want))}</b>${o.venue ? ` · ${esc(nameOf(o.venue))}` : ""} · ${esc(o.status ?? "")}${o.expires_tick != null ? ` · caduca t${esc(o.expires_tick)}` : ""}</span>
      ${o.maker === me.id || o.maker == null ? `<button type="button" class="btn danger small" data-act="cancel-offer" data-id="${esc(o.id)}">Retirar</button>` : acceptControls(o, me.id)}</div>`).join("") : `<div class="empty">No tenemos ofertas abiertas.</div>`)
    + extra.map(([k, list]) => `<div class="subh" style="margin-top:10px">${esc(k.replace(/_/g, " "))}</div>${list.map(o => `<div class="so"><span>#${esc(o.id)} · ${esc(nameOf(o.maker))} da <b>${esc(bundle(o.give))}</b> por <b>${esc(bundle(o.want))}</b></span>${o.maker !== me.id ? acceptControls(o, me.id) : ""}</div>`).join("")}`).join(""));

  // book
  if (!state.bookVenue) state.bookVenue = $("tb-venue")?.value || venueOpts()[0]?.[0];
  if (state.bookVenue && $("tb-venue")) $("tb-venue").value = state.bookVenue;
  if (state.bookVenue) {
    const path = `/api/venues/${enc(state.bookVenue)}/offers`;
    const draw = d => { const list = Array.isArray(d) ? d : d?.offers || d?.book || [];
      put($("tr-book"), list.length ? list.map(o => `<div class="so"><span>#${esc(o.id)} · ${esc(o.maker === me.id ? "Nuestra" : nameOf(o.maker))} da <b>${esc(bundle(o.give))}</b> por <b>${esc(bundle(o.want))}</b></span>${o.maker === me.id ? "<span class='muted'>nuestra</span>" : acceptControls(o, me.id)}</div>`).join("") : `<div class="empty">El libro está vacío.</div>`); };
    const c = cache.get(path); if (c && "data" in c) draw(c.data);
    load(path, 15e3).then(d => { if (core.current?.id === "trade") draw(d); }).catch(e => put($("tr-book"), `<div class="empty">No se pudo cargar: ${esc(e.message)}</div>`));
  }
  // packs
  const packs = myAssets().filter(a => a.kind === "pack");
  put($("tr-packs"), packs.length ? packs.map(a => `<div class="so"><span><b>${esc(a.name || a.ref)}</b> #${esc(a.id)} · nos vale ${esc(fmt(a.your_value, 1))}</span><button type="button" class="btn small" data-act="open-pack" data-id="${esc(a.id)}">Abrir</button></div>`).join("") : `<div class="empty">No tenemos sobres cerrados.</div>`);
}

function formErr(form, msg) { const el = form.querySelector("[data-err]"); if (el) el.textContent = msg || ""; return !msg; }
const intOrNull = v => { if (v === "" || v == null) return null; const n = Number(v); return Number.isInteger(n) ? n : NaN; };
function onSubmit(form) {
  const kind = form.dataset.form;
  formErr(form, "");
  if (kind === "thread") {
    const w = form.with.value; if (!w) return formErr(form, "Elige con quién hablar.");
    const body = { with: w };
    const k = form.kind.value;
    if (k === "buy_pack") body.topic = { buy: { pack: form.pack.value } };
    if (k === "buy_card") body.topic = { buy: { card: form.card.value } };
    if (k === "buy_rarity") body.topic = { buy: { rarity: form.rarity.value, set: form.set.value } };
    if (k === "sell") { const ids = checkedIds($("ft-assets")); if (!ids.length) return formErr(form, "Marca al menos un cromo para vender."); body.topic = { sell: { assets: ids } }; }
    if (!form.venue.disabled && form.venue.value) body.venue = form.venue.value;
    return confirmWrite({ title: `Abrir conversación con ${nameOf(w)}`, method: "POST", path: "/api/threads", body, kind: "thread" });
  }
  if (kind === "msg") {
    if (state.thread == null) return formErr(form, "Elige una conversación.");
    const body = { text: form.text.value };
    const price = intOrNull(form.price.value);
    if (Number.isNaN(price) || (price != null && price < 1)) return formErr(form, "El precio debe ser un número entero de primas.");
    if (price != null) body.price = price;
    if (form.offer.value.trim()) { try { body.offer = JSON.parse(form.offer.value); } catch (e) { return formErr(form, "La oferta no es JSON válido: " + e.message); } }
    if (!body.text && body.price == null && !body.offer) return formErr(form, "Escribe algo o pon un precio.");
    return confirmWrite({ title: `Mensaje en la conversación #${state.thread}`, method: "POST", path: `/api/threads/${enc(state.thread)}/messages`, body, kind: "message", thread: state.thread });
  }
  if (kind === "duel") {
    const id = form.duel.value; if (!id) return formErr(form, "No hay duelo elegido.");
    const body = { text: form.text.value };
    const price = intOrNull(form.price.value), days = intOrNull(form.days.value);
    if (Number.isNaN(price) || Number.isNaN(days)) return formErr(form, "Precio y días deben ser números enteros.");
    if (days != null && (days < 0 || days > 10)) return formErr(form, "Los días van de 0 a 10.");
    if (price != null) { body.price = price; if (days != null) body.offer = { price, days }; }
    else if (days != null) return formErr(form, "Los días solo se mandan junto a un precio.");
    return confirmWrite({ title: `Mensaje en el duelo #${id}`, method: "POST", path: `/api/duels/${enc(id)}/messages`, body, kind: "duel" });
  }
  if (kind === "offer") {
    const body = {};
    if (form.gk.value === "assets") { const ids = checkedIds($("fo-assets")); if (!ids.length) return formErr(form, "Marca qué damos."); body.give = { assets: ids }; }
    else { const c = intOrNull(form.gcash.value); if (!c || c < 1) return formErr(form, "Pon cuántas primas damos (entero)."); body.give = { cash: c }; }
    if (form.wk.value === "cash") { const c = intOrNull(form.wcash.value); if (!c || c < 1) return formErr(form, "Pon cuántas primas pedimos (entero)."); body.want = { cash: c }; }
    else { const refs = [...form.wcards.selectedOptions].map(o => o.value); if (!refs.length) return formErr(form, "Elige qué cromos pedimos."); body.want = { cards: refs }; }
    const exp = intOrNull(form.exp.value); if (!exp || exp < 1) return formErr(form, "La caducidad debe ser un entero de ticks.");
    body.expires_in_ticks = exp;
    if (form.venue.value) body.venue = form.venue.value;
    if (form.to.value) body.to = form.to.value;
    return confirmWrite({ title: "Publicar oferta", method: "POST", path: "/api/offers", body, kind: "listing" });
  }
}
function onAct(btn) {
  const act = btn.dataset.act, id = btn.dataset.id;
  if (act === "preview") return previewValues();
  if (act === "close-thread" && state.thread != null) return confirmWrite({ title: `Cerrar la conversación #${state.thread}`, method: "POST", path: `/api/threads/${enc(state.thread)}/close`, body: undefined, kind: "close", note: "Sus ofertas abiertas se retiran." });
  if (act === "accept-offer") {
    const sel = document.querySelector(`[data-acc-assets="${CSS.escape(id)}"]`);
    const body = sel && sel.value ? { assets: [Number(sel.value)] } : {};
    return confirmWrite({ title: `Aceptar la oferta #${id}`, method: "POST", path: `/api/offers/${enc(id)}/accept`, body, kind: "accept", note: "Lee la <b>estructura</b> de la oferta, no las palabras: es lo único que se ejecuta." });
  }
  if (act === "cancel-offer") return confirmWrite({ title: `Retirar la oferta #${id}`, method: "DELETE", path: `/api/offers/${enc(id)}`, body: undefined, kind: "cancel" });
  if (act === "open-pack") return confirmWrite({ title: `Abrir el sobre #${id}`, method: "POST", path: `/api/packs/${enc(id)}/open`, body: undefined, kind: "pack" });
  if (act === "duel-accept") { const d = $("fd-duel")?.value; if (d) return confirmWrite({ title: `Aceptar la oferta rival del duelo #${d}`, method: "POST", path: `/api/duels/${enc(d)}/accept`, body: undefined, kind: "accept" }); }
  if (act === "flag") {
    const reason = window.prompt("¿Por qué crees que este mensaje es de mala fe? (una denuncia correcta puntúa, una errónea cuesta)", "");
    if (reason === null) return;
    return confirmWrite({ title: `Denunciar el mensaje #${btn.dataset.mid}`, method: "POST", path: "/api/flags", body: { message_id: Number(btn.dataset.mid), reason }, kind: "flag" });
  }
}
document.addEventListener("submit", e => { const f = e.target.closest("form[data-form]"); if (!f) return; e.preventDefault(); onSubmit(f); });
document.addEventListener("click", e => {
  const b = e.target.closest("[data-act],[data-tsel]"); if (!b) return;
  if (b.dataset.tsel) { state.thread = b.dataset.tsel; return core.rerender(); }
  onAct(b);
});
document.addEventListener("change", e => {
  if (e.target.id === "tb-venue") { state.bookVenue = e.target.value; return core.rerender(); }
  if (e.target.closest('form[data-form="thread"],form[data-form="offer"]')) syncForms();
});



export function render(root, ctx) {
  const me = D("me"), clock = D("clock"), catalog = D("catalog"), lb = D("lb"), sched = D("sched");
  if (catalog?.currency_symbol) setSym(catalog.currency_symbol);
  renderTrade();

}
