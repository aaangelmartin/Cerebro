/* window.api — calls to the Bazaar API (relative URLs: works at / and behind the gateway's /v2/). */
(function () {
  "use strict";
  class ApiError extends Error {
    constructor(status, message, body) { super(message || ("HTTP " + status)); this.name = "ApiError"; this.status = status; this.body = body; }
  }
  const TTL = 1500;
  const cache = new Map();   // url -> {at, promise}

  function qs(params) {
    const parts = [];
    for (const [k, v] of Object.entries(params || {})) {
      if (v === undefined || v === null || v === "") continue;
      parts.push(encodeURIComponent(k) + "=" + encodeURIComponent(v));
    }
    return parts.length ? "?" + parts.join("&") : "";
  }

  async function request(method, path, body) {
    const opts = { method, headers: { Accept: "application/json" }, cache: "no-store" };
    if (method !== "GET") {
      opts.headers["X-Dashboard"] = "1";
      if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    }
    let res;
    try { res = await fetch("api/" + path, opts); }
    catch (e) { throw new ApiError(0, "Sin conexión con la API"); }
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (!res.ok) throw new ApiError(res.status, (data && (data.message || data.error)) || ("HTTP " + res.status), data);
    return data;
  }

  function get(path, params, ttl) {
    const url = path + qs(params);
    const now = Date.now();
    const hit = cache.get(url);
    if (hit && now - hit.at < (ttl === undefined ? TTL : ttl)) return hit.promise;
    const promise = request("GET", url);
    cache.set(url, { at: now, promise });
    promise.catch(() => { if (cache.get(url) && cache.get(url).promise === promise) cache.delete(url); });
    return promise;
  }

  function write(method, path, body) { cache.clear(); return request(method, path, body); }

  const enc = encodeURIComponent;
  window.ApiError = ApiError;
  window.api = {
    ApiError,
    get, clearCache() { cache.clear(); },
    overview: (since) => get("overview", { since }),
    status: () => get("status"),
    control: (body) => body === undefined ? get("control") : write("POST", "control", body),
    getControl: () => get("control"),
    controlLog: (since, limit) => get("control-log", { since, limit }),
    decisions: (since, limit) => get("decisions", { since, limit }),
    outcomes: (since, limit) => get("outcomes", { since, limit }),
    council: (since, limit) => get("council", { since, limit }),
    events: (since, limit) => get("events", { since, limit }),
    attribution: (since, limit) => get("attribution", { since, limit }),
    leaderboard: (since, limit) => get("leaderboard", { since, limit }),
    llm: (since, limit) => get("llm", { since, limit }),
    lessons: () => get("lessons"),
    setLesson: (id, status, why) => write("POST", "lessons/" + enc(id), { status, why }),
    novelty: (since, limit) => get("novelty", { since, limit }),
    spend: () => get("spend"),
    llmHealth: () => get("llm/health", {}, 5000),
    brainBudget: () => get("brain/budget", {}, 0),
    strategy: (limit) => get("strategy", { limit }),
    brainChat: (since) => get("brain/chat", { since }, 0),
    brainSay: (text, by) => write("POST", "brain/chat", { text, by: by || "equipo" }),
    outbox: (o) => get("outbox", { kind: o && o.kind, status: o && o.status, since: o && o.since }, 0),
    outboxSet: (id, status, note) => write("POST", "outbox/" + enc(id), { status, note: note || "" }),
    external: (since) => get("brain/external", { since }, 0),
    externalAdd: (text, by, team_hint) => write("POST", "brain/external", team_hint ? { text, by, team_hint } : { text, by }),
    dealerChat: (dealer) => get("dealer-chat", { dealer }, 0),
    dealerChatDo: (what, body) => write("POST", "dealer-chat/" + what, body),
    broker: () => get("broker"),
    duelsLive: () => get("duels"),
    tickLatest: () => get("tick/latest"),
    stop: (by) => write("POST", "stop", { by: by || "dashboard" }),
    unstop: () => write("DELETE", "stop"),
    rec: (name) => get("rec/latest/" + String(name).split("/").map(enc).join("/")),
    recStream: (stream, o) => get("rec/stream/" + enc(stream), { since_seq: o && o.since_seq, limit: o && o.limit, tail: o && o.tail }),
    recDuels: () => get("rec/duels"),
    recDuel: (id) => get("rec/duels/" + enc(id)),
    recThreads: () => get("rec/threads"),
    recThread: (id) => get("rec/threads/" + enc(id)),
    recIndex: () => get("rec/index"),
    notifications: (since) => get("notifications", { since }, 0),
  };
})();
