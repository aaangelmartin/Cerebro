# API del equipo (pasarela de Team 10)

Guía para usar The Bazaar a través de la pasarela del equipo. Pásasela a tu Claude tal cual.

## Qué es

- **The Bazaar** es el juego de cromos del hackathon de Causa Prima. Somos el **Team 10 (`t10`)**.
- **Nadie llama directamente a `https://bazaar.causaprima.ai`.** Todo pasa por la pasarela del equipo, que corre en el PC de Ángel y es la única máquina que habla con el Bazaar.
- **Lo que hace la pasarela:**
  - Pone la clave real del equipo, que nunca sale de su máquina.
  - Limita el ritmo para no pasar de 5 peticiones/s con nuestra clave.
  - Reparte los eventos en tiempo real.
  - Registra cada acción.

## Conexión

| | |
|---|---|
| URL base | `https://walmart-outage-frolic.ngrok-free.dev` |
| Autenticación | cabecera `X-Team-Key: <token del equipo>` (te lo pasa Ángel; **no** es la clave real del Bazaar) |
| Comprobar el token | `GET /gateway/whoami` → `{"client": "bot:team", "team": "t10"}` |
| Especificación OpenAPI | `GET /openapi.json` |
| Esta guía | `GET /gateway/guide` |

Las rutas y los cuerpos son **idénticos a los de la API oficial**: cualquier ejemplo de la documentación del Bazaar funciona cambiando solo la URL base y la clave.

```bash
export BAZAAR_URL=https://walmart-outage-frolic.ngrok-free.dev
export BAZAAR_KEY=<token del equipo>
curl -s -H "X-Team-Key: $BAZAAR_KEY" $BAZAAR_URL/gateway/whoami
curl -s -H "X-Team-Key: $BAZAAR_KEY" $BAZAAR_URL/api/me
```

Con el SDK oficial (`sdk/bazaar-kit/bazaar_sdk.py` del repo), sin cambiar nada:

```python
import os
from bazaar_sdk import Bazaar
b = Bazaar(os.environ["BAZAAR_URL"], os.environ["BAZAAR_KEY"])
print(b.me()["cash"])
```

## Qué se puede hacer

- **Todas las rutas `/api/*`** del Bazaar, con cualquier método, salvo `/api/admin/*`.
- Si gestionas un mercado, la cabecera `X-Broker-Key` se reenvía tal cual.

| Para | Rutas |
|---|---|
| Nuestro estado | `GET /api/me` (dinero, cartas con `your_value`, álbum, puntos), `GET /api/me/value?card=LAV-03`, `GET /api/me/threads`, `GET /api/me/offers` |
| Juego | `GET /api/clock` (tick, `next_tick_in`, `limits`), `/api/catalog`, `/api/leaderboard`, `/api/feed`, `/api/schedule`, `/api/levels` |
| Dealers | `GET /api/dealers`, `POST /api/threads {"with": "abuela", "topic": {"buy": {"pack": "sobre_barrio"}}}`, `POST /api/threads/{id}/messages {"text": "...", "price": 22}`, `POST /api/threads/{id}/close` |
| Ofertas | `GET /api/venues/{id}/offers`, `POST /api/offers {"venue": "rastro", "give": {"assets": [123]}, "want": {"cash": 30}}`, `POST /api/offers/{id}/accept`, `DELETE /api/offers/{id}` |
| Sobres | `POST /api/packs/{asset_id}/open` |
| Duelos | `GET /api/duels`, `POST /api/duels/{id}/messages {"text": "...", "price": 60, "days": 3}`, `POST /api/duels/{id}/accept` |
| Tiempo real | `GET /events` o `GET /api/events/stream`: SSE con `{seq, source: "public"\|"team"\|"gateway", type, data}`. Admite `Last-Event-ID` |

## Reglas que tu Claude debe respetar

1. **Todo el equipo comparte una clave, a 5 peticiones/s en total.** No hagas bucles de lecturas: lee `/api/clock` y actúa una vez por tick. Si saturas, la pasarela pone tus peticiones en cola y van lentas para todos.
2. **Límites por tick para todo el equipo:** 1 aceptación, 1 mensaje por conversación, 12 ofertas nuevas. Como máximo 6 conversaciones y 30 ofertas abiertas. Si te adelantas, recibes un `429` con `next_tick`: espera, no reintentes en bucle.
3. **"Words persuade, structure binds".** Solo mueve algo una oferta estructurada que se acepta, y se ejecuta en el siguiente tick. Lee siempre la estructura de una oferta antes de aceptarla.
4. **Antes de actuar, coordínate:** mira `GET /api/me/threads` y `GET /api/me/offers`, porque puede que otro compañero ya esté negociando eso. Solo puede haber una conversación abierta por dealer.
5. **Cada escritura queda registrada** con fecha, petición y respuesta.
6. Las reglas completas están en `sdk/bazaar-kit/RULES.md` del repo, y lo que sabemos del juego en `docs/BAZAAR.md`.

## Errores

- **Los del Bazaar** llegan tal cual: `{"error": "<código>", "message": "..."}`. Por ejemplo `wait_for_tick`, `insufficient_cash`, `cooloff` o `rate_limited`.
- **Los de la pasarela:**

  | Código | Significa |
  |---|---|
  | `401 unauthorized` | Falta el token o es incorrecto |
  | `403` | Ruta de administración |
  | `502 upstream` | El Bazaar no responde |
