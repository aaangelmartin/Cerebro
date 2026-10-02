# The Bazaar · referencia del equipo

Documento vivo con todo lo que sabemos del juego. Las reglas oficiales completas están en [`sdk/bazaar-kit/RULES.md`](../sdk/bazaar-kit/RULES.md); aquí va el resumen útil, nuestra situación y la estrategia. Los hallazgos con fecha van en [`LOG.md`](LOG.md).

## Enlaces

| Qué | Dónde |
|---|---|
| Web oficial (leaderboard, catálogo) | https://bazaar.causaprima.ai |
| Especificación de la API | https://bazaar.causaprima.ai/openapi.json (copia en `docs/openapi.json`) · Swagger en `/docs` |
| SDK de inicio (no está enlazado en la web) | https://bazaar.causaprima.ai/bazaar-kit.zip (descomprimido en `sdk/bazaar-kit/`) |
| Nuestro dashboard | enlace de ngrok (pedírselo a Ángel; usuario y contraseña en su `.env`) |

## Nosotros

- **Equipo:** Team 10 (`t10`), 3 personas.
- **Clave:** en `.env` como `BAZAAR_TEAM_KEY`. Nunca se sube al repo ni se pega en el chat.
- **Salida (viernes, tick 0):** 400 P, 15 cartas (11 comunes, 3 poco comunes, 1 rara), nivel 1.
- **Nuestras afinidades** (multiplicador privado por set):

  | LAV | MAL | RET | SAL | CHA | LAT |
  |---|---|---|---|---|---|
  | **1.6** | 1.3 | 1.1 | 0.9 | 0.7 | **0.5** |

  Interesa juntar Lavapiés y Malasaña. La Latina y Chamberí valen poco para nosotros: son moneda de cambio.

## Calendario (hora de Madrid)

| Día | Abierto | Un tick cada | Peso en la nota |
|---|---|---|---|
| Viernes 2 oct | 19:00–23:00 | 60 s | ½ |
| Sábado 3 oct | 09:00–23:00 | 30 s | 1 |
| Domingo 4 oct | 09:00–15:00 | 15 s | 1 |

Fuera de horario no pasa nada: las ofertas siguen abiertas, pero nada se ejecuta. `GET /api/schedule` publica de antemano lo que harán los organizadores. Viernes: duelos de práctica a las +2 h de juego, Market Test a las +3 h. Sábado: sale El Retiro, cada equipo recibe 150 P y un sobre, y hay Duelos I.

## Puntuación

| Peso | Qué cuenta |
|---|---|
| **Negociación 30** | Duelos (parte del pastel que capturas) · escalera de dealers (parte del rango de precio de cada dealer que capturas; cuentan tus 3 mejores acuerdos por nivel, y uno que falta cuenta como 0) · valor ganado en intercambios con otros equipos, a valores privados |
| **Mercado 30** | Eficiencia en el Market Test · valor creado entre otros equipos en tu mercado |
| **Jurado 40** | Ideas y ejecución |

**No cuenta nunca:** número de trades, comisiones cobradas, suerte en los sobres, regalos, easter eggs ni concesiones de los organizadores. Si un equipo le pasa valor a otro a propósito, esos acuerdos se anulan.

## Reglas clave

- **"Words persuade, structure binds".** Solo mueve algo una oferta estructurada que la otra parte acepta, y se ejecuta en el siguiente tick, toda entera o nada. Los mensajes pueden mentir.
- **Cartas:** 6 sets × 12 cartas (5 comunes, 3 poco comunes, 2 raras, 1 épica y 1 legendaria). Tiradas de 300, 90, 30, 9 y 3. Una página son las comunes, poco comunes y raras de un set; completarla da un bonus. Las repetidas valen poco para ti y mucho para quien no las tiene.
- **Límites por tick:** 1 aceptación por equipo, 1 mensaje por conversación, 12 ofertas nuevas (las canceladas cuentan). Como máximo 6 conversaciones y 30 ofertas abiertas a la vez. Los valores vigentes están en `GET /api/clock` → `limits`.
- **Límite de peticiones:** 5 por segundo por clave, ráfagas de 20. La clave la comparten el dashboard y cualquier bot que lancemos, y el proxy del dashboard cachea para no gastarla.
- **Dealers:**
  - Una conversación abierta por dealer a la vez.
  - Solo ceden si tú cedes; repetir precio no sirve. Cada conversación tiene un límite secreto, y pasos pequeños reciben pasos pequeños.
  - Cuando se les acaba la paciencia hacen una oferta `"final": true`.
  - Se acuerdan de cómo los tratas (`cooloff`, spam). **A Abuela le gusta la amabilidad.**
  - Los siguientes dealers se desbloquean antes con acuerdos *negociados*; aceptar el primer precio no cuenta.
