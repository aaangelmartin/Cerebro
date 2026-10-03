# Dashboard · contrato entre pantallas

El dashboard de supervisión de Team 10. El diseño aprobado está en Pencil (`dashboard.pen`): frames "01 Home" … "09 Bot" y sus detalles "01b"…; componentes: barra superior `bjgkP`, menú `K3T2g`, barra de filtros `WCson`, barra de precios `U7zsOt`/`O4j5VW`, aviso `YBhTZ`. Las reglas de estilo están en la memoria del usuario y resumidas aquí. Este fichero manda.

## Reglas de estilo (no negociables)

- Casi negro con 3 niveles (`--bg`, `--s1`, `--s2`), líneas finas `--line`. **Esquinas rectas en todo** (solo los puntos de estado son redondos).
- Fuentes: Hanken Grotesk (texto) y Geist Mono (cifras, `font-variant-numeric: tabular-nums`), desde Google Fonts.
- Listas planas como la Home: filas con línea fina abajo y **barra recta de color a la izquierda** según el tipo. Nunca bordes curvos ni bordes parciales.
- Tipos, siempre con **icono + texto** en etiqueta teñida (`ui.typeChip`): COMPRA verde, VENTA rojo, CAMBIO azul, PUJA ámbar, DUELO violeta, DEALER verde azulado, ANUNCIO gris.
- Fuentes de decisión como etiqueta de equipo (`ui.sourceTag`): Opus, Consejo n/n, Reserva, Código.
- Palabras: **Encender/Apagar** y **LIVE/PARADO**. Nunca "armar". Controles solo en la pantalla Bot.
- Somos **Team 10 · Nosotros** (`t10`), siempre resaltado igual.
- Textos en español, claros.

## Ficheros

```
bazaar/dashboard/
  index.html          esqueleto: barra superior, menú, <main id="screen">, pila de avisos  (FOUNDATION)
  styles.css          tokens y componentes compartidos                                    (FOUNDATION)
  ui.js               window.ui: componentes (ver abajo)                                  (FOUNDATION)
  api.js              window.api: llamadas a la API con caché y refresco                  (FOUNDATION)
  app.js              router por hash, refresco, barra superior, menú, avisos             (FOUNDATION)
  screens/<id>.js     una pantalla cada uno                                               (cada agente)
  screens/<id>.css    estilos propios de esa pantalla (opcional, prefijo .scr-<id>)       (cada agente)
```

Sin build ni librerías externas (salvo Google Fonts). Rutas relativas para que funcione en `127.0.0.1:8791/` y en `<pasarela>/v2/`.

## Registro de pantallas

Cada `screens/<id>.js` hace:

```js
window.Screens = window.Screens || {};
window.Screens["home"] = {
  title: "Home",
  // root: <main>; params: lo que va tras "#home/" (p. ej. "#duelos/5407" -> "5407")
  mount(root, params) { /* pinta el esqueleto y estados de carga */ },
  // se llama cada 3 s (y al entrar). data = respuesta de api.overview(); la pantalla pide además lo suyo con api.*
  async refresh(root, data, params) { /* actualiza sin perder scroll ni filtros */ },
  unmount(root) {},
};
```

Ids y orden del menú: `home`, `coleccion`, `mercado`, `duelos`, `competicion`, `rivales`, `supervision`, `laboratorio`, `bot`. Detalles por parámetro: `#coleccion/LAV-04`, `#duelos/5407`, `#mercado/historial`, `#competicion/v05`, `#rivales/t13`, `#supervision/<decision id>`, `#laboratorio/<lesson id>`. Los paneles de detalle se abren como cajón lateral con `ui.drawer`.

## `window.api` (api.js)

Todas devuelven JSON (o lanzan `ApiError` con `.status`). Lecturas cacheadas 2 s.

