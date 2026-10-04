# Plan del domingo 4 de octubre (v2, escrito el sábado a las 23:00)

Estado al cierre del sábado: **1.º con 37,74** (negociación 25,24, mercado 12,5). Caja 340 P. Tres páginas completas (LAV, MAL, RET 01–10) más MAL-11 y RET-11 ("Palacio de Cristal"), todo protegido por nombre. Libres: LAT-02, LAT-04, SAL-01..05. Insignias: Sharp ear, Trickster tricked, Castizo.

## 0. Cómo puntúa (brief oficial "Payday" + lo medido)

- Trato = valor que añade a la colección − precio pagado + precio recibido.
- **Con un equipo:** la ganancia cuenta hasta **+50 por trato**; la pérdida cuenta entera. 10 puntos brutos ≈ 0,46 de tabla (medido el sábado; la tabla es relativa).
- **Con un dealer:** la ganancia solo cuenta en la **escalera** (mejores 3 tratos por dealer; los niveles altos pesan más); la pérdida cuenta entera.
- Caja, cartas en mano, álbum, regalos, huevos y suerte de sobres: no puntúan.
- Marcador: negociación 30; mercado 30 (Market Test 22,5 + tratos reales 7,5); jurado 40.
- Rondas: viernes 0,5, sábado 1, domingo 1. La escalera y los puntos de trato se reinician por ronda.

Consecuencia: **el dinero solo puntúa en tratos con equipos** (hasta +50 cada uno) y en huecos de escalera con compras que ganen valor. Lo demás es cero o resta.

## 1. Horario: dos escenarios, primera comprobación de las 09:00

Verificado en `/api/schedule` y `/api/clock` (sábado 22:46): el domingo abre a las 09:00 en t = 13,361 con ticks de 15 s, y el propio servidor pone el cierre de puertas en t = 19,361 a las 15:00: **una hora de juego = una hora de reloj (240 ticks)**. Con el calendario tal cual, la final (t = 21,65) caería después del cierre, así que lo coherente con el brief es que **el reloj salte a t = 16,65 a las 09:00**. Tabla de Daniel, comprobada:

| t | Evento | Si el reloj salta (brief) | Si corre como está listado |
|---|---|---|---|
| 13,36 | Apertura | 09:00 | 09:00 |
| 14,65 | Market Test "hard" (12 traders) | al abrir o se salta | 10:17 |
| 15,00 | Market Test | al abrir o se salta | 10:38 |
| **16,65** | **Chamberí + ronda 3** | **09:00** | 12:17 |
| 16,70 | +150 P a todos | 09:03 | 12:20 |
| 17,00 | Market Test | 09:21 | 12:38 |
| **18,65** | **Duelos III** (2 vueltas, 12 ticks, decay 0,10, 4 a la vez) | **11:00** | 14:17 |
| 19,00 | Market Test | 11:21 | 14:38 |
| 19,36 | Cierre de puertas (probablemente se mueve) | 11:43 | 15:00 |
| 21,00 | Market Test | 13:21 | fuera |
| 21,45 | Aviso de final | 13:48 | fuera |
| **21,65** | **Grand Final (1 vuelta) y cierran los cinco dealers** | **14:00** | fuera |
| 22,65 | Congelación de puntos | 15:00 | fuera |

- **Primera comprobación a las 09:00: ¿t saltó a 16,65?** (`/api/clock`: `t_hours`, `round`, `round_name`). Si saltó: estamos ya en la ronda 3, Chamberí ha salido y los 150 P llegan a las 09:03 → ir directamente al bloque 4. Si no saltó: sigue la ronda 2 hasta las 12:17 → bloque 3.
- El bot y el cerebro leen el tick y la hora de juego del servidor; lo que cambia son las horas de reloj a las que hablamos con los equipos.
- En ticks: Chamberí y ronda 3 en el evento `round` del feed; Duelos III 480 ticks después de Chamberí; la final 720 ticks después de Duelos III.

## 2. Checklist 08:30–09:00 (Ángel)

