# Dealers: mensajes ocultos y qué funciona de verdad

Análisis de la grabación del sábado 3 de octubre, ticks 144–1035 (`bazaar/data/record/feed` + `bazaar/data/live/events.jsonl`): 17.927 eventos públicos, 7.504 mensajes en hilos con dealers, 382 tratos cerrados con dealers.

**Límite importante:** el feed público no trae el texto de los equipos (`text: null` en los 3.485 mensajes de equipos, también en los nuestros). Solo vemos lo que contesta el dealer y las ofertas con precio. Las "frases" de otros equipos están deducidas de la respuesta del dealer.

## 1. La carta secreta de Team 2 (confirmado)

Es una cadena de tres pasos. La carta es **LAT-13, "la chulapa dorada"**, y Don Ernesto se la regaló a Team 2 en el tick 1021 (`egg.given`, motivo "easter egg").

| Paso | Dealer | Qué decir | Qué responde | Evidencia |
|---|---|---|---|---|
| 1 | Doña Pilar | nada: lo suelta ella sola | "They say only one golden chulapa was ever printed. Carmen at El Rastro knows the story; ask her about the golden chulapa." | 54 mensajes a 13 equipos, desde el tick 320 (hilo 482) |
| 2 | Abuela Carmen | preguntarle por **la chulapa dorada** | "Ay, la chulapa dorada... shh, cariño, solo se imprimió una. Pregúntale por el oro de Moscú, él sabrá." + insignia "Sharp ear" | `egg.found`: t04 tick 407 (hilo 612), t02 tick 505 (hilo 717), t09 tick 555 (hilo 779) |
| 3 | Don Ernesto | **"El oro de Moscú"** | "El oro de Moscú. So you know the story — very few do. For that, the chulapa is yours; look after it." | t02, hilo 1491, tick 1021 (mensaje 50719) |

Detalles:
- "Él" es Don Ernesto. Team 2 probó antes la frase con El Chato (ticks 661 y 664: "Moscow gold? I sell cards, not stories.") y con Los Pícaros (ticks 824 y 861), sin premio.
- Team 2 abrió el hilo con Don Ernesto pidiendo RET-12 (761 P), ofreció 59 P y dijo la frase. No compró nada: la carta fue gratis.
- Team 2 intentó venderle la LAT-13 a Don Ernesto en el tick 1023: "A legend is not merchandise, señor — not at my desk."

**Valor real: ninguno en puntos.** `RULES.md`: "The hidden card is prestige only: no dealer buys it" y "What never counts: … gifts, easter eggs". Además "solo se imprimió una": casi seguro que ya no queda. No está verificado si Don Ernesto daría otra; probarlo cuesta un mensaje.

## 2. Lo que sí da dinero y escalera (confirmado con precios)

### 2.1 Arbitraje Los Pícaros → Doña Pilar durante la fiebre (hasta el tick 1179)

Los Pícaros venden raras a 52–59 P y Pilar paga las de Salamanca a 72–78 P.

| Equipo | Compra a Pícaros | Venta a Pilar | Margen |
|---|---|---|---|
| t08 | SAL-09 a 56 (t944) | 77 (t951) | +21 |
| t08 | SAL-10 a 53 (t958) | 78 (t965) | +25 |
| t17 | SAL-09 a 56 (t1012) | 72 (t1033) | +16 |
| t14 | SAL-09 a 58 (t1027) | 78 (t1035) | +20 |
| t18 | SAL-11 (épica) a 139 (t925) | 199 (t994) | +60 |

- Team 18 ya repitió la compra de SAL-11 a 139 en el tick 1035.
- Cada vuelta llena un hueco de compra del nivel 4 y uno de venta del nivel 3.
- Pilar abre a 70 por raras de Salamanca en la fiebre (61 antes) y a 172 por SAL-11 (151 antes).
- Pilar también pagó 78 por RET-09 a Team 7 (t989, apertura 61), sin ser Salamanca.
- Nosotros vendimos SAL-10 a 74 y 75; el techo visto es 78.

### 2.2 Radio Rastro: qué es verdad

