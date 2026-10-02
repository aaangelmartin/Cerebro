# Investigación: por qué pasamos de 29,1 a 20,4 puntos (ticks 40–153)

Cerrado el viernes a las 22:55, tick 153. Datos: `dashboard/actions.log` (321 acciones), `bot/data/decisions.jsonl` (807 decisiones), `bot/data/memory.json`, el feed público y el leaderboard.

## 1. No hemos perdido puntos: nos han adelantado

Nuestro valor **bruto** de negociación no ha dejado de subir:

| Momento | `neg_points` (bruto) | Puntuación | Puesto |
|---|---|---|---|
| Tick ~75 | 2,0 | 29,13 | 1.º |
| Tick ~98 | 64,6 | 24,65 | 4.º |
| Tick 153 | 68,7 | 20,37 | 5.º |

La puntuación de negociación es **relativa**: el mejor equipo se lleva los 30 puntos y el resto una parte proporcional. Al principio todos estaban a 0 y cualquier ventaja nuestra valía casi el máximo. Ahora el líder (Team 13) tiene unos 101 puntos brutos estimados y nosotros 68,7, es decir, un 68 % de su valor: 20,37 sobre 30.

**Conclusión: no hay ninguna fuga. El problema es que otros crecen más rápido.**

## 2. Dónde nos sacan ventaja

| Equipo | Puntuación | Acuerdos | Álbum | Páginas | Suerte |
|---|---|---|---|---|---|
| t13 | 30,00 | 24 | 25 | 1 | +19,5 |
| t12 | 27,25 | 21 | 23 | 1 | +30,8 |
| t08 | 23,30 | 11 | 22 | 0 | −25,5 |
| **t10 (nosotros)** | **20,37** | **19** | **23** | **1** | **0,0** |

- **Más acuerdos:** el Team 13 lleva 24 y nosotros 19. Desde el tick 113 mantiene una cadena constante de ventas a los dealers (SAL-01 por 5, SAL-02 por 6, LAT-09 por 46, MAL-06 por 15).
- **Sobres:** t12 y t13 acumulan +30,8 y +19,5 de suerte; nosotros 0,0 porque no hemos abierto ninguno. La suerte **no puntúa**, pero las cartas que sacan sí tienen valor para intercambiar, y por eso su álbum crece.
- **El Team 8 demuestra que importa el margen, no el volumen:** con solo 11 acuerdos tiene 23,3 puntos, más que nosotros con 19. Compra con mucho descuento (MAL-10 por 53 con un valor de libro de 70).

## 3. Nuestros errores, por orden de coste

### a) La escalera de dealers está casi a cero (0,068 puntos)

Cuentan nuestros 3 mejores acuerdos por nivel según **qué parte del rango de precio del dealer capturamos**. Los acuerdos del bot:

| Acuerdo | Precio inicial del dealer | Cerrado en | Captura |
|---|---|---|---|
| Compra SAL-07 a Abuela | 29 | 21 | 27,6 % |
| Compra SAL-02 a Abuela | 12 | 8 | 33,3 % |
| **Venta MAL-02 a Abuela** | 5 | 5 | **0 %** |
| **Venta MAL-03 a Abuela** | 5 | 5 | **0 %** |

Las dos ventas se cerraron **al primer precio que ofreció Abuela**. Según las reglas, un acuerdo al precio de salida del dealer no cuenta para la escalera ni para desbloquear. Ganamos 1,8 P de valor en cada una, pero 0 puntos de escalera.

Las compras que hicisteis a mano antes del tick 100 cerraron cerca del precio de salida de Abuela (17, 24, 24, 23), así que tampoco aportaron escalera.

### b) 16 mensajes rechazados por exceso de ritmo

`wait_for_tick`: 10 en duelos, 6 en conversaciones con dealers. El juego permite **un mensaje por lado y tick**, y el bot envió dos. Cada rechazo es una ronda de negociación perdida. Causa probable: el modo revisión de 6 s con 6 duelos a la vez hace que las acciones se desborden al tick siguiente, y entonces el bot vuelve a enviar.

### c) Venta de SAL-10 por error (tick 98)

El bot entregó una carta del equipo (valor 63 para nosotros) por 70 P al Team 13. Fue +2 de valor, pero perdimos la carta que estabais usando para negociar LAV-09 con el Team 7. Ya está corregido y cubierto por tests.

### d) Tres conversaciones gastadas en SAL-07

El bot intentó vender a Abuela y a El Chato una carta que vale 22,5 para nosotros mientras ellos ofrecían 13–14. Ocupó el único hueco de conversación de cada dealer durante varios ticks. Corregido: ya no vende cartas que valgan casi su precio de libro.

### e) El álbum apenas puntúa

Completamos la página de Lavapiés (10/10) y tenemos 23 huecos llenos, igual que el Team 13 con 25. Pero la puntuación mide **valor creado negociando**, no colección. Fue un buen objetivo para el valor privado, no para la nota.

## 4. Lo que sí ha funcionado

- **Duelos:** 19 terminados, 17 con acuerdo. Fórmula confirmada al decimal: **puntos = margen × 0,94^rondas**. Los duelos de práctica no puntúan, pero nos dieron el formato real y el ajuste del negociador.
- **Compra de LAV-09 a El Chato por 90 P** (vale 112 para nosotros) y completó la página de Lavapiés.
- **Valor de la colección:** de 233,9 a 788,2.

## 5. Plan para mañana

1. **Cadena de acuerdos sin parar.** Una conversación abierta con cada dealer en todo momento, vendiendo lo que vale poco para nosotros. El sábado llegan las cartas de El Retiro.
2. **Nunca cerrar al precio de salida del dealer.** Es el cambio de mayor impacto en la escalera: un acuerdo al primer precio da 0 puntos.
3. **Abrir el mercado propio** justo después de la asignación de 150 P (hora 4,05) y antes del primer Market Test (hora 5). Con `"mechanism": "auto"` el juego empareja solo y no hace falta programa. Comisión del 0–1 %, como los otros cuatro mercados. Son 30 puntos que ahora mismo todos tienen a 0.
4. **Arreglar los `wait_for_tick`:** que el bot lleve la cuenta de en qué tick ha hablado ya en cada conversación y duelo.
5. **Valorar abrir sobres** si aparece alguno por debajo de su valor para nosotros. Los líderes han crecido así.