1. Mac encendido y sin suspensión. `bazaar.supervise` vivo y sus 7 procesos (bot, cerebro, broker, recorder, API, lab, vigilante oficial).
2. Túnel de Cloudflare: la URL cambia si se reinició; mirar `bazaar/data/cloudflared.out`.
3. Claves LLM vivas (panel Bot). Presupuesto: quedan ~135 $ de 240 $; el reparto automático da al domingo ~132 $ con 32,5 $ reservados para las dos sesiones de duelos y los tests.
4. Control: `armed` true; `blocked_teams` ["t06"]; `protected` 32 cartas; `caps` 210 por trato / 550 por hora / reserva 5; `matchmaker` on; `avoid_buy_sets` ["RET"].
5. Leer el calendario (bloque 1) y decir al cerebro por el chat en qué ronda estamos y cuándo sale Chamberí.
6. Relanzar los agentes de fondo: vigilante de noticias/huevos y los agentes de huevos (bloque 8).
7. Primer minuto: `/api/me` (caja, ¿llegaron 150 P?), clasificación, que el bot hace ticks de 15 s sin errores, y que no hay dominios en pausa ni hilos manuales.

## 3. Solo si el reloj NO salta: de 09:00 a la salida de Chamberí (sigue la ronda 2): preparar, no gastar

En la ronda 2 ya tenemos 25,2 de 30 en negociación: poco margen. La ronda 3 empieza de cero y vale lo mismo. Regla: **guardar la caja para la ronda 3**; antes solo lo que no cuesta o deja el terreno listo.

- **En la sala (Ángel y Daniel), antes de que empiece la ronda 3 (si el reloj salta, antes de las 09:00 o en los primeros minutos):** cerrar de palabra los tratos que se ejecutarán nada más empezar la ronda 3:
  - Quién nos vende una **LAV-11** (nos vale 288; pagamos hasta 238). Team 3 dijo que no; Team 4 pidió 350 (no). Pedir a Team 17, Team 8, Team 14, Team 9 o Team 1 que la compren a Los Pícaros (~150) y nos la sirvan a 210–235.
  - Quién nos vende una **poco común de Salamanca** (SAL-06, 07 u 08) como última carta de la página: equipos que venden Salamanca barato: Team 12, 2, 13, 15, 17.
  - Quién compra raras de Salamanca a 90–110: Team 1, Team 16, Team 9.
- **Regalo de la Abuela:** uno cada 240 ticks (60 min con ticks de 15 s), en su respuesta a nuestra primera puja con precio. El sábado el bot abrió el hilo en la ventana del tick 1421 y lo cerró sin pujar porque la caja reservada para objetivos dejaba su límite en 0; arreglado (`e5a3fe0`). Dos pujas a mano en los ticks 1426 y 1428 no trajeron regalo: hipótesis de que la carta del huevo del tick 1364 reinició su reloj, así que **el siguiente sería desde el tick 1604** (unos 40 min después de abrir: el domingo abre en el tick ~1444) y luego cada 240 ticks: ~1844, ~2084, ~2324. Si llega antes, la hipótesis es falsa y el reloj es el del último `gift.given`. El vigilante lo comprueba y lo pide a mano si el bot no puja.
- **Market Test "hard" (10:17 si el reloj no salta):** solo medir. Es la única sesión donde nuestro motor ganó al puesto gratuito en simulación. Mirar `bench_efficiency` y `bench_points` después.
- **Huevos del domingo:** ver bloque 8; se pueden probar ya desde las 09:00.
- **No comprar** cartas a dealers en este tramo: llenarían la escalera de la ronda 2, que ya está casi llena, y no la de la ronda 3.

## 4. Primer cuarto de hora de la ronda 3 (09:00 si el reloj salta; 12:17 si no): tratos con equipos

Caja prevista: 340 + 150 = **490 P**. Poner el cerebro en API (`brain_backend: "api"`) durante los primeros 20 minutos de la ronda 3: en el Mac un plan tarda ~74 s (5 ticks).

Orden, cada trato con su tope:

