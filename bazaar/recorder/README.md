# recorder/ · la grabadora de datos

Proceso aparte, solo de lectura, que guarda **todo** lo que pasa en el Bazaar: lo nuestro y lo de cada rival. El dashboard (Home, Colección, Mercado, Duelos, Competición, Rivales, Supervisión, Laboratorio, Bot) lee de aquí.

```bash
.venv/bin/python -m bazaar.recorder.run                                          # real: API pública + pasarela
.venv/bin/python -m bazaar.recorder.run --url http://127.0.0.1:8797 --token sim  # contra sim/fake_bazaar
```

- Lo arranca `bazaar.supervise` (servicio `recorder`). Sigue corriendo aunque exista `bazaar/STOP`, porque no escribe nada en el juego: `client.py` solo sabe hacer `GET`.
- Latido en `data/live/recorder_status.json` (`updated`, `state`: `running` | `closed` | `gateway_down` | `public_down`, peticiones por segundo de cada carril, errores). El supervisor lo reinicia si el latido pasa de 3 ticks con las puertas abiertas.
- Pidfile `data/live/recorder.pid`: solo puede haber una grabadora real a la vez.
- Al reiniciar sigue donde lo dejó. El feed retoma desde el último evento escrito en disco, así que nunca escribe un evento dos veces. Los libros de órdenes hacen una foto completa nueva y un diff de lo que cambió mientras estuvo parada.

## Presupuesto de peticiones

| Carril | Destino | Tope | Uso típico |
|---|---|---|---|
| `public` | `https://bazaar.causaprima.ai` directo, sin clave (el servidor permite 60/s por dirección) | 1,8 pet/s | Con ticks de 15 s: (3 + nº de tiendas + 3,75)/15 s. Cubre hasta unas 20 tiendas en cada tick; si hay más, los libros se leen por turnos. |
| `keyed` | Pasarela `127.0.0.1:8787` con `X-Team-Key` (4,5/s compartido con el bot) | 0,5 pet/s | 4–6 lecturas por tick. Las cartas solo usan lo que sobra, con un máximo de 0,2 pet/s. |

Con las puertas cerradas: reloj y feed cada 30 s, y clasificación, libros y estado privado cada 5 min.

## Qué se graba y cada cuánto

| Stream | Fuente | Frecuencia | Se escribe cuando… |
|---|---|---|---|
| `feed` | `/api/feed?limit=500` | cada 4 s (cada 1 s si llegan más de 120 eventos nuevos) | hay eventos nuevos. Se deduplica por `(id, tick, type)` y cada evento lleva `key`, `seen_tick` y `seen_at`. |
| `clock` | `/api/clock` | una vez por tick, justo después de empezar | cambia algo (sin contar `next_tick_in`) |
| `leaderboard` | `/api/leaderboard` | cada tick | cambia (respuesta completa en `data`) |
| `venues` | `/api/venues` | cada tick | cambia la lista o sus estadísticas |
| `books` | `/api/venues/{id}/offers` de **todas** las tiendas, El Rastro incluido | cada tick | hay ofertas nuevas (`added`, completas), retiradas (`removed`, ids) o cambiadas (`changed`). `venue_gone` indica que la tienda cerró. |
| `book_snapshots` | lo mismo | cada 20 ticks por tienda y al arrancar | siempre (libro completo en `offers`) |
| `catalog`, `dealers`, `levels`, `schedule` | `/api/catalog` (15 min); `/api/dealers` + `/api/dealers/{id}` (2 min y 30 min); `/api/levels`, `/api/schedule` (2 min). También al momento si el feed trae `level.`, `persona.`, `venue.`… | | cambia (`data`; en `dealers`, el detalle lleva `kind: "detail"` y `pid`) |
| `me` | `/api/me` | cada tick, al 30 % del tick (después de las lecturas del bot) | cambia (`data` completo) |
| `my_offers` | `/api/me/offers` | cada tick | hay diff (mismo formato que `books`) |
| `threads` | `/api/me/threads?status=open` cada tick; todas cada 20 ticks; `/api/threads/{id}` cuando una sale de abiertas | | hay mensajes nuevos (`messages_new`), mensajes cambiados (`messages_updated`, p. ej. la oferta pasa a `cancelled`) o cambio de estado |
| `duels` | `/api/duels` cada tick; `?done=true` cada 10 ticks y en cuanto un duelo sale de la lista de vivos | | hay mensajes nuevos o cambian campos (`changed: {campo: [antes, ahora]}`) |
| `cards` | `/api/cards/{id}` de todos los ids, del 1 al mayor visto + 15 | una pasada por hora, a ≤0,2 pet/s | cambia la carta: dueño o historial (`data` completo, `history_len`) |
| `gaps` | la propia grabadora | | `recorder_start`/`recorder_stop`, `outage_start`/`outage_end` (carril `public`/`keyed`, segundos), `feed_gap` (página llena que empieza después de nuestro último id: `after_id`, `before_id`, `missing_at_most`), `doors`, `card_sweep_start`/`card_sweep_end`, `book_missing` |

