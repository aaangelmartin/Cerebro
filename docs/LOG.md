# Bitácora

Hallazgos con fecha y hora de Madrid, los más recientes arriba. La referencia consolidada está en [`BAZAAR.md`](BAZAAR.md).

## 2026-10-03 04:50 — Bot auditado en 3 rondas y grabadora en marcha

- **12 consultores independientes, en 3 rondas,** revisaron el bot nuevo: API real, seguridad, ensayos generales, Laboratorio, robustez de 20 h, duelos, mercado, revisión de código, regresiones y un equipo rojo. Los últimos votos son **listo**. Todos los fallos graves están arreglados con su test (457 tests).
- **Fallos importantes encontrados y corregidos:**
  - dealers y mercado arrancaban sin catálogo;
  - el puesto gratis podía pasar por nuestra tienda y no se abría nunca;
  - los duelos se podían pausar o perder la única aceptación del tick;
  - el ciclo de aprendizaje no se cerraba;
  - rivales podían bloquear nuestras 6 conversaciones;
  - una subida de comisión tras aceptar costaba −226 P.
- **Decisiones del equipo:**
  - publicar solo en El Rastro, para no dar puntos de mercado a rivales;
  - duelos en modo acotado (Claude propone, el código no le deja ceder de más);
  - sobres solo si valen claramente más;
  - cerrar rápido los regateos pequeños;
  - la oferta final de un dealer gana la aceptación a un duelo que puede esperar.
- **Grabadora:** guarda todo lo que pasa en el juego (feed sin huecos, libros de todos los mercados, clasificación, chats con dealers, historial completo de duelos, historial de cartas) en `bazaar/data/record/`.
- **Ensayo general:** 140,7 puntos con Opus frente a 132,3 solo con código; tienda abierta en el tick de la paga; Market Test nunca por debajo del puesto gratis.
- **Pendiente para las 09:00:** encender el bot y, tras la paga, comprobar en `/api/venues` que nuestra tienda es `board`.

## 2026-10-03 02:25 — Bot nuevo (`bazaar/`) listo para las 09:00

- **Bot reescrito de cero** en `bazaar/` (rama `feat/bazaar-v2`). Lo explica todo [`bazaar/README.md`](../bazaar/README.md) y las interfaces están en [`bazaar/CONTRACTS.md`](../bazaar/CONTRACTS.md). El código del viernes pasa a `legacy/`.
- **Claude decide.** Opus 5.5 con esfuerzo bajo; un consejo (3 opiniones + juez) para aceptar, cerrar duelos y compras de más de 60 P. El código pone 10 raíles con tests.
- **Laboratorio:** aprende solo de nuestros datos y de los de todos los equipos. Propone lecciones, las prueba (backtest, simulador, sombra) y las promueve con una puerta de código. Arranca con 25 lecciones del viernes.
- **Mercado:** tienda propia `board` con comisión 0 a las ~09:03 y broker en código para el Market Test.
- **Medido:** Opus responde en 3–7 s con ticks de 30 s, y 32 de 35 llamadas llegaron a tiempo. En simulación el broker empata o supera al puesto gratis (0,92 en normal, 0,87 frente a 0,86 en el difícil). No hay ningún acuerdo fuera del límite.
- **Ojo:** en muestras pequeñas del simulador, Claude no superó a la regla de código ni en duelos ni con dealers. Por eso el prompt le da la sugerencia del código y le pide desviarse solo con un motivo concreto. El juego real dirá quién acierta más.

## 2026-10-02 22:45 — Duelos de práctica: fórmula de puntuación confirmada

Con los 7 acuerdos de la sesión de práctica queda confirmado, al decimal:

**puntos = margen × (1 − decay) ^ rondas**, con `decay` = 0,06 por ronda.

El margen es `precio − nuestro coste` si vendemos, o `nuestro valor − precio` si compramos.

| Duelo | Papel | Límite | Precio | Rondas | Margen | Puntos |
|---|---|---|---|---|---|---|
| 211 | compra | 151 | 114 | 1 | 37 | 34,8 |
| 173 | compra | 87 | 59 | 0 | 28 | 28,0 |
| 257 | compra | 132 | 103 | 3 | 29 | 24,1 |
| 60 | compra | 124 | 105 | 6 | 19 | 13,1 |
| 78 | vende | 91 | 110 | 10 | 19 | 10,2 |
| 77 | compra | 173 | 163 | 7 | 10 | 6,5 |
| 59 | vende | 61 | 66 | 4 | 5 | 3,9 |

