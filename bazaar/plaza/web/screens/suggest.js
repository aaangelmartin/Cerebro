// suggest: tell the host what to fix or add. The team's agent can send the same call.
Plaza.screen("suggest", {
  title: "nav.suggest", needsTeam: true,
  render(root, ctx) {
    const { el } = K;
    const MAX = 600, TOPICS = ["feature", "bug", "price", "other"];
    const TONE = { open: null, planned: "signal", done: "ok", dismissed: "bad" };
    const st = { topic: "feature", busy: false };

    root.appendChild(K.pageHead(t("nav.suggest"), t("suggest.sub")));
    const grid = root.appendChild(el("div", { class: "suggest-grid" }));
    root.appendChild(K.endpoint("POST /plaza/api/suggestions", "GET /plaza/api/me/suggestions"));

    // ---- the form
    const topics = el("div", { class: "suggest-seg", role: "group", "aria-label": t("suggest.topic") });
    const drawTopics = () => K.add(K.clear(topics), TOPICS.map((k) => el("button", { type: "button", class: st.topic === k ? "active" : null, "aria-pressed": String(st.topic === k),
      onclick: () => { st.topic = k; drawTopics(); } }, t("suggest.topic." + k))));
    drawTopics();
    const count = el("span", { class: "id" }, "0 / " + MAX);
    const text = el("textarea", { class: "input suggest-text", maxlength: String(MAX), rows: "7", placeholder: t("suggest.placeholder"), "aria-label": t("suggest.text"),
      oninput: () => { count.textContent = text.value.length + " / " + MAX; send.disabled = st.busy || !text.value.trim(); } });
    const send = K.btn(t("suggest.send"), { kind: "primary", disabled: true, onclick: () => {
      const body = text.value.trim().slice(0, MAX);
      if (!body || st.busy) return;
      st.busy = true; send.disabled = true;
      API.post("/api/suggestions", { text: body, topic: st.topic }).then((r) => {
        K.toast(t("suggest.sent", { id: (r && r.id) || "", tick: K.tick((Plaza.state.status || {}).tick) }), "ok");
        text.value = ""; count.textContent = "0 / " + MAX;
        return load();
      }, (e) => K.toast(t("suggest.failed") + (e && e.message ? ": " + e.message : ""), "bad")).then(() => { st.busy = false; send.disabled = !text.value.trim(); });
    } });
    grid.appendChild(K.panel({ title: t("suggest.new") },
      el("div", { class: "suggest-form" }, K.label(t("suggest.topic")), topics, K.label(t("suggest.text")), text,
        el("div", { class: "suggest-foot" }, send, el("span", { class: "muted" }, t("suggest.from", { team: ctx.me.team })), count))));

    // ---- what the team sent and our answers
    const list = el("div");
    const listPanel = grid.appendChild(K.panel({ title: t("suggest.yours"), note: t("suggest.newest"), flush: true }, list));
    list.appendChild(K.state("loading"));
    function draw(rows) {
      K.clear(list);
      listPanel.querySelector(".panel-note").textContent = rows.length + " · " + t("suggest.newest");
      if (!rows.length) { list.appendChild(el("p", { class: "muted suggest-none" }, t("suggest.none"))); return; }
      rows.slice().sort((a, b) => (b.ts || 0) - (a.ts || 0)).forEach((s) => list.appendChild(el("div", { class: "suggest-row" },
        el("span", { class: "id" }, s.id), el("span", { class: "label suggest-kind" }, t("suggest.topic." + (TOPICS.includes(s.topic) ? s.topic : "other"))),
        el("div", { class: "suggest-body" }, el("div", null, s.text), s.reply ? el("div", { class: "suggest-reply" }, t("suggest.reply") + " · " + s.reply) : null,
          el("div", { class: "id" }, K.tick(s.tick))),
        K.chip(t("suggest.status." + (s.status in TONE ? s.status : "open")), TONE[s.status] || null))));
    }
    function load() {
      return API.get("/api/me/suggestions").then((d) => draw((d && d.suggestions) || []),
        (e) => { K.clear(list).appendChild(K.state("error", t("common.error"), e && e.message)); });
    }
    const stop = API.poll("/api/me/suggestions", 15000, (d) => draw((d && d.suggestions) || []), () => {});
    return stop;
  },
});
