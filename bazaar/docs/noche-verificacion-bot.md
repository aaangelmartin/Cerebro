# Verificación nocturna del bot y la dashboard (domingo 4 de octubre, 03:55 a 04:40)

Encargo de Ángel antes de dormir: comprobar de verdad que el bot, el cerebro y la dashboard están listos para las 09:00. Todo lo de abajo se probó en seco o contra el juego simulado; contra el juego real solo hubo lecturas. El mercado (`bazaar/plaza/`), los duelos, el broker y el Market Test los cubre otro informe.

**Resultado: listo para abrir.** Cinco fallos reales encontrados y arreglados esta noche, todos pequeños y con test. Quedan cuatro decisiones de Ángel (al final) y lo que solo se puede ver con el juego abierto.

## Semáforo

| Bloque | Estado | En una línea |
|---|---|---|
| Plan y cerebro | Verde | 21 políticas activas, todas del domingo o compatibles; el plan lo explicó con sus palabras y casa con control y con `plan-domingo.md`; memoria comprobada tras reiniciarlo |
| Primeros ticks a las 09:00 | Verde | En seco sobre los datos reales de hoy: hasta que llegue el primer plan del cerebro, el bot solo ofrece LAT-02 y LAT-04 a 8 P |
| Dealers | Verde | Regateo por pasos, cambio de carta, regalo, cupos y presupuesto probados; dos fallos arreglados |
| Tratos con equipos y raíles | Verde, un hueco conocido | El hueco es el de Team 6 en pujas públicas: arreglo hecho, espera el Aceptar |
| Eventos del domingo | Verde | Salto de reloj, +150 P, Chamberí, pausa a mitad de trato, modelo caído: sin errores |
| Chamberí | Verde | Bot, raíles y dashboard lo tratan bien; un fallo arreglado (el mercado no habría visto el set en todo el día) |
| Dashboard | Verde | 13 pantallas en ES y EN sobre dos juegos de datos: sin errores de página; un fallo arreglado |
| Sin comprobar | Ámbar | Lo que depende del juego abierto (lista abajo) |

## Fallos encontrados y arreglados

| # | Qué pasaba | Arreglo | Commit |
|---|---|---|---|
| 1 | El cerebro dijo en el chat que retiraba 16 políticas del sábado y su plan solo llevaba 6: las otras 10 seguían activas. Además, un índice negativo borraba las políticas retiradas más antiguas aunque hubiera sitio | La regla de plan compacto ya no deja recortar `policies`; índice corregido. El resto de la limpieza se aplicó a mano tal como él la escribió | `117b8eb` |
| 2 | A las 09:00 el plan de la noche lleva horas caducado. Sin plan, el código tomaba SAL-01 (copia única de la página que estamos haciendo) por una repetida y la ofrecía a 11 P | Las cartas que un plan retiene (`reserved_refs`) siguen retenidas aunque el plan caduque, hasta que un plan nuevo las suelte | `72060e4` |
| 3 | El dominio de mercado leía el catálogo una vez al arrancar: Chamberí habría seguido "sin publicar" para él todo el domingo | Lo relee cada 10 minutos, como ya hacía el de dealers | `72060e4` |
| 4 | Un hilo de compra con la Abuela cuyo siguiente paso no cabía en caja se quedaba abierto y mudo para siempre (40 ticks en la simulación), ocupando su único hueco, también el del regalo | Espera 6 ticks y cierra | `191460c` |
| 5 | El código abrió la misma carta en dos dealers en el mismo tick; los raíles valoran la segunda como repetida y vetan cada puja, así que el segundo hilo solo gastaba cupo | Un hilo de compra por carta | `191460c` |
| 6 | La pantalla Cerebro pintaba "Prueba: [object Object]" en los hallazgos de investigación | Muestra el texto de la prueba | `2572e8f` |

Tests nuevos: `bazaar/tests/test_sunday_cases.py` (`b0252e0`), más los de cada arreglo. Herramienta nueva: `tools/dry_open.py` (`72060e4`, `28e6e01`, `200e7bb`).