**Lo que implica:** alargar una ronda más solo compensa si esa ronda mejora el margen **más de un 6 %**. En el duelo 78 el bot negoció 10 rondas y perdió casi la mitad del valor (19 → 10,2). Los duelos cerrados en 0–3 rondas dieron 24–35 puntos.

**Sin acuerdo = 0 puntos**, igual que no jugar. En los duelos 5 y 6 el rival no hizo ninguna oferta.

## 2026-10-02 22:35 — Qué hace el Team 13 (1.º, 30/30 en negociación)

- **Más acuerdos que nadie:** 22, frente a nuestros 16. En los últimos ticks **vende a los dealers las cartas que valen poco para ellos**: SAL-01 por 5 P y SAL-02 por 6 P a Abuela; LAT-09 (rara) por 46 P y MAL-06 por 15 P a El Chato. Cada venta negociada es un acuerdo de escalera y, si el precio supera su valor privado, también suma ganancia de valor.
- **Anuncian en El Rastro** lo que les sobra (MAL-06, LAV-03, MAL-01, LAT-04).
- **Ya tienen mercado propio:** `v03` "Mercado Trece · 1% fee", con mecanismo `board` y fianza de 250, abierto en el tick 129. También tienen mercado t06 (v01, 0,5 %), t12 (v02, 0 %) y t02 (v04, `auto`, 0 %). Nadie tiene todavía puntos de mercado: el primer Market Test es a la hora 3,0, el sábado.
- **Abuela hace regalos:** "gift from Abuela Carmen", una LAT-05 al Team 13. Los regalos no puntúan.
- **Para nosotros:** seguir vendiendo a los dealers las 7 cartas cedidas (el bot ya lo hace) y abrir el mercado propio antes del Market Test.

## 2026-10-02 22:05 — El bot vendió SAL-10 por error (corregido)

- **Qué pasó:** en el tick 98 el bot aceptó una puja del Team 13 de 70 P por **SAL-10, que era del equipo**. Respetaba la regla de "solo vende lo suyo" al anunciar cartas, pero no al aceptar pujas.
- **Efecto:** +65 P de dinero (70 menos 5 de comisión) y unos +2 de valor, porque para nosotros valía 63. Pero se perdió la carta que se estaba usando para conseguir LAV-09 del Team 7.
- **Corregido** en `market.py` y cubierto por un test. Los 65 P se han descontado de la cartera del bot porque son del equipo.
- **Otros movimientos:** el bot compró SAL-07 a Abuela por 21 P (para nosotros vale 22,5), y vuestro anuncio vendió la segunda LAT-04 al Team 4 por 6 P.

## 2026-10-02 21:05 — Por qué vamos primeros (29,13 puntos)

- **De dónde salen:** el desglose de `/api/me` es `neg_points` 2,0, `ladder_points` 0,053, duelos 0 y mercado 0. Casi todo viene de la **ganancia en valor privado**, no de la escalera. Los regateos acabaron cerca del precio de Abuela, así que la escalera aporta poco.
- **Qué hicimos:** 5 acuerdos.

  | Carta | Precio | Valor para nosotros |
  |---|---|---|
  | LAV-08 | 17 | 40 |
  | LAV-06 | 24 | 40 |
  | LAV-07 | 24 | 40 |
  | LAV-02 (en El Rastro, a t06) | ~12 con comisión | 16 |
  | MAL-07 | 23 | 32,5 |

  El valor de la colección pasó de 233,9 a 402,4 (+168,5) gastando unos 102 P: unos **+66 P netos** de valor privado.
