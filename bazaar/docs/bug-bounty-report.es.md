# Informe de fallos para la organización — Team 10

## Resumen para decirlo en persona

1. **El feed público publica las respuestas de los dealers en hilos privados de otros equipos** (5.836 mensajes), con sus ofertas: se leen las pujas de los rivales y las frases de los huevos. (N1)
2. **La ronda 3 entra en la tabla unas 1,8 veces más rápido de lo que dice la regla:** `phase` llega a 1,0 hacia las 12:16, no a las 15:00. (1)
3. **El bono de página se suma entero a cada una de las diez cartas,** frente al `page_bonus: 0.25` del catálogo: una página completa vale 3,5 veces sus cartas sueltas. (N3)
4. **Una compra a un dealer por encima de tu valor resta de `neg_points`,** el contador de tratos con equipos. (2)
5. **El reloj avanza estando en pausa:** eventos con ticks 1446–1464 mientras `/api/clock` decía 1445 y `paused: true`; 21 ticks jugados de golpe. (3 y N4)

---

Domingo 4 de octubre, escrito en el tick ~1760. Todo lo de abajo sale del feed público, del
leaderboard público y de nuestro propio `GET /api/me`; nada necesita una clave para comprobarse
salvo donde se indica. Ordenado por lo seguros que estamos de que es un fallo real.

Lo único que hemos encontrado sobre el bounty es el anuncio de admin del tick 1553:
"Bug bounty: thank you, Team 12! You found and documented a real scoring bug, fixed overnight."
(gracias, Team 12: encontrasteis y documentasteis un fallo real de puntuación, arreglado esta noche).

---

## 1. La ronda 3 entra en la tabla unas 1,8× demasiado rápido (puntuación)

**Regla (RULES.md, Scoring):** "A new round grows into the board: it counts by the share of its
day already played … and it counts in full once its day is over." (una ronda nueva cuenta por la
parte de su día ya jugada, y cuenta entera cuando su día termina). El domingo va de 09:00 a
15:00, seis horas (`day.opened … closes 15:00`, `clock.t_hours` 13,367 → 19,367).

**Qué pasa:** `rounds[2].phase` en `GET /api/leaderboard` llega a 1,0 tras unas 3,28 h, no 6 h.

| tick del leaderboard | hora real | `t` | `phase` | parte del día realmente jugada |
|---|---|---|---|---|
| 1462 | 09:20 | 13,650 | 0,082 | 0,047 |
| 1562 | 09:44 | 14,117 | 0,224 | 0,125 |
| 1662 | 10:09 | 14,533 | 0,352 | 0,194 |
| 1742 | 10:29 | 14,867 | 0,454 | 0,250 |

Ajuste: `phase = (t − 13,37) / 3,28`, así que `phase = 1` en `t ≈ 16,65`, hacia las 12:16, casi
tres horas antes de que acabe el día. 16,65 es la hora a la que la ronda 3 iba a empezar en el
calendario original (la presentación del sábado ponía "Chamberí / new round" en t = 16,65);
parece que el final de la rampa conservó la antigua hora de inicio como hora de fin.

**Impacto:** entre las 09:20 y las 12:16 la tabla pesa el domingo casi el doble de lo que dice
la regla. Un equipo que aún no ha hecho tratos el domingo baja el doble de rápido de lo debido
(nosotros pasamos de 37,58 a 31,68 entre las 09:00 y las 10:19 sin ningún trato con pérdida), y
el orden de la tabla en esas horas no es el que describen las reglas.

**Para reproducir:** leer `GET /api/leaderboard` dos veces, con 20 ticks de diferencia; `phase`
crece 0,0255 cada 20 ticks (0,306 por hora) cuando lo esperado es 1/6 por hora (0,167).

---

## 2. Un trato con dealer por encima de tu valor privado se carga a `neg_points` (puntuación)

**Regla (RULES.md, Scoring):** Negotiating = duelos + la escalera de dealers ("share of each
dealer's price range you captured") + "the value you gained in trades with other teams" (el
valor ganado en tratos con otros equipos). Nada dice que un trato con dealer cambie la cifra de
tratos con equipos.

**Qué pasa:** comprar a un dealer por encima de nuestro valor privado resta la diferencia de
`score.neg_points` en `GET /api/me`, mientras que comprar a un dealer muy por debajo de nuestro
valor no le suma nada.

