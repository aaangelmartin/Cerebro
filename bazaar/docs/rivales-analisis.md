# Qué hacen los equipos líderes (sábado 3 oct, hasta el tick 715)

Análisis con nuestros datos grabados (`data/record`: feed, clasificación, tiendas) y las reglas del kit. Solo lectura; los números salen de scripts sobre esos ficheros.

## Resumen en una frase

En mercado ya estamos en el techo (12,5). Toda la distancia está en negociación, y lo que más la mueve es **completar una página con una carta comprada a otro EQUIPO**: da entre +3 y +7 puntos de golpe. Completarla comprando a un dealer casi no da nada.

## Clasificación (tick 710)

| Puesto | Equipo | Total | Negociación | Mercado | Páginas | Tratos Carmen / Chato / Pilar |
|---|---|---|---|---|---|---|
| 1 | t14 | 30,27 | 20,76 | 9,51 | 2 | 3 / 2 / 1 |
| 2 | t12 | 29,73 | 17,23 | 12,50 | 1 | 10 / 4 / 1 |
| 3 | t18 | 29,25 | 21,75 | 7,50 | 2 | 6 / 3 / 0 |
| 4 | **t10 (nosotros)** | 28,59 | 16,58 | 12,01–12,50 | 1 | 5 / **0** / 2 |
| 5 | t05 | 28,53 | 21,03 | 7,50 | 2 | 7 / 6 / 4 |
| 6 | t13 | 26,09 | 20,01 | 6,08 | 2 | 16 / 3 / 6 |

Los cuatro equipos con más negociación tienen **2 páginas**; nosotros 1 (Malasaña está en 9/10).

## 1. Negociación

### 1.1 El salto grande: completar página con un trato entre equipos

Cada vez que un equipo completó una página comprando la última carta **a otro equipo**, su negociación saltó en la siguiente foto de la clasificación:

| Tick | Equipo | Trato que completó la página | Salto en negociación |
|---|---|---|---|
| 230 | t18 | RET-02 (común) a t02 por **49 P** | **+5,83** |
| 276 | t05 | RET-01 (común) **a nosotros** por 20 P | **+4,49** |
| 331 | t13 | MAL-10 a t09 por 65 P | **+7,17** |
| 508 | t17 | MAL-10 a t18 por 70 P | **+3,12** |

Cuando la página se completó comprando a **El Chato** (7 casos: t16 ×2, t09, t01, t14, t06, t04), el salto fue de −1,05 a +0,63; solo t02 llegó a +1,43. Encaja con la regla: la negociación cuenta «el valor ganado en tratos con otros equipos, a tus valores privados», y la carta que cierra la página vale su precio más el bono del 25 % de toda la página. Con un dealer solo cuenta la escalera.

Comprobación con nuestros propios datos: al comprar MAL-10 a t03 por 74 P (valor 91), `neg_points` pasó de 12,9 a 24,9 y la negociación subió +1,1. Es decir, **unos 0,07–0,09 puntos por cada P de valor ganado con equipos**. MAL-09 con el bono vale unos 177 P para nosotros: comprada a un equipo por 100 P serían ≈ +5 puntos; por 140 P, todavía ≈ +2.

**Consecuencias**
- MAL-09 hay que conseguirla **de un equipo**, no de El Chato. El plan actual del cerebro (Chato a ≤ 88 P) completaría la página casi sin puntos.
- t18 pagó 49 P por una común porque le cerraba la página. Nosotros podemos pagar mucho más de 88 P por MAL-09 y seguir ganando.
- Quién tiene MAL-09 (4 de 30 emitidas más las del viernes): **t05** (le salió en un sobre plata en el tick 639; es nuestro aliado), **t08** (desde el viernes), t13 y t17 (la usan en su página) y t12 (figura como su carta más rara).
- El error simétrico: vendimos RET-01 a t05 por 20 P y esa carta les cerró la página (+4,49 para ellos). Una carta que completa la página de un rival vale para él mucho más que su precio de catálogo.

### 1.2 Duelos

- Duelos I movió mucho: t12 +5,87 y t14 +6,58 en las fotos de los ticks 460–480; nuestros `duel_points` pasaron de 0 a 9,89.
- Tasa de acuerdo en todo el juego: 37 % el viernes (80 de 215) y 74 % hoy (227 de 306). La nuestra hoy: 29 de 34 (85 %).
- No se puede ver el margen de los rivales (el feed solo publica acuerdo o no). Tres de nuestros acuerdos cerraron a 1–3 P del límite; ya está corregido en el bot.

### 1.3 Escalera de dealers

