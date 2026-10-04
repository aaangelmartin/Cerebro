// API: the only place that talks to the server. Screens never call fetch.
//   API.get("/api/me/trades").then(draw)            paths are under /plaza
//   API.post("/api/me/settings", { paused: true })
//   const stop = API.poll("/api/me/trades", 3000, draw, onError)
//   const stop = API.stream((item) => …)            the floor, live
// Mock mode: ?mock=1 answers from /plaza/static/fixtures (kept for the browser session; ?mock=0 leaves it).
// ?mock=closed, paused, offline, empty and error switch the matching state.
(function () {
  "use strict";
  const BASE = "/plaza";
  const asked = new URLSearchParams(location.search).get("mock");
  let mock = null;
  try {
    if (asked === "0") sessionStorage.removeItem("plaza.mock");
    else if (asked) sessionStorage.setItem("plaza.mock", asked);
    mock = sessionStorage.getItem("plaza.mock");
  } catch (e) { mock = asked && asked !== "0" ? asked : null; }

  // ---- mock: a path to its fixture
  const FIXTURES = [
    [/^\/api\/status$/, () => ({ closed: "status_closed", paused: "status_paused", offline: "status_offline" }[mock] || "status")],
    [/^\/api\/health$/, "health"], [/^\/api\/stats$/, "stats"], [/^\/api\/teams$/, "teams"], [/^\/api\/team\/t\d\d$/, "team"],
    [/^\/api\/market$/, "market"], [/^\/api\/card\/[A-Z]{3}-\d\d$/, "card"], [/^\/api\/offers$/, "offers"],
    [/^\/api\/matches$/, "matches"], [/^\/api\/match\/m-[0-9a-f]+$/, "match"], [/^\/api\/floor$/, "floor"],
    [/^\/api\/connect\/start$/, "connect_start"], [/^\/api\/connect\/status$/, "connect_status"],
    [/^\/api\/me$/, "me"], [/^\/api\/(me|agent)\/cards$/, "me_cards"], [/^\/api\/me\/trades$/, "me_trades"],
    [/^\/api\/me\/activity$/, "me_activity"], [/^\/api\/me\/settings$/, "me_settings"], [/^\/api\/me\/suggestions$/, "suggestions"],
    [/^\/api\/agent\/next$/, "agent_next"],
    [/^\/admin\/api\/([a-z]+)$/, (m) => "admin/" + m[1]],
  ];
  function fixture(path) {
    for (const [rx, name] of FIXTURES) {
      const m = rx.exec(path);
      if (m) return typeof name === "function" ? name(m) : name;
    }
    return null;
  }
  function emptied(obj) {                                    // ?mock=empty: every list comes back empty
    if (Array.isArray(obj)) return [];
    if (obj && typeof obj === "object") return Object.fromEntries(Object.entries(obj).map(([k, v]) => [k, Array.isArray(v) ? [] : v]));
    return obj;
  }
  function mocked(method, path, body) {
    if (mock === "error" && path !== "/api/status") return Promise.reject({ status: 500, error: "mock", message: "mock error" });
    const name = fixture(path);
    if (!name) return method === "GET" ? Promise.reject({ status: 404, error: "not_found", message: "no fixture for " + path }) : Promise.resolve({ ok: true, mock: true, sent: body });
    return fetch(BASE + "/static/fixtures/" + name + ".json").then((r) => {
      if (!r.ok) throw { status: 404, error: "not_found", message: "no fixture " + name };
      return r.json();
    }).then((data) => (mock === "empty" && path !== "/api/status" && path !== "/api/me" ? emptied(data) : data));
  }

  // ---- real
  function call(method, path, body, query) {
    const clean = Object.fromEntries(Object.entries(query || {}).filter(([, v]) => v !== null && v !== undefined && v !== ""));
    const qs = new URLSearchParams(clean).toString();
    if (mock) return mocked(method, path, body);
    const init = { method, credentials: "same-origin", headers: {} };
    if (body !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(body); }
    return fetch(BASE + path + (qs ? "?" + qs : ""), init).then((r) => r.json().catch(() => ({})).then((data) => {
      if (!r.ok) throw { status: r.status, error: data.error || "error", message: data.message || r.statusText };
      return data;
    }), () => { throw { status: 0, error: "offline", message: "the market does not answer" }; });
  }
  const get = (path, query) => call("GET", path, undefined, query);
  const post = (path, body) => call("POST", path, body || {});
  const put = (path, body) => call("PUT", path, body || {});

  /** Calls fn(data) now and every `ms`; skips while the tab is hidden. `path` may be a function returning
   *  [path, query] (for ?since=). Returns stop(). */
  function poll(path, ms, fn, onError) {
    let stopped = false, timer = null;
    const once = () => {
      if (stopped) return;
      if (document.hidden) { timer = setTimeout(once, ms); return; }
      const [p, q] = typeof path === "function" ? path() : [path, undefined];
      get(p, q).then((d) => { if (!stopped) fn(d); }, (e) => { if (!stopped && onError) onError(e); })
        .finally(() => { if (!stopped) timer = setTimeout(once, ms); });
    };
    once();
    return () => { stopped = true; clearTimeout(timer); };
  }

  /** The floor as it happens: server-sent events, or polling when the stream cannot be opened. Returns stop(). */
  function stream(fn, query) {
    if (mock || !window.EventSource) {
      let since = 0;
      return poll(() => ["/api/floor", { ...(query || {}), since }], 3000, (d) => { (d.items || []).forEach(fn); since = mock ? since : d.seq || since; });
    }
    const qs = new URLSearchParams(query || {}).toString();
    let es = new EventSource(BASE + "/api/floor/stream" + (qs ? "?" + qs : "")), stopPoll = null, fails = 0;
    es.onmessage = (e) => { fails = 0; try { fn(JSON.parse(e.data)); } catch (err) { /* a broken line */ } };
    es.onerror = () => {
      if (++fails < 3 || stopPoll) return;
      es.close(); es = null;
      let since = 0;
      stopPoll = poll(() => ["/api/floor", { ...(query || {}), since }], 3000, (d) => { (d.items || []).forEach(fn); since = d.seq || since; });
    };
    return () => { if (es) es.close(); if (stopPoll) stopPoll(); };
  }

  window.API = { get, post, put, poll, stream, get mock() { return mock; }, BASE };
})();