| Función | Endpoint | Devuelve |
|---|---|---|
| `api.overview()` | `GET overview` | resumen para barra superior y Home (existe) |
| `api.status()` | `GET status` | estado del bot (existe) |
| `api.decisions(since)` | `GET decisions?since=` | decisiones del bot (existe) |
| `api.outcomes(since)` | `GET outcomes?since=` | resultados (existe) |
| `api.council(since)` | `GET council?since=` | votos del consejo (existe) |
| `api.lessons()` | `GET lessons` | lecciones (existe) |
| `api.novelty()` | `GET novelty` | novedades (existe) |
| `api.spend()` | `GET spend` | gasto API (existe) |
| `api.broker()` | `GET broker` | estado del broker y Market Test (existe) |
| `api.duelsLive()` | `GET duels` | duelos vivos del bot (existe) |
| `api.control(body)` | `POST control` (`X-Dashboard: 1`) | cambia control (existe) |
| `api.stop()` / `api.unstop()` | `POST/DELETE stop` | STOP (existe) |
| `api.rec(name)` | `GET rec/latest/<name>` | `latest/<name>.json` de la grabadora: `clock`, `me`, `my_offers`, `leaderboard`, `venues`, `catalog`, `dealers`, `levels`, `schedule`, `cards`, `books/<venue>` (NUEVO) |
| `api.recStream(stream, {since_seq, limit, tail})` | `GET rec/stream/<stream>?since_seq=&limit=&tail=` | `{"rows":[...], "last_seq":n}` líneas del stream (`feed`, `leaderboard`, `books`, `book_snapshots`, `me`, `my_offers`, `threads`, `duels`, `cards`, `gaps`, `venues`) en orden de `seq`, de todos los días (NUEVO) |
| `api.recDuels()` / `api.recDuel(id)` | `GET rec/duels`, `GET rec/duels/<id>` | lista (cabeceras) y transcripción completa (NUEVO) |
| `api.recThreads()` / `api.recThread(id)` | `GET rec/threads`, `GET rec/threads/<id>` | lista y conversación completa con dealer (NUEVO) |
| `api.recIndex()` | `GET rec/index` | `index.json` (NUEVO) |
| `api.notifications(since)` | `GET notifications?since=` | avisos para la campana (NUEVO; ver abajo) |

Formatos de la grabadora: `bazaar/recorder/README.md`. Si un endpoint NUEVO aún no existe mientras programas, maneja el error mostrando el estado vacío; no lo inventes con datos falsos.

## `window.ui` (ui.js)

Todas devuelven un `HTMLElement` (o string HTML seguro si se indica). Escapan siempre el texto.

- `ui.el(tag, attrs, ...children)` — crear elementos.
- `ui.typeChip(type, label?, count?)` — `type` ∈ `compra venta cambio puja duelo dealer anuncio`. Icono + texto + tinte + barra izquierda.
- `ui.row({type, cells, onClick})` — fila de lista estilo Home con barra izquierda del color del tipo.
- `ui.sourceTag(source, extra?)` — `opus consejo reserva codigo`; extra p. ej. "3/3".
- `ui.resultChip(status)` — `enviado vetado rechazado pendiente sin_enviar cerrado sin_acuerdo`.
- `ui.teamTag(teamId, {us})` — cuadrado con iniciales + nombre; `t10` → "Team 10 · Nosotros" resaltado.
- `ui.filterBar({types:[...], counts, team:true, search:true, extraRows:[{label, options:[{id,label,icon,count}]}], onChange(state)})` — la barra de filtros de la Home (sus etiquetas son la leyenda). `state = {types:Set, team:"todos"|"nosotros"|"rivales"|"tNN", q, extra:{...}}`.
- `ui.priceBar({min, max, limit, ours, theirs, zone:[lo,hi], closed?:{price}|null, noDeal?:bool, history?:[...], tint, compact})` — barra de precios única: etiquetas siempre visibles ("Nosotros", "Ellos", "Límite"), Nosotros punto relleno, Ellos punto vacío, Límite muro, zona de acuerdo banda.
- `ui.kpi({label, value, sub, tone})`, `ui.meter({label, value, max})`, `ui.sparkline(values, {w,h})`, `ui.bars(series, opts)` — gráficos SVG simples.
- `ui.panel(title, {actions})` — panel con cabecera y línea fina.
- `ui.drawer({title, body})` — cajón lateral derecho; `ui.closeDrawer()`.
- `ui.empty(text)`, `ui.loading()`, `ui.error(err)` — estados.
- `ui.fmtP(n)` ("24,6 P"), `ui.fmtNum(n, dec)`, `ui.fmtTime(ts)`, `ui.fmtAgo(ts)`, `ui.tickTime(tick)`.
- `ui.confirm({title, text, confirmLabel, danger}) -> Promise<bool>` — confirmación dentro de la página (nunca `confirm()`).
- `ui.toast({type, title, text, href})` — aviso informativo (lo usa app.js).

## Avisos

`app.js` pide `api.notifications(since)` cada 3 s y muestra avisos apilados arriba a la derecha (no en Supervisión). Al pulsar, abren `#supervision/<id>`. La campana del extremo derecho de la barra superior abre el panel: activar/quitar avisos flotantes, silenciar 30 min, tipos. Preferencias en `localStorage`.
