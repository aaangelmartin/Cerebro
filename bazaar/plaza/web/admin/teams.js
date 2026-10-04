// Teams: every team's connection, what it declared, and what its agent did. Limits are never shown here:
// the panel knows which cards have one, not how much.
(function () {
  "use strict";
  const { el } = K;
  const A = window.ADM;
  const stateOf = (x) => (x.blocked ? "blocked" : x.verified ? "verified" : x.connected ? "connected" : x.pending_sessions ? "pending" : "notYet");

  Plaza.adminScreen("teams", {
    title: "nav.admin.teams",
    noOverlay: true,                                       // the panel is read with the game closed too
    render(root, ctx) {
      let picked = ctx.query.team || "", stopDetail = null;
      root.appendChild(A.head(t("nav.admin.teams"), t("admin.teams.sub")));
      root.appendChild(K.endpoint("GET /plaza/admin/api/teams", "GET /plaza/admin/api/activity?team=", "GET /plaza/api/team/<id>", "POST /plaza/admin/api/action {block | unblock}"));
      const body = root.appendChild(el("div", { class: "adm-teams" }));
      const side = root.appendChild(el("div", { class: "adm-teams-detail" }));
      const again = () => w.again();

      function drawDetail(row) {
        if (stopDetail) { stopDetail(); stopDetail = null; }
        K.clear(side);
        if (!row) return;
        const grid = side.appendChild(el("div", { class: "adm-grid adm-teams-low" }));
        grid.appendChild(K.panel({ title: t("admin.teams.connection", { team: row.team }), icon: "agent", flush: true }, A.rows([
          [t("admin.col.state"), t("admin.team." + stateOf(row)), row.verified ? "ok" : row.blocked ? "bad" : null],
          [t("admin.col.agent"), t("status." + (row.online ? "connected" : "offline")), row.online ? "ok" : row.agent ? "bad" : null],
          [t("admin.teams.agentSeen"), A.ticksAgo(row.agent_last_seen)],
          [t("admin.col.lastSync"), A.ticksAgo(row.last_sync)],
          [t("admin.teams.lastPost"), A.ticksAgo(row.last_post)],
          [t("admin.teams.pending"), K.num(row.pending_sessions || 0)],
          [t("admin.col.limits"), t(row.limits_set ? "admin.limits.setHidden" : "admin.limits.notSet")],
          [t("admin.col.matches"), K.num(row.matches || 0)],
        ]), el("div", { class: "adm-actions adm-pad" },
          row.blocked ? A.actBtn(t("admin.teams.unblock"), { action: "unblock", team: row.team }, again, { kind: "primary" })
            : A.actBtn(t("admin.teams.block"), { action: "block", team: row.team }, again, { confirm: true, kind: "danger" }),
          K.btn(t("admin.teams.trades"), { small: true, iconAfter: "arrow", onclick: () => Plaza.go("/plaza/admin/trades?team=" + row.team) }))));

        const sheet = grid.appendChild(K.panel({ title: t("admin.teams.sheet", { team: row.team }), note: t("admin.teams.sheetNote"), icon: "cards" }, K.state("loading")));
        const sheetBody = sheet.querySelector(".panel-body");
        API.get("/api/team/" + row.team).then((s) => {
          K.clear(sheetBody);
          const strip = (title, cls, cards) => [K.label(title + " · " + cards.length, "adm-zone " + cls),
            cards.length ? el("div", { class: "card-strip adm-teams-cards" }, cards.slice(0, 12).map((c) => el("div", { class: "adm-teams-card" }, K.card(c, { size: "sm", owned: cls === "give" }),
              el("span", { class: "adm-source" }, t("admin.source." + (c.source === "declared" ? "agent" : c.source === "human" ? "human" : "inferred")))))) : el("div", { class: "adm-quiet" }, t("admin.none"))];
          K.add(sheetBody, [strip(t("admin.teams.available"), "give", s.available || []), strip(t("admin.teams.wanted"), "get", s.wanted || [])]);
        }, (e) => { K.clear(sheetBody); sheetBody.appendChild(K.state(e && e.status === 404 ? "empty" : "error", null, (e && e.message) || "")); });

        const rec = grid.appendChild(K.panel({ title: t("admin.teams.record", { team: row.team }), note: t("admin.teams.recordNote"), icon: "activity", flush: true }));
        const recBody = rec.appendChild(el("div", { class: "adm-teams-record" }));
        const rw = A.watch(recBody, "/admin/api/activity", (d) => {
          const items = (d.items || []).filter((i) => !API.mock || i.team === row.team || i.to === row.team).slice(-40).reverse();
          if (Array.isArray(d.limits_set)) recBody.appendChild(el("div", { class: "adm-strip adm-pad" }, K.label(t("admin.teams.limitsOn")),
            d.limits_set.length ? d.limits_set.map((r) => K.id(r)) : K.id(t("admin.none"))));
          recBody.appendChild(items.length ? K.feed(items.map((i) => ({ tick: i.tick, text: A.item(i) }))) : K.state("empty", t("admin.teams.noRecord")));
        }, () => ({ team: row.team }));
        stopDetail = rw.stop;
      }

      const w = A.watch(body, "/admin/api/teams", (d) => {
        const teams = d.teams || [];
        body.appendChild(K.kpis([{ label: t("admin.kpi.connected"), value: K.num(d.connected || 0) + " / " + K.num(teams.length) }, { label: t("admin.kpi.verified"), value: K.num(d.verified || 0) },
                                 { label: t("admin.kpi.online"), value: K.num(d.online || 0) }, { label: t("admin.teams.limitsKpi"), value: K.num(teams.filter((x) => x.limits_set).length) }]));
        if (!teams.length) { body.appendChild(K.state("empty", t("admin.noData"))); drawDetail(null); return; }
        const order = { verified: 0, connected: 1, pending: 2, blocked: 3, notYet: 4 };
        const sorted = teams.slice().sort((a, b) => order[stateOf(a)] - order[stateOf(b)] || Number(b.online) - Number(a.online) || a.team.localeCompare(b.team));
        if (!sorted.find((x) => x.team === picked)) picked = sorted[0].team;
        const table = K.table([
          { label: t("admin.col.team"), render: (x) => A.team(x.team) },
          { label: t("admin.col.state"), render: (x) => [K.chip(t("admin.team." + stateOf(x)), { verified: "ok", blocked: "bad", pending: "warn" }[stateOf(x)] || ""), x.paused ? K.chip(t("status.paused"), "pause") : null] },
          { label: t("admin.col.agent"), render: (x) => (x.agent ? K.pill(t("status." + (x.online ? "connected" : "offline")), x.online ? "ok" : "bad") : "–") },
          { label: t("admin.col.lastSync"), render: (x) => A.ticksAgo(x.last_sync) },
          { label: t("admin.teams.available"), num: true, render: (x) => K.num(x.available || 0) },
          { label: t("admin.teams.wanted"), num: true, render: (x) => K.num(x.wants || 0) },
          { label: t("admin.col.limits"), render: (x) => t(x.limits_set ? "admin.limits.set" : "admin.limits.notSet") },
          { label: t("admin.col.matches"), num: true, render: (x) => K.num(x.matches || 0) },
        ], sorted, { onrow: (x) => { picked = x.team; w.redraw(); } });
        [...table.querySelectorAll("tbody tr")].forEach((tr, i) => { if (sorted[i].team === picked) tr.classList.add("adm-picked"); });
        body.appendChild(K.panel({ title: t("admin.teams.all"), note: t("admin.teams.allNote"), flush: true }, table));
        drawDetail(sorted.find((x) => x.team === picked));
      });
      return () => { w.stop(); if (stopDetail) stopDetail(); };
    },
  });
})();
