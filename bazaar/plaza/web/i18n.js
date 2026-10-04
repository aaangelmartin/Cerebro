// Texts in English and Spanish. Each screen registers its own keys (i18n/<screen>.js) with its prefix.
//   I18N.register("en", { "home.title": "Home" });  t("home.title");  t("common.ticks", { n: 3 })
// The language is `?lang=en|es`, else what the browser stored, else English.
(function () {
  "use strict";
  const LANGS = ["en", "es"];
  const dicts = { en: {}, es: {} };
  const warned = new Set();
  let stored = null;
  try { stored = localStorage.getItem("plaza.lang"); } catch (e) { /* private window */ }
  const asked = new URLSearchParams(location.search).get("lang");
  let lang = LANGS.includes(asked) ? asked : LANGS.includes(stored) ? stored : "en";

  function register(l, dict) { Object.assign(dicts[l] || (dicts[l] = {}), dict); }

  function t(key, vars) {
    let s = dicts[lang][key];
    if (s === undefined) s = dicts.en[key];
    if (s === undefined) {
      if (!warned.has(key)) { warned.add(key); console.warn("i18n: missing key " + key); }
      return key;
    }
    return vars ? s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] === undefined ? m : String(vars[k]))) : s;
  }

  function setLang(l) {
    if (!LANGS.includes(l) || l === lang) return;
    lang = l;
    try { localStorage.setItem("plaza.lang", l); } catch (e) { /* private window */ }
    document.documentElement.lang = l;
    listeners.forEach((fn) => fn(l));
  }

  const listeners = [];
  /** Numbers as the language writes them: 1,819 in English, 1.819 in Spanish. */
  function n(num, opts) { return typeof num === "number" ? num.toLocaleString(lang === "es" ? "es-ES" : "en-GB", opts) : "–"; }

  document.documentElement.lang = lang;
  window.I18N = { register, t, setLang, n, onChange: (fn) => listeners.push(fn), get lang() { return lang; }, LANGS,
                  keys: () => ({ en: Object.keys(dicts.en), es: Object.keys(dicts.es) }) };
  window.t = t;
})();
