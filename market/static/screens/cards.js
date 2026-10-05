// cards: My cards. Two zones: what the team can part with (red) and what it wants (green), with the private
// limits only this team sees. The agent keeps all of it; the human's only tool is a quiet override, which is a
// POST /api/me/cards with the browser session and can be handed back to the agent card by card.
Plaza.screen("cards", {
  title: "nav.cards", needsTeam: true,
  render(root, ctx) {
    const { el } = K;
    const REF = /^[A-Z]{3}-\d{2}$/;
    const SHOWN = 6;                                          // wanted cards before "Show more"
    // Limits live in this closure only: never in localStorage, sessionStorage or the URL.
    const st = { data: null, market: {}, catalog: [], editing: false, edits: {}, more: false, saving: false, error: null };

    const head = root.appendChild(el("div"));
    root.appendChild(Signals.block(ctx, "both"));
    const body = root.appendChild(el("div", { class: "cards-body" }));
    body.appendChild(K.state("loading", t("cards.loading")));
    root.appendChild(K.endpoint("GET /Cerebro/market/api/me/cards", "POST /Cerebro/market/api/me/cards", "POST /Cerebro/market/api/me/card/<ref>", "PUT /Cerebro/market/api/team/<team>"));

    // ---- numbers typed by a human: whole, 1 to 2000, or empty
    const whole = (v) => (v === "" || v === null || v === undefined ? null : /^\d{1,4}$/.test(String(v).trim()) ? parseInt(v, 10) : NaN);
    const valid = (n) => n === null || (Number.isInteger(n) && n >= 1 && n <= 2000);
    const edit = (ref) => st.edits[ref] || (st.edits[ref] = {});
    const pending = () => Object.keys(st.edits).filter((r) => Object.keys(st.edits[r]).length).length;
    const overrides = () => [].concat(st.data.have || [], st.data.want || []).filter((c) => c.by === "human");

    function numInput(ref, key, value, label) {
      const cur = key in (st.edits[ref] || {}) ? st.edits[ref][key] : value;
      const input = el("input", { class: "input cards-num num", type: "text", inputmode: "numeric", maxlength: "4", autocomplete: "off", "aria-label": label + " " + ref,
        value: cur === null || cur === undefined ? "" : String(cur), oninput: () => {
          const n = whole(input.value);
          input.classList.toggle("is-bad", !valid(n));
          if ((n === null ? null : n) === (value === undefined ? null : value)) delete edit(ref)[key]; else edit(ref)[key] = n;
          drawHead();
        } });
      return el("label", { class: "cards-field" }, el("span", { class: "label" }, label), input, el("span", { class: "cards-p" }, "P"));
    }

    // ---- one card of a zone
    function tile(c, zone) {
      const mk = st.market[c.ref] || {};
      const lim = c.limits || {};
      const removed = (st.edits[c.ref] || {}).remove;
      const info = el("div", { class: "cards-info" });
      const tags = el("div", { class: "cards-tags" });
      if (zone === "give") tags.appendChild(K.chip(t(c.as === "for_sale" ? "cards.forSale" : "cards.duplicate")));
      if (zone === "get" && c.finishes_page) tags.appendChild(K.chip(t("cards.finishes"), "signal"));
      if (c.by === "human") tags.appendChild(K.chip(t("cards.byHand"), null, "hand"));
      info.appendChild(tags);
      if (st.editing) {
        if (zone === "give") K.add(info, [c.as === "for_sale" ? numInput(c.ref, "price", c.price, t("common.price")) : el("div", { class: "cards-big" }, t("cards.swap")),
          numInput(c.ref, "min", lim.min, t("common.min")), numInput(c.ref, "value", lim.value, t("common.value"))]);
        else K.add(info, [numInput(c.ref, "bid", c.bid, t("cards.bid")), numInput(c.ref, "max", lim.max, t("common.max")), numInput(c.ref, "value", lim.value, t("common.value"))]);
        info.appendChild(el("div", { class: "cards-actions" },
          K.btn(t(removed ? "cards.keepIt" : "cards.remove"), { small: true, kind: "quiet", icon: removed ? null : "close", onclick: () => {
            if (removed) delete edit(c.ref).remove; else edit(c.ref).remove = zone;
            draw();
          } }),
          c.by === "human" ? K.btn(t("cards.release1"), { small: true, kind: "quiet", icon: "agent", onclick: () => release([{ ref: c.ref, zone, as: c.as }]) }) : null));
      } else {
        if (zone === "give") info.appendChild(el("div", { class: "cards-big num" }, c.as === "for_sale" && typeof c.price === "number" ? K.price(c.price) : t("cards.swap")));
        else info.appendChild(el("div", { class: "cards-line" }, el("span", { class: "muted" }, t(typeof c.bid === "number" ? "cards.bid" : "common.max")),
          el("span", { class: "cards-big num" }, typeof c.bid === "number" ? K.price(c.bid) : typeof lim.max === "number" ? K.price(lim.max) : "–")));
        const priv = [];
        if (zone === "give" && typeof lim.min === "number") priv.push([t("common.min").toLowerCase(), lim.min]);
        if (zone === "get" && typeof c.bid === "number" && typeof lim.max === "number") priv.push([t("common.max").toLowerCase(), lim.max]);
        if (typeof lim.value === "number") priv.push([t("cards.worth"), lim.value]);
        if (priv.length) info.appendChild(el("div", { class: "cards-line cards-private", title: t("common.private") }, K.icon("lock", 12),
          priv.map(([k, v]) => el("span", null, el("span", { class: "muted" }, k + " "), el("b", { class: "num" }, K.price(v))))));
        // the market's last price of the card, on its own line so it never gets cut
        if (typeof mk.last_price === "number") info.appendChild(el("div", { class: "cards-line" }, el("span", { class: "muted" }, t("cards.last")),
          el("b", { class: "num" }, K.price(mk.last_price)), el("span", { class: "id" }, K.tick(mk.last_tick))));
        const n = zone === "give" ? mk.seekers : mk.holders;
        info.appendChild(el("div", { class: "cards-line muted" }, zone === "give"
          ? (n ? t(n === 1 ? "cards.wantedBy1" : "cards.wantedBy", { n }) : t("cards.nobodyAsking"))
          : (n ? t(n === 1 ? "cards.heldBy1" : "cards.heldBy", { n }) : t("cards.nobodySelling"))));
      }
      return el("div", { class: "cards-tile" + (removed ? " is-removed" : "") },
        K.card(c, { owned: zone === "give", size: "md", href: st.editing ? null : "/Cerebro/market/card/" + c.ref }), info);
    }

    // ---- adding a card by hand (override only)
    function adder(zone) {
      const list = "cards-catalog";
      const input = el("input", { class: "input", type: "text", maxlength: "6", autocomplete: "off", spellcheck: "false", list, placeholder: t(zone === "give" ? "cards.addGive" : "cards.addGet"),
        "aria-label": t(zone === "give" ? "cards.addGive" : "cards.addGet") });
      const add = () => {
        const ref = input.value.trim().toUpperCase();
        if (!REF.test(ref)) return K.toast(t("cards.badRef"), "bad");
        if (st.catalog.length && !st.catalog.some((c) => c.ref === ref)) return K.toast(t("cards.unknownRef", { ref }), "bad");
        const here = (zone === "give" ? st.data.have : st.data.want) || [];
        if (here.some((c) => c.ref === ref)) return K.toast(t("cards.already", { ref }), "bad");
        send([{ op: "add", list: zone === "give" ? "spares" : "wants", ref }]);
      };
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
      return el("div", { class: "cards-adder" }, input, K.btn(t("cards.add"), { small: true, onclick: add }));
    }

    // ---- writes: every one is a call the agent can make too
    function send(calls) {
      if (st.saving || !calls.length) return Promise.resolve();
      st.saving = true; drawHead();
      return calls.reduce((p, c) => p.then(() => (c.limits ? API.post("/api/me/card/" + c.ref, c.limits) : API.post("/api/me/cards", c))), Promise.resolve())
        .then(() => { st.edits = {}; K.toast(t("cards.saved", { tick: K.tick((ctx.status || {}).tick) }), "ok"); },
              (e) => K.toast(t("cards.saveFailed") + (e && e.message ? ": " + e.message : ""), "bad"))
        .then(() => { st.saving = false; return load(); });
    }
    function save() {
      const calls = [];
      for (const [ref, e] of Object.entries(st.edits)) {
        if (e.remove) { calls.push({ op: "remove", list: e.remove === "get" ? "wants" : listOf(ref), ref }); continue; }
        for (const k of ["price", "bid", "min", "max", "value"]) if (k in e && !valid(e[k])) return K.toast(t("cards.badNumber"), "bad");
        const c = find(ref);
        if ("price" in e) { if (e.price === null) return K.toast(t("cards.needPrice", { ref }), "bad"); calls.push({ op: "add", list: "for_sale", ref, price: e.price }); }
        if ("bid" in e) calls.push(e.bid === null ? { op: "add", list: "wants", ref } : { op: "add", list: "wants", ref, bid: e.bid });
        const limits = {};
        for (const k of ["min", "max", "value"]) if (k in e) limits[k] = e[k];
        if (Object.keys(limits).length && c) calls.push({ ref, limits });
      }
      return send(calls);
    }
    const find = (ref) => [].concat(st.data.have || [], st.data.want || []).find((c) => c.ref === ref);
    const listOf = (ref) => { const c = (st.data.have || []).find((x) => x.ref === ref); return c && c.as === "for_sale" ? "for_sale" : c && c.as === "duplicate" ? "spares" : "have"; };
    function release(cards) {
      return send(cards.map((c) => ({ op: "release", list: c.zone === "get" ? "wants" : c.as === "for_sale" ? "for_sale" : c.as === "duplicate" ? "spares" : "have", ref: c.ref })));
    }

    // ---- drawing
    function drawHead() {
      K.clear(head);
      const d = st.data;
      if (!d) { head.appendChild(K.pageHead(t("nav.cards"), t("cards.sub"))); return; }
      const mine = overrides();
      const right = st.editing
        ? [K.btn(t("cards.discard"), { kind: "quiet", onclick: () => { st.editing = false; st.edits = {}; draw(); } }),
           K.btn(t("cards.saveOverride"), { icon: "check", disabled: st.saving || !pending(), onclick: save }),
           K.btn(t("cards.release"), { icon: "agent", disabled: st.saving || !mine.length, title: t("cards.releaseHint"),
             onclick: () => release((d.have || []).filter((c) => c.by === "human").map((c) => ({ ref: c.ref, zone: "give", as: c.as }))
               .concat((d.want || []).filter((c) => c.by === "human").map((c) => ({ ref: c.ref, zone: "get" })))) })]
        : [K.btn(t("cards.override"), { small: true, kind: "quiet", icon: "hand", onclick: () => { st.editing = true; draw(); } })];
      head.appendChild(K.pageHead(t("nav.cards"), st.editing ? t("cards.subOverride", { n: pending() }) : t("cards.subAgent", { tick: K.tick(d.tick) }), ...right));
      if (st.editing) head.querySelector(".page-title").appendChild(el("span", { class: "chip tone-signal cards-mode" }, t("cards.overrideTag")));
      head.appendChild(el("p", { class: "cards-privacy" }, K.icon("lock", 13), t("cards.privacy")));
    }

    function draw() {
      drawHead();
      K.clear(body);
      const d = st.data;
      if (st.error) { body.appendChild(K.state("error", t("common.error"), st.error, K.btn(t("common.retry"), { small: true, onclick: load }))); return; }
      if (!d) { body.appendChild(K.state("loading", t("cards.loading"))); return; }
      const give = (d.have || []).filter((c) => c.as !== "keep");
      const kept = (d.have || []).filter((c) => c.as === "keep");
      const want = d.want || [];
      if (!give.length && !want.length && !kept.length && !st.editing) {
        body.appendChild(K.state("empty", t("cards.emptyTitle"), t("cards.emptyText"), K.btn(t("cards.seeApi"), { small: true, onclick: () => ctx.go("/Cerebro/market/docs") })));
        return;
      }
      const count = (n) => t(n === 1 ? "common.card1" : "common.cards", { n });
      const zone = (kind, title, cards, emptyKey) => {
        const shown = kind === "get" && !st.more && !st.editing ? cards.slice(0, SHOWN) : cards;
        return K.panel({ title, note: count(cards.length), icon: kind, zone: kind },
          st.editing ? adder(kind) : null,
          cards.length ? el("div", { class: "cards-grid" }, shown.map((c) => tile(c, kind))) : el("p", { class: "muted cards-none" }, t(emptyKey)),
          shown.length < cards.length ? el("button", { class: "btn cards-more", type: "button", onclick: () => { st.more = true; draw(); } },
            t("cards.showMore", { n: cards.length - shown.length }), K.icon("chevron", 14)) : null);
      };
      body.appendChild(el("div", { class: "cards-zones" }, zone("give", t("cards.available"), give, "cards.noneGive"), zone("get", t("cards.wanted"), want, "cards.noneGet")));
      if (kept.length) body.appendChild(K.panel({ title: t("cards.kept"), note: count(kept.length), icon: "shield" },
        el("div", { class: "card-strip" }, kept.map((c) => K.card(c, { size: "sm", href: "/Cerebro/market/card/" + c.ref })))));
      if (st.editing && st.catalog.length && !document.getElementById("cards-catalog")) {
        body.appendChild(el("datalist", { id: "cards-catalog" }, st.catalog.map((c) => el("option", { value: c.ref }, c.name))));
      }
    }

    function load() {
      return API.get("/api/me/cards").then((d) => { st.data = d; st.error = null; draw(); }, (e) => { st.error = (e && e.message) || t("common.error"); if (!st.data) draw(); });
    }
    const timer = setInterval(() => { if (!st.editing && !st.saving && !document.hidden) load(); }, 5000);
    load();
    // The market gives each card's last price and how many teams hold or want it. Public numbers only.
    const stopMarket = API.poll("/api/market", 15000, (m) => {
      st.catalog = m.cards || [];
      st.market = Object.fromEntries(st.catalog.map((c) => [c.ref, c]));
      if (st.data && !st.editing) draw();
    }, () => {});
    return () => { clearInterval(timer); stopMarket(); };
  },
});
