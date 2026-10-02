# Bitácora

Hallazgos con fecha y hora de Madrid, los más recientes arriba. La referencia consolidada está en [`BAZAAR.md`](BAZAAR.md).

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
