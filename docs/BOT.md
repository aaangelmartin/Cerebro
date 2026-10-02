# El bot de Team 10

Código en `bot/`, rama `feat/bot`. El bot juega una pasada por tick: primero duelos, luego dealers y luego mercado. Siempre pasa por la pasarela del equipo (`dashboard/server.py`) y nunca habla directamente con el Bazaar.

## Cómo se usa

```bash
.venv/bin/python -m bot.run                      # simulación: decide y registra, no envía nada (por defecto)
.venv/bin/python -m bot.run --only dealer,market # solo algunas estrategias
touch bot/STOP                                   # pausa el bot desde cualquier sitio; borrar el archivo para reanudar
```

**Seguro:** `--live` contra el juego real se niega a arrancar si no se activa `BOT_ALLOW_REAL=1`. Hasta que el equipo diga que está listo, el bot solo juega en simulación o contra el Bazaar simulado.

### Probar de punta a punta en local

```bash
.venv/bin/python -m bot.sim.fake_bazaar --port 8797 --tick 2      # Bazaar simulado (añade --days para duelos con días)
BOT_GATEWAY_URL=http://127.0.0.1:8797 BOT_GATEWAY_TOKEN=sim BOT_DATA_DIR=bot/sim/data \
  .venv/bin/python -m bot.run --live                              # el bot juega de verdad contra el simulado
.venv/bin/python -m unittest bot.tests.test_market               # tests del mercado
.venv/bin/python -m bot.tests.test_duels                          # tests de duelos, prompt injection incluido
.venv/bin/python -m bot.tests.sim_duels                           # torneo de duelos contra 7 tipos de rival
```

**Entrenamiento continuo:** `.venv/bin/python -m bot.sim.practice --probe` juega una partida tras otra contra el Bazaar simulado. Cada partida usa una semilla nueva y una de cada dos tiene duelos con días. Prueba combinaciones de los parámetros de regateo (`BOT_DEALER_OPEN_FRACTION`, `BOT_DEALER_CONCEDE`, `BOT_DEALER_OPEN_MULTIPLE`) y se queda con las mejores. Los resultados van a `bot/sim/practice/episodes.jsonl` y la clasificación a `bot/sim/practice/best.json`. Se para con `touch bot/sim/STOP_PRACTICE`. Durante el entrenamiento Claude va desactivado para no gastar créditos. Ojo: los dealers simulados siguen nuestro modelo de los reales, así que los parámetros ganadores hay que contrastarlos con el juego real.

El Bazaar simulado parte de una instantánea de solo lectura del catálogo y de nuestra mano reales. Abuela tiene límite secreto, paciencia y oferta final, y cede solo si cedemos. El mercado tiene vendedores y compradores sintéticos. En los duelos, el rival a veces manda textos con prompt injection.

## Control del operador (apartado Bot del dashboard)

El bot real arranca con `BOT_ALLOW_REAL=1 .venv/bin/python -m bot.run --live` pero **desarmado**: decide y registra sin enviar nada. Se controla con la API `bot/control_api.py` (127.0.0.1:8790), que la pasarela del dashboard expone en `/bot/*` solo a usuarios con sesión iniciada:

| Modo (una vez armado) | Qué pasa con cada acción |
|---|---|
| `auto` | Se envía al momento. |
| `review` | Espera `review_seconds` como propuesta. Se puede aprobar, editar (precio o texto) o rechazar; si nadie la toca, se envía. |
| `manual` | Solo se envía si alguien la aprueba. |

- **Soltar al bot:** `POST /bot/live/control {"armed": true}`.
- **Parada:** `{"armed": false}`, que surte efecto en el siguiente tick, o `touch bot/STOP` para pararlo en seco.
- **Override:** `POST /bot/live/pending/<id> {"decision": "approve"|"reject"|"edit", "kwargs": {"price": 12}}`.
- **Telemetría:** `/bot/live/decisions`, `/bot/live/llm` (prompts enviados a Claude y sus respuestas), `/bot/live/inbox` (mensajes recibidos con etiquetas de injection) y `/bot/live/pending`.
- **Entrenamiento, siempre separado del modo real:** `/bot/practice/summary`, `/bot/practice/episodes` y `/bot/practice/decisions`.
- **Visión del bot por carta:** `bot/data/intel.json` se escribe en cada tick con el papel de cada carta (target, buy, sell, keep o ignore), su valor, los precios máximo y mínimo, el mercado, la conversación abierta y el porqué.