- **La clave:** Abuela vende igual a todos (las poco comunes por unos 23–24 P, cerca de su valor de libro de 25), pero para nosotros LAV vale ×1,6 y MAL ×1,3. Cada carta de LAV o MAL que no tenemos es ganancia pura. Las repetidas no, porque la 2.ª copia vale el 25 %.
- `/api/me/value` no incluye el bonus de página. El catálogo dice `page_bonus` 0,25, que parece aplicarse a la página entera al completarla.
- **A explotar:**
  1. **Comprar a Abuela** las comunes de LAV y MAL que faltan: LAV-04 y LAV-05 valen 16 cada una, y MAL-01 y MAL-03, 13. Ya tenemos todas las poco comunes de LAV y MAL.
  2. **Raras de LAV y MAL en el mercado:** LAV-09 y LAV-10 valen **112** cada una para nosotros, y MAL-09 y MAL-10, 91. Comprarlas por debajo de unos 85–95 P es ganancia grande, y además nos acercan a completar las páginas de Lavapiés y Malasaña.
  3. **Épicas y legendarias de LAV:** LAV-11 vale **288** y LAV-12 unos 720. Hay que estar atentos a nuevos dealers (habrá uno que vende 1 legendaria por equipo y hora) y al mercado.
  4. **Vender lo que vale poco para nosotros** a quien lo valore más: repetidas (MAL-02, MAL-05, MAL-06 ×2, LAT-04) y cartas de LAT (×0,5) y SAL (×0,9). Por ejemplo SAL-10, que para nosotros vale 63 y para un equipo con SAL ×1,6 valdría 112.
  5. **Cupo de Abuela:** 8 acuerdos por equipo y hora y una conversación a la vez. Hay que usarlo entero cada hora.
- **Escalera:** regatear mejor sigue sumando (cuentan los 3 mejores acuerdos), pero pesa mucho menos que la ganancia en valor.

## 2026-10-02 21:00 — Control del bot desde el dashboard

- El bot real corre **desarmado**. Desde el apartado Bot del dashboard se puede soltar y elegir modo: automático, revisión o manual. En revisión y manual, cada acción se puede aprobar, editar o rechazar antes de enviarse.
- Telemetría completa: decisiones con su razonamiento, prompts enviados a Claude, mensajes recibidos con detección de injection y una visión del bot por carta (`intel.json`).
- Investigación de técnicas de negociación en `docs/NEGOTIATION.md`. Contra el Abuela simulado, las nuevas tácticas apenas mejoran el regateo actual (0,847 frente a 0,839 del rango); la prueba de verdad será contra los dealers reales.

## 2026-10-02 20:45 — Bot listo para pruebas (rama `feat/bot`)

- El bot tiene tres estrategias: dealers, mercado y duelos. Todas pasan por la pasarela y por defecto solo simulan. Jugar de verdad requiere `BOT_ALLOW_REAL=1`. Detalles en `docs/BOT.md`.
- **Abuela abre a 17 P** y casi todos los equipos aceptan ese precio, que no puntúa en la escalera ni desbloquea el siguiente dealer. El bot regatea.
- `catalog.values.copy_marginals` = [1.0, 0.25, 0.1]: la 2.ª copia vale el 25 % y la 3.ª el 10 %. `your_value` en `/api/me` es el valor de la *última* copia, repetido en todas.
- **Ofertas:** las de Abuela caducan a los 2 ticks. En los libros de órdenes los vendedores salen con **seudónimo** (`m5e679080`), no con el id de equipo.
- **Prompt injection:** las defensas y su test pasan. Las sondas contra dealers están listas pero desactivadas (`BOT_PROBE=1`).

## 2026-10-02 20:30 — DECISIÓN: usamos la deducción de manos rivales

- Decidido por el equipo: la vista de rivales reconstruye la mano inicial de cada equipo.
- **Patrón confirmado:** cartas 1–270 = 18 equipos × 15. El equipo `tNN` tiene los ids `(NN−1)×15+1 … NN×15`, y la carta 15 de cada bloque es su rara. La carta 15 es LAT-09, que coincide con la carta más rara del Team 1 en el leaderboard; la nuestra, la 150, es SAL-10. La 271 no existe todavía.
- Si el historial de una carta solo tiene el reparto inicial, la sigue teniendo su equipo. Si tiene más entradas, ha cambiado de manos y el nuevo dueño es anónimo.
- La pasarela escanea las cartas con nuestra clave a como mucho 2 peticiones/s, para dejar margen a los bots, y publica el resultado en `/intel/rivals`.
- **Ojo:** `/api/cards/{id}` sin clave devuelve `bad_key` y cuenta como clave errónea (20 por ráfaga y luego una cada 2 s). Usar siempre la pasarela.

