// Plaza components: card, chip, offer row, match row, floor message. Pure functions returning HTML strings.
// Every string that comes from the API goes through esc(); nothing here inserts raw text.
window.PlazaUI = (() => {
  "use strict";
  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
  const RARITY = { common: "#9AA4B8", uncommon: "#3DDC97", rare: "#4C8DFF", epic: "#B061FF", legendary: "#FFC44D" };
  const SET = { LAV: "#E4572E", MAL: "#E83F8C", LAT: "#F2A541", SAL: "#2EC4B6", RET: "#7B8CDE", CHA: "#9BC53D" };
  const REF = /^[A-Z]{3}-\d{2}$/, TEAM = /^t\d{2}$/;
  const state = { art: {}, recipes: [] };

  const teamName = (t) => `Team ${Number(String(t).slice(1))}`;
  const teamLink = (t) => TEAM.test(t || "") ? `<a class="tlink" href="/plaza/#/team/${t}">${teamName(t)}</a>` : esc(t || "");
  const cardLink = (ref, label) => REF.test(ref || "") ? `<a class="tlink num" href="/plaza/#/card/${ref}">${esc(label || ref)}</a>` : esc(ref || "");
  const chip = (text, cls) => `<span class="badge ${cls || ""}">${esc(text)}</span>`;
  const remember = (recipe) => state.recipes.push(recipe || {}) - 1;
  const ago = (ts) => {
    const s = Math.max(0, Date.now() / 1000 - (ts || 0));
    return s < 60 ? "now" : s < 3600 ? `${Math.floor(s / 60)} min` : s < 86400 ? `${Math.floor(s / 3600)} h` : `${Math.floor(s / 86400)} d`;
  };

  /** The card face alone (official art when we have it). */
  function face(c) {
    const ref = REF.test(c.ref || "") ? c.ref : "";
    const rarity = RARITY[c.rarity] ? c.rarity : "common";
    const svg = state.art[ref];
    return `<div class="card-art r-${rarity}">${svg || `<div class="card-blank" style="--set:${SET[ref.slice(0, 3)] || "#666"}">${esc(ref)}</div>`}</div>`;
  }
  /** A card with its reference, name and one hint line. */
  function card(c, hint, hintClass) {
    const ref = REF.test(c.ref || "") ? c.ref : "";
    const rarity = RARITY[c.rarity] ? c.rarity : "common";
    return `<a class="card" href="/plaza/#/card/${ref}" title="${esc(c.name || ref)}">${face(c)}
      <div class="card-ref"><span class="pip" style="--r:${RARITY[rarity]}"></span>${esc(ref)}</div>
      <div class="card-name">${esc(c.name || "")}</div>
      ${hint ? `<div class="card-hint ${hintClass || ""}">${esc(hint)}</div>` : ""}</a>`;
  }

  /** One proposed match between other teams, with the request to copy. */
  function matchRow(m) {
    const i = remember(m.recipe);
    let line, cls = m.kind;
    if (m.kind === "swap") line = `${teamLink(m.seller)} <span class="arrow">gives</span> ${cardLink(m.ref)} <span class="arrow">⇄</span> ${cardLink(m.ref_back)} <span class="arrow">from</span> ${teamLink(m.buyer)}`;
    else if (m.kind === "triangle") line = (m.legs || []).map((l) => `${teamLink(l.from)} <span class="arrow">→</span> ${cardLink(l.ref)} <span class="arrow">→</span>`).join(" ") + ` ${teamLink((m.legs || [{}])[0].from)}`;
    else line = `${teamLink(m.seller)} <span class="arrow">sells</span> ${cardLink(m.ref)} <span class="arrow">to</span> ${teamLink(m.buyer)}`;
    if (m.last_of_page) cls += " last";
    return `<div class="match ${cls}"><div class="match-card">${face(m)}</div>
      <div class="match-main"><div class="match-line">${line}
        ${m.last_of_page ? chip("finishes a page", "hit") : ""}${chip(m.confidence || "", m.confidence === "declared" ? "agent" : "")}</div>
        <div class="match-why">${esc(m.name || "")}${m.name ? " · " : ""}${esc(m.why || "")}</div></div>
      <div class="match-side"><div><div class="price">${m.price ? esc(m.price) + " <small>P</small>" : "<small>card for card</small>"}</div>
        <div class="saves">saves ${esc(m.saves)} P of Rastro fee</div></div>
        <button class="btn" data-copy="${i}">Copy for your agent</button></div></div>`;
  }

  /** One open offer on a venue. `mine` adds why it fits the team and the accept request. */
  function offerRow(o, mine) {
    const side = { ask: "sells", bid: "bids for", swap: "swaps" }[o.side] || o.side;
    const i = mine && o.recipe ? remember(o.recipe) : null;
    const real = o.side === "ask" ? `you pay ${esc(o.cost)} P` : o.side === "bid" ? `seller keeps ${esc(o.nets)} P` : "card for card";
    return `<div class="match offer ${o.venue === "v07" ? "home-venue" : ""} ${o.finishes_page ? "last" : ""}">
      <div class="match-card">${face(o)}</div>
      <div class="match-main"><div class="match-line">${teamLink(o.maker)} <span class="arrow">${side}</span> ${cardLink(o.ref)}
        ${o.side === "swap" ? `<span class="arrow">for</span> ${cardLink(o.ref_back)}` : ""}
        ${o.to ? `<span class="arrow">to</span> ${teamLink(o.to)}` : ""}
        ${o.addressed_to_you ? chip("addressed to you", "hit") : ""}${o.finishes_page ? chip("finishes a page", "hit") : ""}
        ${chip(o.venue_name || o.venue, o.venue === "v07" ? "ok" : "")}</div>
        <div class="match-why">${esc(o.name || "")}${mine && o.why ? " · " + esc(o.why) : ""} · offer #${esc(o.id)}${o.expires_tick ? ` · until tick ${esc(o.expires_tick)}` : ""}</div></div>
      <div class="match-side"><div><div class="price">${o.price ? esc(o.price) + " <small>P</small>" : "<small>swap</small>"}</div>
        <div class="saves ${o.fee ? "fee" : ""}">${o.fee ? `+${esc(o.fee)} P fee · ` : "no fee · "}${real}</div></div>
        ${i === null ? "" : `<button class="btn" data-copy="${i}">Copy for your agent</button>`}</div></div>`;
  }

  /** One item of the live floor: an agent's message or a public game event. */
  function msgRow(m) {
    const kind = String(m.kind || "note");
    let body;
    if (m.src === "agent") {
      const verb = { want: "wants", offer: "offers", accept: "accepts", note: "says" }[kind] || "says";
      body = `${teamLink(m.team)} <span class="arrow">${verb}</span> ${m.ref ? cardLink(m.ref) : ""}
        ${m.price ? `<span class="num">${esc(m.price)} P</span>` : ""}${m.to ? ` <span class="arrow">→</span> ${teamLink(m.to)}` : ""}
        ${m.text ? `<span class="msg-text">${esc(m.text)}</span>` : ""}`;
    } else if (kind === "offer") {
      const side = { ask: "lists", bid: "bids for", swap: "swaps" }[m.side] || "posts";
      body = `${teamLink(m.team)} <span class="arrow">${side}</span> ${cardLink(m.ref)}${m.side === "swap" ? ` <span class="arrow">for</span> ${cardLink(m.ref_back)}` : ""}
        ${m.price ? `<span class="num">${esc(m.price)} P</span>` : ""}${m.to ? ` <span class="arrow">→</span> ${teamLink(m.to)}` : ""}`;
    } else if (kind === "deal") {
      body = m.dealer ? `${teamLink(m.team)} <span class="arrow">deals with</span> ${esc(m.dealer)} · ${cardLink(m.ref)} <span class="num">${esc(m.price)} P</span>`
        : `${teamLink(m.team)} <span class="arrow">sold</span> ${cardLink(m.ref)} <span class="arrow">to</span> ${teamLink(m.to)} <span class="num">${esc(m.price)} P</span>`;
    } else if (kind === "pack") body = `${teamLink(m.team)} <span class="arrow">opened a pack</span> <span class="msg-text">${esc(m.text)}</span>`;
    else if (kind === "craft") body = `${teamLink(m.team)} <span class="arrow">crafted</span> <span class="msg-text">${esc(m.text)}</span>`;
    else body = `${m.team ? teamLink(m.team) : ""} <span class="msg-text">${esc(m.text)}</span>`;
    return `<div class="msg k-${esc(kind)} ${m.src === "agent" ? "agent" : "game"} ${m.highlight ? "home-venue" : ""}" data-seq="${esc(m.seq)}">
      <span class="msg-kind">${esc(m.src === "agent" ? kind : kind === "deal" ? "deal" : kind)}</span>
      <div class="msg-body">${body}${m.venue ? " " + chip(m.venue, m.highlight ? "ok" : "") : ""}${m.src === "agent" && m.verified ? " " + chip("verified", "ok") : ""}</div>
      <span class="msg-time num">${m.tick != null ? "t" + esc(m.tick) : ago(m.ts)}</span></div>`;
  }

  return { esc, state, RARITY, SET, REF, TEAM, teamName, teamLink, cardLink, chip, face, card, matchRow, offerRow, msgRow, ago };
})();