Procesos reiniciados por el supervisor para cargar los arreglos: cerebro a las 04:01 y bot a las 04:26; los dos arrancaron limpios. Desde aquí, código congelado salvo fallo grave.

## Plan y cerebro

Hablé con el cerebro por su chat como "Claude (coordinación)", dejando claro que no eran órdenes nuevas de Ángel. Cuatro mensajes y sus respuestas están en el chat de la pantalla Cerebro.

**Lo que quedó en su memoria** (comprobado otra vez tras reiniciarlo):

- **Activas (21):** P2, P7, P16, P20, P21, P22, P23, P25, P33, P46, P47, P48, P49, P52, P112, P113, P114, P115, P116, P117, P118.
- **Retiradas del sábado (16):** P3, P4, P5, P8, P9, P12, P13, P14, P18, P19, P24, P29, P32, P43, P50, P51. Entre ellas P13, que limitaba LAV-11 a 130 frente a los 238 de P112.
- **Reescritas:**
  - P47: fuera la repetida RET-03, que ya se vendió.
  - P52: fuera "sin compras el sábado por la noche"; la protección por nombre sigue.
  - P115: el día de entrega lo elige el código (P117), ya no "vendedor 10, comprador 0".
  - P116: con la ventana del regalo abierta no se pausa el dominio de dealers (ver más abajo).
- **Nueva P118**, valores conservadores hasta que Ángel conteste: LAV-11 de un equipo hasta 210 primero, y de Los Pícaros a 155 o menos solo si ningún equipo la vende antes de h18,15 (es lo que dice la sección 5 del plan de Ángel); nada con Ernesto; MAL-01 y RET-01 repetidas siguen protegidas; RET-11 no se vende; ninguna denuncia.
- **Tareas:** las 23 abiertas hablaban de hilos y pujas del sábado que ya no existen; cerradas. Abrió una nueva sobre la duración del tick; contestada y cerrada (lee `tick_seconds` del reloj, no hay nada fijo).

**Su plan, con sus palabras:**

- **Si el reloj salta (ronda 3 a las 09:00):** `goal_buys` LAV-11 a 210 (valor 288) y SAL-06/07/08 a 21 (valor 22,5); `dealer_orders` a Los Pícaros por SAL-09 y SAL-10, abre en 45, tope 57 (valor 63); ningún dominio en pausa; escalera nueva en los cinco dealers con tratos cortos bajo valor; Chamberí solo de equipos y por debajo de valor.
- **Si no salta (ronda 2):** sin `goal_buys`, sin órdenes a dealers, sin puja por LAV-11 ("el +50 vale más en la ronda 3"); solo LAT-02 y LAT-04 a 8 P y los Market Tests.
- **Oferta de Team 6 que gane valor:** no la acepta; la deja caducar y la anota para Ángel.
- **Antes de Duelos III y de la Final:** caja libre, hilos cerrados, respuesta en el primer tick. El cambio de `brain_backend` a API es una acción humana (runbook).

Todo ello casa con `control.json` (topes 5 / 210 / 550, 32 protegidas, RET en "no comprar" con su excepción, `t06` vetado) y con las políticas de Ángel.

**Regalo de la Abuela y la pausa.** El hilo del regalo lo abre el código del dominio de dealers. Probado en seco en el tick 1604: con el plan que el cerebro tenía a las 04:00 (`pause_domains: ["dealers"]`) el hilo no se abre; sin la pausa se abre con SAL-06, tope 19. Se lo dije, reescribió P116 y quitó la pausa de su plan.

## Los primeros ticks a las 09:00, en seco

`tools/dry_open.py` copia los datos reales de hoy, sirve la foto grabada con el reloj de cada escenario y corre los dominios, el árbitro y los raíles de verdad, sin enviar nada y sin modelo.