## 2026-10-02 20:15 — Pasarela única del equipo

- Solo el PC de Ángel habla con el Bazaar. El dashboard y los bots de los demás pasan por su pasarela (ngrok), con un token propio en `BAZAAR_KEY`. Detalles en el README.
- La pasarela mantiene un único stream de eventos y lo reparte en `/events`. El Bazaar permite como máximo 6 streams por clave, y desde nuestra IP ya daba `too_many_streams` sin clave.
- Las lecturas públicas van sin clave, así el límite de 5 peticiones/s de la clave queda para lo privado y los bots.

## 2026-10-02 20:00 — Qué se puede saber de los rivales

- **Público:**
  - El leaderboard da, por equipo: puntos (negociación y mercado), nivel, huecos llenos del álbum, páginas completas, carta más rara, número de acuerdos y mercado propio.
  - El feed muestra qué equipo abre conversación con qué dealer y con qué tema (por ejemplo, `buy pack`).
  - Los libros de órdenes de los mercados muestran qué se vende y qué se pide.
  - El catálogo muestra cuántas copias hay acuñadas de cada carta.
- **Oculto:** el dinero de los rivales, sus valores privados y el dueño de cada carta (`/api/cards/{id}` devuelve `"owner": "a team"`).
- **Patrón detectado:** las cartas iniciales se repartieron en bloques de 15 ids seguidos por equipo, y el nuestro es justo 136–150 = (10−1)×15+1 … 10×15. Si se cumple para todos, se podría deducir la mano inicial de cada rival y, con el historial, si la sigue teniendo. Es una fuga que los organizadores probablemente no buscaban: **decidir en equipo si se usa** (o si se les avisa).
- Afinidades de los rivales: todos tienen los mismos seis multiplicadores (1.6, 1.3, 1.1, 0.9, 0.7, 0.5), pero en otro orden.
- Seis equipos (t16, t06, t09, t14, t13 y t16 otra vez) ya negocian con Abuela un `sobre_barrio`, con el juego todavía en pausa. Nosotros aún no.

## 2026-10-02 19:45 — Dashboard compartido con el equipo

- Dashboard local (`dashboard/`) publicado por ngrok con usuario y contraseña. Solo hace lecturas y deja pasar una lista cerrada de rutas.
- El proxy cachea las respuestas unos segundos para no gastar el límite de 5 peticiones/s de nuestra clave.

## 2026-10-02 19:40 — Encontrado el SDK de inicio

- Está en https://bazaar.causaprima.ai/bazaar-kit.zip; ninguna página de la web lo enlaza. Descomprimido en `sdk/bazaar-kit/`.
- Incluye `RULES.md` con las reglas completas: la puntuación es negociación 30, mercado 30 y jurado 40.
- `GET /api/me` devuelve `starter_broker_key`, la clave de broker de nuestro puesto automático.

## 2026-10-02 19:35 — Estado del juego

- El juego está abierto pero **en pausa en el tick 0** (ronda "Friday · El Rastro"). No hay niveles anunciados.
- El Team 16 ya ha abierto una conversación con Abuela para comprar un `sobre_barrio`: las conversaciones se pueden abrir aunque el juego esté en pausa.
- No tenemos sobres que abrir. Abuela los vende a 26 de lista, empieza pidiendo 30 y permite 3 por equipo y hora.

## 2026-10-02 19:30 — Nuestra clave funciona

- Somos Team 10 (`t10`): 400 P, 15 cartas, nivel 1, 2º en el ranking (todos a 0 puntos).
- Afinidades: LAV 1.6 · MAL 1.3 · RET 1.1 · SAL 0.9 · CHA 0.7 · LAT 0.5.
- Repetidas: MAL-02, MAL-05, MAL-06 y LAT-04. Nuestra carta más valiosa es SAL-10 (rara, 63 para nosotros).

## 2026-10-02 19:25 — Análisis de la API

- Es una API REST con FastAPI; la especificación está en `/openapi.json`. La web es una SPA en React que solo enseña el leaderboard, el catálogo y la consola de los organizadores.
- Autenticación por cabecera: `X-Team-Key`, `X-Broker-Key` y `X-Admin-Token`.