| # | Trato | Precio | Ganancia | Quién |
|---|---|---|---|---|
| 1 | Comprar **LAV-11** a un equipo | hasta 238 (tope de control 210: subirlo a 240 si hace falta, decisión de Ángel) | +50 | puja pública en El Rastro + lo hablado en la sala |
| 2 | Vender repes a equipos por encima de nuestro valor: MAL-01 ×2, RET-01 ×1 (hay que liberar la copia sobrante en control), LAT-02, LAT-04 | lo que paguen sobre nuestro valor de repe | hasta +50 cada una si le completa página a alguien (nunca a Team 6 ni a un rival directo) | cerebro + sala |
| 3 | **Puentes** (comprar a dealer por debajo de nuestro valor una carta que NO tenemos y venderla a un equipo a valor + 50): raras de Salamanca (Los Pícaros ~53; nos valen 63; a Team 1/16/9 a 90–113), RET no (ya la tenemos: una segunda copia vale un cuarto) | compra ≤ 57; venta ≥ 90 | +27 a +50 por vuelta | fork a mano o bot con `resell_to` |
| 4 | **Salamanca completa**: SAL-09 y SAL-10 a Los Pícaros (≤ 57 cada una; llenan dos huecos L4 de la escalera nueva), dos poco comunes a un dealer solo por debajo de 22,5, y **la última (una poco común) a un equipo** | última: hasta 60 | +50 | bot (la última queda reservada para equipo: commit `dce639c`) |
| 5 | Chamberí: ver bloque 6 | | | |

Reglas de cierre con equipos: que **acepten ellos nuestra oferta** (la comisión de El Rastro, 5 % + 1 P, la paga quien acepta). Los agentes rivales no contestan a los hilos del juego: los tratos del sábado salieron hablando en persona.

## 5. Escalera de dealers de la ronda 3 (15 huecos nuevos)

Valor a captura completa (escala del sábado): L5 ≈ 1,3 de tabla por hueco, L4 ≈ 1,07, L3 ≈ 0,8, L2 ≈ 0,53, L1 ≈ 0,27. Solo cuentan tratos que ganen valor; la captura depende de cuánto se baja desde la apertura.

| Nivel | Dealer | Qué tratos | Escalera de pasos |
|---|---|---|---|
| L4 | Los Pícaros | SAL-09, SAL-10 (para la página), una épica que no tengamos por debajo de nuestro valor (LAV-11 a ~150 si ningún equipo la sirve en la primera hora y media de la ronda 3) | primera puja ~65 % de su apertura, +6–8 P por mensaje, aceptar su "final"; si cambian la carta, repetir la puja nombrándola |
| L5 | Don Ernesto | Una legendaria que nos valga más que el precio: **LAV-12 720**, **MAL-12 701** (sube por tener MAL-11), **RET-12 593** (sube por tener RET-11), SAL-12 405 (no). Su apertura 761; el sábado bajó a 731 con pasos de 5 P; el brief habla de ~470 "para un negociador paciente" | pujas serias desde ~430, pasos de 10, paciencia; nunca trucos (ya avisó una vez) |
| L3 | Doña Pilar | Venderle raras o poco comunes por encima de nuestro valor (solo compra) | abrir a 1,5 × su apertura, bajar 3 P por mensaje, tras su "final" solo aceptar |
| L2 | El Chato | Solo tratos que ganen valor: venderle repes de poco común (paga 13–17) | pasos de 2–4 P, nunca de 1 P |
| L1 | Abuela | Venderle repes de poco común (18–20) o comunes por encima de valor | pasos de 1–3 P |

**Decisión de Ángel:** una legendaria cuesta casi toda la caja (≥ 470 P) por ~1,3 puntos; dos tratos con equipos de +50 dan ~4,6 por menos de 400 P. La legendaria solo si, pasada la primera hora de la ronda 3, sobra caja y no quedan tratos con equipos. Exige subir `max_spend_per_deal` a ~500.

## 6. Chamberí (afinidad 0,7)

- 12 cartas, página de 10. Nos valen: común 7, poco común 17,5, rara 49, CHA-11 126, CHA-12 315. Página 185,5 + bono ~46.
- A precio de dealer cada carta cuesta más de lo que nos vale (10 > 7, 25 > 17,5, 53 > 49): **comprar a un dealer resta**. Solo se compra a equipos por debajo de nuestro valor.
- Chamberí como **puente**: no sirve con compra a dealer (resta). Sí sirve vender a equipos con afinidad alta las cartas de Chamberí que nos lleguen de regalos o tratos.
- La página solo si sale casi entera de equipos a precio bajo; la última carta, a un equipo. Abandonar si a mitad de la ronda 3 faltan más de 3 cartas.
- Posibles claves de huevo en los textos de Chamberí: CHA-12 "It stops only for collectors", CHA-11 "The station time forgot", CHA-06 "Closed in 1966, opened again for you", CHA-10 "A poet lived here".

## 7. Duelos III (11:00 si el reloj salta; 14:17 si no) y Grand Final (14:00 si salta)