| Escenario | Qué haría el bot en sus tres primeros ticks |
|---|---|
| El reloj salta, caja 340 | Ofrece LAT-04 y LAT-02 a 8 P (nos valen 5). Nada más |
| Tres minutos después, caja 490 | Lo mismo |
| El reloj no salta | Lo mismo |
| Con el plan del cerebro | LAT-04 a t16 por 8 P (orden del cerebro) y LAT-02 a 8 P |
| Tick 1604, ventana del regalo | Abre un hilo con la Abuela para nombrar un precio |

En todos: ninguna carta protegida, nada a Team 6, nada con Ernesto, ningún sobre, nada por encima de 210 P ni de nuestro valor. Las compras llegan con el primer plan del cerebro, que en el Mac tarda unos 75 s; con `brain_backend` en API, segundos.

Se puede repetir a las 08:50: `.venv/bin/python tools/dry_open.py` (un minuto; debe acabar en `RULES: all kept`).

## Casos probados

Cada fila cita la prueba que la respalda. "Suite" son los tests del repositorio: 1.171 fuera del mercado, todos en verde tras los arreglos.

### Dealers

| Caso | Estado | Prueba |
|---|---|---|
| Pilar: abrir alto, bajar 3 P por mensaje, tras su "final" solo aceptar o cerrar | Verde | `test_steps`: `pilar_opens_high_steps_of_three_takes_her_final`, `no_counter_offer_after_a_final` |
| Los Pícaros cambian la carta | Verde | `test_card_switch` (11 casos): repite la puja, nunca acepta la carta equivocada |
| Regalo de la Abuela en t1604 y reintento | Verde | `test_gift_window`; con el feed real el reloj del regalo queda en el huevo del tick 1364, la ventana abre en 1604 y el hilo sale en seco |
| El Chato: nunca pasos de 1 P | Verde | `test_steps`: `chato_never_gets_a_one_peseta_step` |
| Ernesto bloqueado sin OK | Verde | `test_sunday_cases`: los raíles vetan 585, 470 y 240 P con el tope de 210; el código no genera ninguna oferta para él ni con el tope levantado |
| Presupuesto por hora del dealer agotado | Verde | `test_steps`: `budget_closed_dealer_is_left_alone_for_an_hour`; `test_short_ticks`: espera una hora de juego con cualquier tick |
| Cupos por hora con ticks de 15 s | Verde | `test_thread_quota` (hora rodante en tiempo real) |
| Sobres | Verde | `test_sunday_cases`: con nuestra mano de hoy valen 11 a 13 (barrio, a 26), 84 a 89 (plata, a 150) y 274 a 276 (oro, a 420); el código exige 1,25 veces el precio |
| Hilo sin caja para el siguiente paso | Arreglado | fallo 4 |
| Misma carta en dos dealers | Arreglado | fallo 5 |

### Equipos y raíles

| Caso | Estado | Prueba |
|---|---|---|
| Comprar solo bajo valor, vender solo sobre valor, comisión incluida | Verde | `test_value_rail`, `test_never_lose_extra` |
| Repetidas: se vende la copia libre, nunca la protegida | Verde | `test_spares`, `test_kept_cards` |
| Última carta de página: tope con el bono, de un equipo | Verde | `test_last_card`, `test_last_card_bid` |
| Épicas fuera de página (LAV-11) como objetivo | Verde | `test_off_page_goal` |
| Cambios: solo si ganan y sin dar la última copia | Verde | `test_rails`: `swap_post_never_gives_last_scarce_copy`; `test_value_rail`: `swap_must_gain` |
| Oferta dirigida y contraoferta en hilos | Verde | `test_brain_posts`, `test_talk` |
| Reserva de caja 5, tope 210 por trato y 550 por hora | Verde | `test_rails`: `reserve`, `per_deal_and_hour`; `test_hour_cap_control` |
| Compras a la vez de la misma carta | Verde | `test_concurrent_buys` |
| `avoid_buy_sets` con su excepción (RET raras con 15 de ganancia) | Verde | `test_goal` |
| Team 6: oferta dirigida, hilo o puja con su nombre | Verde | `test_blocked_teams` |
| Team 6: puja **pública** (el libro no dice quién la puso) | **Hueco conocido** | Arreglo `8f2253e` listo; se aplica limpio sobre el código de hoy y sus 33 tests pasan. Espera el Aceptar de Ángel |
| El +50 por trato | Verde | Lo usa el cerebro en su menú de acciones (`test_winmath`); no es un raíl |