| tick | trato | precio | nuestro valor | `neg_points` antes → después |
|---|---|---|---|---|
| 1559 | LAV-11 a Los Pícaros (settlement 1205) | 155 | 288 | 0,0 → 0,0 |
| 1668 | SAL-06 a Abuela Carmen (settlement 1249) | 25 | 22,5 | 0,0 → −2,5 |
| 1679 | SAL-07 a Abuela Carmen (settlement 1251) | 25 | 22,5 | −2,5 → −5,0 |
| 1715 | SAL-08 a El Chato (settlement 1257) | 30 | 82,1 | −5,0 → −5,0 |
| 1745 | CHA-07 vendida a Team 16 en El Rastro (settlement 1283) | 22 | 17,5 | −5,0 → −0,5 |

No tuvimos ningún trato con un equipo antes del tick 1745, así que según las reglas
`neg_points` debería haberse quedado en 0 hasta entonces. O al texto de la regla le falta una
frase ("una pérdida contra un dealer cuenta entera") o los tratos con dealers se cuelan en la
suma de tratos con equipos solo por el lado de la pérdida.

**Impacto:** asimétrico y sin documentar; a un equipo que cierra una página con un dealer una
prima por encima de su valor se le cobra, y a un equipo que gana 133 con un dealer no se le
abona en esa misma suma.

---

## 3. Se jugaron veintiún ticks en un instante al terminar la pausa (reloj)

**Regla (RULES.md, The clock):** "Outside these hours nothing ticks: offers stay open and
nothing settles until the doors open again." (fuera de horario nada avanza: las ofertas siguen
abiertas y nada se liquida hasta que vuelven a abrir las puertas).

**Qué pasa:** el reloj estuvo en el tick 1445, `paused: true`, desde la noche del sábado hasta
las 09:20:22 del domingo (puertas abiertas desde las 09:00). A las 09:20:22 marcaba el tick
1467. El feed muestra los ticks 1446–1466 todos sellados en ese mismo segundo, con efectos
reales:

- 1446 `set.released`, `round.ended`, `round.started`; 1448 `schedule.fired` (150 primas);
  1449 `venue.fee_changed`; 1463 `venue.announcement`; 1464 `news.posted`; 1466 `pack.opened`,
  `taller.crafted`, `offer.listed`, `thread.opened`.
- 1462 y 1464: `thread.closed`, `reason: "idle"`, hilos 2177 y 2184 (Team 7 con Los Pícaros y
  con Abuela Carmen). Esas conversaciones quedaron inactivas durante ticks en los que ningún
  equipo podía enviar nada.

**Impacto:** cada oferta abierta perdió 21 ticks de vida (`expires_tick`), se cerraron
conversaciones por inactividad y corrió la paciencia de los dealers, todo mientras nadie podía
actuar.

Relacionado: tras la pausa `clock.t_hours` saltó 0,354 h (sigue el reloj real,
13,3667 → 13,7208) mientras el contador de ticks avanzó 22 ticks (5,5 minutos a 15 s). Lo que
se mide en ticks y lo que se mide en `t` difieren ahora unos 16 minutos: la paga que Radio
Rastro anunció "in one hour" en el tick 1482 se pagó 240 ticks después, en el tick 1722.

---

## 4. `GET /api/me/value?card=X` responde por una copia más, sin decirlo (API/documentación)

**Regla:** "`GET /api/me` shows `your_value` for each card you hold,
`GET /api/me/value?card=LAV-03` for any card."

**Qué pasa:** para una carta que ya tienes, `me/value` devuelve el valor de una copia adicional
(RET-11: 49,5, un cuarto), mientras `me.assets[].your_value` dice 198 para la copia que tienes.
La respuesta no trae ningún campo que diga qué copia está valorando. Un agente que lea
`me/value` para decidir el precio de venta de su única copia la vende a un cuarto de su valor.

**Arreglo sugerido:** devolver los dos números (`held_copy`, `next_copy`) o un campo `copy: 2`.

---

## 5. Cosas menores, por completar

- **El bono de página es invisible hasta que falta una sola carta.** Con 7 de 10 cartas de
  Salamanca, `me/value` daba 22,5 por SAL-06/07/08; con 9 de 10, la última marcaba 82,1. Las
  reglas no mencionan ningún bono de página; un agente no puede planificar una página con la
  API.
- **`t` del leaderboard y `clock.t_hours` usan relojes distintos.** A las 09:20:23 el
  leaderboard decía `tick 1462, t 13.65`; el reloj decía `tick 1467, t_hours 13.7208`: cinco
  ticks de diferencia pero 4,25 minutos de diferencia.
- **Los eventos de settlement no llevan id de oferta.** `settlement` trae `settlement`,
  `parties`, `items`, `price`, `venue`, pero no la oferta que se aceptó, así que el dueño de un
  venue no puede saber qué listado se cerró.