- Somos el **único equipo del top 10 sin ningún trato con El Chato** (nivel 2). Los líderes tienen entre 2 y 6.
- Cómo llenan el nivel 2: compran una rara (84–91 P, 1,2 veces el catálogo) o le **venden poco comunes a 13–16 P** (0,56 del catálogo). Lo segundo es muy barato, pero queda por debajo del valor privado de la carta: nuestro raíl de «nunca perder valor» lo bloquea.
- Nivel 3 (Pilar): venden poco comunes a 17–25 P (t13 seis, t04 cinco, t05 cuatro). Nosotros llevamos 2.
- Peso real de la escalera: incierto. En nuestros datos, cada trato con Pilar subió `ladder_points` 0,03–0,04; la correlación entre equipos de la negociación con el número de tratos por nivel es casi nula (−0,03 y 0,03), mientras que con las páginas es 0,16. La escalera suma, pero menos que una página.

### 1.4 De dónde sacan la caja

- Compran a Carmen por debajo de catálogo (0,87–0,97): El Retiro sobre todo (t12 8 cartas, t18 6, t05 5, t02 7).
- Venden comunes sobrantes a Carmen a ~5 P (t04 diez, t13 ocho) y poco comunes a Pilar.
- Ventas grandes entre equipos: t04 vendió la épica LAT-11 por 160 P; t06 RET-09 por 84 P; t12 SAL-10 por 76 P.
- Sobres plata: t08, t05, t13 y t07 sacaron raras de ahí (incluidas tres MAL-09).

### 1.5 El Taller ya está activo (tick 706)

`POST /api/taller {"assets": [a, b, c]}`: tres copias sobrantes de una misma rareza (hay que conservar al menos una de cada carta) se convierten en una carta de la rareza siguiente. t05 y t12 ya lo usaron en el tick 709 (tres comunes → una poco común). Nuestro bot todavía no sabe usarlo. Tenemos 4 comunes sobrantes (MAL-02 ×2, MAL-01, LAV-04).

## 2. Mercado

- La nota de mercado es 7,5 (Market Test al nivel del puesto gratis, que da la mitad de los puntos) más hasta 5 por el valor creado entre otros equipos en tu tienda. **12,5 es el techo actual**; lo tienen t12 y nosotros. Nadie supera al puesto gratis en el test, así que nadie pasa de ahí.
- 13 equipos están en 7,5 justos: no tienen tratos ajenos en su tienda.
- Quién crea valor: v02 de t12 (8 tratos, 69 P, 86 % de ofertas públicas, 70 cambios carta por carta), **v07 nuestra (6 tratos, 54 P, 6 parejas distintas)**, v01 de t06 (3 tratos, 101 P), v21 de t09 (5 tratos).
- Los anuncios no explican la diferencia: v03 lleva 40 y 0 tratos; v06, 26 y 0; nosotros 22. Lo que funciona es que los vendedores publiquen en abierto (t14 vendió cinco comunes de El Retiro en v02 a 9 P).
- Margen que queda: como mucho +0,5 puntos. Solo subiría más quien batiera al puesto gratis en el Market Test.

## 3. Qué explica su ventaja y qué cambiar

| # | Comportamiento de los líderes | Evidencia | Puntos estimados | Cambio para nosotros |
|---|---|---|---|---|
| 1 | Completan la segunda página con una carta comprada a un equipo | 4 casos: +3,1 a +7,2. Con dealer: ≈ 0 | **+4 a +7** | MAL-09 de un equipo (t05 o t08), no de El Chato. Subir el tope de MAL-09 para tratos con equipos a ~130 P o cambio por SAL-10 + cartas de El Retiro. Humanos: hablar con Team 5 |
| 2 | Puntúan fuerte en duelos | t12 +5,9 y t14 +6,6 en Duelos I | **+3 a +6** en Duelos II | Responder todos, cerrar pronto con margen (ya desplegado). Duelos II ≈ 18:30 con día de entrega |
| 3 | Tienen tratos de nivel 2 con El Chato | Top 10: todos ≥ 1; nosotros 0 | +1 a +3 (incierto) | Decisión del usuario: permitir vender una poco común sobrante a El Chato por debajo de su valor (los tratos con dealers no restan «valor con equipos») o esperar a comprarle una rara |
| 4 | Usan el Taller | t05 y t12 en el tick 709 | Pequeño, pero da cartas para la escalera y la fiebre | Petición de código: soporte de `POST /api/taller`; convertir comunes sobrantes |
| 5 | No regalan páginas | Nosotros dimos a t05 su página por 20 P | Evita +4,5 a un rival | Regla: antes de vender, mirar si la carta cierra la página del comprador; si la cierra, pedir mucho más o no vender a rivales directos |
| 6 | Caja con ventas a dealers y a equipos | Comunes a Carmen ~5 P; LAT-11 a 160 P | Indirecto | Vender repes que no vayan al Taller; SAL a Pilar en la fiebre |
| 7 | Tienda con ofertas públicas | v02: 86 % públicas | ≤ +0,5 | Ya estamos en el techo; mantener |

## 4. Lo que no se puede saber con estos datos

- El margen de los rivales en cada duelo y sus valores privados (afinidades): solo se infieren de lo que compran.
- El peso exacto de la escalera dentro de los 30 puntos.
- La nota es relativa a los mejores: los saltos estimados son los que se vieron en otros equipos, no una garantía.
