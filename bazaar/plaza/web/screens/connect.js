// connect: the only thing a human does. Pick the team, paste one prompt to the agent, and the page watches the
// agent, in this order: it redeems the code, sends it in the game with its own key, the market sees it (identity
// verified), only then it lists its cards, and it starts reading its queue. Then How it works, then Home.
(function () {
  "use strict";
  const { el } = K;
  const CHECKS = ["agent_called", "verified", "cards_listed", "agent_online"];
  const MOCK_STEPS = { waiting: {}, called: { agent_called: true }, verified: { agent_called: true, verified: true },
                       listed: { agent_called: true, verified: true, cards_listed: true } };

  Plaza.screen("connect", {
    title: "nav.connect",
    noNav: true,
    noOverlay: true,
    render(root, ctx) {
      const st = { teams: null, team: null, start: null, status: null, checking: false, error: null, stop: null, left: false };
      const tickS = (ctx.status && ctx.status.tick_seconds) || 15;
      const ticks = (seconds) => Math.max(1, Math.round(seconds / tickS));

      root.appendChild(K.pageHead(t("connect.title"), t("connect.sub")));
      const cols = root.appendChild(el("div", { class: "connect-cols" }));
      const colTeam = cols.appendChild(el("section", { class: "panel connect-step" }));
      const colPrompt = cols.appendChild(el("section", { class: "panel connect-step" }));
      const colReady = cols.appendChild(el("section", { class: "panel connect-step" }));
      root.appendChild(el("p", { class: "connect-safe connect-rule" }, K.icon("warning", 14), t("connect.rule")));
      root.appendChild(K.endpoint("POST /plaza/api/connect/start", "GET /plaza/api/connect/status", "GET /plaza/AGENTS.md"));

      const stepHead = (n, title, done) => el("div", { class: "connect-head" },
        el("span", { class: "connect-n" + (done ? " is-done" : "") }, done ? K.icon("check", 16) : String(n)), el("h2", { class: "connect-h" }, title));

      function drawTeam() {
        K.clear(colTeam).appendChild(stepHead(1, t("connect.pick"), Boolean(st.team)));
        if (st.teams === null) { colTeam.appendChild(K.state("loading")); return; }
        if (st.teams === false) {
          colTeam.appendChild(K.state("error", null, t("connect.noTeams"), K.btn(t("common.retry"), { small: true, onclick: loadTeams })));
          return;
        }
        colTeam.appendChild(el("div", { class: "connect-teams", role: "group", "aria-label": t("connect.pick") }, st.teams.map((tm) =>
          el("button", { type: "button", class: "connect-team" + (st.team === tm.team ? " active" : ""), "aria-pressed": String(st.team === tm.team),
                         title: K.teamName(tm.team), onclick: () => pick(tm.team) }, tm.team))));
        colTeam.appendChild(el("p", { class: "connect-hint" }, st.team ? t("connect.picked", { name: K.teamName(st.team), team: st.team }) : t("connect.pickHint")));
      }

      function drawPrompt() {
        K.clear(colPrompt).appendChild(stepHead(2, t("connect.paste"), Boolean(st.status && st.status.agent_called)));
        if (!st.team) { colPrompt.appendChild(el("p", { class: "connect-wait" }, t("connect.pickFirst"))); return; }
        if (st.already) {
          colPrompt.appendChild(el("div", { class: "connect-result is-ok", role: "status" }, K.icon("check", 18),
            el("div", null, el("div", { class: "connect-result-title" }, t("connect.alreadyTitle", { name: K.teamName(st.team) })), el("div", null, t("connect.alreadyText")))));
          colPrompt.appendChild(K.btn(t("connect.enter"), { kind: "primary", iconAfter: "arrow", onclick: () => ctx.go("/plaza/home") })).classList.add("connect-copy");
          colPrompt.appendChild(K.btn(t("connect.again"), { small: true, onclick: () => pick(st.team, true) }));
          return;
        }
        if (st.error) {
          colPrompt.appendChild(K.state("error", null, st.error, K.btn(t("common.retry"), { small: true, onclick: () => pick(st.team) })));
          return;
        }
        if (!st.start) { colPrompt.appendChild(K.state("loading")); return; }
        const left = st.status ? st.status.code_expires_in : st.start.code_expires_in;
        colPrompt.appendChild(el("pre", { class: "connect-prompt", tabindex: "0", "aria-label": t("connect.paste") }, st.start.prompt));
        colPrompt.appendChild(K.btn(t("connect.copy"), { kind: "primary", icon: "copy", onclick: () => K.copy(st.start.prompt, t("connect.copied")) })).classList.add("connect-copy");
        colPrompt.appendChild(el("div", { class: "connect-meta" },
          el("span", null, t("connect.code")), K.id(st.start.connect_code),
          st.status && st.status.agent_called ? el("span", null, t("connect.codeUsed")) : left > 0 ? el("span", null, t("connect.expires", { n: ticks(left) }))
            : K.btn(t("connect.newCode"), { small: true, onclick: () => pick(st.team) })));
        colPrompt.appendChild(el("p", { class: "connect-safe" }, K.icon("shield", 14), t("connect.safe")));
      }

      function drawReady() {
        const s = st.status;
        K.clear(colReady).appendChild(stepHead(3, t("connect.ready"), Boolean(s && s.connected)));
        if (!st.start) {
          colReady.appendChild(K.btn(t("connect.readyBtn"), { disabled: true })).classList.add("connect-ready");
          colReady.appendChild(el("p", { class: "connect-wait" }, t("connect.readyHint")));
          return;
        }
        if (s && s.connected) {
          colReady.appendChild(el("div", { class: "connect-result is-ok", role: "status" }, K.icon("check", 18),
            el("div", null, el("div", { class: "connect-result-title" }, t("connect.connected")), el("div", null, t("connect.connectedText", { name: K.teamName(st.team) })))));
          colReady.appendChild(K.btn(t("connect.seeHow"), { kind: "primary", iconAfter: "arrow", onclick: finish })).classList.add("connect-ready");
          return;
        }
        const verified = Boolean(s && s.verified);
        if (verified) {                                             // the team is proved: the human goes in and watches,
          colReady.appendChild(K.btn(t("connect.enter"), { kind: "primary", iconAfter: "arrow", onclick: finish })).classList.add("connect-ready");   // first and biggest
          colReady.appendChild(el("div", { class: "connect-result is-ok", role: "status" }, K.icon("check", 18),
            el("div", null, el("div", { class: "connect-result-title" }, t("connect.verifiedTitle")), el("div", null, t("connect.verifiedText", { name: K.teamName(st.team) })))));
        }
        const box = colReady.appendChild(el("div", { class: "connect-result", role: "status" }));
        box.appendChild(el("div", { class: "connect-result-title" }, verified ? t("connect.agentLeft") : s && s.agent_called ? t("connect.notYet") : t("connect.waiting")));
        const now = CHECKS.find((k) => !(s && s[k]));                 // the checks happen in this order: the first one missing is the one to wait for
        box.appendChild(el("ol", { class: "connect-checks" }, CHECKS.map((k) => {
          const ok = Boolean(s && s[k]);
          return el("li", { class: ok ? "is-ok" : k === now ? "is-now" : "" }, K.icon(ok ? "check" : k === now ? "clock" : "close", 13),
            el("span", null, t("connect.check." + k), !ok && k === now ? el("span", { class: "connect-check-help" }, t("connect.help." + k)) : null));
        })));
        const seen = s && s.agent_last_seen ? Math.round(Date.now() / 1000 - s.agent_last_seen) : null;
        if (s && s.agent_called && seen !== null && seen > 60) {
          box.appendChild(el("p", { class: "connect-hint connect-stopped" }, K.icon("warning", 13), t("connect.stopped", { n: seen })));
        }
        if (verified) {                                             // what to tell the agent, ready to copy
          const say = t("connect.tell", { team: st.team });
          box.appendChild(el("pre", { class: "connect-prompt connect-tell", tabindex: "0" }, say));
          box.appendChild(K.btn(t("connect.copyTell"), { small: true, icon: "copy", onclick: () => K.copy(say, t("connect.copiedTell")) }));
        }
        const again = colReady.appendChild(K.btn(st.checking ? t("connect.checking") : verified ? t("connect.checkAgain") : t("connect.readyBtn"),
          { disabled: st.checking, small: verified, onclick: () => check(true) }));
        if (!verified) again.classList.add("connect-ready");
        if (st.checked) colReady.appendChild(el("p", { class: "connect-hint", role: "status" }, st.checked));
        if (!verified) colReady.appendChild(el("p", { class: "connect-hint" }, t("connect.listedHint")));
        colReady.appendChild(el("p", { class: "connect-hint" }, t("connect.auto")));
      }

      const draw = () => { drawTeam(); drawPrompt(); drawReady(); };

      function finish() {
        st.left = true;
        Plaza.refresh().then(() => ctx.go("/plaza/how?first=1"), () => ctx.go("/plaza/how?first=1"));
      }

      function check(byHand) {
        if (!st.start || st.left) return Promise.resolve();
        if (byHand) { st.checking = true; drawReady(); }
        return API.get("/api/connect/status").then((s) => {
          const step = API.mock ? MOCK_STEPS[ctx.query.step] : null;      // mock only: the states before "connected"
          if (step) s = { ...s, connected: false, agent_called: false, verified: false, cards_listed: false, agent_online: false, ...step };
          st.status = s; st.checking = false;
          if (st.left) return;
          if (byHand) st.checked = s.connected ? "" : t("connect.checkedAt", { time: new Date().toLocaleTimeString(), what: (s.missing || []).map((k) => t("connect.check." + k)).join(", ") });
          if (!API.mock && !s.agent_called && !s.connected && s.code_expires_in <= 0) { pick(st.team); return; }   // the code ran out unused: a fresh prompt, by itself
          draw();
          if (s.connected) { if (st.stop) st.stop(); st.stop = null; setTimeout(() => { if (!st.left) finish(); }, 1600); }
        }, (e) => {
          st.checking = false;
          if (st.left) return;
          if (e && e.status === 401) { st.start = null; st.status = null; st.error = t("connect.expired"); if (st.stop) st.stop(); st.stop = null; }
          else if (byHand) K.toast((e && e.message) || t("common.error"), "bad");
          draw();
        });
      }

      function pick(team, again) {
        const inAs = Plaza.hasTeam() && Plaza.state.me.team;       // this browser already holds a proved session
        if (inAs && inAs === team && !again && !st.start) { st.team = team; st.already = true; draw(); return; }
        st.already = false;
        if (st.stop) st.stop();
        Object.assign(st, { team, start: null, status: null, error: null, stop: null });
        draw();
        API.post("/api/connect/start", { team, lang: I18N.lang }).then((out) => {
          if (st.left || st.team !== team) return;
          st.start = out;
          draw();
          let timer = setInterval(() => { if (!document.hidden) check(false); }, 3000);
          st.stop = () => clearInterval(timer);
        }, (e) => {
          if (st.left || st.team !== team) return;
          st.error = (e && e.message) || t("common.error");
          draw();
        });
      }

      function loadTeams() {
        st.teams = null; drawTeam();
        API.get("/api/teams").then((d) => {
          if (st.left) return;
          st.teams = (d.teams || []).filter((tm) => !tm.host && tm.team !== d.host);
          const asked = ctx.query.team;
          draw();
          if (asked && st.teams.some((tm) => tm.team === asked)) pick(asked);
        }, () => { if (!st.left) { st.teams = false; drawTeam(); } });
      }

      draw();
      loadTeams();
      return () => { st.left = true; if (st.stop) st.stop(); };
    },
  });
})();
