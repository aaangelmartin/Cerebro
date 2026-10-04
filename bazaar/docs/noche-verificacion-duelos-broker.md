# Verificación de la noche: duelos, broker y Market Test

Domingo 4 de octubre, 04:00–05:00. Todo se probó en simulación o con datos grabados; contra el juego real
solo hubo lecturas. Gasto de modelo de estas pruebas: **0,51 $**.

## Resumen

| Punto | Estado | En una línea |
|---|---|---|
| Duelos: estrategia | Verde | Ninguna variante de parámetros mejora de forma clara; se quedan como están |
| Duelos: cuatro a la vez, ticks de 15 s | Verde | Los cuatro reciben respuesta en su primer tick aunque Claude tarde o falle |
| Duelos: límite | Verde | Ningún precio cruza el límite en 440 duelos simulados ni en 68 reproducidos |
| Duelos: presupuesto | Verde | 102 duelos cuestan entre 3 y 16 $; hay 40 $ reservados |
| Duelos: aceptar cuatro en un tick | Arreglado | El tope era 3 y el domingo hay 4 en vivo; el bot ya corre el tope nuevo |
| Market Test | Verde | Igual que el puesto gratuito en normal, 0,02 por encima en difícil; sin cambios |
| Broker: fallo o lentitud de la plaza | Arreglado | Las llamadas a la plaza tienen 2 s de plazo y el broker arranca aunque la plaza no importe |
| Broker: latido | Arreglado | Se escribe antes de las lecturas lentas; un juego lento ya no parece un broker colgado |
| Broker: ofertas dirigidas | Arreglado | Una oferta dirigida a un equipo ya no se cruza con un tercero |
| Broker: enlace del mercado | Arreglado | El anuncio del venue solo lleva el enlace cuando alguien enciende `plaza: "on"` |
| Broker en marcha | Verde | Reiniciado a las 04:33 con todo este código; ver "Reinicio" |

## Duelos

Formato del domingo (del calendario del juego): Duelos III a t = 18,65 con dos vueltas (68 duelos) y la
Final a t = 21,65 con una (34 duelos). Cada duelo dura 12 ticks, decaimiento 0,10 por ronda, precio y días
de entrega, cuatro en vivo a la vez.

### Qué pasó el sábado (Duelos II, 68 duelos)

- 60 tratos y 8 sin trato; 1297 puntos. De los 8 sin trato, en 4 el rival no dijo nada.
- La fórmula está comprobada en los 60 tratos, al decimal: `(margen + peso × días) × (1 − decaimiento)^rondas`.
  Como vendedor cada día suma; como comprador cada día cuesta.
- El rival aceptó nuestra oferta en 25 tratos; nosotros la suya en 28.
- 10 rivales no hicieron ninguna oferta y 18 hicieron una sola.
- La regla "nunca cruzar el límite en precio" costó como mucho 13 puntos (duelos 5778 y 5806). Las reglas
  dicen que un trato fuera del límite resta puntos, así que la regla se queda.

### Herramienta nueva: `python -m bazaar.duels.sunday_eval`

Juega la política de código en el formato del domingo, con el mismo mensaje que manda el servidor.

- Sin opciones: contra once tipos de rival sobre los escenarios de Duelos II.
- `--variants`: una línea por variante de parámetros.
- `--replay`: reproduce a los 68 rivales reales de Duelos II en el reloj nuevo. Cada rival repite sus
  ofertas en el mismo punto del duelo y acepta lo que se sabe que acepta. No reacciona a lo que hacemos,
  así que es un mínimo, el mismo para todas las variantes.

### Política de código contra once tipos de rival (12 ticks, decaimiento 0,10, 400 duelos por tipo)

| Rival | Puntos por duelo | Tratos | Rondas por trato | Parte del total |
|---|---|---|---|---|
| mirror (nuestra propia política) | 32,9 | 100 % | 1,4 | 0,49 |
| splitter (regatea hacia el medio) | 19,6 | 98 % | 2,2 | 0,31 |
| eager (cede cada tick) | 15,0 | 96 % | 1,4 | 0,23 |
| mute (no ofrece, a veces acepta) | 14,9 | 48 % | 0,0 | 0,24 |
| fixed (una sola oferta) | 13,1 | 68 % | 0,8 | 0,21 |
| stepped (cede si le contestan) | 9,6 | 94 % | 4,9 | 0,15 |
| injector (texto con inyección) | 9,5 | 90 % | 4,9 | 0,15 |
| slow (despierta cada tres ticks) | 6,4 | 66 % | 2,9 | 0,11 |
| tough (duro, pasos de 1–2 P) | 2,3 | 37 % | 6,9 | 0,04 |
| absurd (abre a 3× el total) | 1,9 | 33 % | 5,2 | 0,03 |
| silent (no contesta) | 0,0 | 0 % | — | 0,00 |
| **Mezcla parecida a la del sábado** | **11,7** | **67 %** | **2,3** | **0,18** |

