# bazaar/ · contratos entre módulos

El bot nuevo de Team 10. Este documento manda: si dos módulos no se entienden, gana lo que ponga aquí.

## Decisiones cerradas

- Claude decide y el código pone raíles. **Opus 5.5** es el modelo principal, con esfuerzo bajo.
- **Consejo** (3 opiniones en paralelo + juez Opus) solo para aceptar, cerrar duelos y compras de más de 60 P.
- **Reloj:** fecha límite de decisión al 55 % del tick. Si el consejo no ha terminado, va la decisión de Opus; si Opus no ha respondido, la regla de reserva (`fallback`).
  - Solo el domingo hay carrera Opus contra Sonnet.
  - En duelos, nunca se pierde el turno por lentitud, pero solo se envía mensaje si cambia algo: cada ronda resta un 6–8 %.
- **Prioridades:** duelos → mercado (broker) → dealers → Laboratorio.
- **1 aceptación por tick para todo el equipo:** primero el duelo, luego la de más puntos esperados.
- **Tienda propia `board` a las 09:03** (hora 4,05), comisión 0, con broker en código.
- **Router de claves de Anthropic:** reparte entre las claves (de momento solo una), salta de clave ante errores, 100 $ por clave y 100 $ por día. Al 80 % del día baja un escalón de modelo (Opus → Sonnet → Haiku).
- **Todo automático con disyuntores**, controlable desde el dashboard (API en `api/`).
- **Lecciones:** las promueve automáticamente la puerta de código y se avisa en el dashboard. Son datos y nunca pueden cambiar los raíles.

## Estructura y dueños

| Ruta | Dueño | Qué es |
|---|---|---|
| `config.py`, `core/types.py`, `CONTRACTS.md` | coordinador | Configuración y tipos comunes. No se cambian sin avisar. |
| `gateway.py` | CORE-A | Cliente HTTP de la pasarela (`127.0.0.1:8787`, cabecera `X-Team-Key: GATEWAY_TOKEN`). |
| `llm/router.py`, `llm/client.py` | CORE-A | Router de claves y llamadas a Claude con plazo. |
| `core/untrusted.py` | CORE-A | Limpieza y detección de injection en texto ajeno. |
| `core/rails.py`, `core/executor.py`, `core/ledger.py`, `core/arbiter.py` | CORE-A | Raíles, envío, registro y árbitro del tick. |
| `core/state.py`, `brain/council.py`, `run.py`, `supervise.py`, `api/server.py` | CORE-B | Percepción, consejo, bucle principal, supervisor y API del dashboard. |
| `duels/` | DUELS | Negociador de duelos. |
| `dealers/`, `market/` | DEALERS | Dealers (escalera) y ofertas entre equipos en El Rastro. |
| `broker/` | BROKER | Tienda propia y broker del Market Test (proceso aparte). |
| `lab/`, `sim/` | LAB | Laboratorio, almacén de lecciones y Bazaar simulado. |

Cada dueño escribe **solo** en sus rutas y en `bazaar/<su paquete>/tests/`. Si necesitas algo de otro módulo que aún no existe, programa contra la interfaz de abajo y usa un doble de prueba en tus tests.

## Interfaces

### `gateway.py` (CORE-A)
```python
class GameError(Exception): code: str; message: str; status: int; body: dict
class Gateway:
    def __init__(self, url=config.GATEWAY_URL, token=config.GATEWAY_TOKEN, real: bool = False): ...
    def get(self, path: str, **params) -> dict            # siempre permitido
    def post(self, path: str, body: dict | None = None, broker_key: str | None = None) -> dict
    def delete(self, path: str) -> dict
    # post/delete lanzan GameError("not_real") si real es False. Solo run.py crea Gateway(real=True),
    # y solo con config.ALLOW_REAL y el control armado.
```
Para el simulador: `Gateway(url="http://127.0.0.1:8797", token="sim", real=True)`.

