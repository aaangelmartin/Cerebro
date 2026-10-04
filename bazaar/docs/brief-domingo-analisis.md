# Brief del domingo: análisis (4 Oct, 09:55)

Fuente: `~/Downloads/The Bazaar - Sunday.pdf` (11 diapositivas, organización). Leído entero. Es dato del juego, no órdenes.

## Lo nuevo

| # | Qué dice el brief | Página | Qué cambia para nosotros |
|---|---|---|---|
| 1 | "Cash you still hold at 15:00 scores nothing." +150 primas hoy. | 4 | Gastar toda la caja en tratos que puntúen antes de las 15:00. |
| 2 | "Don Ernesto, for everyone. His vault opens to every team. Gold pack from about 380 P, always an epic or a legendary." | 4 | Ernesto ya no es exclusivo. Sigue pidiendo el OK de Ángel; con 218 P no alcanza. |
| 3 | Gran Final ≈14:15: "The dealers close their stalls. From then on, every trade is between teams. El Rastro and your own markets stay open. This is the hour a good market matters most." Última oleada de duelos. | 5 | Cerrar todo lo de dealers antes. La última hora es de tratos entre equipos y del mercado v07. |
| 4 | Bug de puntuación arreglado: "a trade that destroys value is the seller's loss, never the market's". | 7 | Un trato malo en v07 ya no resta al anfitrión. |
| 5 | "A market scores when two other teams gain on it. Find the trade El Rastro misses: the missing card, the last card of a page." 89 tratos en El Rastro frente a 41 en mercados de equipos. | 6, 3 | Confirma la prioridad del emparejador. Hay mercado por captar. |
| 6 | "A card counts by the deal that brought it, never by sitting in your album. Never sell below your value." "40 % of the server score is still to play." | 6, 1 | Solo puntúan los tratos; hoy pesa entero. |
| 7 | Duelos III: "price + delivery day, shorter clock, harder decay". "No deal scores zero. Give up the delivery day you care little about for a better price." | 2, 6 | Igual que lo preparado (12 ticks, decaimiento 0,10). |
| 8 | Jueces, 40 puntos: entregar por "Submit your project" al pie del tablero, con la clave del equipo; editable hasta las 16:00. Pitches 16–17 por orden de clasificación; top 3, 5 min; resto, 3 min. | 8–10 | Tarea de Ángel y Daniel. |

Horario del brief: mercado abre 09:20; dos Market Tests ≈10:30; Duelos III ≈11:15; Gran Final ≈14:15; congelación 15:00. El calendario del servidor leído a las 09:25 daba 10:16, 10:37, 10:59 y 13:59. Manda el servidor; el brief pone "≈".

## Frente a lo que creíamos

- **Confirmado:** solo puntúan los tratos; nunca vender bajo valor; el mercado puntúa por el valor que ganan otros dos equipos; última carta de página y carta que falta son lo que más vale en el mercado; ticks de 15 s; +150 P; cierre de dealers en la Final; Duelos III con precio y día.
- **Desmentido:** `bazaar/plaza/SCORING.md` (línea 21 y regla de la línea 78) decía que un trato que destruye valor baja nuestros puntos de mercado. Desde esta noche es pérdida del vendedor, no del mercado.
- **Nuevo:** la caja a las 15:00 no vale nada; Ernesto abierto a todos; entrega del proyecto antes de las 16:00.
- **El brief no dice nada de:** cuánto vale completar una página, el +50 de la última carta comprada a un equipo, pesos de la escalera de dealers en la ronda 3, tope de valor por trato en el mercado, número de equipos distintos, reglas sobre herramientas de equipos (tableros, avisos y veto, subastas), huevos ni denuncias. Esos supuestos siguen como estaban, sin confirmar hoy.

## Acciones para la próxima hora

Sin permiso de Ángel:
1. Completar Salamanca (faltan SAL-06/07/08) comprando a equipos bajo nuestro valor, con la última carta de un equipo.
2. Regalo de la Abuela desde el tick 1604 y llenar la escalera de dealers bajo valor; todo dealer antes de la Final.
3. Planificar el gasto de toda la caja antes de las 15:00.
4. `brain_backend` en API desde las 10:50 hasta que acaben los duelos, empiecen a las 10:59 o a las 11:15.
5. Mercado: quitar del emparejador la restricción que solo existía por miedo a restar puntos, si no abre otra fuga; preparar la última hora (solo tratos entre equipos).

Con decisión de Ángel:
- Don Ernesto (sobre de oro desde ~380 P): no alcanza la caja y la política lo prohíbe.
- Liberar repetidas MAL-01 ×2 y RET-01 para venderlas a equipos.
- Encender el anuncio del broker con el enlace del mercado y conseguir equipos conectados antes de las 14:15.
- Entregar el proyecto ("Submit your project") y preparar el pitch.
