# Runbook del domingo 4 de octubre (Team 10)

Checklist para operar el bot y la dashboard. El plan de juego está en `plan-domingo.md`; aquí solo va qué mirar, cuándo y qué hacer si algo falla. Prevuelo hecho el domingo a las 03:30 y verificación completa en seco a las 04:40: los resultados, caso por caso, están en `noche-verificacion-bot.md`.

## Lo primero: el Mac

- **Enchufado a la corriente.** A las 03:28 estaba con batería al 11 %; a las 04:30 ya enchufado. `caffeinate` evita que se duerma, no que se apague.
- Tapa abierta, wifi de la sala conectada. Comprobar: `pmset -g batt` debe decir `AC Power`.

## El reloj del domingo

El calendario del servidor (leído a las 23:47 del sábado) pone la apertura en t = 16,65 a las 09:00 y la congelación en t = 22,65 a las 15:00. Son 6 horas de juego en 6 horas de reloj: **una hora de juego son 60 minutos reales, 240 ticks de 15 s**. Eso solo cuadra si el reloj salta de 13,37 a 16,65 al abrir, así que la rama A es la esperada.

| t | Qué pasa | Rama A: el reloj salta | Rama B: no salta |
|---|---|---|---|
| 16,65 | Abre, sale Chamberí, empieza la ronda 3 | 09:00 | 12:17 |
| 16,70 | +150 P | 09:03 | 12:20 |
| 17,00 | Market Test | 09:21 | 12:38 |
| 18,65 | Duelos III (2 vueltas, 12 ticks, decaimiento 0,10, 4 a la vez) | 11:00 | 14:17 |
| 19,00 | Market Test | 11:21 | 14:38 |
| 21,00 | Market Test | 13:21 | no llega |
| 21,45 | Aviso de final | 13:48 | no llega |
| 21,65 | Final de duelos; cierran los cinco dealers | 14:00 | no llega |
| 22,65 | Se congela la puntuación | 15:00 | no llega |

En la rama B los Market Tests de t = 14,65 y t = 15,00 caen a las 10:17 y 10:38.

## 08:45 a 09:00

1. Mac enchufado y despierto.
2. Dashboard abierta (`#home`). Caja de estado: Bot ENCENDIDO con 6/6 procesos, Grabación ENCENDIDA, Claude 3/3 claves.
3. Pantalla Bot: topes 5 / 210 / 550, RET en "no comprar" con su excepción, equipos vetados `t06`, ningún dominio en pausa, sin hilos manuales ni ofertas protegidas.
4. Cerebro → Para el equipo → Cambios de código: decidir **Aceptar** el veto duro a Team 6 (`code-8d5dd3bf`). Comprobado: se aplica limpio sobre el código actual y sus tests pasan.
5. Cerebro: leer su último mensaje antes de pegarle nada. No tiene tareas abiertas (las 23 de anoche se cerraron de madrugada) y guarda 21 políticas activas: P112 a P118 son el plan del domingo.
6. Contestar las decisiones pendientes (abajo). Hasta entonces rige lo conservador (P118).
7. **08:55, pantalla Bot: `brain_backend` en API.** En el Mac el primer plan tarda unos 75 s (cinco ticks); en API, segundos. Devolverlo a auto hacia las 09:20.
8. Opcional, un minuto: `.venv/bin/python tools/dry_open.py`. Repite en seco los primeros ticks del bot sobre los datos de ese momento, sin enviar nada; debe acabar en `RULES: all kept`.
9. No hay nada que arrancar a mano: con las puertas cerradas el bot espera y sale solo.

## 09:00 a 09:10

1. Barra superior: el tick avanza y la cuenta atrás va de 15 en 15 s.
2. **¿Saltó el reloj?** Home → "Siguiente evento", o `curl -s https://bazaar.causaprima.ai/api/clock`: mirar `t_hours`, `round` y `round_name`.
   - `t_hours` ≈ 16,65 y ronda 3: rama A. Chamberí ya está y los 150 P llegan a las 09:03.
   - `t_hours` ≈ 13,37 y ronda 2: rama B. El plan dice no gastar caja en dealers hasta la ronda 3 (P113).