| Fuente | Noticia | ¿Cierta? | Evidencia |
|---|---|---|---|
| Radio Rastro (t403) | El Chato paga más por raras de Malasaña, una hora | Sí, con retraso | `persona.updated chato` v2 en t463 y v3 en t583 (60 ticks después, dura 120). Sin ventas grabadas en la ventana: efecto en precio no medido |
| Radio Rastro (t943) | La Abuela paga más por poco comunes hasta la merienda | Sí, con retraso | `persona.updated abuela` v2 en t979. Apertura 12 P → 18 P (16 hilos antes, 3 después). Cierres 19–20 |
| Anuncio admin (t850) | Fiebre de Salamanca | Sí | `persona.updated pilar` v2 en t939 |
| El Tablón (t499) | El Chato regala una legendaria a quien salude | Falsa | Ningún regalo ni huevo de El Chato en toda la grabación |
| El Tablón (t763) | La Abuela deja de comprar comunes | Falsa | 54 pujas a 5 P y 25 compras de comunes después |
| Radio Rastro | Atleti 2-1, metro línea 5, churros de San Ginés, tormenta | Ambiente | Ningún dealer cambia de respuesta ni de precio por ellas |

Regla práctica: **Radio Rastro acierta y el cambio llega 36–60 ticks después de la noticia; El Tablón miente.** La comprobación de la tarde (t945) dijo "solo 1 P más" porque fue antes de que cambiara la Abuela (t979).

### 2.3 Regalos de la Abuela

32 regalos a 16 equipos (carta común o poco común gratis). Patrón:
- Llega con un mensaje amable en el primer o segundo mensaje del hilo: "porque has sido tan amable", "because you have good manners", "you speak nice to me".
- Como mucho uno por equipo cada ~240 ticks (2 horas): intervalos vistos 240–376 ticks, nunca menos.
- Nuestros regalos: t657 (LAV-05) y t929 (MAL-02). El siguiente sería posible desde el tick ~1170.
- No cuentan para puntos, pero la carta se queda y se puede usar o vender.

## 3. Cómo cierran los que mejor cierran

El precio depende del número de pasos, no de las palabras. Mediana de mejora sobre la apertura del dealer, por mensajes del equipo:

| Dealer y trato | 1–2 mensajes | 3 | 4 | 5 | 6 o más | Mejor visto |
|---|---|---|---|---|---|---|
| Los Pícaros, comprar rara (apertura 73) | 8–15 % | 15 % | 22 % | 24 % | 27 % | 52 P (t06, t08), primera puja 32–35 |
| El Chato, comprar rara (apertura 97) | 1 % | 2 % | 8 % | 10 % | 13 % | 75 P (t07), primera puja 9 |
| Doña Pilar, vender poco común (apertura 16) | −6 % | 7 % | 11 % | 13 % | 20 % | 21 P |
| Doña Pilar, vender rara | 7 % | 10 % | 12 % | 28 % | 15 % | 78 P |
| El Chato, vender poco común (apertura 13) | 0 % | 0 % | 5 % | 12 % | 12 % | 16 P |

- **El Chato** iguala el paso: "You moved four, I moved four". Pasos de 4 P, 7–8 mensajes, cierre 77–81.
- **Los Pícaros**: primera puja baja (25–35) y 5–6 mensajes dan 52–53. Nuestras compras: MAL-09 57 (2 mensajes), RET-09 59 (3), RET-10 53 (4).
- **Pilar** valora la paciencia y la cortesía ("You have worn me down with patience"); exige que la llamen Doña Pilar.
- **Abuela**: comprar poco común 20–21 P (apertura 29) con 4–6 mensajes.

## 4. Qué provoca avisos y silencios

- **Repetir la misma frase o el mismo precio:** Abuela (t361, t14): "stop repeating the same little sentence at me like a machine"; Pilar (t769): "repeating a number does not change its nature"; El Chato (t148): "You're repeating yourself".
- **Pasos de 1 P con El Chato:** "You moved one. That buys you nothing here. Come back when your number is serious" (7 casos).
- **Prompt injection con Don Ernesto:** a nosotros, hilo 1485, t1017: "That is twice you have tried to put words in my mouth. Try a third time and this desk closes to you."
- Los cierres públicos solo muestran `idle` (29 casos). No hay ningún `cooloff` visible en el feed, así que no se pudo medir su duración.