- Duelos III: 12 ticks por duelo (3 minutos con ticks de 15 s), decay 0,10 por ronda de charla, 4 a la vez, 2 vueltas, precio + días. Grand Final: 1 vuelta, mismos parámetros.
- Sábado: 68 duelos, 60 acuerdos, media 19,1, cero fuera de límite. Arreglado el texto del vendedor (`b1e9d21`).
- Guía: responder en el primer tick; una oferta clara; **cerrar siempre** (sin acuerdo = 0); con decay 0,10 aceptar antes; final corto en los últimos ticks; **usar los días también como comprador** (media del sábado 0,6 días: ahí puede haber pastel); nunca cruzar el límite.
- Con ticks de 15 s el plazo de decisión es el 65 % del tick (9,75 s); si el modelo no llega, responde el código en ese tick.
- Cerebro en API desde 5 minutos antes hasta el final de cada sesión. Desde 5 ticks antes: solo duelos.
- Presupuesto (`d78db49`): el reparto reserva 20 $ por sesión de duelos, 40 $ para Duelos III y la Final, dentro de los 240 $ del evento. Los duelos ya no tienen tope por propósito: aunque el cerebro lo fije, el modelo no se corta a mitad de sesión (solo lo para el tope del día). El sábado NO hubo corte: Duels II costó 5,12 $, con Opus decidiendo el 78 % de las acciones de principio a fin y cero errores; el "15,53 de 15,53" del panel era el gasto del día (incluía 4 $ de evaluación) igualado al reparto.
- Día de entrega (`863a93f`): el día va a quien más le importa. Cada objeto tiene un rango de pesos por papel y jugamos cada objeto en los dos papeles, así que nuestros duelos en el otro papel dicen cuánto vale un día para el rival. Si su peso es claramente mayor (≥ 1,25 veces el nuestro y ≥ 0,5 puntos más), como comprador ofrecemos 10 días y como vendedor 0, y el precio cobra la diferencia. En Duels II eso dejó unos 7,6 puntos de pastel por acuerdo sin coger (ejemplo: La Sala Pentagrama, un día nos costaba 1,3–2,4 como comprador y le daba 3,9–6,9 al vendedor). Hasta tener 2 duelos del otro papel en ese objeto, se juega como el sábado.
- Apertura: como comprador abrimos a 0,8 del pastel estimado (antes 0,9; Daniel midió bien: 0,68 veces el límite y 2,2 rondas por acuerdo frente a 1,7 como vendedor). El calendario de concesión usa ya la duración real del duelo (12 ticks, no 16).
- El límite es de PRECIO, no de utilidad: el servidor lo dice en `limit_meaning` ("never pay above your value" / coste del vendedor). El caso del duelo 5778 (31 P con 10 días, coste 36) sigue siendo un no: vender por debajo del coste resta aunque los días compensen.
- Prueba en seco a 15 s (14 duelos, 4 a la vez, plazo 9,75 s): Opus contestó el primer tick en 14 de 14 (máximo 8,2 s); en toda la sesión, 59 decisiones del modelo y 7 de la reserva (6 llamadas pasaron de 9,5 s), ninguna respuesta fuera del tick. Modelo 12,7 puntos por duelo frente a 10,9 del código. Latencia p50 7,1 s, p90 9,0 s: justa; si la API va lenta, la reserva contestará más, pero siempre en el tick.
- Control: `duel_claude_mode` sin fijar (corre `bounded`), `duel_days_sign` sin fijar (el lector ya distingue comprador y vendedor). `brain_backend`: ponerlo en `api` 5 minutos antes de cada sesión de duelos y devolverlo a `auto` al acabar (`POST /control {"brain_backend": "api"}`): los planes en el Mac tardan ~74 s, cinco ticks de 15 s.

## 8. Huevos y cartas ocultas (en segundo plano todo el día)

Huevos conocidos: Abuela (chulapa dorada → Sharp ear; chotis → Castizo; cocido de tres vuelcos → carta), Los Pícaros (timo de la estampita → Trickster tricked), El Chato (bocadillo de calamares en un hilo de rara → sobre), Don Ernesto ("el oro de Moscú" → LAT-13, única, gastada). Se disparan con una clave castiza en un hilo normal; el dealer la repite.

