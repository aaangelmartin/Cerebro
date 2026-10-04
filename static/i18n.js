/* window.I18N — Spanish / English for the dashboard. Loaded before ui.js; dictionaries live in i18n/<scope>.js
   and call I18N.register(lang, {...}) with flat keys ("scope.key"). See i18n/README.md. */
(function () {
  "use strict";
  const LANGS = ["es", "en"];
  const LOCALES = { es: "es-ES", en: "en-GB" };
  const STORE = "bazaar.lang";
  const dicts = { es: {}, en: {} };
  const warned = new Set();

  function pick() {
    let q = null;
    try { q = new URLSearchParams(location.search).get("lang"); } catch (e) { q = null; }
    if (q && LANGS.includes(q.toLowerCase())) return q.toLowerCase();
    let s = null;
    try { s = localStorage.getItem(STORE); } catch (e) { s = null; }
    return LANGS.includes(s) ? s : "es";
  }

  function register(lang, dict) {
    if (!dicts[lang]) dicts[lang] = {};
    Object.assign(dicts[lang], dict || {});
  }
  function has(key, lang) { return Object.prototype.hasOwnProperty.call(dicts[lang || I18N.lang] || {}, key); }
  function fill(s, vars) {
    if (!vars) return s;
    return s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] === undefined || vars[k] === null ? m : String(vars[k])));
  }
  function t(key, vars) {
    const own = dicts[I18N.lang] || {};
    let s = Object.prototype.hasOwnProperty.call(own, key) ? own[key] : undefined;
    if (s === undefined && Object.prototype.hasOwnProperty.call(dicts.es, key)) s = dicts.es[key];
    if (s === undefined) {
      if (!warned.has(key)) { warned.add(key); console.warn("i18n: missing key " + key); }
      return key;
    }
    return fill(String(s), vars);
  }
  // plural(3, "common.team") -> "common.team.one" for 1, "common.team.other" otherwise; {n} is filled in.
  function plural(n, key, vars) {
    const k = key + (Number(n) === 1 ? ".one" : ".other");
    return t(has(k) || has(k, "es") ? k : key, Object.assign({ n }, vars || {}));
  }
  function n(num, opts) {
    if (num === null || num === undefined || num === "" || !isFinite(Number(num))) return "—";
    return Number(num).toLocaleString(I18N.locale, opts || {});
  }
  // 3 -> "3.º" (es) / "3rd" (en)
  function ordinal(num) {
    const v = Number(num);
    if (!isFinite(v)) return String(num);
    if (I18N.lang !== "en") return v + ".º";
    const a = v % 10, b = v % 100;
    return v + (a === 1 && b !== 11 ? "st" : a === 2 && b !== 12 ? "nd" : a === 3 && b !== 13 ? "rd" : "th");
  }
  // "a, b and c" / "a, b y c"
  function list(items) {
    const ls = (items || []).map(String);
    if (!ls.length) return "";
    if (ls.length === 1) return ls[0];
    return ls.slice(0, -1).join(", ") + " " + t("common.and") + " " + ls[ls.length - 1];
  }
  // The screens build text when they load, so a language change reloads the page (the hash keeps the screen).
  function setLang(lang) {
    lang = String(lang || "").toLowerCase();
    if (!LANGS.includes(lang) || lang === I18N.lang) return;
    try { localStorage.setItem(STORE, lang); } catch (e) { /* private mode */ }
    let url = null;
    try {
      const u = new URL(location.href);
      if (u.searchParams.has("lang")) { u.searchParams.set("lang", lang); url = u.href; }
    } catch (e) { url = null; }
    if (url) location.replace(url); else location.reload();
  }

  const lang = pick();
  const I18N = { lang, locale: LOCALES[lang], langs: LANGS, dicts, register, t, has, plural, n, ordinal, list, setLang };
  document.documentElement.lang = lang;
  window.I18N = I18N;
  window.t = t;
})();
