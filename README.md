# ClaudeHackathon · The Bazaar (Team 10)

Nuestro trabajo para **The Bazaar · Cromos de Madrid**, el juego del hackathon de Causa Prima (2–4 oct 2026). Este repo y el dashboard son el punto común de información del equipo.

- **Qué sabemos del juego:** [`docs/BAZAAR.md`](docs/BAZAAR.md)
- **Bitácora de hallazgos:** [`docs/LOG.md`](docs/LOG.md)
- **SDK oficial y reglas:** [`sdk/bazaar-kit/`](sdk/bazaar-kit/)
- **Especificación de la API:** [`docs/openapi.json`](docs/openapi.json)

## Puesta en marcha

```bash
cp .env.example .env      # y rellena BAZAAR_TEAM_KEY (nunca se sube al repo)
python3 dashboard/server.py
# -> http://127.0.0.1:8787
```

Para compartir el dashboard con el equipo:

```bash
set -a; . ./.env; set +a
ngrok http 8787 --basic-auth "$DASHBOARD_USER:$DASHBOARD_PASSWORD"
```

El dashboard solo lee: el servidor añade la clave del equipo y solo deja pasar una lista cerrada de rutas `GET` de la API, además de `docs/LOG.md` y `docs/BAZAAR.md`.

## Usar el SDK

```bash
set -a; . ./.env; set +a
export BAZAAR_KEY="$BAZAAR_TEAM_KEY"
python3 sdk/bazaar-kit/starter_agent.py   # ojo: compra y abre un sobre de verdad
```

## Cómo trabajamos

Cada hallazgo nuevo va a `docs/LOG.md`, con fecha y hora, y, si cambia la referencia, también a `docs/BAZAAR.md`. El dashboard muestra los dos documentos.