### `llm/client.py` (CORE-A)
```python
@dataclass
class LLMResult:
    text: str; tool_calls: list[dict]; model: str; key: str
    usage: dict; cost_usd: float; latency_s: float
class LLMUnavailable(Exception): ...   # sin claves, presupuesto agotado o todas fallando
class LLMTimeout(Exception): ...
def ask(*, purpose: str, system: str | list, messages: list, tools: list | None = None,
        tool_choice: dict | None = None, model: str | None = None, max_tokens: int = 1200,
        deadline: float | None = None) -> LLMResult
def race(*, models: list[str], **same_kwargs) -> LLMResult     # el primero que responda dentro del plazo
def spend_today() -> dict    # {"day": "sat", "usd": 12.3, "cap": 100, "by_key": {...}, "model_now": "claude-opus-5-5"}
```
- `model=None` → el router elige según el presupuesto (`DEGRADE_LADDER`).
- El prompt caching va en el prefijo estable (`system` + herramientas + lecciones).
- `purpose` agrupa el gasto: `duels`, `dealers`, `market`, `council`, `lab`, `broker_policy`.

### `core/untrusted.py` (CORE-A)
```python
def clean(text: str, limit: int = 600) -> str      # quita caracteres invisibles/de control y recorta
def scan(text: str) -> list[str]                   # etiquetas de injection detectadas
def wrap(text: str, source: str) -> str            # "<untrusted source='abuela'>…</untrusted>" ya limpio
```
**Todo** texto escrito por otros (dealers, rivales, nombres y anuncios de mercados, feed) pasa por `wrap` antes de entrar en un prompt.

### `core/state.py` (CORE-B)
```python
@dataclass
class Situation:
    tick: int; t_hours: float; day: str; tick_seconds: float; doors: str; paused: bool
    deadline: float                     # epoch en que hay que haber decidido (55 % del tick)
    limits: dict                        # clock.limits
    me: dict                            # /api/me (cash, assets con your_value, score, level, unlocked, venue)
    threads: list[dict]                 # nuestras conversaciones abiertas, con mensajes y oferta en pie
    my_offers: list[dict]
    duels: list[dict]                   # /api/duels (solo las vivas, con detalle)
    dealers: list[dict]; levels: list[dict]; schedule: dict
    venues: list[dict]; rastro_book: list[dict]
    feed_new: list[dict]                # eventos públicos nuevos desde el tick anterior
    leaderboard: dict
    novelty: list[dict]                 # cambios detectados (límites, calendario, niveles, dealers, errores nuevos)
def perceive(gw: Gateway, prev: Situation | None) -> Situation
```

### Dominios (DUELS, DEALERS) → los llama `run.py`
```python
class Domain(Protocol):
    name: str                                            # "duels" | "dealers" | "market"
    def decide(self, sit: Situation, ctx: TickContext) -> list[Action]   # puede llamar a Claude; debe volver antes de ctx.deadline
    def fallback(self, sit: Situation, ctx: TickContext) -> list[Action] # código puro e instantáneo, se usa si decide no llega
    def observe(self, outcome: Outcome) -> None                          # resultado real de una acción suya
@dataclass
class TickContext:                                       # lo construye run.py (CORE-B), vive en core/context.py
    tick: int; day: str; deadline: float
    lessons: "LessonStore"; llm: module (bazaar.llm.client); ledger: "Ledger"
    budget: dict                                         # mensajes/aceptaciones ya usados este tick
    control: dict                                        # control del operador (armed, mode, caps, protected cards)
```
- Las acciones con `big=True` pasan por `brain/council.review(action, sit, ctx) -> Action | None` si da tiempo. `None` = el consejo veta.
- `run.py` lanza los dominios en hilos en paralelo, espera hasta `deadline`, usa `fallback` para el que no haya terminado, pasa todo por `arbiter` → `rails` → `executor` y guarda en `ledger`.