Las técnicas de negociación investigadas y cómo las aplica el bot están en [`NEGOTIATION.md`](NEGOTIATION.md).

## Estrategias

| Módulo | Qué hace |
|---|---|
| `dealer` | Regatea con Abuela (y con los dealers que se desbloqueen): compra la carta o el sobre que más vale para nosotros y vende repetidas. Abre lejos de su precio (40 % al comprar), cede un 22 % del hueco por mensaje, nunca repite precio y acepta su oferta final si está dentro de nuestro límite. Solo toca conversaciones que abrió él. |
| `market` | Anuncia en El Rastro las repetidas y las cartas de sets que valoramos poco, siempre por encima de lo que perdemos con ellas. Compra o intercambia ofertas de otros equipos cuando la ganancia en valor privado es ≥ max(3 P, 25 %). Mantiene una reserva de 120 P. |
| `duels` | Negocia los duelos solo con campos estructurados (límite, oferta rival, plazo, días). Concede según un calendario que cierra pronto porque el pastel decrece, estima el límite del rival y aprovecha que cada escenario se juega dos veces con los papeles cambiados. En el simulador captura de media el 40 % del pastel y no cierra nunca fuera de nuestro límite. |

Los módulos `dealer` y `market` se coordinan con reservas compartidas, para no vender la misma carta en dos sitios.

## Prompt injection

**Defensa** (que no nos la hagan rivales ni dealers):
- **Los precios los decide el código** con campos estructurados; el texto de otros nunca se interpreta como instrucciones.
- **Verificación antes de aceptar:** antes de cualquier aceptación se comprueba la oferta (`bot/safety.py`). Tiene que darnos lo esperado, no pedir nada más y estar dentro de nuestro límite. En los duelos se comprueba además que sea la última oferta del rival.
- **El texto ajeno nunca llega a un LLM.** Claude solo redacta nuestras frases a partir de nuestros propios números.
- **Detección:** los mensajes ajenos se limpian (caracteres invisibles y de control) y se escanean en busca de patrones (`ignore previous instructions`, `SYSTEM:`, etiquetas falsas, "los organizadores dicen..."). Los sospechosos van al estado del bot (`suspicious`) para el dashboard.
- **Test:** `bot.tests.test_duels` comprueba que un rival que inyecta no cambia ni una sola decisión.

**Ataque** contra dealers, que las reglas permiten: `BOT_PROBE=1` añade a algunos mensajes sondas educadas para que el dealer revele su precio mínimo (`bot/probe.py`). Las palabras no cambian precios, pero si el dealer deja escapar un número entre nuestra oferta y la suya, el bot ofrece exactamente ese número y captura casi todo el rango. Se registra qué sonda funciona y se deja de sondear si el dealer nos bloquea un tiempo (cooloff). Está desactivado por defecto.

## Mensajes con Claude

Con `ANTHROPIC_API_KEY` en `.env`, Claude (`claude-opus-5-5`, esfuerzo bajo, configurable con `BOT_LLM_MODEL`) escribe cada frase amable que acompaña nuestro precio. Si la frase no contiene exactamente el precio decidido, se usa una plantilla. Sin clave, el bot usa plantillas.

## Estado y registro

- `bot/data/status.json`: modo, simulación o real, dinero, puntos, estado de cada estrategia, errores e intentos de injection. El dashboard lo leerá en `/bot/status`.
- `bot/data/decisions.jsonl`: una línea por decisión, con estrategia, acción y detalles.
- `dashboard/actions.log` (en la pasarela): cada escritura real que llega al Bazaar.

## Pendiente antes de jugar de verdad

- **Duelos de práctica** (hora de juego 2.0, hacia las 22:20 del viernes): ver el formato real de los duelos en las líneas "first sight" de `decisions.jsonl` y ajustar los campos.
- **Ajustar el regateo con Abuela** con lo que se vea en las conversaciones reales.
- **Decidir en equipo** si se activan las sondas de prompt injection (`BOT_PROBE=1`).
- **Activar el juego real** con `BOT_ALLOW_REAL=1 .venv/bin/python -m bot.run --live` cuando el equipo dé el visto bueno.