## Estructura en disco

Todo bajo `config.DATA / "record"` (en real, `bazaar/data/record/`):

```
record/
  index.json                 punto de entrada: streams, ficheros, bytes, último seq/ts/tick; documentos latest/; enlaces
  state.json                 estado interno para reanudar (no lo uses en el dashboard)
  <stream>/YYYY-MM-DD.jsonl   un registro JSON por línea, solo se añaden líneas; rota por día (hora local)
  latest/
    clock.json  me.json  my_offers.json  leaderboard.json  venues.json  catalog.json
    dealers.json  dealers/<pid>.json  levels.json  schedule.json  cards.json ({id: carta})
    books/<venue>.json       {"tick", "venue", "offers": [...]} libro actual de cada tienda
  duels/<id>.json            transcripción COMPLETA de cada duelo (el servidor solo da los últimos 6 mensajes;
                             aquí se acumulan todos), cabecera actual, status_history, message_count
  threads/<id>.json          conversación completa con cada dealer (mensajes por id, con sus ofertas), status_history
```

Cada línea de un stream tiene `seq` (sube siempre por stream, también entre días y reinicios), `ts` (epoch con milisegundos) y `tick` (el tick del juego cuando se grabó; en el feed el tick del evento es `tick` y el nuestro, `seen_tick`). Para seguir un stream en vivo, guarda el último `seq` y lee las líneas nuevas del fichero del día. El último registro de cada stream está en `index.json`, que se reescribe cada 30 s.

Recetas para el dashboard:
- **Mercado en vivo:** `latest/books/*.json` y el final de `feed`. **Historial:** `book_snapshots` más `books`, aplicados en orden de `seq`.
- **Competición (precio y volumen):** eventos de venta del `feed` (por tipo), más `venues` (trades, volume, fees de cada tienda).
- **Duelos:** `duels/<id>.json`. **Dealers:** `threads/<id>.json`.
- **Rivales:** `leaderboard` (serie completa), los `feed` con `actor`, las ofertas por `maker` en `books` y `cards` (quién tuvo qué y cuándo).
- **Supervisión:** `data/live/recorder_status.json` y el stream `gaps`.

## Enlaces a otros registros (no se duplican)

- **Broker / Market Test:** lo graba el broker en `data/live/bench/<día>-<run>.jsonl`, un registro por tick con el libro del bench, el plan, los resultados y los traders. Los cruces de ofertas públicas en nuestra tienda van a `data/live/bench/public-<día>.jsonl`, solo en los ticks con plan. El latido está en `data/live/broker_status.json`. La grabadora no lee `/api/broker/book` (necesita la clave del broker), pero el libro público de nuestra tienda sí queda en `books`, como el de cualquier otra.
- **Decisiones del bot:** `data/live/decisions.jsonl`, `outcomes.jsonl`, `llm.jsonl` y `council.jsonl` (`core/ledger.py`).
- Las rutas exactas están en `index.json → links`.

## Disco

Medido con el Bazaar real del viernes: unos 470 B por evento del feed y unos 35 KB por cada ronda de fotos de libros. Con ticks de 30 s y 14 h, entre 30 y 60 MB al día, y como mucho unos 100 MB si el mercado se dispara. Sin compresión, así que se puede leer con `tail` y `jq`.