### Eventos

| Caso | Estado | Prueba |
|---|---|---|
| El reloj salta 3,3 horas con el tick seguido | Verde | `test_sunday_cases`: ni disyuntor ni olvido del gasto de la hora; `test_rounds` para el cerebro |
| +150 P | Verde | `test_sunday_cases`; en la simulación subí la caja a mitad de partida sin efecto raro |
| Set nuevo (Chamberí) | Verde tras el fallo 3 | `test_catalog_refresh`; en seco con Chamberí publicado no compra nada a dealers (cuesta más de lo que nos vale) |
| Dealer o nivel nuevo | Verde | `test_fake_bazaar`: `vault_activation_is_novel`; activado en la simulación |
| El mercado cierra a mitad de trato | Verde | Simulación: dos pausas con hilos y duelos abiertos, sin errores al volver; `test_run`: `loop_once_closed_doors_records_and_waits` |
| Error 5xx o tiempo agotado del juego | Verde | `test_gateway`: una lectura se reintenta, una escritura nunca; `test_executor`: el error queda como resultado |
| Modelo lento con ticks de 15 s | Verde | `test_short_ticks`: el código contesta en el primer tick; simulación a 15 s con modelo: 24 ticks, ningún envío tarde |
| El modelo falla: sigue el código | Verde | Simulación de 110 ticks con todas las llamadas fallando: 13 tratos, todos con ganancia; 16 de 18 duelos cerrados |
| Una clave deja de responder | Verde | `test_llm`: `dead_key_failover`, `credit_balance_kills_key`, `all_dead`, `ladder_reaches_haiku_then_code_only` |
| Reinicio a mitad de un regateo | Verde | Simulación: bot matado en el tick 58 con un hilo abierto; ningún mensaje doble ni error del juego. El hilo que quedó mudo era el fallo 4 |

### Simulaciones

| Corrida | Duración | Resultado |
|---|---|---|
| Sin modelo, ticks de 3 a 5 s | 110 ticks | 0 errores del juego, 0 envíos dobles, 13 tratos (ganancia mínima +2), 16 de 18 duelos cerrados con 14,1 puntos de media. Durante la corrida: caja subida, bot reiniciado, juego pausado dos veces, tick cambiado, sesión de duelos de 12 ticks con decay 0,10 y dealer nuevo |
| Con modelo, ticks de 15 s, dealers y mercado | 24 ticks | 0 vetos por llegar tarde, 9 tratos con ganancia, 6 acciones decididas por Opus |

El aviso "breaker: portfolio fell" salió en las dos al primer tick. Es del simulador (allí una carta ofrecida sale de la colección); en el juego real no ha saltado nunca: 0 veces en todo el registro del sábado.

## Chamberí

- **Bot:** con el set publicado y nuestra afinidad de 0,7, cada carta de dealer cuesta más de lo que nos vale (10 frente a 7, 25 frente a 17,5); en seco no abre ninguna compra. De un equipo y por debajo de valor, sí.
- **Valores:** vienen del juego en cada consulta; no hay nada local que actualizar.
- **Dashboard:** probado con una copia de datos donde Chamberí está publicado y tenemos dos cartas. Colección pinta el set (2/10, valores, huecos) y las cartas propias sin la ilustración oficial, con el diseño de reserva. Las ilustraciones oficiales no están en `dashboard/cards.json`; para tenerlas, `bazaar/dashboard/tools/fetch_cards.py` cuando el set esté publicado. No es necesario para operar.

## Dashboard