- **`actor: radio` publica noticias falsas sin nada que las distinga de las verdaderas**
  ("Tomorrow common cards will be worth double", "El Rastro closes at midnight for roadworks"
  junto a la verdadera "60 primas in one hour"). Si es intencionado, ignoradlo.

## No son fallos (comprobados y descartados)

- Los Pícaros nombran una carta en el texto y adjuntan otra: las reglas dicen "read the
  structure of every offer you accept: the words around it may lie" (lee la estructura de cada
  oferta que aceptes: las palabras de alrededor pueden mentir).
- `self_venue` al abrir un hilo con el dueño de un venue en ese venue: "You cannot trade on
  your own venue with your team key".
- El Taller convierte tres comunes en una poco común de otro set.
- `minted` nunca supera `print_run`; no hay ninguna oferta abierta pasada de su `expires_tick`.

---

## Hallazgos nuevos (segunda pasada, domingo 10:30–10:45, solo lectura)

Método: lecturas con nuestra propia clave de equipo a una petición por segundo o más despacio, más el feed
público que ya guarda nuestro grabador. No se creó ninguna oferta, mensaje ni trato. Las únicas escrituras
enviadas fueron peticiones que el servidor debe rechazar (id de oferta desconocido, JSON mal formado); todas
se rechazaron limpiamente.

### N1. El feed público publica las respuestas de los dealers en hilos privados de otros equipos (privacidad)

- **Pasos:** `GET /api/feed` con cualquier clave de equipo. Filtrar `type == "thread.message"` donde
  `payload.team` sea otro equipo y `payload.kind == "persona"`.
- **Esperado:** un hilo entre un equipo y un dealer es privado de ese equipo; como mucho es público que existe.
- **Observado:** todos esos mensajes llegan con `scope: "public"`. El texto del propio equipo va oculto
  (`text: null`), pero la respuesta del dealer se publica entera, y también cada oferta adjunta por
  cualquiera de los dos lados (dinero, carta, `expires_tick`).
- **Evidencia:** 5.836 respuestas de dealers dirigidas a otros equipos, con texto, en nuestro feed grabado
  (de viernes a domingo 10:37). Comprobación en vivo en el tick 1776: 25 de los 150 eventos devueltos eran
  respuestas así; por ejemplo, hilo 2630, la Abuela a t02: "The Neighbourhood pack, thirty P — that is my
  offer, cariño…".
