// settings: the three switches the contract has (language, what the agent does with a match, pause new matches)
// and the state of the connection. Every one is a POST /api/me/settings the agent can send too.
Plaza.screen("settings", {
  title: "nav.settings", needsTeam: true,
  render(root, ctx) {
    const { el } = K;
    const st = { data: null, busy: false };
    root.appendChild(K.pageHead(t("nav.settings"), K.teamName(ctx.me.team) + " · " + ctx.me.team));
    const body = root.appendChild(el("div", { class: "settings-list" }));
    body.appendChild(K.state("loading"));
    root.appendChild(K.endpoint("GET /plaza/api/me/settings", "POST /plaza/api/me/settings", t("settings.agentToo")));

    function change(patch) {
      if (st.busy) return;
      st.busy = true;
      API.post("/api/me/settings", patch).then((d) => {
        st.data = d && d.team ? d : { ...st.data, ...patch };
        K.toast(t("settings.saved", { tick: K.tick((Plaza.state.status || {}).tick) }), "ok");
        if (patch.lang) I18N.setLang(patch.lang);
      }, (e) => K.toast(t("settings.failed") + (e && e.message ? ": " + e.message : ""), "bad")).then(() => { st.busy = false; draw(); });
    }
    const seg = (key, value, options) => el("div", { class: "settings-seg", role: "group" }, options.map(([v, label]) =>
      el("button", { type: "button", class: v === value ? "active" : null, "aria-pressed": String(v === value), onclick: () => { if (v !== value) change({ [key]: v }); } }, label)));
    const row = (title, text, call, control) => el("div", { class: "settings-row" },
      el("div", { class: "settings-text" }, el("h2", null, title), el("p", null, text), call ? el("code", { class: "settings-call" }, call) : null), control);

    function draw() {
      K.clear(body);
      const d = st.data;
      if (!d) { body.appendChild(K.state("loading")); return; }
      const s = (ctx.me && ctx.me.status) || {};
      K.add(body, [
        row(t("settings.lang"), t("settings.langText"), 'POST /plaza/api/me/settings {"lang": "es"}', seg("lang", I18N.lang, [["en", "English"], ["es", "Español"]])),
        row(t("settings.trades"), t("settings.tradesText"), 'POST /plaza/api/me/settings {"default_mode": "ask_me"}',
          seg("default_mode", d.default_mode || "auto", [["auto", t("settings.auto")], ["ask_me", t("settings.askMe")]])),
        row(t("settings.matches"), t("settings.matchesText"), 'POST /plaza/api/me/settings {"paused": true}',
          seg("paused", Boolean(d.paused), [[false, t("settings.running")], [true, t("settings.paused")]])),
        row(t("settings.agent"), t("settings.agentText"), null, el("div", { class: "settings-agent" },
          K.pill(t(s.agent_online ? "status.connected" : "status.offline"), s.agent_online ? "ok" : "bad"),
          K.chip(t(s.verified ? "settings.verified" : "settings.notVerified"), s.verified ? "ok" : "warn"),
          K.chip(t(s.cards_listed ? "settings.listed" : "settings.notListed"), s.cards_listed ? "ok" : "warn"),
          K.btn(t("settings.reconnect"), { small: true, onclick: () => ctx.go("/plaza/connect") }))),
      ]);
    }
    API.get("/api/me/settings").then((d) => { st.data = d; draw(); },
      (e) => { K.clear(body).appendChild(K.state("error", t("common.error"), e && e.message, K.btn(t("common.retry"), { small: true, onclick: () => ctx.go("/plaza/settings") }))); });
  },
});