| Cuándo | Con quién | Qué probar |
|---|---|---|
| 09:00+ | Doña Pilar | Hilo de venta de **RET-11 "Palacio de Cristal"** con "as promised, para el hueco de su álbum". Ella: "Vuelva el domingo con el Palacio de Cristal… los domingos se abren los álbumes". **Ojo:** venderle RET-11 por debajo de 198 resta la diferencia entera: abrir alto (≥ 250) y NO cerrar por debajo de 198 sin el sí de Ángel. Alternativas baratas: LAT-07 "Vermut del Domingo" o LAT-06 (nos valen 12,5) |
| 09:00+ | Abuela | "Mañana me las enseñas todas, hijo", "bring the churros Sunday", "I show you new things": hilo normal + "le traigo los churros y el álbum: tres páginas completas" |
| 09:00+ | Don Ernesto | Un solo mensaje limpio: "receives only the most accomplished collectors, on Sundays": presentarse con tres páginas completas. Sin pujas adjuntas que pueda aceptar |
| 09:00+ | El Chato | Opcional (188 P): pagarle un sobre de plata sin regatear y volver a preguntar por "la del Manzanares". Probable improvisación: no recomendado |
| Tras salir Chamberí | Todos | Las claves de los textos de Chamberí (bloque 6) |
| Todo el día | Vigilante | `egg.*`, `badge.*`, catálogo (73 cartas, 1 oculta), noticias; copiar al momento cualquier huevo nuevo de otro equipo |

Regalos de comida castiza dan carta o sobre (`egg.given`), no insignia. Ninguno puntúa en el marcador; pueden contar para el jurado.

Denuncias: el sábado +10 cada una, tope de 3. **Probar una** en la ronda 3 con un cambio de carta nuevo de Los Pícaros; si suma, seguir de una en una hasta 3.

## 9. Mercado (v07)

- Matchmaker activo dentro del broker: anuncia pares y la receta que funciona (oferta dirigida de vendedor a comprador en v07, y el comprador acepta). Excluye a los rivales directos y a los equipos vetados.
- Anuncio de Chamberí preparado en el cerebro: lanzarlo en el tick de salida.
- En la sala: cuando dos equipos vayan a cerrar un trato grande entre ellos, pedirles que lo hagan en v07 (0 % de comisión): nos da puntos de "tratos reales".
- Market Tests: automáticos; se empata con el puesto gratuito. No tocar el broker cerca de un test.

## 10. Qué NO hacer

- Sobres a ciegas (oro, plata, barrio).
- Vender a un dealer por debajo de nuestro valor (Team 16 y Team 6 perdieron más de 2 puntos así).
- Comprar a un dealer por encima de nuestro valor (Chamberí, La Latina, segundas copias).
- Nada a **Team 6** (vetado en código: `blocked_teams`), ni completar la página a un rival directo.
- Vender o cambiar cartas de las páginas completas ni MAL-11.
- Reiniciar el bot durante duelos o tests.

## 11. Riesgos y qué vigilar

- **Team 6** (hace puentes y tiene buen mercado), **Team 5** (copia nuestras frases de huevos; mejor negociación bruta), **Team 18** (épicas). La ronda 3 empieza de cero: la ventaja del sábado no se arrastra dentro de la ronda.
- Ticks de 15 s: no vistos en vivo. Mirar en los primeros minutos que el bot decide dentro del tick y que el recorder no pasa de su tope de peticiones.
- Forks tocando código a la vez: el domingo, un solo despliegue cada vez y nunca durante duelos o tests.
- La caja: se supone que pasa del sábado al domingo (pasó del viernes al sábado); no confirmado.

## 12. Hechos frente a suposiciones

Hechos: fórmula de puntuación (brief), calendario del servidor, valores de cartas (`/api/me/value`), resultados del sábado.
Suposiciones: que el reloj salte a t = 16,65 a las 09:00 (bloque 1), que la caja pase de ronda, que el tope de denuncias sea por ronda, que la escala de la escalera se mantenga, el precio real de Don Ernesto.

## 13. Repes: cuándo liberarlas

Hoy están protegidas por nombre todas las cartas que no son de La Latina ni de Salamanca (orden de Ángel del sábado). Repes dentro de lo protegido: **MAL-01 ×3** (sobran 2) y **RET-01 ×2** (sobra 1).

