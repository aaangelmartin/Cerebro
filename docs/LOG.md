# Bitácora

Hallazgos con fecha y hora de Madrid, los más recientes arriba. La referencia consolidada está en [`BAZAAR.md`](BAZAAR.md).

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