3. 09:03 en la rama A: la caja pasa de 340 a 490 P.
4. Supervisión: el bot decide y envía en cada tick, sin vetos repetidos ni el aviso "breaker".
5. La oferta 19999 (LAT-02 a t08 por 8 P) caduca en el tick 1446. Es lo único que teníamos abierto.
6. **Hasta que llegue el primer plan del cerebro el bot solo ofrece LAT-02 y LAT-04 a 8 P** (probado en seco). Si en Mercado → "Nuestras ofertas abiertas" aparece una carta de Salamanca o una protegida, parar con `touch bazaar/STOP` y mirar.
7. Cerebro, primer plan de la ronda 3: `goal_buys` con LAV-11 a 210 y SAL-06/07/08 a 21; órdenes a Los Pícaros por SAL-09 y SAL-10 (abre en 45, tope 57); ningún dominio en pausa. En la rama B: sin compras ni órdenes, y dealers sin pausar para que salga el hilo del regalo.

## Hitos

| Cuándo (rama A) | Qué hacer |
|---|---|
| 09:03 | Decidir legendaria o LAV-11 (ver decisiones) |
| 09:20 | Market Test: el broker debe estar vivo (pantalla Broker). `brain_backend` otra vez en auto |
| 10:00 a 10:45 | Ventana del regalo de la Abuela: el bot abre un hilo y nombra un precio. Si es por ticks cae hacia el tick 1604; si es por horas, una hora después |
| 10:55 | **Pantalla Bot: `brain_backend` en API** para Duelos III |
| 11:00 a 11:50 | Duelos III: pantalla Duelos; cada duelo se contesta en su primer tick |
| 12:00 | `brain_backend` otra vez en auto |
| 13:48 | Aviso de final: últimos tratos con dealers antes de las 14:00 |
| 13:55 | `brain_backend` en API para la Final |
| 14:00 a 15:00 | Final: solo puntúan los duelos |
| 15:00 | Congelación. No apagar nada hasta ver la tabla final |

## Si algo falla

Todo desde la raíz del repositorio (`cd ~/Desktop/ClaudeHackathon`).

| Síntoma | Qué hacer |
|---|---|
| Parar toda escritura ya | `touch bazaar/STOP` (el bot se para; quitarlo con `rm bazaar/STOP`) |
| El bot no avanza | `kill $(pgrep -f "bazaar.run --live")`; el supervisor lo levanta en 10 s |
| El cerebro no planifica | `kill $(pgrep -f "bazaar.strategist.run")` |
| El broker no aparece en un Market Test | `kill $(pgrep -f "bazaar.broker.run")` |
| Grabación con huecos | `kill $(pgrep -f "bazaar.recorder.run")` |
| La dashboard no carga datos | `kill $(pgrep -f "bazaar.api.server")` |
| El panel no deja entrar o da 502 | Gateway, siempre así: `kill $(lsof -tiTCP:8787 -sTCP:LISTEN); DASHBOARD_ENV_FILE=.env nohup .venv/bin/python -u legacy/dashboard/server.py > bazaar/data/gateway.out 2>&1 &` |
| No hay supervisor (`pgrep -f bazaar.supervise` vacío) | `BAZAAR_ALLOW_REAL=1 BAZAAR_SUPERVISE_SKIP=plaza nohup .venv/bin/python -u -m bazaar.supervise > bazaar/data/live/supervise.out 2>&1 &` |
| Aviso "breaker: portfolio fell" | El bot deja de comprar 10 ticks (2,5 min) y sigue solo. Mirar qué trato lo causó |
| Un dealer pausado por 3 rechazos seguidos | Vuelve solo a los 10 ticks. Los duelos nunca se pausan |
| Las tres claves fallan | El bot sigue con código, sin modelo. Mirar Bot → Claude y el gasto del día |