Con el reloj del sábado (16 ticks, 0,08) la misma mezcla da 10,4 puntos sobre escenarios algo distintos:
el formato corto no rompe nada. El texto con inyección no cambia ninguna decisión.

### Variantes de parámetros

Mezcla simulada (11,69 puntos de base) y reproducción de los rivales reales (1008 puntos de base en el
reloj del domingo, 1066 en el del sábado):

| Variante | Mezcla | Reproducción, domingo | Reproducción, sábado |
|---|---|---|---|
| Abrir como vendedor a 0,8 (hoy 0,9) | −0,07 | −1 | +3 |
| Abrir como vendedor a 1,0 | −0,01 | −13 | −4 |
| Abrir como comprador a 0,7 (hoy 0,8) | −0,07 | −14 | −1 |
| Abrir como comprador a 0,9 | +0,05 | +6 | +16 |
| Aceptar al 50 % del total (hoy 60 %) | −0,14 | −38 | −36 |
| Aceptar al 70 % | +0,06 | −4 | +7 |
| Aceptar cualquier cosa dentro del límite en los 3 últimos ticks (hoy 2) | −0,09 | −7 | −2 |
| Solo en el último tick | +0,05 | −5 | −8 |
| Ceder antes (BETA 1,5) | −0,04 | +9 | +9 |
| Ceder más tarde (BETA 3) | +0,03 | −6 | +4 |
| Sin el tick de sondeo | −0,45 | −29 | −34 |

**Decisión: no se cambia ningún parámetro.** Ninguna variante gana en las tres columnas; las diferencias
son de menos del 1,5 %, dentro del ruido. Las dos que sí se mueven (aceptar al 50 % y quitar el sondeo)
pierden entre un 3 y un 4 %, así que confirman los valores actuales.

### Claude contra código, cuatro duelos a la vez, reloj del domingo

Dieciséis rivales reales reproducidos, en tandas de cuatro, con el plazo real de un tick de 15 s (8,25 s):

| | Puntos | Tratos | Rondas por trato | Vendedor | Comprador |
|---|---|---|---|---|---|
| Código solo | 183,1 | 12 de 16 | 1,67 | 101,1 | 82,0 |
| Claude con el guardia | 178,8 | 12 de 16 | 1,42 | 88,1 | 90,8 |

- Empate práctico: la diferencia es un solo duelo (5806, donde el código aceptó 88 y Claude esperó).
- Claude contestó los 16 duelos en su primer tick. La decisión de un tick con cuatro duelos tardó 3,1 s
  de media, 5,7 s en el percentil 90 y 6,9 s como máximo, por debajo de los 8,25 s.
- 57 llamadas, 0,51 $: unos 0,03 $ por duelo. El sábado real fueron 0,15 $ por duelo (15,5 $ en 102
  duelos). Para los 102 duelos del domingo son entre 3 y 16 $, frente a los 40 $ reservados.

### Latencia y fallos del modelo

Tests nuevos (`bazaar/duels/tests/test_sunday_format.py`) con cuatro duelos en vivo:

- Claude tarda más que el tick: los cuatro reciben la apertura de código en menos de un segundo.
- Claude caído, respuesta inútil o interruptor abierto: lo mismo, sin llamadas de más.
- Claude pide un precio fuera de todos los límites: el guardia lo corrige en los cuatro.
- Claude acepta todo: no se acepta ninguna oferta fuera del límite.

En simulación, contestar por primera vez en el tick 1, 2 o 4 en vez del 0 no baja los puntos (11,6 → 11,7
→ 11,8 → 12,0): perder el primer tick no es grave.

### Reinicio a mitad de sesión

La memoria de duelos se guarda en disco cada tick. Tras un reinicio el duelo conserva sus 12 ticks y el
bot no repite mensaje a un rival callado (test). Sin memoria alguna, sigue jugando dentro del límite.

### Aceptar cuatro duelos en el mismo tick

- El bot limitaba las aceptaciones de duelo a tres por tick. El domingo hay cuatro en vivo y los cuatro de
  una tanda acaban en el mismo tick: la cuarta aceptación del último tick se habría perdido (cero puntos).
- El juego cuenta las aceptaciones de duelo aparte de las de ofertas. El sábado hubo cuatro ticks con dos
  aceptaciones de duelo y las dos entraron (1250, 1259, 1265, 1337). Tres o cuatro en un tick no se han
  visto nunca.
