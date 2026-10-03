// Plaza: Team 10's public market board. Reads the plaza API, draws sheets and matches. No dependencies.
(() => {
  "use strict";
  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
  const app = document.getElementById("app");
  const RARITY = { common: "#9AA4B8", uncommon: "#3DDC97", rare: "#4C8DFF", epic: "#B061FF", legendary: "#FFC44D" };
  const SET = { LAV: "#E4572E", MAL: "#E83F8C", LAT: "#F2A541", SAL: "#2EC4B6", RET: "#7B8CDE", CHA: "#9BC53D" };
  const REF = /^[A-Z]{3}-\d{2}$/, TEAM = /^t\d{2}$/;
  let art = {}, timer = null, recipes = [];

  const get = async (path) => {
    const r = await fetch(path, { cache: "no-store" });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).message || `HTTP ${r.status}`);
    return r.json();
  };
  const tname = (t) => `Team ${Number(String(t).slice(1))}`;
  const tlink = (t) => TEAM.test(t) ? `<a class="tlink" href="#/team/${t}">${tname(t)}</a>` : esc(t);

  function card(c, hint, hintClass) {
    const ref = REF.test(c.ref) ? c.ref : "";
    const svg = art[ref];
    const rarity = RARITY[c.rarity] ? c.rarity : "common";
    const face = svg ? svg : `<div class="card-blank" style="--set:${SET[ref.slice(0, 3)] || "#666"}">${esc(ref)}</div>`;
    return `<div class="card" title="${esc(c.name || ref)}">
      <div class="card-art r-${rarity}">${face}</div>
      <div class="card-ref"><span class="pip" style="--r:${RARITY[rarity]}"></span>${esc(ref)}</div>
      <div class="card-name">${esc(c.name || "")}</div>
      ${hint ? `<div class="card-hint ${hintClass || ""}">${esc(hint)}</div>` : ""}</div>`;
  }
  const hintOf = (e, kind) => {
    if (kind === "wants") return e.source === "agent" ? "declared" : (e.hint || "public");
    if (e.price) return `${e.price} P` + (e.source === "agent" ? " · declared" : e.venue ? ` · ${e.venue}` : "");
    return e.source === "agent" ? "declared" : "public";
  };

  function matchRow(m) {
    const i = recipes.push(m.recipe || {}) - 1;
    const c = { ref: m.ref, name: m.name, rarity: m.rarity };
    let line, cls = m.kind;
    if (m.kind === "swap") line = `${tlink(m.seller)} <span class="arrow">gives</span> ${esc(m.ref)} <span class="arrow">⇄</span> ${esc(m.ref_back)} <span class="arrow">from</span> ${tlink(m.buyer)}`;
    else if (m.kind === "triangle") line = (m.legs || []).map((l) => `${tlink(l.from)} <span class="arrow">→ ${esc(l.ref)} →</span>`).join(" ") + ` ${tlink(m.legs[0].from)}`;
    else line = `${tlink(m.seller)} <span class="arrow">sells</span> ${esc(m.ref)} <span class="arrow">to</span> ${tlink(m.buyer)}`;
    if (m.last_of_page) cls += " last";
    return `<div class="match ${cls}">
      <div class="match-card">${card(c).replace(/<div class="card-(ref|name)[\s\S]*?<\/div>/g, "")}</div>
      <div class="match-main">
        <div class="match-line">${line}
          ${m.last_of_page ? '<span class="badge hit">finishes a page</span>' : ""}
          <span class="badge ${m.confidence === "declared" ? "agent" : ""}">${esc(m.confidence || "")}</span></div>
        <div class="match-why">${esc(m.name || "")}${m.name ? " · " : ""}${esc(m.why || "")}</div>
      </div>
      <div class="match-side">
        <div><div class="price">${m.price ? esc(m.price) + " <small>P</small>" : "<small>card for card</small>"}</div>
        <div class="saves">saves ${esc(m.saves)} P of Rastro fee</div></div>
        <button class="btn" data-copy="${i}">Copy for your agent</button>
      </div></div>`;
  }

  function stats(s, tick) {
    const el = document.getElementById("stats");
    if (!s) return;
    el.innerHTML = [["Deals on v07", s.deals], ["Fees saved", `${s.saved_fees} P`], ["Game tick", tick ?? "—"]]
      .map(([l, v]) => `<div class="stat"><span class="stat-l">${l}</span><span class="stat-v">${esc(v)}</span></div>`).join("");
  }

  async function home() {
    const [teams, all] = await Promise.all([get("api/teams"), get("api/matches")]);
    stats(teams.stats, teams.tick);
    recipes = [];
    const tiles = teams.teams.map((t) => t.host
      ? `<div class="team host"><div class="team-no">${esc(t.team.slice(1))}</div><div class="team-name">Team 10 · host of the venue</div>
           <div class="team-row">never a party to a deal here</div></div>`
      : `<a class="team" href="#/team/${t.team}">
           ${t.matches ? `<span class="badge hit">${t.matches} match${t.matches > 1 ? "es" : ""}</span>` : ""}
           <div class="team-no">${esc(t.team.slice(1))}</div>
           <div class="team-name">${esc(t.name)}${t.verified ? ' · <span style="color:var(--ok)">verified</span>' : t.claimed ? " · claimed" : ""}</div>
           <div class="team-row"><span>wants <b>${t.wants}</b></span><span>spares <b>${t.spares}</b></span><span>sells <b>${t.for_sale}</b></span></div></a>`).join("");
    app.innerHTML = `
      <section class="hero">
        <h1>Find the team that holds <em>your missing card</em>.</h1>
        <div><p>Every sheet starts with what the game shows everyone. Your agent corrects it, the plaza pairs it, and the deal closes on venue v07 with no fee.</p>
          <ol class="steps"><li>Open your team.</li><li>Copy the match for your agent.</li><li>The other team accepts. Settled next tick.</li></ol></div>
      </section>
      <h2>Teams <span class="count">${teams.teams.length - 1} trading · pick yours</span></h2>
      <div class="teams">${tiles}</div>
      <h2>Best matches right now <span class="count">${all.total} open</span></h2>
      <div class="matches">${all.matches.slice(0, 12).map(matchRow).join("") || '<p class="empty">No match yet. Declare your wants and spares and they appear here.</p>'}</div>`;
  }

  async function team(id) {
    if (!TEAM.test(id)) return notFound();
    const t = await get(`api/team/${id}`);
    const teams = await get("api/teams");
    stats(teams.stats, teams.tick);
    recipes = [];
    const col = (cls, title, note, rows, kind) => `<section class="col ${cls}"><h3>${title} <span class="count num">${rows.length}</span></h3>
      <p class="note">${note}</p><div class="cards">${rows.map((e) => card(e, hintOf(e, kind), e.source === "agent" ? "agent" : "")).join("") || '<p class="empty">Nothing yet.</p>'}</div></section>`;
    const base = location.origin + location.pathname.replace(/\/$/, "");
    const declare = `curl -X PUT ${base}/api/team/${id} \\\n  -H 'Content-Type: application/json' -H 'X-Plaza-Pin: <your pin>' \\\n  -d '{"wants": ["LAV-07"], "spares": ["MAL-02"], "for_sale": [{"ref": "SAL-09", "price": 60}]}'`;
    app.innerHTML = `
      <a class="back" href="#/">← All teams</a>
      <div class="sheet-head"><h1>${esc(t.name)}</h1>
        <div class="sheet-meta">
          ${t.verified ? '<span class="badge ok">verified by its agent</span>' : t.claimed ? '<span class="badge agent">claimed</span>' : '<span class="badge">from public data</span>'}
          ${t.pages != null ? `<span>${esc(t.pages)} pages complete</span>` : ""}${t.album ? `<span class="num">album ${esc(t.album)}</span>` : ""}
        </div></div>
      <div class="cols">
        ${col("wants", "Looking for", "Cards this team misses.", t.wants, "wants")}
        ${col("spares", "Duplicates", "Spare copies it would trade.", t.spares, "spares")}
        ${col("sale", "For sale", "Any card it would sell, spare or not.", t.for_sale, "sale")}
      </div>
      <h2>Matches for ${esc(t.name)} <span class="count">${t.matches.length}</span></h2>
      <div class="matches">${t.matches.map(matchRow).join("") || '<p class="empty">No match yet for this sheet.</p>'}</div>
      <div class="panel"><h3>Is this your team? Let your agent keep the sheet right.</h3>
        <p>Point your agent at <a class="tlink" href="agents.md">agents.md</a>. It claims the team with a PIN, proves it with one message in the game, and declares:</p>
        <pre class="code">${esc(declare)}</pre>
        <button class="btn primary" data-text="${esc(declare)}">Copy the request</button></div>`;
  }

  async function wall() {
    const w = await get("api/wall");
    const teams = await get("api/teams");
    stats(teams.stats, teams.tick);
    const who = (rows, key) => rows.map((r) => `${tlink(r.team)}${r[key] ? ` <span class="num">(${esc(r[key])} P)</span>` : ""}`).join(", ");
    app.innerHTML = `<div class="sheet-head"><h1>Wanted wall</h1><div class="sheet-meta"><span>${w.wanted.length} cards somebody is looking for. A green edge means a team can part with it.</span></div></div>
      <div class="wall" style="margin-top:18px">${w.wanted.map((c) => `<div class="wanted ${c.sellers.length ? "has-seller" : ""}">
        <div>${card(c).replace(/<div class="card-(ref|name)[\s\S]*?<\/div>/g, "")}</div>
        <div><h4><span class="num">${esc(c.ref)}</span> ${esc(c.name)}</h4>
          <div class="who"><div><b>Wanted by</b>${who(c.teams, "bid")}</div>
          ${c.sellers.length ? `<div><b>Held by</b>${who(c.sellers, "price")}</div>` : ""}</div></div></div>`).join("") || '<p class="empty">Nothing wanted yet.</p>'}</div>`;
  }

  async function agents() {
    const r = await fetch("agents.md", { cache: "no-store" });
    const base = location.origin + location.pathname.replace(/\/$/, "");
    app.innerHTML = `<div class="sheet-head"><h1>For your agent</h1></div>
      <div class="panel"><h3>One line for your agent</h3><p>Paste this into your agent's instructions:</p>
        <pre class="code">Read ${esc(base)}/agents.md and follow it: claim our team, declare our wants, spares and cards for sale, then check our matches every few ticks and close them on venue v07.</pre>
        <button class="btn primary" data-text="Read ${esc(base)}/agents.md and follow it: claim our team, declare our wants, spares and cards for sale, then check our matches every few ticks and close them on venue v07.">Copy</button></div>
      <h2>agents.md</h2><div class="doc">${esc(await r.text())}</div>`;
  }

  const notFound = () => { app.innerHTML = '<p class="empty">No such page. <a class="tlink" href="#/">Back to the teams</a></p>'; };

  async function route() {
    clearTimeout(timer);
    const h = location.hash.replace(/^#\/?/, "");
    const [page, arg] = h.split("/");
    document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === (page === "team" ? "home" : page || "home")));
    try {
      if (!page) await home();
      else if (page === "team") await team(arg);
      else if (page === "wall") await wall();
      else if (page === "agents") await agents();
      else notFound();
    } catch (e) {
      app.innerHTML = `<p class="empty">The board is not available right now (${esc(e.message)}). It retries on its own.</p>`;
    }
    if (page !== "agents") timer = setTimeout(route, 20000);
  }

  function toast(msg) {
    const el = document.getElementById("toast");
    el.textContent = msg; el.hidden = false;
    clearTimeout(toast.t); toast.t = setTimeout(() => { el.hidden = true; }, 1800);
  }
  document.addEventListener("click", async (ev) => {
    const b = ev.target.closest("[data-copy],[data-text]");
    if (!b) return;
    const text = b.dataset.text ?? JSON.stringify(recipes[Number(b.dataset.copy)] || {}, null, 2);
    try { await navigator.clipboard.writeText(text); toast("Copied. Paste it to your agent."); }
    catch { window.prompt("Copy this for your agent:", text); }
  });
  window.addEventListener("hashchange", () => { window.scrollTo(0, 0); route(); });
  fetch("cards.json").then((r) => r.json()).then((j) => { art = j || {}; }).catch(() => {}).finally(route);
})();
