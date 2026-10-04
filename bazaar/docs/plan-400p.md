# Plan para los 400 P extra (tick 1201, reloj pausado, sábado 20:30)

Estado: 1.º con 33,98 (negociación 21,48, mercado 12,5). Caja 173 P. Páginas LAV, MAL, RET completas y protegidas. SAL 4/10. Nivel 5.

## 1. El anuncio

- **Hecho:** el admin pausó el reloj en el tick 1201 con el aviso "Announcement at the front: Payday, tips, and a congratulation".
- **Sin confirmar en datos:** la cifra de 400 P. `/api/schedule` no tiene ningún `grant_all` nuevo (solo el de 150 P del domingo en h16,7) y nuestra caja sigue en 173. La cifra viene de Ángel, en la sala. Se sabrá al reanudar.
- Caja y cartas pasaron del viernes al sábado, así que la caja pasa de ronda (hecho medido una vez).

## 2. Qué puntúa (medido hoy)

| Gasto | Efecto medido | Puntos de tabla |
|---|---|---|
| Trato con un EQUIPO ganando valor (a nuestros valores) | `neg_points` sube la ganancia, con tope de +50 por trato (RET-03: ganaba 69,9, sumó 50) | +50 ≈ **+1,5 a +2,3** |
| Compra a DEALER ganando valor | 0 `neg_points`; solo escalera (MAL-09, RET-09/10, 19 casos) | escalera: ~0,05–0,1 por hueco bueno |
| Trato con DEALER perdiendo valor | resta (nosotros −7,3; Team 16 vendió SAL-11 a Don Ernesto a 116 y su negociación cayó de 19,82 a 14,22) | negativo, puede ser enorme |
| Denuncia correcta | +10 `neg_points`, tope 3 | +0,46 a +0,88 cada una |
| Escalera completa | `ladder_points` 0,149 → 0,432 en la tarde | ~5–9 de tabla por punto de escalera; todo lo nuestro ≈ 2–4 |
| Hueco L5 (Don Ernesto) | Team 8 le vendió LAV-11 a 120: +0,10 | casi nada |
| Páginas, álbum, valor de las cartas en mano | no puntúan por sí mismos | 0 |

Conclusión: **el dinero solo puntúa de verdad si pasa por un trato con un equipo con ganancia grande para nosotros.** Las páginas solo importan por el bono de la última carta si se compra a un equipo.

## 3. Valores exactos para nosotros (`/api/me/value`)

| Carta | Nos vale | Dónde está | Precio visto |
|---|---|---|---|
| LAV-11 (épica) | 288 | Los Pícaros (2 de 9 acuñadas, las dos ya en manos de dealers) | 147 a Team 8 |
| MAL-11 (épica) | 234 | **Team 8 la tiene** (comprada a 128 en t1116) | 128 |
| RET-11 (épica) | 198 | Los Pícaros (0 de 9) | — |
| SAL-11 (épica) | 162 | Team 18 la vende a 245 | 139–146 |
| LAV-12 / MAL-12 / RET-12 (legendarias) | 720 / 585 / 495 | Don Ernesto, lista 585, abre 761 | ninguna vendida |
| SAL-09, SAL-10 | 63 | Los Pícaros 54–57 | — |
| SAL-06/07/08 | 22,5 | Abuela pide 25–26 | — |
| SAL-05 (con 9/10: ~9 + bono ~60) | 9 hoy | equipos | — |
| Chamberí común / poco común / rara | 7 / 17,5 / 49 | dealers a 10 / 25 / ~55 (por encima de valor: restaría) | — |
| Segunda copia: RET-09 19, LAV-10 28, MAL-10 23, RET-03 1,1, MAL-06 3,2 | | | |

Tiradas: épicas 9, legendarias 3. No se ha abierto ningún sobre de oro (contenido desconocido).

## 4. Opciones, de más a menos puntos por P