- El tope pasa a cuatro (commit `19141fe`). El bot se reinició a las 04:26, con el cambio ya en disco.

### Sin probar con el juego abierto

- Cuatro aceptaciones de duelo en un mismo tick.
- Que los rivales del domingo se comporten como los del sábado.
- El coste real de la carrera Opus + Sonnet en ticks cortos (aquí salió a 0,03 $ por duelo).

Qué mirar en los primeros minutos de Duelos III (11:00 si el reloj salta): en Duelos de la dashboard, que
los cuatro duelos de la primera tanda tienen oferta nuestra en el primer tick y que la columna de origen
dice Claude y no código. Si dice código en todos, mirar las claves en Bot.

## Broker

### Quién hace qué

- **La plaza** (`bazaar/plaza`) empareja a equipos con agente conectado. Les dice que publiquen una
  oferta **dirigida** en v07 y que el otro la acepte. El broker no interviene en esos tratos.
- **El broker** (`bazaar/broker`) hace tres cosas: juega el Market Test, cruza las ofertas **públicas** que
  se solapan en v07 (una venta y una puja de la misma carta, de dos equipos distintos, al punto medio), y
  cada 5 ticks invita a parejas de otros equipos con un anuncio en el venue.
- Los equipos que usan solo la API del juego no necesitan la plaza: publican en v07 y el broker cruza.
- No se pisan: el anuncio pone primero las parejas declaradas en la plaza y quita las repetidas (test), y
  el cruce público deja en paz las ofertas dirigidas (arreglado esta noche, test).
- Team 10 nunca es parte: el juego no deja operar en el venue propio y el emparejador no nos propone.

### Qué sabe el broker de un trato

Solo ve precios: la venta, la puja y quién las hizo, con alias. No ve cuánto vale la carta para cada
equipo, así que **no puede saber** si un cruce crea o resta valor. El trato que nos restó el sábado
(t04 → t09, RET-06 a 28 P) lo cerraron ellos aceptando la oferta, sin broker. El sábado el broker no
cruzó ninguna oferta pública (no llegó a haber dos que se solaparan): los 11 tratos de v07 los aceptaron
los propios equipos. El cruce público solo está probado con tests.

Lo que sí hace: los anuncios no empujan precios por debajo del suelo de cada rareza, y dejan fuera a los
dos rivales mejor colocados y a los equipos de `blocked_teams`.

### Arreglos de esta noche

1. **La plaza no puede colgar al broker** (`fa9327e`). Las dos funciones de la plaza que usa el
   emparejador corren en su propio hilo con 2 s de plazo y se dejan dos minutos en paz tras un fallo.
   Medido: 0,00 s hoy. Antes una llamada lenta habría dejado el latido viejo, y el domingo el supervisor
   reinicia el broker a los 30 s.
2. **Latido antes del trabajo lento** (`fa9327e`). Se escribe al empezar el tick y antes del emparejador.
   El sábado a las 23:00 el supervisor ya reinició el broker por un latido de 104 s durante un corte de red.
3. **Ofertas dirigidas** (`fa9327e`). Una oferta con destinatario solo se cruza con ese equipo.
4. **Arranque sin la plaza** (`a5c35a0`). El broker importaba la plaza al arrancar; un error de sintaxis
   allí lo habría dejado sin arrancar, y con él el Market Test. Ahora arranca y anuncia sin el enlace.
5. **El enlace del mercado no sale solo** (`d5e41d1`). Los anuncios del venue los leen todos los equipos.
   Con la dirección ya puesta en `control.plaza_url`, el broker la habría publicado en su primer anuncio
   tras abrir, antes de que Ángel decida compartirla. Ahora el anuncio lleva el enlace solo cuando
   `control.json` dice `plaza: "on"`. Para encenderlo: `POST /control {"plaza": "on"}` (la API ya lo
   acepta, sin reinicios). El mercado funciona igual con la clave ausente; solo calla la dirección.

### Comprobado

- Comisión 0 % y venue `board` abierto (lectura del juego: v07, 11 tratos, 8 equipos).
- Con `plaza: "on"` el anuncio acaba en el enlace nuevo, `https://market.nglmrtn.com/plaza/` (sale de
  `control.plaza_url`); sin la clave, el mismo anuncio sale sin enlace. Probado en seco con los datos
  reales: 23 parejas, 0,08 s, quedan fuera t18, t05 y t06.