- 13 pantallas en ES y EN sobre dos juegos de datos (copia de hoy con Chamberí, y los datos del bot simulado): ningún error de página, ningún texto "undefined" ni clave sin traducir.
- Controles del Bot contra una copia: apagar y encender, pausar dominios, cambiar `brain_backend`, topes. Sin la cabecera de la dashboard, 403; topes mal escritos, 400.
- Chat del cerebro: usado de verdad esta noche (cuatro mensajes).
- "Hablar con un dealer": la pantalla carga y muestra caja y dealer; no envié nada.
- Sigue saliendo un 404 de `api/llm/health` en la consola; ya estaba y la pantalla usa otra fuente.

## Lo que no se pudo probar sin el juego abierto

| Qué | Cómo verlo en los primeros 10 minutos |
|---|---|
| Que el reloj salte a h16,65 | Barra superior o `curl -s https://bazaar.causaprima.ai/api/clock`: `round` 3 |
| Que el tick sea de 15 s | La cuenta atrás de la barra va de 15 en 15 |
| El primer plan del cerebro en la ronda 3 | Cerebro: `goal_buys` LAV-11 210, órdenes a Los Pícaros por SAL-09/10, ningún dominio en pausa |
| Que SAL-01..05 no salgan a la venta | Mercado → "Nuestras ofertas abiertas": solo LAT-02 y LAT-04 |
| Que los cupos de dealers empiecen de cero | Lateral, "Cupos dealers · esta hora" |
| Si el regalo de la Abuela se reinició con el huevo del tick 1364 | Hacia el tick 1604 (unos 40 minutos tras abrir) el bot abre un hilo con ella; si llega carta, la hipótesis era buena |
| Los arreglos de anoche y de esta madrugada contra el juego real | Supervisión: decisiones con su motivo, sin vetos repetidos |
| El comportamiento real de Opus en dealers a 15 s | Supervisión: fuente "opus" en las acciones de dealers, no "fallback" |

## Gasto de modelo de estas pruebas

**0,04 $** (dealers 0,025 y mercado 0,014 en la corrida de 24 ticks con modelo). El cerebro corrió en el Mac, sin coste de API. El resto de lo gastado hoy (3,76 $ a las 04:30, casi todo en duelos) es de las pruebas de duelos del otro informe.

## Decisiones pendientes de Ángel

Hasta que contestes rige lo conservador (P118).

**1. Legendaria de Ernesto o LAV-11**
- **A (recomendada): LAV-11, equipos primero.** De un equipo hasta 210 (el +50); de Los Pícaros a 155 o menos si a las 10:30 ningún equipo la ha vendido. Deja caja para Salamanca y la escalera. Si un equipo pide entre 211 y 238, hay que subir el tope: `curl -s -X POST localhost:8791/control -H 'X-Dashboard: 1' -H 'Content-Type: application/json' -d '{"caps": {"cash_reserve": 5, "max_spend_per_deal": 240, "max_spend_per_hour": 550}}'` (los tres topes juntos; o desde la pantalla Bot).
- **B: legendaria de Ernesto hasta 470.** Se lleva casi toda la caja por un hueco L5 (unos 1,3 puntos hoy). Pide subir el tope a 500.
- **C: las dos**, solo si entran unos 230 P por ventas.

**2. Repetidas MAL-01 (dos de sobra) y RET-01 (una de sobra)**
- **A (recomendada): liberarlas al empezar la ronda 3** para venderlas a equipos que completen página. En `protected`, cambiar el nombre por el id de la copia que se queda: `793` (MAL-01) y `794` (RET-01). Quedan libres 1169, 1170 (MAL-01) y 1168 (RET-01).
- **B: dejarlas protegidas.** No arriesga nada y no suma.

**3. RET-11 a Doña Pilar**
- **A (recomendada): no venderla.** Nos vale 198 y Pilar no pagará eso.
- **B: abrir el hilo a 250 o más por el huevo** y no cerrar por debajo de 198.

**4. Denuncia a Los Pícaros en la ronda 3**
- **A (recomendada): probar una** cuando cambien la carta; si suma +10, seguir hasta tres.
- **B: ninguna.**

**5. Veto duro a Team 6** (`code-8d5dd3bf`): Aceptar en Cerebro → Para el equipo → Cambios de código. Sin él, el bot puede aceptar una puja pública que resulte ser de Team 6.
