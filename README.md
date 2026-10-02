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

Para compartirlo con el equipo:

```bash
ngrok http 8787        # la autenticación la hace el propio servidor
```

## Pasarela: una sola máquina habla con el Bazaar

`dashboard/server.py` corre en el PC de Ángel y es la **única** máquina que habla con la API del Bazaar. El resto del equipo (el dashboard y los bots) habla con esa máquina a través de ngrok:

- **Dashboard (navegador):** usuario y contraseña (`DASHBOARD_USER` y `DASHBOARD_PASSWORD`). Lee una lista cerrada de rutas y envía las acciones de la consola manual, que llevan la cabecera `X-Dashboard: 1`.
- **Bots:** usan el SDK oficial sin cambios, apuntando a la pasarela. La pasarela cambia el token por la clave real, que nunca sale de su máquina:

  ```bash
  export BAZAAR_URL=https://<url-de-ngrok>
  export BAZAAR_KEY=<GATEWAY_TOKEN>      # pedírselo a Ángel, NO es la clave del equipo
  python3 sdk/bazaar-kit/starter_agent.py   # ojo: compra y abre un sobre de verdad
  ```

  Pueden usar cualquier ruta salvo `/api/admin/*`. La cabecera `X-Broker-Key` se reenvía tal cual.
- **Tiempo real:** `GET /events` (o `/api/events/stream` desde el SDK) es un stream SSE único que reparte los eventos privados del equipo y el feed público. Así no se gastan los 6 streams que permite el Bazaar por clave.
- **Límite de peticiones:** la pasarela no deja pasar más de 4,5 peticiones/s con la clave (el Bazaar permite 5). Si os pasáis, las peticiones esperan en vez de fallar. Las lecturas públicas van sin clave y tienen su propio límite.
- **Registro:** cada escritura queda en `dashboard/actions.log` (no se sube al repo), con quién la hizo (`dashboard` o `bot`), la petición y la respuesta.

## Cómo trabajamos

Cada hallazgo nuevo va a `docs/LOG.md`, con fecha y hora, y, si cambia la referencia, también a `docs/BAZAAR.md`. El dashboard muestra los dos documentos.