- Liberarlas **al empezar la ronda 3**: en `control.protected`, quitar el nombre (`MAL-01`, `RET-01`) y poner el id de la copia de la página (el más antiguo de cada una); las otras copias quedan libres.
- A quién: equipos a los que les falte esa carta para una página (les vale carta + bono; a nosotros la repe nos vale un cuarto). RET-01: la buscaron Team 15, Team 14 y Team 9. MAL-01: preguntar en la sala quién completa Malasaña.
- Precio: nuestro valor de repe + 50 da el máximo; cualquier precio por encima del valor de repe suma.
- **Nunca a Team 6** (vetado en código) ni a un rival directo al que le complete página (Team 5, Team 18).

## 14. Diferencias con el plan de Daniel (`bazaar/docs/daniel-sunday-strategy.md`), para decidir entre los dos

Coincidimos en casi todo: equipos primero (tope +50), LAV-11 hasta 238, vender repes, puentes Pícaros → equipo, nada de sobres, nunca vender cartas de página ni MAL-11, matchmaker en v07, Chamberí solo por debajo de valor, cerrar todos los duelos. Su calendario de dos columnas es el que usa este plan.

| Punto | Daniel | Este plan | Cifras |
|---|---|---|---|
| **Legendaria a Don Ernesto (su opción A) frente a LAV-11 de un equipo (B)** | Recomienda A: ≤ 470 P, +231 a +250 de valor de carta, "cinco veces B" | Recomienda B y el resto de tratos con equipos; A solo si sobra caja | El marcador no cuenta valor de carta. Con dealer la ganancia solo entra en la escalera: un hueco L5 vale 5/15/3 = 0,111 de escalera × captura; 1,0 de escalera ≈ 12 de tabla el sábado (medido en tres tramos: +0,047 → +0,59; +0,105 → +1,33; +0,108 → +1,29) y ≈ 7 con las tres rondas: **A ≈ 1,3 de tabla hoy, ≈ 0,8 al final, por ~470 P**. Con equipo, +50 brutos ≈ 2,3 de tabla el sábado, ≈ 1,4 al final (medido al decimal en 5 tratos): **B ≈ 1,4 al final por ≤ 238 P**. Por P, B rinde unas 3,5 veces más. Con 490 P: A deja 20 P y nada más; B deja ~250 P para Salamanca (última carta a un equipo, otro +50), dos huecos L4 y los puentes. B + Salamanca ≈ 2,8 al final + escalera L4, frente a 0,8 de A |
| Si se hace B primero | — | Ya no llega para A (quedan ~250 P) | Solo cabrían las dos si entran ~230 P por ventas y puentes |
| LAV-12 con LAV-11 en mano | — | Probablemente sube de 720 a ~863 (MAL-12 585 → 701 y RET-12 495 → 593 al tener la 11: ×1,199). No cambia los puntos de A: la escalera mide la captura, no la ganancia | Sin verificar para Lavapiés |
| Tope por trato | Pide subirlo para Ernesto | Hoy 210; para A habría que ponerlo en ~480 solo para esa compra | Decisión de Ángel |
| Duelos: apertura como comprador | Dice que el bot abre a 0,68× del límite (pide ≥ 0,75×) y tarda 2,2 rondas frente a 1,7 como vendedor | No lo he podido verificar esta noche con los datos de Duels II | Si es cierto, con decay 0,10 cada ronda de más cuesta un 10 %: subir la apertura de comprador a ≥ 0,75×. Va al issue de duelos; nada se despliega sin tests |
| Duelo 5778 (precio del rival bajo nuestro límite, +8,8 contando días) | Mantiene la regla de precio | El brief de duelos define el margen como margen de precio + peso × días; si el límite es de utilidad, ese trato era positivo y había que aceptarlo | Hay que comprobarlo en un duelo real cerrado así; hasta entonces, regla de precio (la segura) |
| Caja antes de la ronda 3 | Tratos pequeños con dealers al empezar la ronda | Igual; y si el reloj no salta, no gastar en la ronda 2 (ya estamos en 25,2 de 30) | — |
| Salamanca como cuarta página | No la menciona | La última carta (una poco común) a un equipo: +50 | Tenemos SAL-01..05 |

Dos avisos para Daniel:
- **El chat del cerebro admite 4000 caracteres** desde el sábado (`b894e68`): puede pegar sus directivas enteras, sin partirlas.
- **Quién manda si chocan:** las directivas de Daniel se aplican salvo que choquen con las políticas de Ángel (nada con Don Ernesto ni compras por encima del tope sin su OK, nada a Team 6, cartas protegidas). Si chocan, el cerebro abre una tarea y no ejecuta.