Registros: `bazaar/data/live/supervise.log` dice qué se reinició y cuándo; cada proceso escribe en `bazaar/data/live/<nombre>.out`.

## Decisiones pendientes de Ángel y Daniel

Con opciones y recomendación en `noche-verificacion-bot.md`. Hasta que se contesten, el cerebro aplica lo conservador (P118): LAV-11 de un equipo hasta 210 y, si a las 10:30 ningún equipo la ha vendido, de Los Pícaros a 155 o menos; nada con Ernesto; repetidas protegidas; RET-11 no se vende; ninguna denuncia.

1. **Legendaria de Don Ernesto (hasta 470 a 500 P) o LAV-11 de un equipo (hasta 238 P).** Recomendado: equipos primero. Pagar más de 210 por LAV-11 pide subir el tope por trato a 240; la legendaria, a 500. Los tres topes van juntos: `curl -s -X POST localhost:8791/control -H 'X-Dashboard: 1' -H 'Content-Type: application/json' -d '{"caps": {"cash_reserve": 5, "max_spend_per_deal": 240, "max_spend_per_hour": 550}}'`, o desde la pantalla Bot.
2. **Liberar las repetidas MAL-01 ×2 y RET-01** para venderlas a equipos. Hoy están protegidas por nombre: en `protected`, cambiar `MAL-01` por `793` y `RET-01` por `794` (los ids de las copias que se quedan).
3. **RET-11 a Doña Pilar** por su huevo. Por debajo de 198 P pierde valor.
4. **Probar una denuncia a Los Pícaros en la ronda 3**: no se sabe si el tope de tres es por ronda.
5. **Aceptar el veto duro a Team 6** en el taller. Comprobado otra vez a las 04:30: se aplica limpio y sus 33 tests pasan. Tras aceptarlo hay que reiniciar el bot (`kill $(pgrep -f "bazaar.run --live")`); mejor antes de las 09:00.

## Lo que no se ha podido comprobar antes de abrir

- Que el reloj salte a 16,65 (lo dice el calendario, no un tick real).
- El regalo de la Abuela: el bot da por bueno que el huevo del tick 1364 reinició su reloj, así que lo intenta desde el tick 1604 (unos 40 minutos tras abrir) y no antes. Si a las 09:45 no ha abierto un hilo con ella, mirar en Bot que dealers no esté en pausa.
- Los arreglos de anoche y de esta madrugada no han corrido aún contra el juego abierto; sí en seco y contra el juego simulado (`noche-verificacion-bot.md`).
- El broker corre el código de las 23:00 del sábado. Conviene reiniciarlo antes de las 09:00, cuando los arreglos del mercado estén subidos, para que cargue los anuncios con el enlace nuevo.

## Cambios hechos de madrugada en la memoria del cerebro

Todos por su chat, como coordinación y no como órdenes de Ángel; copia previa en `bazaar/data/live/brain_memory.json.bak-0400`.

| Cambio | Motivo |
|---|---|
| Retiradas P3, P4, P5, P8, P9, P12, P13, P14, P18, P19, P24, P29, P32, P43, P50, P51 | Reglas del sábado (fiebre de Salamanca, hitos por hora, escalera vieja, Duels I y II). P13 limitaba LAV-11 a 130. El cerebro las retiró en el chat; su plan solo llevó 6 y el resto se aplicó a mano |
| P47 reescrita | La repetida RET-03 ya se vendió |
| P52 reescrita | Fuera "sin compras el sábado por la noche"; la protección por nombre sigue igual |
| P115 reescrita | El día de entrega lo elige el código (P117), no "vendedor 10, comprador 0" |
| P116 reescrita por el cerebro | Con la ventana del regalo abierta no pausa dealers: la pausa impide el hilo del regalo |
| P118 nueva | Valores conservadores para las decisiones pendientes de Ángel |
| 23 tareas cerradas, y una nueva sobre la duración del tick contestada | Hablaban de hilos y pujas del sábado |
