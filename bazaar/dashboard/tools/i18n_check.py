#!/usr/bin/env python3
"""Check the dashboard's Spanish / English dictionaries against the code.

    python bazaar/dashboard/tools/i18n_check.py [--strict] [--quiet]

Reports: keys used in the code but missing in a language, keys present in only one language, placeholders
that differ between the languages, keys nobody uses, and Spanish text still written in the .js files.
Exit code 1 when a used key is missing or the two languages differ; with --strict also when Spanish text is left.
Needs `node` (it loads the dictionaries the same way the browser does).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DICTS = ROOT / "i18n"
SKIP = {"cromo.js", "i18n.js"}          # cromo.js is the port of the official card face
TOKEN = re.compile(r"//[^\n]*|/\*.*?\*/|\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`", re.S)
PLACE = re.compile(r"\{(\w+)\}")
ACCENT = re.compile(r"[áéíóúñÁÉÍÓÚÑ¿¡º]")
WORDS = re.compile(
    r"\b(sin|hace|ahora|todos|todas|ninguna?|cargando|cerrad[oa]s?|abiert[oa]s?|tiendas?|ofertas?|compras?|ventas?|"
    r"cambios?|pujas?|duelos?|equipos?|puntos|dinero|nivel|hoy|ayer|valor|precio|cartas?|esperando|pendientes?|"
    r"enviad[oa]s?|vetad[oa]s?|rechazad[oa]s?|motivo|gasto|presupuesto|claves?|reglas|aprobar|encender|apagar|"
    r"encendid[oa]|apagad[oa]|buscar|guardar|cerrar|quedan?|nuestr[oa]s?|ellos|nosotros|desde|hasta|cada|"
    r"todav[ií]a|mejor|peor|ganancia|acuerdo|tratos?|rondas?|mensajes?|avisos?|nuevo|nueva)\b", re.I)


def load_dicts() -> dict[str, dict[str, str]]:
    files = sorted(p for p in DICTS.glob("*.js"))
    script = (
        "const d={};global.I18N={register(l,o){d[l]=Object.assign(d[l]||{},o||{});},t:(k)=>k,lang:'es'};"
        "global.window=global;"
        + "".join(f"require({json.dumps(str(p))});" for p in files)
        + "process.stdout.write(JSON.stringify(d));"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def literals(path: Path):
    """(line, text) for every string literal outside comments."""
    src = path.read_text(encoding="utf-8")
    for m in TOKEN.finditer(src):
        tok = m.group(0)
        if tok.startswith("//") or tok.startswith("/*"):
            continue
        yield src.count("\n", 0, m.start()) + 1, tok[1:-1]


def main(argv: list[str]) -> int:
    strict, quiet = "--strict" in argv, "--quiet" in argv
    dicts = load_dicts()
    es, en = dicts.get("es", {}), dicts.get("en", {})
    scopes = {k.split(".", 1)[0] for k in list(es) + list(en)}
    key_rx = re.compile(r"^(?:%s)\.[\w.]*$" % "|".join(sorted(map(re.escape, scopes)))) if scopes else None

    used: dict[str, str] = {}        # key -> first place
    prefixes: dict[str, str] = {}
    leftovers: list[str] = []
    sources = [p for p in sorted(ROOT.glob("*.js")) if p.name not in SKIP and not p.is_symlink()]
    sources += sorted((ROOT / "screens").glob("*.js"))
    for path in sources:
        rel = path.relative_to(ROOT)
        for line, text in literals(path):
            if key_rx and key_rx.match(text):
                (prefixes if text.endswith(".") else used).setdefault(text, f"{rel}:{line}")
                continue
            plain = re.sub(r"\$\{[^}]*\}", " ", text)
            if ACCENT.search(plain) or (" " in plain.strip() and WORDS.search(plain)):
                leftovers.append(f"{rel}:{line}: {text.strip()[:110]}")

    def known(key: str, d: dict) -> bool:
        return key in d or f"{key}.one" in d or f"{key}.other" in d

    missing = [f"{k}  ({where}; missing in {', '.join(l for l, d in (('es', es), ('en', en)) if not known(k, d))})"
               for k, where in sorted(used.items()) if not (known(k, es) and known(k, en))]
    dead_prefix = [f"{p}  ({where})" for p, where in sorted(prefixes.items()) if not any(k.startswith(p) for k in es)]
    only_es = sorted(set(es) - set(en))
    only_en = sorted(set(en) - set(es))
    places = [k for k in sorted(set(es) & set(en)) if set(PLACE.findall(str(es[k]))) != set(PLACE.findall(str(en[k])))]
    same = [k for k in sorted(set(es) & set(en)) if es[k] == en[k] and ACCENT.search(str(es[k]))]

    def is_used(k: str) -> bool:
        base = re.sub(r"\.(one|other)$", "", k)
        return k in used or base in used or any(k.startswith(p) for p in prefixes)

    orphans = [k for k in sorted(set(es) | set(en)) if not is_used(k)]

    def show(title: str, rows: list[str], limit: int = 400) -> None:
        print(f"\n{title}: {len(rows)}")
        if not quiet:
            for r in rows[:limit]:
                print("  " + r)
            if len(rows) > limit:
                print(f"  … {len(rows) - limit} more")

    print(f"keys: es {len(es)} · en {len(en)} · used in code {len(used)} (+{len(prefixes)} dynamic prefixes)")
    show("Used in code but missing in a dictionary", missing + dead_prefix)
    show("Only in Spanish", only_es)
    show("Only in English", only_en)
    show("Placeholders differ between languages", places)
    show("English equal to a Spanish text with accents (probably not translated)", same)
    show("Spanish text still in the code", leftovers)
    show("Keys nobody uses", orphans)
    bad = bool(missing or dead_prefix or only_es or only_en or places)
    if strict and leftovers:
        bad = True
    print("\nRESULT: " + ("FAIL" if bad else "OK"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
