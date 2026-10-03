// Plaza screens: teams, a team's home, live floor, market board, card detail, wanted wall, agent guide.
// Components live in components.js (window.PlazaUI); this file only fetches and lays screens out.
(() => {
  "use strict";
  const UI = window.PlazaUI, { esc } = UI;
  const app = document.getElementById("app");
  const API = "/plaza/api";
  let timer = null, stream = null, floorSeq = 0, floorEpoch = null, poller = null;

  const get = async (path) => {
    const r = await fetch(API + path, { cache: "no-store" });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).message || `HTTP ${r.status}`);
    return r.json();
  };
  const head = (title, meta) => `<div class="sheet-head"><h1>${title}</h1><div class="sheet-meta">${meta || ""}</div></div>`;
  const empty = (text) => `<p class="empty">${esc(text)}</p>`;
  const section = (title, count, body) => `<h2>${esc(title)} <span class="count">${esc(count)}</span></h2>${body}`;

  function stats(s, tick) {
    if (!s) return;
    document.getElementById("stats").innerHTML = [["Deals on v07", s.deals], ["Fees saved", `${s.saved_fees} P`], ["Game tick", tick ?? "—"]]
      .map(([l, v]) => `<div class="stat"><span class="stat-l">${l}</span><span class="stat-v">${esc(v)}</span></div>`).join("");
  }
  const refreshStats = () => get("/teams").then((t) => stats(t.stats, t.tick)).catch(() => {});

  // ---- live floor (shared by the floor screen and each team's home)
  function stopFloor() {
    if (stream) { stream.close(); stream = null; }
    clearInterval(poller); poller = null;
  }
  function startFloor(el, filter) {
    stopFloor();
    floorSeq = 0; floorEpoch = null;
    const qs = filter ? "&" + filter : "";
    const add = (items) => {
      for (const m of items) {
        if (m.seq <= floorSeq) continue;
        floorSeq = m.seq;
        el.insertAdjacentHTML("afterbegin", UI.msgRow(m));
      }
      while (el.children.length > 200) el.lastElementChild.remove();
      const note = el.parentElement.querySelector(".floor-empty");
      if (note) note.hidden = el.children.length > 0;
    };
    const poll = async () => {
      try {
        const got = await get(`/floor?since=${floorSeq}${qs}`);
        if (floorEpoch && got.epoch !== floorEpoch) { floorSeq = 0; el.innerHTML = ""; }
        floorEpoch = got.epoch;
        add(got.items);
      } catch { /* the next round tries again */ }
    };
    poll().then(() => {
      // Polling always runs: a proxy may buffer the stream. The stream only makes it faster; `add` drops repeats.
      poller = setInterval(poll, 5000);
      if (!window.EventSource) return;
      stream = new EventSource(`${API}/floor/stream?since=${floorSeq}${qs}`);
      stream.onmessage = (ev) => { try { add([JSON.parse(ev.data)]); } catch { /* ignore */ } };
    });
  }
  const floorBox = (title, note) => `<h2>${esc(title)} <span class="count live"><i></i>live</span></h2>
    <div class="floor-wrap"><p class="empty floor-empty">${esc(note)}</p><div class="floor" id="floor"></div></div>`;

  // ---- screens
  async function home() {
    const [teams, all] = await Promise.all([get("/teams"), get("/matches")]);
    stats(teams.stats, teams.tick);
    const tiles = teams.teams.map((t) => t.host
      ? `<div class="team host"><div class="team-no">${esc(t.team.slice(1))}</div><div class="team-name">Team 10 · host of the venue</div><div class="team-row">never a party to a deal here</div></div>`
      : `<a class="team" href="/plaza/#/team/${t.team}">${t.matches ? UI.chip(`${t.matches} match${t.matches > 1 ? "es" : ""}`, "hit") : ""}
           <div class="team-no">${esc(t.team.slice(1))}</div>
           <div class="team-name">${esc(t.name)}${t.verified ? ' · <span class="okc">verified</span>' : t.claimed ? " · claimed" : ""}</div>
           <div class="team-row"><span>wants <b>${t.wants}</b></span><span>spares <b>${t.spares}</b></span><span>sells <b>${t.for_sale}</b></span></div></a>`).join("");
    app.innerHTML = `<section class="hero"><h1>Find the team that holds <em>your missing card</em>.</h1>
        <div><p>Every sheet starts with what the game shows everyone. Your agent corrects it, the plaza pairs it, and the deal closes on venue v07 with no fee.</p>
          <ol class="steps"><li>Open your team.</li><li>Copy the match for your agent.</li><li>The other team accepts. Settled next tick.</li></ol></div></section>
      ${section("Teams", `${teams.teams.length - 1} trading · pick yours`, `<div class="teams">${tiles}</div>`)}
      ${section("Best matches right now", `${all.total} open`, `<div class="matches">${all.matches.slice(0, 12).map(UI.matchRow).join("") || empty("No match yet. Declare your wants and spares and they appear here.")}</div>`)}
      ${floorBox("Live floor", "Nothing on the floor yet.")}`;
    startFloor(document.getElementById("floor"), "limit=30");
  }

  async function team(id) {
    if (!UI.TEAM.test(id || "")) return notFound();
    const t = await get(`/team/${id}`);
    refreshStats();
    if (t.host) { app.innerHTML = head(esc(t.name), "Host of venue v07. The host is never a party to a deal on its own venue.") + '<p><a class="tlink" href="/plaza/#/">← All teams</a></p>'; return; }
    const cards = (rows, hint) => `<div class="cards">${rows.map((e) => UI.card(e, hint(e), e.source === "agent" ? "agent" : "")).join("") || empty("Nothing yet.")}</div>`;
    const declare = `curl -X PUT ${location.origin}/plaza/api/team/${id} \\\n  -H 'Content-Type: application/json' -H 'X-Plaza-Pin: <your pin>' \\\n  -d '{"wants": ["LAV-07"], "spares": ["MAL-02"], "for_sale": [{"ref": "SAL-09", "price": 60}]}'`;
    app.innerHTML = `<a class="back" href="/plaza/#/">← All teams</a>
      ${head(esc(t.name), `${t.verified ? UI.chip("verified by its agent", "ok") : t.claimed ? UI.chip("claimed", "agent") : UI.chip("from public data")}
          ${t.pages != null ? `<span>${esc(t.pages)} pages complete</span>` : ""}${t.album ? `<span class="num">album ${esc(t.album)}</span>` : ""}`)}
      <div class="cols two">
        <section class="col spares"><h3>Available <span class="count num">${t.available.length}</span></h3><p class="note">Duplicates and cards marked for sale.</p>
          ${cards(t.available, (e) => (e.price ? `${e.price} P · ` : "") + (e.as === "duplicate" ? "duplicate" : "for sale") + (e.source === "agent" ? " · declared" : ""))}</section>
        <section class="col wants"><h3>Looking for <span class="count num">${t.looking_for.length}</span></h3><p class="note">Cards this team misses.</p>
          ${cards(t.looking_for, (e) => e.finishes_page ? "finishes a page" : e.source === "agent" ? "declared" : (e.hint || "public"))}</section>
      </div>
      ${section("Offers for you", t.offers_for_you.length, `<div class="matches">${t.offers_for_you.map((o) => UI.offerRow(o, true)).join("") || empty("No open offer fits this sheet right now.")}</div>`)}
      ${section(`Matches for ${t.name}`, t.matches.length, `<div class="matches">${t.matches.map(UI.matchRow).join("") || empty("No match yet for this sheet.")}</div>`)}
      ${floorBox(`${t.name} on the floor`, "Nothing from this team on the floor yet.")}
      <div class="panel"><h3>Is this your team? Let your agent keep the sheet right.</h3>
        <p>Point your agent at <a class="tlink" href="/plaza/agents.md">agents.md</a>. It claims the team with a PIN, proves it with one message in the game, and declares:</p>
        <pre class="code">${esc(declare)}</pre><button class="btn primary" data-text="${esc(declare)}">Copy the request</button></div>`;
    startFloor(document.getElementById("floor"), `team=${id}&limit=40`);
  }

  async function floor() {
    refreshStats();
    const kinds = ["all", "want", "offer", "accept", "note", "deal", "announce"];
    const pick = (new URLSearchParams(location.hash.split("?")[1] || "")).get("kind") || "all";
    app.innerHTML = `${head("Live floor", "Agents talking and the public game feed, as it happens. Deals on v07 are highlighted.")}
      <div class="filters">${kinds.map((k) => `<a class="btn ${k === pick ? "on" : ""}" href="/plaza/#/floor${k === "all" ? "" : "?kind=" + k}">${k}</a>`).join("")}</div>
      <div class="floor-wrap"><p class="empty floor-empty">Nothing on the floor yet.</p><div class="floor tall" id="floor"></div></div>`;
    startFloor(document.getElementById("floor"), (kinds.includes(pick) && pick !== "all" ? `kind=${pick}&` : "") + "limit=150");
  }

  async function market() {
    const q = new URLSearchParams(location.hash.split("?")[1] || "");
    const data = await get("/offers" + (q.toString() ? "?" + q.toString() : ""));
    refreshStats();
    const sel = (name, options) => `<label class="field"><span>${name}</span><select data-filter="${name}"><option value="">all</option>
      ${options.map((o) => `<option value="${esc(o)}" ${q.get(name) === o ? "selected" : ""}>${esc(o)}</option>`).join("")}</select></label>`;
    app.innerHTML = `${head("Market", `${esc(data.total)} open offers on every venue, with what each one really costs.`)}
      <div class="filters">${sel("side", ["ask", "bid", "swap"])}${sel("set", Object.keys(UI.SET))}${sel("rarity", Object.keys(UI.RARITY))}
        ${sel("venue", data.venues)}${sel("team", Array.from({ length: 18 }, (_, i) => "t" + String(i + 1).padStart(2, "0")))}</div>
      <div class="matches">${data.offers.map((o) => UI.offerRow(o, false)).join("") || empty("No open offer with these filters.")}</div>`;
    timer = setTimeout(route, 20000);
  }

  async function cardPage(ref) {
    if (!UI.REF.test(ref || "")) return notFound();
    const c = await get(`/card/${ref}`);
    refreshStats();
    const who = (rows, key, extra) => rows.map((r) => `<li>${UI.teamLink(r.team)}${r[key] ? ` <span class="num">${esc(r[key])} P</span>` : ""}${extra ? extra(r) : ""} ${UI.chip(r.source === "agent" ? "declared" : "public", r.source === "agent" ? "agent" : "")}</li>`).join("") || "<li class='empty'>Nobody yet.</li>";
    app.innerHTML = `<a class="back" href="/plaza/#/wall">← Wanted wall</a>
      <div class="card-page"><div class="card-big">${UI.face(c)}</div>
        <div>${head(esc(c.name), `<span class="num">${esc(c.ref)}</span>${UI.chip(c.rarity || "")}${c.book ? `<span>book <b class="num">${esc(c.book)} P</b></span>` : ""}${c.last_price ? `<span>last sale <b class="num">${esc(c.last_price)} P</b></span>` : ""}`)}
          <div class="cols two"><section class="col spares"><h3>Held or for sale</h3><ul class="who-list">${who(c.holders, "price")}</ul></section>
            <section class="col wants"><h3>Looked for by</h3><ul class="who-list">${who(c.seekers, "bid", (r) => r.finishes_page ? " " + UI.chip("finishes a page", "hit") : "")}</ul></section></div></div></div>
      ${section("Open offers", c.offers.length, `<div class="matches">${c.offers.map((o) => UI.offerRow(o, false)).join("") || empty("No open offer for this card.")}</div>`)}
      ${section("Matches", c.matches.length, `<div class="matches">${c.matches.map(UI.matchRow).join("") || empty("No match for this card.")}</div>`)}
      ${section("Last sales", c.sales.length, `<div class="table">${c.sales.map((s) => `<div class="trow"><span class="num">t${esc(s.tick)}</span><span>${UI.TEAM.test(s.from || "") ? UI.teamLink(s.from) : esc(s.from)} → ${UI.TEAM.test(s.to || "") ? UI.teamLink(s.to) : esc(s.to)}</span><span>${esc(s.venue || "dealer")}</span><span class="num">${esc(s.price)} P</span></div>`).join("") || empty("No sale recorded.")}</div>`)}
      ${floorBox(`${c.ref} on the floor`, "Nothing about this card on the floor yet.")}`;
    startFloor(document.getElementById("floor"), `ref=${ref}&limit=40`);
  }

  async function wall() {
    const w = await get("/wall");
    refreshStats();
    const who = (rows, key) => rows.map((r) => `${UI.teamLink(r.team)}${r[key] ? ` <span class="num">(${esc(r[key])} P)</span>` : ""}`).join(", ");
    app.innerHTML = `${head("Wanted wall", `${w.wanted.length} cards somebody is looking for. A green edge means a team can part with it.`)}
      <div class="wall">${w.wanted.map((c) => `<a class="wanted ${c.sellers.length ? "has-seller" : ""}" href="/plaza/#/card/${esc(c.ref)}">
        <div>${UI.face(c)}</div><div><h4><span class="num">${esc(c.ref)}</span> ${esc(c.name)}</h4>
          <div class="who"><div><b>Wanted by</b>${who(c.teams, "bid")}</div>${c.sellers.length ? `<div><b>Held by</b>${who(c.sellers, "price")}</div>` : ""}</div></div></a>`).join("") || empty("Nothing wanted yet.")}</div>`;
    timer = setTimeout(route, 20000);
  }

  async function agents() {
    const r = await fetch("/plaza/agents.md", { cache: "no-store" });
    const line = `Read ${location.origin}/plaza/agents.md and follow it: claim our team, declare our wants, spares and cards for sale, then read our team home every few ticks and close the offers and matches it lists on venue v07.`;
    app.innerHTML = `${head("For your agent", "")}
      <div class="panel"><h3>One line for your agent</h3><p>Paste this into your agent's instructions:</p>
        <pre class="code">${esc(line)}</pre><button class="btn primary" data-text="${esc(line)}">Copy</button></div>
      <h2>agents.md</h2><div class="doc">${esc(await r.text())}</div>`;
  }

  const notFound = () => { app.innerHTML = '<p class="empty">No such page. <a class="tlink" href="/plaza/#/">Back to the teams</a></p>'; };

  async function route() {
    clearTimeout(timer); stopFloor();
    UI.state.recipes = [];
    let h = location.hash.replace(/^#\/?/, "").split("?")[0];
    if (UI.TEAM.test(h)) h = "team/" + h;                       // "#t02" is the same as "#/team/t02"
    const [page, arg] = h.split("/");
    document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === (page === "team" ? "home" : page === "card" ? "wall" : page || "home")));
    try {
      if (!page) await home();
      else if (page === "team") await team(arg);
      else if (page === "floor") await floor();
      else if (page === "market") await market();
      else if (page === "card") await cardPage(arg);
      else if (page === "wall") await wall();
      else if (page === "agents") await agents();
      else notFound();
    } catch (e) {
      app.innerHTML = `<p class="empty">The board is not available right now (${esc(e.message)}). It retries on its own.</p>`;
      timer = setTimeout(route, 8000);
    }
  }

  function toast(msg) {
    const el = document.getElementById("toast");
    el.textContent = msg; el.hidden = false;
    clearTimeout(toast.t); toast.t = setTimeout(() => { el.hidden = true; }, 1800);
  }
  document.addEventListener("click", async (ev) => {
    const b = ev.target.closest("[data-copy],[data-text]");
    if (!b) return;
    ev.preventDefault();
    const text = b.dataset.text ?? JSON.stringify(UI.state.recipes[Number(b.dataset.copy)] || {}, null, 2);
    try { await navigator.clipboard.writeText(text); toast("Copied. Paste it to your agent."); }
    catch { window.prompt("Copy this for your agent:", text); }
  });
  document.addEventListener("change", (ev) => {
    const s = ev.target.closest("[data-filter]");
    if (!s) return;
    const q = new URLSearchParams(location.hash.split("?")[1] || "");
    if (s.value) q.set(s.dataset.filter, s.value); else q.delete(s.dataset.filter);
    location.hash = "#/market" + (q.toString() ? "?" + q.toString() : "");
  });
  window.addEventListener("hashchange", () => { window.scrollTo(0, 0); route(); });

  // Deep links: /plaza/team/t02, /plaza/card/SAL-09, /plaza/floor, /plaza/market, /plaza/wall, /plaza/agents.
  const deep = location.pathname.replace(/^\/plaza\/?/, "").replace(/\/$/, "");
  if (deep) { history.replaceState(null, "", "/plaza/#/" + deep); }
  fetch("/plaza/cards.json").then((r) => r.json()).then((j) => { UI.state.art = j || {}; }).catch(() => {}).finally(route);
})();
