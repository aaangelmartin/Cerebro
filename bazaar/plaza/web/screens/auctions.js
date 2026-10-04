// auctions: lots running now and the last ones. The card, the best bid, ticks left, every bid in public, and how
// many teams want it. A connected team bids, starts a lot from a card it holds, and accepts or withdraws its own.
Plaza.screen("auctions", {
  title: "nav.auctions",
  render(root, ctx) {
    const { el } = K;
    const st = { data: null, cat: {}, error: null, busy: false, form: Boolean(ctx.query && ctx.query.card) };
    const REF = /^[A-Z]{3}-\d{2}$/;

    root.appendChild(K.pageHead(t("nav.auctions"), t("auc.sub"), K.link("/plaza/board", { class: "btn sm" }, K.icon("performance", 13), t("nav.board"))));
    const feeds = root.appendChild(el("div", { class: "board-feeds id" }));
    const make = root.appendChild(el("div"));
    const body = root.appendChild(el("div", { class: "auc-body" }));
    body.appendChild(K.state("loading"));
    root.appendChild(el("p", { class: "muted board-note" }, t("auc.public")));
    root.appendChild(K.endpoint("GET /plaza/lots.json", "POST /plaza/api/lots", "POST /plaza/api/lot/<id>/bid"));

    const feed = (path, label) => el("span", { class: "board-feed" }, el("a", { href: path, target: "_blank", rel: "noopener" }, label || path.replace("/plaza/", "")),
      el("button", { type: "button", class: "board-copy", title: t("board.copy"), "aria-label": t("board.copy") + " " + path, onclick: () => K.copy(location.origin + path) }, K.icon("copy", 12)));
    K.add(feeds, [el("span", { class: "label" }, t("auc.json")), feed("/plaza/lots.json"), feed("/plaza/AGENTS-AUCTIONS.md"), feed("/plaza/board.json")]);

    const card = (lot) => ({ ...(st.cat[lot.ref] || {}), ref: lot.ref, name: lot.name, rarity: lot.rarity });
    function send(path, payload, done) {
      if (st.busy) return;
      st.busy = true;
      API.post(path, payload).then((out) => { K.toast(done || t("auc.done"), "ok"); return out; }, (e) => { K.toast((e && e.message) || t("common.error"), "bad"); })
        .then(() => { st.busy = false; load(); });
    }

    function drawMake() {
      K.clear(make);
      if (!ctx.me) { make.appendChild(el("p", { class: "coll-connect" }, K.link("/plaza/connect", { class: "btn sm" }, K.icon("agent", 13), t("auc.connect")))); return; }
      if (!st.form) { make.appendChild(el("p", { class: "coll-connect" }, K.btn(t("auc.new"), { small: true, onclick: () => { st.form = true; drawMake(); } }))); return; }
      const input = (key, attrs) => el("label", { class: "auc-field" }, el("span", { class: "label" }, t(key)), el("input", { class: "input", ...attrs }));
      const ref = input("auc.card", { type: "text", maxlength: "6", autocomplete: "off", value: (ctx.query && ctx.query.card) || "" });
      const start = input("auc.startPrice", { type: "number", min: "1", max: "2000", step: "1", inputmode: "numeric" });
      const reserve = input("auc.reserve", { type: "number", min: "1", max: "2000", step: "1", inputmode: "numeric" });
      const ticks = input("auc.ticks", { type: "number", min: "4", max: "240", step: "1", inputmode: "numeric", value: "40" });
      const val = (f) => f.querySelector("input").value.trim();
      const go = K.btn(t("auc.create"), { small: true, kind: "primary", onclick: () => {
        const r = val(ref).toUpperCase();
        if (!REF.test(r)) return K.toast(t("auc.badRef"), "bad");
        const payload = { card: r };
        for (const [k, f] of [["start", start], ["reserve", reserve], ["ticks", ticks]]) {
          if (val(f) === "") continue;
          const n = Number(val(f));
          if (!Number.isInteger(n) || n < 1) return K.toast(t("board.badPrice"), "bad");
          payload[k] = n;
        }
        st.form = false;
        send("/api/lots", payload, t("auc.created", { ref: r }));
        drawMake();
      } });
      make.appendChild(K.panel({ title: t("auc.new"), icon: "cards" }, el("div", { class: "auc-form" }, ref, start, reserve, ticks,
        el("div", { class: "board-form-btns" }, go, K.btn(t("board.cancel"), { small: true, onclick: () => { st.form = false; drawMake(); } }))),
        el("p", { class: "muted board-help" }, t("auc.public"))));
    }

    function lotBox(lot) {
      const you = lot.you || {};
      const open = lot.state === "open";
      const left = open ? t(lot.ticks_left === 1 ? "auc.left1" : "auc.left", { n: lot.ticks_left }) : null;
      const tone = { open: "ok", awarded: "ok", settled: "ok", ended: "warn" }[lot.state];
      const acts = [];
      if (ctx.me && open && you.role !== "seller") {
        acts.push(K.btn(t("auc.bidAt", { price: K.price(lot.next_bid) }), { small: true, kind: you.winning ? null : "primary", disabled: Boolean(you.winning),
          onclick: () => send("/api/lot/" + lot.id + "/bid", { price: lot.next_bid }) }));
      }
      if (you.role === "seller" && (open || lot.state === "ended") && lot.best_bid) acts.push(K.btn(t("auc.accept"), { small: true, kind: "primary", onclick: () => send("/api/lot/" + lot.id + "/accept", {}) }));
      if (you.role === "seller" && (open || lot.state === "ended")) acts.push(K.btn(t("auc.cancel"), { small: true, onclick: () => send("/api/lot/" + lot.id + "/cancel", {}) }));
      if (!ctx.me && open) acts.push(K.link("/plaza/connect", { class: "btn sm" }, K.icon("agent", 13), t("auc.bid")));
      const bids = lot.bids.slice().reverse().slice(0, 6);
      return el("div", { class: "auc-lot" + (open ? "" : " is-done") },
        el("div", { class: "auc-card" }, K.card(card(lot), { size: "md", href: "/plaza/card/" + lot.ref })),
        el("div", { class: "auc-main" },
          el("div", { class: "auc-top" }, K.link("/plaza/card/" + lot.ref, { class: "board-title" }, lot.name),
            el("span", { class: "chip" + (tone ? " tone-" + tone : "") }, t("auc.state." + lot.state)),
            you.role === "seller" ? el("span", { class: "chip" }, t("auc.yours")) : you.role === "bidder" && open ? el("span", { class: "chip" + (you.winning ? " tone-ok" : "") }, t(you.winning ? "auc.winning" : "auc.outbid")) : null),
          el("div", { class: "id muted" }, lot.ref.replace("-", " · ") + "  ·  " + t("rarity." + (lot.rarity || "common")) + "  ·  " + t("auc.seller", { team: K.teamName(lot.seller) }) + "  ·  " + lot.id),
          el("div", { class: "auc-price" }, el("span", { class: "num auc-best" }, lot.best_bid ? K.price(lot.best_bid) : "–"),
            el("span", { class: "label" }, lot.best_bid ? t("auc.best") + " · " + t("auc.by", { team: K.teamName(lot.best_bidder) }) : t("auc.noBid") + " · " + t("auc.start", { price: K.price(lot.start) }))),
          el("div", { class: "id" }, [left, open ? t("auc.ends", { tick: K.tick(lot.ends_tick) }) : null, open ? t("auc.next", { price: K.price(lot.next_bid) }) : null,
            t(lot.bid_count === 0 ? "auc.bids0" : lot.bid_count === 1 ? "auc.bids1" : "auc.bids", { n: lot.bid_count }),
            you.role === "seller" ? t(you.reserve_set ? "auc.reserveSet" : "auc.reserveNone") : null].filter(Boolean).join("  ·  ")),
          lot.wanted_by ? el("div", { class: "id get" }, t(lot.wanted_by === 1 ? "auc.wanted1" : "auc.wanted", { n: lot.wanted_by })) : null,
          acts.length ? el("div", { class: "auc-acts" }, acts) : null),
        el("div", { class: "auc-bids" }, el("div", { class: "label" }, t("auc.history")),
          bids.length ? bids.map((b) => el("div", { class: "auc-bid id" + (b.state === "live" ? " live" : "") }, el("span", { class: "num" }, K.price(b.price)), el("span", null, K.teamName(b.team)),
            el("span", { class: "muted" }, K.tick(b.tick) + " · " + t("auc.b." + b.state)))) : el("div", { class: "id muted" }, t("auc.bids0"))));
    }

    function draw() {
      K.clear(body);
      if (st.error) { body.appendChild(K.state("error", t("common.error"), st.error, K.btn(t("common.retry"), { small: true, onclick: load }))); return; }
      const d = st.data;
      if (!d) { body.appendChild(K.state("loading")); return; }
      body.appendChild(K.panel({ title: t("auc.live"), note: t((d.lots || []).length === 1 ? "common.card1" : "common.cards", { n: (d.lots || []).length }), icon: "activity" },
        (d.lots || []).length ? el("div", { class: "auc-list" }, d.lots.map(lotBox)) : K.state("empty", t("auc.none"), t("auc.noneText")),
        el("p", { class: "muted board-help" }, t("auc.commit", { n: (d.rules || {}).post_ticks || 12 }))));
      if ((d.recent || []).length) body.appendChild(K.panel({ title: t("auc.recent"), icon: "offers" }, el("div", { class: "auc-list" }, d.recent.map(lotBox))));
    }

    function load() { return API.get("/api/lots").then((d) => { st.data = d; st.error = null; draw(); }, (e) => { if (!st.data) { st.error = (e && e.message) || t("common.error"); draw(); } }); }
    drawMake();
    API.get("/api/board").then((d) => { (d.cards || []).forEach((c) => { st.cat[c.ref] = c; }); draw(); }, () => {});
    const stop = API.poll("/api/lots", 5000, (d) => { st.data = d; st.error = null; draw(); }, (e) => { if (!st.data) { st.error = (e && e.message) || t("common.error"); draw(); } });
    return () => stop();
  },
});
