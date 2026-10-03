# Bazaar v2 · el bot de Team 10

El bot nuevo, escrito de cero el sábado 3 de octubre de madrugada. Claude (Opus 5.5) decide y el código pone raíles; un Laboratorio aprende solo de todo lo que pasa en el juego. Las interfaces entre módulos están en [`CONTRACTS.md`](CONTRACTS.md).

## Arranque de las 09:00

El supervisor ya corre desde la madrugada en modo real **desarmado**: lee el juego, decide y registra, pero no envía nada.

1. **Comprobar** que todo está vivo:
   ```bash
   curl -s localhost:8791/health
   curl -s localhost:8791/status | python3 -m json.tool | head -40
   ```
   Tiene que verse `doors: open`, un `tick` que avanza y `allow_real: true`.
2. **Mirar qué haría** en los primeros ticks:
   ```bash
   curl -s 'localhost:8791/decisions?since=0' | tail -c 2000
   ```
   Con el bot desarmado, cada decisión sale como `dry_run`.
3. **Armar:**
   ```bash
   curl -s -X POST -H 'X-Dashboard: 1' -H 'Content-Type: application/json' \
     -d '{"armed": true, "by": "angel"}' localhost:8791/control
   ```
   A las ~09:03 llegan los 150 P y el bot abre la tienda propia (`board`, comisión 0) él solo.
4. **Parar en seco:** `touch bazaar/STOP`, o `{"armed": false}` en el mismo `POST /control`.

Si hay que arrancarlo de cero:

```bash
BAZAAR_ALLOW_REAL=1 nohup .venv/bin/python -u -m bazaar.supervise > bazaar/data/live/supervise.out 2>&1 &
```

La pasarela sigue corriendo desde `legacy/dashboard/server.py` en el puerto 8787. Si se cae:

```bash
DASHBOARD_ENV_FILE=.env nohup .venv/bin/python -u legacy/dashboard/server.py > bazaar/data/gateway.out 2>&1 &
```

## Procesos

| Proceso | Qué hace | Latido |
|---|---|---|
| `bazaar.run --live` | Un ciclo por tick: percibe, decide con Claude, raíles, envía y registra | `data/live/status.json` |
| `bazaar.broker.run` | Tienda propia y broker del Market Test | `data/live/broker_status.json` |
| `bazaar.lab.run` | Laboratorio: ingiere, propone lecciones, las prueba y las promueve | `data/lab/lab_status.json` |
| `bazaar.recorder.run` | Grabadora de solo lectura: feed, libros de todas las tiendas, clasificación, duelos y conversaciones completas en `data/record/` ([README](recorder/README.md)) | `data/live/recorder_status.json` |
| `bazaar.api.server` | API del dashboard en `127.0.0.1:8791` | `/health` |
| `bazaar.supervise` | Reinicia lo que se cae o se queda colgado | `data/live/supervise.log` |

## Claves de Anthropic

`ANTHROPIC_API_KEY_A`, `_B` y `_C` en `.env`; si no hay ninguna, se usa `ANTHROPIC_API_KEY`.

- El router reparte las llamadas por saldo y salta de clave si una falla.
- Topes: 100 $ por clave y 100 $ por día.
- Al 80 % del día baja de modelo (Opus → Sonnet → Haiku).
- El gasto está en `GET /spend`.

## Pruebas

```bash
.venv/bin/python -m unittest discover -s bazaar -t .           # 290 tests; escriben en una carpeta temporal
.venv/bin/python -m bazaar.sim.fake_bazaar --port 8797 --tick 30 --duels-at 2 --bench-at 3 &
.venv/bin/python -m bazaar.run --sim                           # el bot contra el Bazaar simulado (data/sim/)
.venv/bin/python -m bazaar.duels.tournament                    # torneo de duelos
.venv/bin/python -m bazaar.dealers.evaluate                    # regateo con dealers
.venv/bin/python -m bazaar.broker.sim_book --seeds 300         # broker contra el puesto gratis
```

Los tests y las ejecuciones con `--sim` nunca escriben en `data/live`. El gasto de API se apunta siempre en el mismo sitio, porque el dinero es real.