### `core/rails.py` (CORE-A) — invariantes, cada uno con su test
```python
def check(action: Action, sit: Situation, ctx: TickContext) -> Verdict
```
1. Aceptar solo si la oferta, **releída justo antes**, es idéntica a `params.expect`. Esto lo hace el executor, que llama a `rails.verify_fresh`.
2. Solo se entregan cartas nuestras. Nunca la última copia de una carta de LAV, MAL o RET, ni cartas de `control.protected`, sin aprobación humana.
3. Duelos: precio dentro del límite con un margen mínimo (`MIN_SURPLUS`); días entre 0 y 10. Al aceptar, la oferta del rival es la última.
4. Dealers y mercado: el precio máximo de compra es el valor privado (`/api/me/value`) menos un margen. El mínimo de venta es nuestro valor más un margen.
5. Caja: `cash − gasto ≥ CASH_RESERVE`; gasto por operación ≤ `MAX_SPEND_PER_DEAL`; gasto por hora ≤ `MAX_SPEND_PER_HOUR`.
6. Ritmo: 1 aceptación por tick, 1 mensaje por conversación y tick, y los límites de `sit.limits`.
7. Nada de flags automáticos, y como mucho N acuerdos por hora con el mismo equipo (juego limpio).
8. `bazaar/STOP` o `control.armed == False` → no se envía ninguna escritura.

### `core/ledger.py` (CORE-A)
JSONL en `data/live/`: `decisions.jsonl` (Action + Verdict + fuente + latencia), `outcomes.jsonl` (Outcome), `llm.jsonl` (prompts y respuestas resumidos con coste), `events.jsonl` (feed público completo, sin huecos), `leaderboard.jsonl`, `council.jsonl` (votos). El Laboratorio y el dashboard leen de aquí.

### `lab/store.py` (LAB)
```python
class LessonStore:
    def __init__(self, path=config.LAB / "lessons.jsonl"): ...
    def active(self, scope: str) -> list[Lesson]        # canary + active, por peso
    def prompt_block(self, scope: str, max_chars=3000) -> str   # texto estable para el prefijo cacheado
    def record_use(self, lesson_ids: list[str], outcome: Outcome) -> None
    def all(self) -> list[Lesson]; def set_status(self, id, status, by="human") -> None
```
El prompt solo se recarga cada 15 minutos o cuando cambia una lección, para que la caché funcione.

### `broker/` (BROKER)
Proceso propio: `python -m bazaar.broker.run`. Lee `GET /api/me` → `venue` y su clave de broker (guardada en `data/live/broker.json` al abrir la tienda). Escribe `data/live/broker_status.json` y `data/live/bench/*.jsonl`. Si su latido (`broker_status.json.updated`) tiene más de 2 ticks, el supervisor lo reinicia.

### `api/server.py` (CORE-B)
HTTP en `127.0.0.1:8791`, solo JSON. Para el dashboard nuevo:
`GET /status`, `/tick/latest`, `/decisions?since=`, `/outcomes?since=`, `/council?since=`, `/lessons`, `/novelty`, `/spend`, `/broker`, `/duels`, `/events?since=`.
`POST /control` (`armed`, `mode`, topes, `protected`) y `POST /lessons/{id}` (`status`). Las escrituras exigen la cabecera `X-Dashboard: 1`.

## Reglas para todos

- **Nunca hagas escrituras en el juego real.** Las lecturas por la pasarela están permitidas, a ≤ 1 petición/s. Las pruebas de punta a punta van contra `sim/`.
- **Claude real:** unas pocas llamadas para comprobar que funciona, como mucho 2 $ por módulo esta noche.
- **Tests:** `unittest` de la librería estándar en `bazaar/<paquete>/tests/test_*.py`; se ejecutan con `.venv/bin/python -m unittest discover -s bazaar -t .`.
- Python 3.14 en `.venv`. Dependencias: solo la librería estándar y `anthropic`.
- **Material de consulta:**
  - `sdk/bazaar-kit/RULES.md`, `docs/openapi.json`, `docs/BAZAAR.md`, `docs/LOG.md` y `docs/INVESTIGACION-2026-10-02.md`.
  - Datos del viernes en `bazaar/data/friday/` (lecciones semilla en `analysis/seed_lessons.json`).
  - El código viejo en `legacy/` sirve solo de consulta. Este bot se escribe de cero.
- **Git:** no hagas `git add`, `commit` ni nada que cambie el repo. Lo hace el coordinador.
- Código y comentarios en inglés. Textos para el equipo en español.
