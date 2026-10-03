// Plaza admin: our own view of the public board. Served only behind the dashboard login.
(() => {
  "use strict";
  const UI = window.PlazaUI, { esc } = UI;
  const app = document.getElementById("app");
  const A = "/plaza/admin/api";
  const get = async (p) => (await fetch(A + p, { cache: "no-store" })).json();
  const act = async (body) => {
    await fetch(A + "/action", { method: "POST", headers: { "Content-Type": "application/json", "X-Dashboard": "1" }, body: JSON.stringify(body) });
    draw();
  };
  const when = (ts) => ts ? UI.ago(ts) + " ago" : "never";

  async function draw() {
    const [o, a] = await Promise.all([get("/overview"), get("/activity")]);
    document.getElementById("stats").innerHTML = [["Plaza", o.enabled ? "on" : "off"], ["Claimed", o.active_teams], ["Verified", o.verified_teams], ["Tick", o.tick ?? "—"]]
      .map(([l, v]) => `<div class="stat"><span class="stat-l">${l}</span><span class="stat-v">${esc(v)}</span></div>`).join("");
    const f = o.funnel, row = (cells) => `<div class="trow" style="grid-template-columns: repeat(${cells.length}, minmax(0, 1fr))">${cells.map((c) => `<span>${c}</span>`).join("")}</div>`;
    app.innerHTML = `<div class="sheet-head"><h1>Plaza admin</h1><div class="sheet-meta">
        <button class="btn" data-act='{"action":"${o.enabled ? "off" : "on"}"}'>${o.enabled ? "Close the plaza" : "Open the plaza"}</button>
        <button class="btn" data-act='{"action":"refresh"}'>Refresh now</button></div></div>
      <h2>Funnel</h2><div class="table">${row(["matches proposed", "open offers on v07", "following a match", "offers listed on v07", "deals on v07", "volume", "mm_points", "fees saved"].map(esc))}
        ${row([f.matches_proposed, f.open_offers_on_venue, f.open_offers_following_a_match, f.offers_listed_on_venue, f.deals_on_venue, f.volume_on_venue + " P", o.value.mm_points ?? "—", (o.value.saved_fees ?? 0) + " P"].map((v) => `<b class="num">${esc(v)}</b>`))}</div>
      <h2>Teams</h2><div class="table">${row(["team", "state", "declared", "agent seen", "last post", "wants / available / matches", ""].map(esc))}
        ${o.teams.map((t) => row([UI.teamLink(t.team), t.verified ? UI.chip("verified", "ok") : t.claimed ? UI.chip("claimed", "agent") : UI.chip("public"), esc(when(t.declared_at)), esc(when(t.last_seen)), esc(when(t.last_post)),
          `<span class="num">${esc(t.wants)} / ${esc(t.available)} / ${esc(t.matches)}</span>`,
          `<button class="btn" data-act='{"action":"${t.blocked ? "unblock" : "block"}","team":"${esc(t.team)}"}'>${t.blocked ? "Unblock" : "Block"}</button>`])).join("")}</div>
      <h2>Requests <span class="count">${esc(o.totals.requests)} · ${esc(o.totals.errors)} errors · ${esc(o.floor.streams)} live streams</span></h2>
      <div class="table">${Object.entries(o.requests).map(([k, v]) => row([esc(k), `<span class="num">${esc(v.requests)}</span>`, `<span class="num">${esc(v.errors)} errors</span>`])).join("")}</div>
      <h2>Activity <span class="count">${esc(a.items.length)} items, hidden ones included</span></h2>
      <div class="floor-wrap"><div class="floor tall">${a.items.slice().reverse().map((m) => UI.msgRow(m).replace("</div>\n      <span class=\"msg-time", (m.src === "agent" ? ` <button class="btn" data-act='{"action":"${m.hidden ? "unhide" : "hide"}","message":${Number(m.id)}}'>${m.hidden ? "Unhide" : "Hide"}</button>` : "") + "</div>\n      <span class=\"msg-time")).join("")}</div></div>`;
  }
  document.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-act]");
    if (b) act(JSON.parse(b.dataset.act));
  });
  draw(); setInterval(draw, 15000);
})();
