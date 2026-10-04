# Informe de fallos para la organización — Team 10

## Resumen para decirlo en persona

1. **La ronda 3 entra en la tabla unas 1,8 veces más rápido de lo que dicen las reglas:** `phase` llega a 1,0 hacia las 12:16, no a las 15:00.
2. **Una compra a un dealer por encima de tu valor resta de `neg_points`,** el contador de tratos con equipos; una compra a dealer muy por debajo no suma ahí.
3. **Al quitar la pausa se jugaron 21 ticks de golpe:** hilos cerrados por "idle" y ofertas que perdieron 21 ticks de vida sin que nadie pudiera actuar.

Además: `GET /api/me/value` da el valor de una copia más sin decirlo (RET-11: 49,5 frente a 198).

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