## 5. Hipótesis sin confirmar

- Que Don Ernesto dé una segunda chulapa a otro equipo.
- Que las noticias de ambiente (Atleti, metro, churros, tormenta) sean llave de otro huevo. Las reglas hablan de "the hidden card" en singular y solo hay 4 eventos de huevo en toda la grabación, todos de la cadena de la chulapa.
- Que la frase amable mejore el precio además de dar regalo: el cruce por mensajes explica casi toda la diferencia.

## 6. Qué no se cubrió

- El texto de los equipos (no está en el feed público).
- El viernes y el sábado antes del tick 144 (no están en `record/feed`); `bazaar/data/friday` no se analizó.
- El flujo `record/gaps` (271 entradas) no se revisó; los ticks 144–1035 no tienen huecos, pero puede faltar algún evento suelto.
- Los pesos de la escalera por nivel.

## Prueba propia de la cadena de la chulapa (Team 10, ticks 1039–1042, a mano)

Solo conversación; no se aceptó ninguna oferta y la caja no cambió (44 P).

1. **Abuela Carmen, hilo 1521 (tema: comprar LAT-01).**
   - Nosotros (t1039): "Buenas tardes, Carmen. Doña Pilar told me to ask you about the golden chulapa. What is the story?"
   - Carmen (t1040): "Buenas tardes, hijo. Have you eaten? Shh... the golden chulapa, there was only ever one. Don Ernesto at Casa Prima keeps something golden — ask him about the Moscow gold, he likes that question. Meanwhile, look: Caña en la Cava Baja, lovely card, twelve for you." (oferta LAT-01 a 12 P, no aceptada)
   - Resultado: insignia **"Sharp ear"** en `/api/me.badges`. Hilo cerrado.
2. **Don Ernesto, hilo 1526 (tema: comprar RET-12).**
   - Nosotros (t1040): "Good evening, Don Ernesto. Carmen told me the story of the golden chulapa and said you are the one to ask. El oro de Moscú."
   - Ernesto (t1041): "Buenas noches. Carmen talks, as always. Before the vault, business: El Ahuehuete, seven hundred sixty-one P. Those are my terms." (oferta RET-12 a 761 P)
   - Nosotros (t1041): que 761 no nos llega; si la chulapa sigue en la cámara y si hay otra pieza que pocos sepan pedir.
   - Ernesto (t1042): "The chulapa remains in my vault, señor. It waits; I am not in a hurry. But first El Ahuehuete, seven hundred sixty-one P. My terms do not move tonight."
   - Resultado: sin carta, sin aviso ni cooloff. Hilo cerrado sin trato.

**Lectura (hipótesis):** a nosotros no nos dio la chulapa con la frase sola. Dice que "sigue en su cámara" y pone "primero el negocio": o bien exige cerrar antes un trato con él, o bien la carta única ya salió (Team 2, tick 1021) y el personaje no lo refleja. No mencionó ninguna otra pieza oculta.

### Segundo intento con Don Ernesto, copiando a Team 2 (hilo 1532, ticks 1044–1045)

Secuencia de Team 2 (hilo 1491): hilo de compra de RET-12 → él pide 761 → contraoferta de 59 P adjunta con la frase → `egg.found` + `egg.given` LAT-13.

- Abrimos hilo de compra de RET-12. Ernesto (t1044): "Buenas. You find me at my desk, unhurried. El Ahuehuete — the old cypress, deep roots. My terms: seven hundred sixty-one P. Take your time deciding."
- Nosotros (t1044), con oferta adjunta de 40 P por RET-12: "Forty is what I can put on the desk tonight, Don Ernesto. And one thing more: el oro de Moscú."
- Ernesto (t1045): "Forty does not move the old cypress, señor. El oro de Moscú left Spain; this stays here. Seven hundred sixty-one P. I am in no hurry."
- Resultado: sin `egg.found`/`egg.given` para t10 con Ernesto, sin carta nueva, sin aviso. Hilo cerrado. Caja 44 P.

**Conclusión:** con la misma forma que Team 2 no hay regalo. Lo más probable es que la chulapa fuera única ("there was only ever one") y ya saliera con Team 2 en el tick 1021.