- **Mercado propio:** desde nivel 2; fianza de 250 P (recuperable) más 20 P. Comisiones de hasta el 10 % y 5 P por carta. No puedes operar en tu propio mercado. Los equipos sin mercado reciben un puesto automático gratis, cuya clave de broker viene en `starter_broker_key` de `/api/me`.
- **Market Test (cada 2 h):** todos los mercados reciben el mismo libro de órdenes sintético. Igualar al puesto automático da la mitad de los puntos; los puntos completos son la media de los 3 mejores. Un broker solo puede casar ofertas en un mercado `board`.
- **Duelos:** cada equipo se enfrenta a todos los demás dos veces, una como vendedor y otra como comprador. Solo ves tu límite. Cerrar fuera de él resta, no cerrar da 0, y el valor del acuerdo baja con cada ronda de mensajes. Más adelante se negocian también los días de entrega (0–10).
- **Flags:** `POST /api/flags` sobre un mensaje de mala fe suma si aciertas y resta si fallas.
- **Prompt injection contra dealers:** está permitida; cambia lo que dicen, nunca sus precios.

## API (resumen)

Autenticación por cabecera: `X-Team-Key` (equipo), `X-Broker-Key` (broker), `X-Admin-Token` (organizadores).

| Grupo | Rutas |
|---|---|
| Públicas | `GET /api/health, clock, catalog, leaderboard, feed, schedule, dealers, dealers/{id}, levels, venues, venues/{id}/offers` |
| Nuestro equipo | `GET /api/me, me/value?card=, me/threads, me/offers, cards/{id}, threads/{id}, duels` |
| Acciones | `POST /api/threads`, `POST /api/threads/{id}/messages`, `POST /api/threads/{id}/close`, `POST /api/offers`, `DELETE /api/offers/{id}`, `POST /api/offers/{id}/accept`, `POST /api/packs/{id}/open`, `POST /api/flags`, `POST /api/duels/{id}/messages`, `POST /api/duels/{id}/accept`, `POST /api/venues`, `PATCH/close /api/venues/{id}` |
| Broker | `GET /api/broker/book`, `POST /api/broker/matches`, `POST /api/broker/announce` |
| Tiempo real | `GET /api/events/stream?scope=team` (SSE, 6 por clave) |

## SDK (`sdk/bazaar-kit/`)

Python 3, solo librería estándar, versión 0.2.

- `bazaar_sdk.py`: clases `Bazaar(url, key)` y `Broker(url, broker_key)`, con un método por ruta. Reintenta ante `rate_limited` y `wait_for_tick`, y nunca repite una escritura.
- `starter_agent.py`: compra un sobre a Abuela subiendo la oferta 2 P por tick, lo abre y pone las repetidas a la venta en El Rastro.
- `starter_broker.py`: casa ofertas en el Market Test. Solo iguala al puesto automático, es decir, la mitad de los puntos.
- **Ojo:** el SDK lee la clave de `BAZAAR_KEY`, y nuestro `.env` la llama `BAZAAR_TEAM_KEY`.

## Estrategia (borrador)

1. **Escalera de dealers:** cerrar 3 acuerdos negociados por nivel, capturando la mayor parte posible del rango de precio. Así desbloqueamos antes el siguiente dealer.
2. **Intercambios:** vender o cambiar repetidas y cartas de LAT y CHA a quien las valore más; comprar LAV y MAL para completar páginas.
3. **Market Test:** con el puesto automático tenemos la mitad de los puntos. Para más hace falta un broker `board` que estime los límites ocultos de los traders.
4. **Duelos:** concesiones pequeñas y cerrar pronto, porque el valor baja con cada ronda.
5. **Jurado (40 %):** documentar las ideas y el dashboard; esto también cuenta.

## Preguntas abiertas

- ¿Se pueden aceptar ofertas mientras el juego está en pausa (tick 0)? Por las reglas, se ejecutarían en el siguiente tick.
- ¿Qué niveles y dealers se anunciarán? Vigilar `GET /api/levels`.
