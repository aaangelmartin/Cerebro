# Bitácora

Hallazgos con fecha y hora de Madrid, los más recientes arriba. La referencia consolidada está en [`BAZAAR.md`](BAZAAR.md).

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