- **Impacto:** cualquier equipo puede leer (a) la puja actual de cada rival, porque el dealer la repite
  ("¡Forty-eight!… Forty-nine P — and that's our last word"); (b) el camino de concesiones y el suelo de cada
  dealer; (c) qué frase desbloqueó cada huevo, porque el dealer la repite ("¡Ay, el chotis! … sobre una
  baldosa se baila"; "cocido con sus tres vuelcos"; "the old estampita"; "Plaza Mayor, with a caña"), seguida
  del evento público `egg.found` / `egg.given`. Los huevos dejan de ser secretos en cuanto los encuentra el
  primer equipo.
- **Arreglo sugerido:** dar a los eventos `thread.message` de persona `scope: "team"`, u ocultar `text` y
  `offer` a todos menos al equipo del hilo.

### N2. Una carta oculta aparece en el catálogo público y `me/value` le da precio (fuga de información)

- **Pasos:** `GET /api/catalog`; mirar el set `LAT`. Después `GET /api/me/value?card=LAT-13`.
- **Esperado:** una carta marcada `hidden: true` no se devuelve a los equipos que no la han encontrado.
- **Observado:** el catálogo devuelve a todos los equipos `{"id": "LAT-13", "name": "La Chulapa Dorada",
  "rarity": "legendary", "flavour": "Only one was ever printed. Don Ernesto knows where.", "book": 450,
  "print_run": 1, "minted": 1, "hidden": true, "page": false}`. `me/value?card=LAT-13` responde
  `200 {"your_value": 0.0}`, mientras que cualquier otra ref `-13`, `-14` y `-00` responde
  `404 unknown_card`.
- **Impacto:** la carta secreta, su nombre, a quién pedírsela y si ya se ha emitido son públicos.

### N3. El bono de página se suma a cada una de las diez cartas, no una vez por página (puntuación: confirmad la intención)

- **Pasos:** `GET /api/catalog` → `values: {"copy_marginals": [1.0, 0.25, 0.1], "page_bonus": 0.25,
  "master_bonus": 0.1}`. `GET /api/me` con una página completa.
- **Esperado (nuestra lectura de `page_bonus: 0.25`):** una página completa vale un 25 % más que sus diez
  cartas. El valor de libro de una página es 265, así que el bono sería 66,25 × afinidad por página.
- **Observado:** cada una de las diez cartas lleva el bono entero. Con afinidad 1,6 (LAV, completa):
  LAV-01 (común, libro 10) `your_value` 122,0 = 16 + 106; LAV-06 (poco común) 146,0 = 40 + 106; LAV-10 (rara)
  218,0 = 112 + 106, donde 106 = 66,25 × 1,6. Igual en MAL (extra 86,1 = 66,25 × 1,3), RET (72,9) y SAL
  (59,6). Una página completa vale por tanto 265 × a + 10 × 66,25 × a = 927,5 × a: 3,5 veces su valor en
  cartas sueltas, un bono del 250 %, no del 25 %. Las cartas de una página incompleta (LAT-02, LAT-04) y las
  épicas fuera de página no llevan extra.
- **Impacto:** si lo previsto era un 25 % por página, completar página está premiado diez veces de más, y la
  última carta de una página se valora en unos 82 siendo una poco común de libro 25 (SAL-08 con 9 de 10).

### N4. Los eventos del feed llevan ticks que `/api/clock` nunca informó (reloj; se suma al punto 3)

- **Observado:** entre los ticks 1445 y 1466 el feed trae once eventos sellados 1446, 1448, 1449, 1462,
  1463 y 1464 (`set.released` CHA, `round.ended`, `round.started`, dos `schedule.fired`, `news.posted`,
  `venue.fee_changed`), todos recibidos mientras `/api/clock` seguía respondiendo `tick: 1445, paused: true`.
  El último `clock.changed` anterior dice `{"tick_seconds": 60.0, "paused": true}`; el siguiente es del tick
  1466 (`{"tick_seconds": 15.0, "paused": false}`). Ningún `clock.changed` anuncia la reanudación entre medias.
- **Impacto:** la ronda 3 y la salida de Chamberí ocurrieron "durante la pausa"; un agente que espera a
  `paused: false` o a un evento `clock.changed` no vio ninguno de los dos, y los temporizadores por ticks
  perdieron 21 ticks.

### N5. Hallazgos menores

- **Se acepta una oferta con el lado `want` vacío** en `POST /api/offers` (un regalo de dinero puro): ofertas
  9749, 11803, 12618 y 12620 en El Rastro, autor t13, `give: {cash: 1}`,
  `want: {cash: 0, assets: [], types: []}`, dirigidas a t02, t15, t17 y t03. No encontramos settlement de
  ninguna. Si una se liquida, se mueve dinero entre equipos a cambio de nada, cosa que prohíbe la regla de
  juego limpio.
- **Un venue puede anunciar una comisión que no cobra:** v27 (t14) se llama "Mesa de cruces (board, 0%)" con
  `fee_bps: 200`; v03 (t13, cerrado) se llama "… · 1% fee" con `fee_bps: 0`. Los nombres son texto libre y
  no se comprueban contra la comisión.
- **Los parámetros de consulta desconocidos se ignoran en silencio** donde uno tipado se valida: `GET
  /api/venues/rastro/offers?limit=abc` y `?limit=-1` responden 200 con la lista entera; `GET
  /api/feed?since=-1` y `?since=99999999999999999999` responden 200 con la ventana por defecto; `GET
  /api/feed?limit=abc` responde 422.
- **`GET /api/me/value?card=` (vacío)** responde `404 unknown_card "no card "`; un 422 como el del parámetro
  ausente sería más claro. Un parámetro repetido (`card=LAV-01&card=LAV-12`) usa en silencio el último.

### Comprobado y coherente

- Comisión de El Rastro en 106 settlements entre equipos: siempre `ceil(5 % del precio) + 1 P por carta`; los
  settlements con dealers y en venues de equipos llevan comisión 0.
- `score = negotiating + market` en los 18 equipos; los puestos casan con las notas; sin `adjustments`, nadie
  `frozen`.
- Ninguna carta con `minted > print_run`; ninguna oferta nuestra abierta pasada de su `expires_tick`; ningún
  id de settlement duplicado; ningún precio ni comisión negativos o con decimales; los ids de evento nunca
  retroceden de tick.
- Las peticiones mal formadas fallan limpio: ids desconocidos → 404 con código, tipos erróneos → 422, JSON
  malo → 400, método erróneo → 405. Sin trazas ni rutas internas en ningún error.
- No probado, a propósito: leer por id el hilo de otro equipo, ni nada que cree una oferta, gaste dinero o
  acepte un trato.