| # | Opción | Coste | `neg_points` | Tabla (estimado) | Riesgo / urgencia | Choca con |
|---|---|---|---|---|---|---|
| 1 | Vender la RET-03 repetida (asset 1062) a un equipo que monta El Retiro (Team 7 compró RET-09 a 66 y RET-10 a 77; Team 13, Team 16) a 45–55 | ingresa ~50 | +42 a +50 | +1,3 a +2,3 | nunca a Team 6; hay que desproteger esa copia | protección en control |
| 2 | Comprar MAL-11 a Team 8 con oferta dirigida en El Rastro a 165 (máx. 184) | ≤184 | +50 | +1,5 a +2,3 | urgente: puede venderla a un dealer | tope por trato 120 |
| 3 | Puja pública en El Rastro por LAV-11 a 205 (cualquier equipo la compra a Los Pícaros a ~140 y gana ~55 P) | 205 | +50 | +1,5 a +2,3 | quedan 7; con 400 P todos pueden ir a por épicas; necesita que un equipo la sirva | tope por trato 120 |
| 4 | Última carta de Salamanca (SAL-05) a un equipo a ≤18, tras comprar las otras cinco | ~175 en total | +50 | +1,5 a +2,3 | necesita vendedor; las cinco primeras no puntúan | — |
| 5 | Vender la MAL-06 repetida (asset 1124) a un equipo a ~28 | ingresa 28 | +20 a +25 | +0,6 a +1,1 | bajo | — |
| 6 | Reventa dealer → equipo: rara de Salamanca a Los Pícaros a 54 (no resta: nos vale 63) y venta a un equipo a 75–84 | 54, vuelve con +25 | +12 a +21 | +0,4 a +1,0 | solo con puja de equipo a la vista; hoy no hay ninguna por Salamanca | — |
| 7 | Puja pública por RET-11 a 148 | 148 | +50 | +1,5 a +2,3 | margen mínimo para quien la sirva (Pícaros 128–147) | tope por trato |
| 8 | Dos huecos de El Chato (L2) | ~50 | 0 | +0,15 a +0,25 cada uno | solo con ganancia de valor | — |
| — | Don Ernesto (L5), sobre de oro, legendaria, épica comprada directamente a Los Pícaros, Chamberí a precio de dealer | 140–600 | 0 o negativo | ≤ +0,1 | **no hacer** | — |

## 5. Reparto propuesto de ~573 P

**Esta noche (ronda 2), en este orden al reanudar:**
1. Oferta dirigida a Team 8 por MAL-11: 165 P (subir hasta 184).
2. RET-03 repetida a Team 7 a 52 P (después Team 13 / Team 16; nunca Team 6).
3. Puja pública por LAV-11 a 205 P; pedir por WhatsApp a un equipo de media tabla que la sirva.
4. MAL-06 repetida a ~28 P a un equipo.
5. Desde el tick 1235 solo duelos (Duelos II siguen siendo la mayor bolsa de puntos).
6. Tras los duelos: SAL-09 y SAL-10 a Los Pícaros (≤57) y las poco comunes de Salamanca solo a ≤21.

Gasto máximo esta noche: ~184 + 205 + ~115 = ~505; ingresos ~80.

**Mañana 09:00 a ≈10:20 (sigue la ronda 2):** terminar Salamanca hasta 9/10 sin la última; mantener la puja de LAV-11 si no se sirvió.

**Ronda 3 (desde ≈10:20, 150 P más):** SAL-05 a un equipo (≤18) para que el +50 caiga en la ronda nueva; segunda épica por puja (RET-11 a 148 o MAL-11 si falló con Team 8); una denuncia de prueba; Chamberí solo comprando a equipos por debajo de valor.

## 6. Efecto de que todos reciban 400 P

- Las épicas de Los Pícaros se agotarán (9 por set); los equipos que las compren y no las quieran son nuestros vendedores.
- Los equipos pagarán más por raras: poner en venta lo que nos vale poco (repes) y vigilar pujas ≥75 por raras para la reventa.
- Nuestro mercado v07: anuncio al reanudar ("0 % frente al 5 % + 1 P de El Rastro en tratos de épicas y raras"); el valor creado ahí es nuestro `mm_points`.

## 7. Decisiones de Ángel

1. **Subir topes:** `max_spend_per_deal` de 120 a 210 y `max_spend_per_hour` de 250 a 550 (los actuales son los de `config.py`; control no los fija).
2. **Desproteger la RET-03 repetida** (asset 1062) para venderla a Team 7 / 13 / 16, manteniendo protegida la 627.
3. **Repartir épicas entre rondas:** MAL-11 y LAV-11 esta noche, o guardar una para la ronda 3.

## 8. Hechos frente a estimaciones

- Hechos: valores exactos, tope +50 por trato, 0 por dealers, resta por pérdida, tiradas, quién tiene MAL-11, precios vistos, calendario.
- Estimaciones: 400 P; conversión a tabla (0,03–0,046 por `neg_point`, la tabla es relativa); que Team 8 venda; que alguien sirva la puja de LAV-11; que Team 7 quiera RET-03; cómo convierte la ronda 3.
- Sin comprobar: si una puja pública bloquea la caja; el valor exacto de la copia de RET-03 al venderla; si el tope de +50 se aplica también a la venta.