- Un anuncio como mucho cada 20 ticks, contando los que otros hagan en nuestro venue (test).
- No anuncia durante un Market Test ni en los 12 ticks anteriores; con ticks de 15 s son 3 minutos.
- Un fallo al leer el libro se apunta y el tick siguiente sigue (test nuevo).
- Los 97 tests del broker pasan, y la suite completa también (1460 tests).

### Sin probar con el juego abierto

- Un cruce público real en v07 (nunca ha habido dos ofertas públicas que se solapen).
- Un anuncio real con el código nuevo: el juego está en pausa y el broker no anuncia con las puertas
  cerradas.

Qué mirar a las 09:00: `bazaar/data/live/broker_status.json` debe cambiar de `updated` cada pocos
segundos y de `tick` cada 15 s. En `bazaar/data/live/matchmaker.json`, `last_text` es el último anuncio:
sin enlace mientras `plaza` no esté en `on`, y acabado en el enlace nuevo después.

## Market Test

### Qué mide y dónde estamos

El juego da el mismo libro sintético a todos los venues y mide la eficiencia del emparejamiento. Igualar
al puesto gratuito da medio punto de banco; el punto entero es la media de los tres mejores venues.

| Sesión del sábado | Eficiencia (servidor) | Puesto gratuito (réplica) | Emparejados | Rechazos | Puntos de banco |
|---|---|---|---|---|---|
| b7 | 0,899 | 0,892 | 5 | 2 (sondas) | 0,5 |
| b25 | 0,933 | 0,931 | 4 | 0 | 0,5 |
| b43 | 0,878 | 0,797 | 5 | 0 | 0,5 |
| b60 | 0,878 | 0,926 | 6 | 0 | 0,5 |
| b78 | 0,886 | 0,883 | 6 | 0 | 0,5 |
| b95 | 0,854 | 0,651 | 4 | 0 | 0,5 |

- Los dos rechazos ("price must sit between the ask and the bid") fueron sondas de la primera sesión; la
  regla quedó fijada y no ha habido más.
- En las seis sesiones emparejamos exactamente lo que habría emparejado el puesto gratuito. Nadie tiene
  más de 12,50 en mercado: somos los primeros en ese componente.
- El margen sobre el puesto es mínimo por diseño (análisis del sábado en `bazaar/broker/IMPROVEMENT_NOTES.md`):
  no se cambia nada.

### Simulación de esta noche (60 sesiones por tipo)

| Tipo | Broker | Puesto gratuito |
|---|---|---|
| Normal (10 operadores, 16 ticks) | 0,931 | 0,933 |
| Difícil (12 operadores, 16 ticks) | 0,879 | 0,859 |

Sin errores. Si el motor falla, el broker cruza como el puesto gratuito, así que nunca baja de medio punto.

### Domingo

- Si el reloj salta a t = 16,65 a las 09:00, los tests son a t = 17,0, 19,0 y 21,0: **09:21, 11:21 y
  13:21**. Los dos de t = 14,65 (difícil) y 15,0 quedan por detrás del salto; pueden lanzarse al abrir o
  no lanzarse.
- El de las 11:21 coincide con Duelos III. Son procesos distintos: no se estorban.
- El broker detecta el test difícil por el nombre en el calendario o por tener 12 operadores.
- Modo actual: `smart`, escrituras activas, clave del venue presente.
- Un reinicio a mitad de test no es grave: el broker reconstruye el libro en el tick siguiente. Aun así,
  **no reiniciar el broker entre las :18 y las :27 de las horas impares** (09, 11, 13).

## Reinicio del broker

El broker corría el código del sábado a las 23:00. Se reinició dos veces por el supervisor (`kill` del
proceso; el supervisor lo levanta en 10 s): a las 04:28 con los cuatro primeros arreglos y a las 04:33 con
el del enlace. Arrancó limpio las dos veces: clave del venue presente, escrituras activas, modo `smart`,
regla `quotes`, sin errores, y la plaza importa bien. El bot se reinició a las 04:26 (otro fork) y ya
corre el tope de cuatro aceptaciones de duelo.

Si el código Python de `bazaar/plaza/` cambia después de las 04:33, conviene repetir el reinicio del broker
para que el emparejador use la versión final; no es urgente, porque el broker solo le pide a la plaza las
parejas declaradas y su dirección.

## Commits

- `afd8fec` y `27d15bc`: `bazaar/duels/sunday_eval.py`, `bazaar/duels/tests/test_sunday_format.py`.
- `fa9327e`, `a5c35a0` y `d5e41d1`: `bazaar/broker/{engine,matchmaker,run}.py` y sus tests.
- `19141fe`: `bazaar/core/context.py`, `bazaar/core/tests/test_accept_budgets.py`.
