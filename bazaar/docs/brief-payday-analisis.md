# Brief "Payday": mercado y escalera en puntos de tabla (sáb 3 oct, tick ~1227)

Fuentes: `~/Downloads/The Bazaar - Payday.pdf`, `sdk/bazaar-kit/RULES.md`, `data/record/{leaderboard,me,venues}`, `data/live/bench/*`, `/api/schedule`, `/api/catalog`. Solo lectura; 0 $ de API.

## A. Market Test

### Fórmula (reconstruida)
- Tabla = media ponderada de rondas: (0,5·viernes + 1·sábado + 1·domingo) / suma de pesos de lo ya jugado. Hoy el divisor es 1,5; al final será 2,5. El viernes el mercado fue 0 para todos.
- Ronda de mercado = 22,5 × `bench_points` + 7,5 × (nuestro valor creado / el del mejor venue).
- Evidencia: con `bench_points` 0,5 y `mm_points` 0 nuestra tabla subió de 4,8 a 7,5 (ticks 220–330, la ronda "crece"), es decir 11,25 de ronda / 1,5. Con `mm_points` 1,6 pasó a 11,84 y a 12,5 al ser el mejor venue: (11,25 + 7,5) / 1,5 = 12,5. Bajó a 12,06 cuando otro venue nos superó en valor creado.
- Los 11 equipos sin tratos en su venue (puestos `auto` y mercados `board` de t04 y t01) marcan 7,5 exactos; los que marcan más tienen tratos reales (t06, t09, t14, t17, t16, t08). No hay ningún indicio de un venue por encima del puesto gratuito. Por debajo sí: t03 5,86 y t13 6,65.
- "Mean of the top three": si nadie supera al puesto, la media de los tres mejores es el propio puesto y todos quedan en 0,5. Hipótesis (no verificada): entre puesto (0,5) y media del top 3 (1,0) la escala es lineal; un solo venue por encima, aunque sea por poco, tendría los otros dos del top 3 al nivel del puesto y cobraría 1,0 o casi.

### Qué valdría superar al puesto
| Sesiones superadas | Ronda | Tabla final |
|---|---|---|
| El test de esta noche (1 de 6 del sábado; 8 si cuentan los dos de mañana antes de la ronda 3) | +1,9 (o +1,4) | +0,75 (o +0,56) |
| Las 3 del domingo en ronda 3 (h17, h19, h21) | +11,25 | +4,5 |
Con la hipótesis lineal da igual superarlo un 1 %, 3 % o 5 %: basta estar por encima. Si la escala fuera proporcional a la eficiencia, un 1–5 % daría solo +0,05 a +0,25 de tabla.

### ¿Se puede superar?
- El puesto `auto` cruza todos los pares cruzados cada tick (RULES: "the engine crosses every pair first"), no uno solo. No hay ventaja por casar varios.
- El precio del emparejamiento no cambia la ganancia medida (límite del comprador − límite del vendedor) y el servidor solo acepta precio entre ask y bid: un par no cruzado (79/80) se rechaza (2 sondas rechazadas en b7).
- El libro del broker trae por orden: id, precio y `expires_tick`. No trae límites. La salida ya es conocida y el oráculo con salidas no gana (`headroom.py`).
- En las 5 sesiones reales (b7, b25, b43, b60, b78) casamos exactamente lo que el puesto: 0,892 / 0,931 / 0,797 / 0,926 / 0,883 en replay.
- **Única rendija medida:** en el perfil "hard" del simulador nuestro motor supera al puesto (0,863 frente a 0,847). El primer test del domingo es "The hard Market Test: firmer and more impatient traders", 12 traders (h14,65). No hay ningún test hard real grabado.
- Conclusión: no hay vía segura. Mantener `matcher: engine` (no pasar a `stall`) para el test hard y medir; no construir nada esta noche.

## B. Escalera de dealers

### Valor en tabla
- La escalera se reinicia por ronda (tick 160: 0,068 → 0).
- 1,0 de `ladder_points` ≈ 12 de tabla hoy (≈ 18 de ronda; ≈ 7,2 de tabla final). Medido: +0,047 → +0,59 (t970); +0,105 → +1,33 (t1030); +0,108 → +1,29 (t1090–1170).
- Peso por hueco = nivel / 15 / 3 × captura; captura = parte del rango apertura→límite del dealer. Cuadra con MAL-09 (57 desde 73: +0,047) y RET-10 (53: +0,059) si el límite de Los Pícaros es ~43.

| Hueco | Escalera máx. | Tabla hoy | Tabla final |
|---|---|---|---|
| L1 | 0,022 | 0,27 | 0,16 |
| L2 | 0,044 | 0,53 | 0,32 |
| L3 | 0,067 | 0,80 | 0,48 |
| L4 | 0,089 | 1,07 | 0,64 |
| L5 | 0,111 | 1,33 | 0,80 |
Comparación: un trato con equipo al tope (+50 `neg_points`) ≈ 2,3 de tabla hoy, 1,4 final.

### Opciones
- **L2 con El Chato (1 de 3):** solo hay un trato que gane valor: venderle la MAL-06 repetida (él paga 13–17; nos vale 3,2). Da como mucho +0,3–0,5 hoy; vendida a un equipo a 28 da +1,1. Sus raras (77–97) y poco comunes (33) cuestan más de lo que nos valen: pérdida entera.
- **L5, legendaria de Don Ernesto:** LAV-12 nos vale 720; a ~500 (abre 761) gana valor y captura ~0,9 → ~+1,2 hoy (0,7 final) por 500 P. Un trato de épica con equipo da el doble por un tercio de la caja.
- **Sobre de oro (~380):** 2 poco comunes + 2 raras + épica 85 % / legendaria 15 %; libro esperado 410,5, para nosotros bastante menos (muchas saldrían repetidas de LAV/MAL/RET). "Pack luck never counts": no se sabe cómo valora el marcador el sobre; riesgo de pérdida entera. No.

### Orden recomendado
1. Tratos con equipos de ganancia ≥ 50 (MAL-11, LAV-11, SAL-11, repes vendidas caras).
2. Duelos II.
3. Con la caja que sobre y si los tratos con equipos no salen: LAV-12 a Don Ernesto ≤ 500 (requiere subir el tope por trato a ~510; decisión de Ángel).
4. Mañana, ronda 3: escalera a cero, 15 huecos; los de L4/L5 con compras que ganen valor.

## Calendario (de `/api/schedule`, horas de juego)
h13,0 Market Test · h13,37 cierre sábado / abre domingo 09:00 con ticks de 15 s · h14,65 test hard · h15,0 test · **h16,65 ronda 3 + Chamberí** · h16,7 +150 P · h17,0 test · h18,65 Duelos III (12 ticks, decay 0,10, 4 a la vez) · h19,0 test · h21,0 test · h21,65 cierran los 5 dealers + Grand Final · h22,65 congelación.
El brief pone "Sun 09:00: +150, Don Ernesto opens to every team, a new round"; el calendario del servidor pone la ronda 3 en h16,65 (≈10:38 con ticks de 15 s y sin pausas). Si manda el servidor, la ronda 2 sigue mañana de 09:00 a ~10:38, con sus dos tests.

## Sin verificar
- La forma de la escala entre 0,5 y 1,0 y si se aplica por sesión o sobre la media de la ronda.
- Que el perfil "hard" real se parezca al del simulador.
- Que 1,0 de escalera valga lo mismo cuando cambie el mejor equipo (la tabla es relativa).
- El límite de Don Ernesto y cómo puntúa un sobre.
- Qué hora de reloj tendrá cada hora de juego el domingo (pausas, duración del tick).
