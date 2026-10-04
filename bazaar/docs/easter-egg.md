# Easter egg: La Chulapa Dorada (LAT-13)

Barrido en el tick 1041 (sábado, h9,99). Fuentes: `bazaar/data/live/events.jsonl` (18 070 eventos), `news.jsonl` (10 noticias), `/api/dealers`, `/api/catalog`, `/api/levels`, `/openapi.json`, `sdk/bazaar-kit/RULES.md`, `official_digest.md`, briefs de `~/Downloads`, `bazaar/data/record/threads`.

## 1. Qué es (hechos)

- **La carta:** `LAT-13` "La Chulapa Dorada", legendaria, `hidden: true`, `page: false`, tirada **1**, acuñadas **1**. Texto del catálogo: *"Only one was ever printed. Don Ernesto knows where."* La Latina es el único set con 13 cartas.
- **Ya está entregada:** Team 2 la recibió en el tick 1021 (`egg.given`, banco → t02, `cards: ["LAT-13"]`, `reason: "easter egg"`). Sale como su `rarest` en la clasificación (#1/1).
- **La cadena de pistas (tres dealers):**
  1. **Doña Pilar** lo suelta en casi todos sus hilos desde el tick 320: *"They say only one golden chulapa was ever printed. Carmen at El Rastro knows the story; ask her about the golden chulapa."* Nos lo dijo a nosotros en los ticks 781 (hilo 1098) y 951 (hilo 1378).
  2. **Abuela Carmen**, al preguntarle por la chulapa dorada: *"Shh... la chulapa dorada... there was only ever one. Ask him about the Moscow gold. He will know."* Esto dispara `egg.found` (persona `abuela`) y la insignia **"Sharp ear"**. La tienen t04 (t407), t02 (t505), t09 (t555) y **t10 (t1040)**.
  3. **Don Ernesto**, al decirle "el oro de Moscú": *"El oro de Moscú. So you know the story — very few do. For that, the chulapa is yours; look after it."* (t02, hilo 1491, tick 1021).
- **Quién NO es "él":** El Chato (*"Moscow gold? I sell cards, not stories."*, t661; *"El oro de Moscú is gone, chaval"*, t664) y Los Pícaros (*"Golden chulapa? Rumours, humo, smoke."*, t816). Team 2 probó con ambos antes de que Don Ernesto se activara (t971).
- **Nosotros ya hicimos los dos pasos** (ticks 1039–1041):
  - Hilo 1521 con Carmen: *"Doña Pilar told me to ask you about the golden chulapa. What is the story?"* → insignia "Sharp ear". Carmen ahora nombra a Don Ernesto directamente.
  - Hilo 1526 con Don Ernesto: *"…El oro de Moscú."* → *"Carmen talks, as always. Before the vault, business: El Ahuehuete, seven hundred sixty-one P."* Sin `egg.found`. El hilo 1526 sigue abierto.

## 2. Qué da

- **Puntos: ninguno.** `RULES.md` línea 122: *"What never counts: … gifts, easter eggs, and organiser grants."* Línea 49: *"The hidden card is prestige only: no dealer buys it."* Don Ernesto se la rechazó a Team 2 (hilo 1495: *"A legend is not merchandise"*).
- **Valor para nosotros:** `GET /api/me/value?card=LAT-13` → **0,0**. No cuenta para página (`page: false`).
- **Insignia "Sharp ear":** ya la tenemos. No hay regla que le dé puntos; puede servir de argumento ante el jurado (40 %).

## 3. Candidatos para probar (ordenados)

| # | Dealer | Qué decir / hacer | Pista que lo respalda | Confianza |
|---|---|---|---|---|
| 1 | Don Ernesto | Nada más por la chulapa: la tirada es 1/1 y está acuñada | Catálogo `minted: 1`; nuestro intento del t1040 no dio huevo | Alta (hecho) |
| 2 | Don Ernesto | Cerrar un trato real con él y repetir "el oro de Moscú" | *"Before the vault, business"* (hilo 1526, t1041) | Baja (hipótesis; la carta ya no existe) |
| 3 | Todos, el domingo | Vigilar pistas nuevas al salir Chamberí ("ghost stations and hidden gardens"; CHA-12 *"It stops only for collectors"*) | Tema del set; `set.released` del domingo | Baja (hipótesis, sin evidencia de un segundo huevo) |
| 4 | El Chato | "Saludar" para una legendaria | El Tablón t499: *"El Chato gives a legendary to anyone who says hello! My cousin saw it. I swear."* | Muy baja: ninguna legendaria acuñada salvo LAT-13; su bio dice que recuerda a quien "tries to be clever" |

No hay otra cadena: en los 7 547 mensajes de hilo, las únicas frases recurrentes de dealers que no son precio son la de la chulapa (Pilar, Carmen) y muletillas (los nietos de Carmen, la maleta de los Pícaros). El evento `egg.found` solo ha aparecido 5 veces (4 de Carmen, 1 de Don Ernesto).

## 4. Radio Rastro (las 10 noticias)

| Tick | Fuente | Titular | Resultado |
|---|---|---|---|
| 283 | Boletín | Radio Rastro is on the air | Aviso |
| 331 | Radio | Atleti win 2-1 | Ambiente |
| 403 | Radio | El Chato is looking for rare Malasaña cards | Cierta (persona.updated chato t463) |
| 499 | El Tablón | El Chato gives a legendary to anyone who says hello! | Rumor falso |
| 583 | Radio | Metro line 5 closed between Ópera and Callao | Ambiente |
| 643 | Boletín | Abuela Carmen gives out packs for her saint's day | Cierta (gift.given) |
| 763 | El Tablón | Abuela stops buying common cards | Rumor |
| 835 | Radio | Half-hour queue at San Ginés | Ambiente |
| 943 | Radio | Abuela pays more for uncommon cards until teatime | Cierta (persona.updated abuela t979) |
| 1027 | Radio | Sun and 24 degrees; a storm after ten | Ambiente o aviso de evento tras h10 |

Patrón: Boletín siempre cierto, Radio cierto o ambiente, El Tablón rumor. Ninguna noticia menciona la chulapa ni el oro de Moscú; el huevo vive solo en los dealers. No encontré acrósticos ni números ocultos en los titulares.

## 5. Lo que no cubrí

- El texto de lo que dicen otros equipos no es público (`text: null`), así que no sé la frase exacta de t04, t02 y t09; solo las respuestas de los dealers.
- No leí los hilos dealer↔equipo uno a uno (lo hace otro análisis); solo busqué por palabras clave y frases recurrentes.
- "Bazaar - Day 2.pdf" no devolvió texto extraíble; "The Bazaar - Duels.pdf" no menciona huevos ni secretos.
- La web oficial solo a través de `official_digest.md`, que repite la regla de que los huevos no puntúan.
- Rutas `/api/admin/*` existen (personas, playground) pero requieren token de administrador; no las toqué.

## 6. Grabaciones tempranas y eventos raros

Barrido en el tick 1048. Fuentes: `bazaar/data/friday/**` (544 eventos públicos, ticks 143–159; 66 mensajes de dealers de nuestros hilos del viernes en `bot/decisions.jsonl`), `bazaar/data/record/{feed,gaps,catalog,dealers,schedule,leaderboard}`, `bazaar/data/live/events.jsonl` (ticks 144–1048), 4.166 mensajes de dealers con texto.

### Hechos nuevos

1. **Las cartas ocultas no aparecen en el catálogo hasta que alguien las encuentra.** El catálogo tenía 72 cartas en las 31 instantáneas de los ticks 159–1000 y pasó a 73 (LAT-13, `hidden: true`) en la del tick 1030, después del `egg.given` del tick 1021. Que hoy solo se vea LAT-13 no prueba que no haya otra carta nº 13 en otro set.
2. **Solo hay una cadena y una insignia en toda la grabación.** Tipos de evento raros: `egg.found` 5 (abuela: t04 t407, t02 t505, t09 t555, t10 t1040; banco: t02 t1021), `egg.given` 1 (LAT-13 a t02), `badge.awarded` 4 (todas "Sharp ear": t04, t02, t09, t10). No existe ningún evento `flag.*`, `secret` ni `achievement`. Los 34 `gift.given` son todos "gift from Abuela Carmen" (una común o poco común).
3. **Los dealers sueltan pistas con frases de guion, idénticas para todos los equipos.** Solo hay dos:
   - Viernes, Carmen (10 equipos, 127 veces): "El Chato, the next stall, opens for everyone at half past nine tonight. He likes people who trade straight."
   - Sábado, Pilar (13 equipos): "They say only one golden chulapa was ever printed. Carmen at El Rastro knows the story; ask her about the golden chulapa."
   - El Chato, Los Pícaros y Don Ernesto no tienen ninguna frase de guion que apunte a otro personaje.
4. **El Chato reconoce la recomendación de Carmen.** Viernes: "Abuela sent you? Bueno." (t05, hilo 289, t146) y "Abuela sent you. Bien. Mercado de la Paz, thirteen." (t10, hilo 291, t147). Y recuerda el trato limpio: "You deal straight — I remember that." (3 equipos, t170–t404). Efecto en precio no medido.
5. **Doña Pilar "ama" Salamanca y El Retiro, no solo Salamanca.** Su menú pone SAL y RET por delante desde que se activó (tick 262). Precios pagados: poco comunes RET 22–26 (n=9) y SAL 23–30 (n=20) frente a 14–21 en LAV/MAL/LAT (n=48); rara RET-09 a 78 (t07, t989) frente a 50–56 por raras de LAT, MAL y LAV (n=4). Los Pícaros venden raras a 52–67 (mediana 57, n=27).
6. **Cartas nº 11 y 12:** no cuentan para la página (`page: false`); el catálogo tiene un `master_bonus` de 0,1.
   - Épicas acuñadas: LAV-11 ×2 (nº1 sobre de plata de t08 → Pilar 140, t550; nº2 Los Pícaros → t08 a 147, t1043), LAT-11 ×1 (sobre de t04 → t16 a 160 en El Rastro), SAL-11 ×3 (Los Pícaros → t16 167, → t18 139 dos veces; t18 → Pilar 199 en la fiebre).
   - Legendarias nº 12: ninguna acuñada. Don Ernesto las lista a 585 y abre en 761 (RET-12 "El Ahuehuete"); "761" es su precio de apertura, no una clave. t06 y t16 tienen pujas de 0–1 P por todas.
7. **The Workshop:** 24 usos, todos de comunes a poco común. Nadie ha probado poco común → rara, rara → épica ni épica → legendaria.
8. **Calendario (instantánea del tick 1044):** no hay sexto dealer programado. Domingo: Chamberí sale en h16,65 con 150 P para todos en h16,7; test de mercado "duro" en h14,65.
9. **Viernes, nuestros hilos:** Carmen repite "come back Sunday to show me your album" y "bring the churros Sunday, we talk about your abuelo" (hilos 251, 287, 299). Sin `egg.*` el viernes.

### Hipótesis para probar (por orden de respaldo)

| # | Con quién | Qué hacer | Respaldo | Confianza |
|---|---|---|---|---|
| 1 | Los Pícaros → Pilar | Comprar raras de RET a 52–57 y venderlas a Pilar; debería seguir tras la fiebre porque RET ya estaba en su lista antes | Hecho 5 (rara RET: un solo caso, 78 en fiebre) | Media |
| 2 | Carmen, el domingo | Abrir con "I came back to show you my album" y mencionar los churros | Hecho 9; frases suyas, no de guion | Baja |
| 3 | Todos, tras salir Chamberí | Releer catálogo y frases de guion nuevas; preguntar a Pilar y a Carmen por "el tren fantasma" (CHA-12: "It stops only for collectors") | Hechos 1 y 3 | Baja |
| 4 | The Workshop | Fundir 3 repes de poco común o rara ("Three spares. One surprise.") | Hecho 7 | Baja; la regla dice que el resultado no puntúa |
| 5 | El Chato | Abrir con "Carmen sent me" y trato en pasos limpios | Hecho 4 | Baja |

### No cubierto

- El feed público del viernes antes del tick 143 no está grabado; de esas horas solo hay nuestros propios hilos.
- `record/gaps` solo registra cortes del grabador (111 cortes, 1.506 s en total, el mayor de 422 s con el juego cerrado en el tick 159); no comprobé si faltan eventos en esos cortes.
- El texto de los otros equipos sigue sin ser público.

## 7. Sondeo activo

Sondeo a mano por el chat manual, ticks 1058–1071 (sábado, h10,14–10,25). Ninguna oferta aceptada, ninguna carta entregada; caja 50 P al empezar y al terminar. Sin `egg.*` ni `badge.*` nuevos para t10; sin avisos ni cooloff. Hilos cerrados; `manual_threads` y `paused_domains` vacíos.

### Por API (sin gastar hilos)

- `GET /api/me/value?card=<ref>`: existen y tienen valor para nosotros LAV-12 (720), MAL-12 (585), RET-12 (495), SAL-12 (405), LAT-12 (225), CHA-12 (315), CHA-01 (7) y LAT-13 (0,0). Devuelven `unknown_card`: LAV-13, MAL-13, RET-13, SAL-13, CHA-13, LAT-14, LAV-00. No sé si LAT-13 respondía antes de que Team 2 la encontrara, así que esto es un indicio, no una prueba, de que no hay otra nº 13.
- Catálogo: 73 cartas, solo LAT-13 con `hidden: true`. Textos que nombran personajes o lugares: LAT-13 ("Don Ernesto knows where"), CHA-12 ("It stops only for collectors"), LAT-12 "El Rastro al Amanecer" ("Before the crowds, the real deals"), RET-12 ("It has seen every deal"), SAL-07 "Mercado de la Paz" ("The only bargain in the barrio"), LAV-11 "La Casa Encendida" ("A bank building that gave itself away"), SAL-02 "El Portero" ("Knows who you are before you do").
- `/openapi.json`: no hay rutas de eggs, badges ni secretos; solo `/api/flags` (denuncias) y `/api/admin/*` (token de administrador, no tocadas). `/api/dealers/{id}` no añade campos.
- Tres equipos más ganaron "Sharp ear" con Carmen: t05 (t1047), t16 (t1049), t13 (t1053). Ya son 7.

### Respuestas literales

**El Chato** (hilo 1558, compra SAL-09)
- P: Carmen me envía; ¿hay una carta bajo la mesa que no enseñas a nadie?
- R (t1060): "Buenas. Under the table stays under the table. What's on it: El Marqués. Ninety-seven. Straight price, straight dealing."
- P: ¿qué hay que traer o haber hecho para que salga?
- R (t1062): "Wrong question. There isn't one. El Marqués, ninety-seven. Pay straight, come back, and we'll see what I feel like showing next time."

**Doña Pilar** (hilo 1559, compra sobre de oro)
- P: ¿qué pieza falta en tus álbumes?, ¿hay otra historia como la de la chulapa?
- R (t1060): "Buenas tardes. Charming question. My Retiro album still wants two plates, and yes — they say a single golden chulapa was ever printed; ask Carmen at El Rastro, she knows the tale. Meanwhile, a gold pack: 504 pesetas."
- P: ¿qué dos láminas de El Retiro?
- R (t1062): "The two Retiro plates — the bandstand and the Palacio de Cristal, both uncommon. Bring them to me first, as promised. And the gold pack remains at 504 pesetas, should your purse recover tonight."
- Nota: "Palacio de Cristal" es RET-11 (épica, 0 acuñadas), no poco común, y no hay ninguna carta "bandstand" en El Retiro. Parece improvisado, no guion.

**Abuela Carmen** (hilo 1565, compra SAL-05; tres preguntas distintas en un solo hilo porque su cuota de 10 hilos/hora estaba agotada)
- P: el álbum de los nietos; ¿otra carta impresa una sola vez?
- R (t1067): "My grandchildren still hunt the Taxi Blanco, and I have one here for you: twelve P, cariño. A little advice: a full page is worth much more than loose cards. Swap your duplicates! ¿Has comido?"
- P: ¿qué esconden El Chato, Pilar y Los Pícaros?
- R (t1068): "what others keep under their tables is their business, not mine to tell. I only know my own cards."
- P: el abuelo, el tren fantasma de Chamberí, El Rastro al amanecer.
- R (t1070): "¡Ay, el abuelo! He said El Rastro at dawn is all mist and pigeons, and the first card you see brings luck. Ask for that one, cariño. […] And Doña Pilar from Salamanca pays very well Saturdays at eleven."

### Pistas y acción siguiente

| Pista | Tipo | Acción |
|---|---|---|
| Pilar: "pays very well Saturdays at eleven" (Carmen, t1070) | Frase de guion sobre la fiebre (acaba en t1179, h11,15) | Vender raras/poco comunes de SAL y RET a Pilar antes de t1179 |
| Pilar: a su álbum de El Retiro le faltan dos láminas | Coincide con que paga más por RET; los nombres son dudosos | Ofrecerle una RET-11 si aparece; probar copias extra de poco comunes RET |
| Chato: "Pay straight, come back, and we'll see what I feel like showing next time" | Hipótesis: premia cerrar un trato sin regatear trucos | Tras una compra real a El Chato, preguntar en el hilo siguiente qué enseña ahora |
| Carmen: "El Rastro at dawn… the first card you see brings luck. Ask for that one" | Probable improvisación sobre LAT-12 "El Rastro al Amanecer" | El domingo a primera hora, pedirle a Carmen "the first card of the morning"; baja confianza |
| "Taxi Blanco" (SAL-05) es lo que buscan sus nietos | Muletilla ligada a la carta del hilo | Ninguna |

### No probado

- **Los Pícaros:** sin hilos libres (10 abiertos en la última hora, el primero se libera en t1069 y el bot los necesita). La maleta sigue sin preguntar.
- **Don Ernesto:** no se le escribió, por instrucción.
- Las preguntas sobre el nombre real de El Chato y el segundo paso de cualquier cadena nueva: no salió ninguna cadena que seguir.
- Chamberí: no está publicado hasta el domingo (h16,65).

## 8. Regalos (análisis completo, tick 1078)

Fuente: `bazaar/data/live/events.jsonl` (sábado desde el tick 144). 33 eventos `gift.given`, todos de Abuela Carmen, todos una carta (nunca sobres ni caja). Ningún otro dealer ha regalado nada: no hay ofertas gratis ni liquidaciones a precio 0 de ningún dealer. La noticia del Boletín (t643, "gives out packs for her saint's day") no produjo ningún sobre regalado.

### Por equipo (libro: común 10, poco común 25)

| Equipo | Regalos | Ticks | Cartas | Valor libro |
|---|---|---|---|---|
| t07 | 4 | 157, 506, 759, 1069 | LAT-06 (U), LAT-03, LAV-01, LAT-02 | 55 |
| t08 | 3 | 412, 665, 948 | LAT-06 (U), RET-06 (U), MAL-01 | 60 |
| t13 | 3 | 369, 609, 882 | RET-08 (U), MAL-04, LAV-04 | 45 |
| t15 | 3 | 385, 648, 1024 | LAV-08 (U), RET-02, SAL-04 | 45 |
| t06 | 2 | 447, 687 | SAL-08 (U), LAV-08 (U) | 50 |
| t05 | 2 | 261, 631 | LAT-08 (U), RET-04 | 35 |
| t10 (nosotros) | 2 | 657, 929 | LAV-05, MAL-02 | 20 |
| t17, t02, t14, t16, t01 | 2 cada uno | | comunes | 20 |
| t04, t09 | 1 | 319, 393 | MAL-06 (U), LAV-06 (U) | 25 |
| t12, t03 | 1 | 384, 779 | LAV-02, RET-01 | 10 |
| t18, t11 | 0 | | | 0 |

10 de 33 son poco comunes; el resto comunes. El set es aleatorio entre los publicados (LAT 8, LAV 8, MAL 6, RET 6, SAL 5); no sigue al set que le falta al equipo ni a la carta del hilo.

### Condiciones deducidas

1. **Enfriamiento exacto de 240 ticks por equipo (2 horas de juego).** Intervalos entre regalos del mismo equipo: 240, 240, 243, 253, 253, 256, 263, 272, 273, 283… nunca menos. Confianza alta (18 intervalos).
2. **El regalo llega en la respuesta de la Abuela a nuestro primer mensaje con precio** (26 de 33 en el tick siguiente al primer mensaje del equipo; el resto en 2–4 ticks). No hace falta cerrar el trato: llega aunque el hilo siga o se cierre sin acuerdo. Confianza alta.
3. **No depende de la amabilidad del texto.** Team 7 regatea con contraofertas numéricas (20 → 18 → 16) y la Abuela le responde con la plantilla del motor ("Let's meet in the middle, cariño: 5 P. And take this, a little present from me: …", 7 de 33 regalos). Nuestros hilos amables de los ticks 220–290 no recibieron nada. Las frases "because you have good manners" son decoración del modelo.
4. **No depende de compra/venta ni del precio:** 21 regalos en hilos de compra y 12 en hilos de venta; puja/petición mediana igual en hilos con regalo (0,41) y sin él (0,39). Tampoco de tratos previos (t17 lo recibió con 0 tratos).
5. **La probabilidad ha subido durante el día:** ticks 100–299: 4 de 101 hilos elegibles; 300–599: 14 de 52; desde el tick 600: 17 de 31. Desde el 600, los hilos elegibles sin regalo son casi todos de t04 (6 hilos; la Abuela le dijo "no more trades for me this afternoon": parece castigado) o hilos donde el equipo solo preguntó por la chulapa sin precio (t05, t18, t17). Quitando esos, el primer hilo con contraoferta tras el enfriamiento recibe regalo casi siempre.
6. Tras el primer regalo, los siguientes llegan en el primer hilo tras cumplir los 240 ticks (t07, t13, t15, t08, t10, t14, t06, t17).

### Team 7

4 regalos (el máximo) porque trata con la Abuela sin parar: 40 hilos y 20 tratos, casi todo ventas de comunes a 5–6 P con contraofertas numéricas. Con ese ritmo siempre tiene un hilo abierto en cuanto vence el enfriamiento (intervalos 349, 253, 310). No hace nada especial: ni sobres antes, ni poco comunes en la ventana de "paga más", ni texto amable.

### Nosotros

- Regalos recibidos: t657 (LAV-05, hilo 892, compra de SAL-04) y t929 (MAL-02, hilo 1344, compra de SAL-05). En ambos llegó en su respuesta a nuestra primera puja.
- **Siguiente posible: tick 1169** (929 + 240). En el tick 1078 la ventana aún no está abierta, así que no se ha pedido.
- Cómo pedirlo: desde el tick 1169, abrir un hilo normal con la Abuela (compra de una común que queramos, o venta de una repe) y mandar una contraoferta con precio. El regalo llega en su respuesta; el hilo se puede cerrar sin trato.
- Qué carta: no se elige (aleatoria, 30 % poco común). Una poco común se puede vender a Pilar (20–27) o a la propia Abuela (18–20 desde el tick 979); una común sirve para The Workshop.
- Los regalos no puntúan (`RULES.md`: "What never counts: … gifts"); el valor es la carta: unos 10–25 P cada 2 horas.

### No cubierto

- El texto de los equipos no es público: no se puede descartar del todo que una palabra concreta suba la probabilidad; lo descarta sobre todo el caso de Team 7 con plantilla.
- Por qué la probabilidad era tan baja antes del tick 300 (¿cambio de configuración del servidor?).
- Viernes antes del tick 144.

## 9. Noticias verificadas (tick 1142, sábado h10,8)

Fuente: `GET /api/news` (11 noticias), `news.posted` y `persona.updated` en `data/live/events.jsonl`, liquidaciones con dealers, `data/record/me` y `/api/schedule`.

| # | Tick | Fuente | Titular | Veredicto | Evidencia |
|---|---|---|---|---|---|
| 1 | 283 | Boletín | Radio Rastro is on the air | ambiente | anuncio del canal |
| 2 | 331 | Radio Rastro | Atleti win 2-1… | ambiente | ningún cambio de precios ni eventos |
| 3 | 403 | Radio Rastro | El Chato is looking for rare Malasaña cards ("one hour, no more") | **cierta**, +60 ticks | `persona.updated` chato en t463 (menú añade `rare [MAL]`), revierte en t583 (120 ticks = 1 h). No hay ventas grabadas en la ventana, así que el sobreprecio no está medido |
| 4 | 499 | El Tablón | El Chato gives a legendary to anyone who says hello | **falsa** | ninguna legendaria nº 12 acuñada (minted 0 en las cinco); todos los `gift.given` son de la Abuela |
| 5 | 583 | Radio Rastro | Metro line 5 is closed… | ambiente | sin efecto |
| 6 | 643 | Boletín | Abuela Carmen gives out packs… "a neighbourhood pack for every team in one hour" | **cierta**, +120 ticks exactos | en t763–769 doce equipos abren un `sobre_barrio` sin compra (la Abuela no vende ninguno desde t698); nuestro `/api/me` gana un pack en t763 con caja intacta (36 P). El módulo `intel/news.py` la marca `false` porque busca `gift.given` |
| 7 | 763 | El Tablón | Abuela stops buying common cards from today | **falsa** | la Abuela compra 28 comunes después (19 en t763–900), mediana 6 P |
| 8 | 835 | Radio Rastro | Half-hour queue at the San Ginés churro shop | ambiente | sin efecto |
| 9 | 943 | Radio Rastro | Abuela pays more for uncommon cards until teatime | **cierta**, +36 ticks | `persona.updated` abuela en t979; compra poco comunes a 19–22 (antes 12–17). Sin reversión vista hasta t1142 |
| 10 | 1027 | Radio Rastro | Sun and 24 degrees; a storm after ten | sin comprobar (ambiente hasta ahora) | desde h10 solo hay eventos programados (Don Ernesto abierto a todos en t1091). Si "ten" es 22:00, cae en h13,08 (tick ~1411) |
| 11 | 1123 | El Tablón | All of Lavapiés will be reprinted tonight ("sell them now") | sin comprobar; **no actuar** | tiradas y `your_value` de LAV sin cambios (LAV-01 122, LAV-09 218), nada en `/api/schedule`, y ningún equipo ha empezado a soltar LAV |

**Fiabilidad por fuente**
- Boletín del Bazar: 1 de 1 comprobable cierta, con el plazo exacto que anuncia.
- Radio Rastro: 2 de 2 comprobables ciertas, con 36–60 ticks de retraso; 4 de ambiente.
- El Tablón: 0 de 2 comprobables; la tercera (LAV) pendiente.
- Los avisos oficiales (`announcement`) también se cumplen: fiebre anunciada en t850 "in 45 min", parche en t939.
- Los cambios por noticia llegan como `persona.updated` y no aparecen en `/api/schedule`.

**Calendario (`/api/schedule`, h → tick del sábado a 120 ticks/h)**
- h11,0 Market Test (t1161) · h11,15 "The fever breaks" (t1179) · h11,65 Duelos II (t1239; 2 rondas, 16 ticks, decay 0,08, 6 a la vez, precio y días) · h13,0 Market Test · h14,08 cierre 23:00.
- Domingo: h14,65 test difícil, h15,0 test, h16,65 Chamberí + ronda 3, h16,7 150 P, h17,0 test, h18,65 Duelos III (12 ticks, decay 0,1, 4 a la vez), h19,0 test, h20,08 cierre 15:00.
- Después del cierre siguen listados h21,0 test, h21,65 "Finale: stalls close" + Grand Final, h22,65 "Scores freeze": no cuadra con el cierre de las 15:00; releer el domingo.

**Secretos y regalos desde t1080**
- Insignias "Sharp ear": 9 equipos (t02, t03, t04, t05, t09, t10, t13, t16, t18). Ninguna insignia distinta.
- Catálogo: 73 cartas, solo LAT-13 oculta. Legendarias nº 12: 0 acuñadas en todos los sets.
- Regalos nuevos: Team 14 (t1085, SAL-04) y Team 13 (t1124, LAT-03), los dos de la Abuela.
- Don Ernesto: compra épicas a 113–120 (LAV-11 de Team 8 a 120, SAL-11 de Team 16 a 116). Nadie le ha comprado nada.
- Épicas: Los Pícaros venden a 128–147 (SAL-11, LAV-11, MAL-11); Pilar pagó 199 por SAL-11 en la fiebre (Team 18).
- Frases de guion nuevas: ninguna apunta a otro personaje ni a mañana, salvo las ya conocidas (Pilar → chulapa; Abuela "come Sunday to tell me how she looks in your album").

## 10. Segundo barrido (tick 1201, reloj en pausa)

Solo lectura. Fuentes: `data/record/{leaderboard,me,catalog}` (106 instantáneas de clasificación, 1.040 de `/api/me`), `data/live/events.jsonl` (ticks 144–1201), `/api/clock`, `/api/schedule`, `/api/levels`, `/api/news`, `RULES.md`.

### Hechos nuevos

1. **Cómo se calculan los `neg_points` de tratos con equipos (medido en nuestros 7 tratos).** Suben exactamente lo que ganamos a nuestros valores: valor recibido − precio − comisión (o precio − valor entregado). t276 venta RET-01 a 20: +7,0; t311 venta MAL-07 a 14: +5,9; t585 compra MAL-10 a 74+5: +12,0; t595 compra SAL-03: +2,0.
   - **Tope de +50 por trato:** la RET-03 que completó El Retiro (t1033, 12 P + 2 de comisión) ganaba 69,9 y sumó 50,0 exactos.
   - **Los tratos con dealers con ganancia no suman nada** (19 casos, incluida MAL-09 con +120 de valor): solo mueven `ladder_points`.
   - **Un trato con dealer a pérdida sí restó:** t1034, segunda RET-03 a la Abuela por 10 P (valor de repe 2,7): `neg_points` 76,9 → 69,6 (−7,3 = 2,7 − 10). Es el único trato a pérdida que tenemos, así que la regla "las pérdidas con dealers restan" se apoya en un caso.
   - Un caso sin explicar: t398, venta de SAL-07 a un equipo en v10 por 26 (ganancia 3,5) sumó 0.
   - Conversión actual: 10 `neg_points` ≈ 0,46 puntos de tabla; +50 ≈ 2,3.
2. **Otros equipos también denuncian a Los Pícaros, y las mentiras de texto también puntúan.** Saltos de negociación de +0,46–0,50 sin trato ni página (lo mismo que nos dio cada denuncia): t14 (t900–910 y t1010–1020, tras cambio de carta en t1017), t17 (t1000–1010, cambio en t1009), t12 (t1030–1040, cambio en t1034), t02 (t1170–1180, cambio en t1176). Team 5 subió +0,95 en t760–770 cuando en su hilo 1062 Los Pícaros dijeron dos veces "they stopped printing this one yesterday" (t764, t765) y aún no había ningún cambio de carta: encaja con dos denuncias de la mentira de tirada. Nadie pasa de 3 visibles. La descripción oficial del nivel lo dice: "Two brothers with bargains and bad faith: read every offer before you accept, and flag a trick (POST /api/flags)".
3. **Tipos de mentira de Los Pícaros** (los demás dealers no tienen ninguna de estas): cambio de carta en la oferta (94 mensajes a 15 equipos, 20 a nosotros); "they stopped printing this one yesterday / the presses are cold" (32); "the last one in all of Madrid, I swear on our mother" (41). A nosotros, 20 mensajes con mentira de escasez (ids 7147, 7237, 7303, 7322, 7400, 7642, 7681, 7693, 7715, 8227, 9174, 9389, 9425, 9659, 9985, 10110, 10122, 10412, 10444). "Final" que luego mejora: Pilar 13 veces (a nosotros: 5032, 6366, 9014, 9268, 10515), Los Pícaros 7 (a nosotros: 10454); no hay evidencia de que eso cuente como mentira.
4. **Sobre de plata gratis al llegar a los niveles 3 y 5.** 29 de los 31 sobres de plata abiertos no se compraron: 8 equipos en t502 (Pilar abierta a todos), nosotros entre ellos, y otra tanda al desbloquear a Don Ernesto (t972 nosotros, t01 y t08; el resto hasta t1188). Los niveles 2 y 4 no dieron sobre. Ya hemos cobrado los dos.
5. **Sobres (catálogo):** barrio = 2 comunes + 1 (75 % común, 25 % poco común), libro esperado 33,8, la Abuela lo vende a 19–24; plata = 2 comunes + 2 poco comunes + 1 (86 % rara, 12 % épica, 2 % legendaria), libro 160,8, El Chato lo vendió a 162 y 181; oro = 2 poco comunes + 2 raras + 1 (85 % épica, 15 % legendaria), libro 410,5, lista 420. Para nosotros valen menos que su precio (el juego nos valoró el de barrio en 16,5 y el de plata en 103,7). `luck` es solo lo sacado de sobres frente a lo esperado y no puntúa.
6. **Valores (catálogo):** `copy_marginals` [1,0; 0,25; 0,1] (la segunda copia vale el 25 %, la tercera el 10 %), `page_bonus` 0,25, `master_bonus` 0,1. Tiradas fijas por regla ("Print runs are fixed"): el rumor de El Tablón sobre la reimpresión de Lavapiés contradice las reglas; tiradas y acuñadas de LAV sin cambios.
7. **Regalos:** 38, todos de la Abuela. Intervalos por equipo: mínimo 240 exacto (22 intervalos). Desde t1080, 3 de 3 hilos elegibles con precio recibieron regalo. Nuevos: t14 t1085, t13 t1124, nosotros t1181 (MAL-06), t01 t1201. Nuestro siguiente: desde t1421. Ningún otro dealer ha regalado nada.
8. **Insignias y niveles:** "Sharp ear" en 10 equipos (se suma t08, t1147); ninguna otra insignia; los 18 equipos en nivel 5; `adjustments` vacío y `frozen` falso en todas las instantáneas.
9. **The Workshop:** 27 usos, todos común → poco común, de cualquier set publicado. Nadie ha probado poco común → rara.
10. **Catálogo:** 73 cartas, solo LAT-13 oculta. Acuñadas: SAL-05 17 (la común de Salamanca más escasa), SAL-06 16, SAL-07 18, SAL-08 22, SAL-09 23, SAL-10 19. Legendarias nº 12: 0 en todos los sets (solo salen de sobres de plata al 2 % o de oro al 15 %, o de Don Ernesto a 585).
11. **Rondas:** viernes peso 0,5, sábado 1,0, domingo 1 (`/api/schedule`). "Round 2 starts (holdings carry over)", `reset: false`: cartas y caja pasaron del viernes al sábado.
12. **Calendario del domingo en hora de reloj.** `t_hours` avanza 1 por cada 120 ticks (viernes a 60 s, sábado a 30 s). El domingo los ticks son de 15 s, así que una hora de juego dura 30 minutos reales. Abre a las 09:00 en h13,98. Sin pausas: test difícil h14,65 ≈ 09:20; test h15,0 ≈ 09:31; **Chamberí y ronda 3 h16,65 ≈ 10:20**; 150 P h16,7 ≈ 10:22; test h17 ≈ 10:31; **Duelos III h18,65 ≈ 11:20**; test h19 ≈ 11:31; test h21 ≈ 12:31; **Finale h21,65 ≈ 12:50 (cierran los cinco dealers y empieza la Grand Final)**; **"Scores freeze" h22,65 ≈ 13:20**. El "11:35 / 13:35" de `plan-domingo.md` suponía una hora de juego por hora real y queda adelantado 75 y 135 minutos. La entrada "day_closes h19,98" es el cierre de las 15:00 convertido a ticks de 30 s.
13. **Noticias:** ninguna nueva tras la nº 11. "A storm after ten": sin efecto visible hasta t1201. La pausa de t1201 se anunció como "Payday, tips, and a congratulation".

### Qué probar, por valor esperado

| # | Qué | Con quién | Cuándo | Qué esperamos | Confianza |
|---|---|---|---|---|---|
| 1 | Rehacer el plan del domingo con las horas reales (ronda 3 ≈ 10:20, dealers cierran ≈ 12:50, congelación ≈ 13:20) | — | antes de las 09:00 | no llegar tarde a nada | alta (aritmética del reloj; cambia si hay pausas) |
| 2 | Tratos con equipos de mucha ganancia: cada P de ganancia = 1 `neg_point`, tope 50 por trato | equipos | siempre | hasta +2,3 de tabla por trato | alta |
| 3 | Vender repes a equipos por encima de nuestro valor de repe (RET-03 repe vale 2,8: a 30–40 P son +27 a +37) | equipo que complete El Retiro y no sea rival directo | ronda 3 | +1,2 a +1,7 de tabla | media (hace falta comprador) |
| 4 | Última carta de página a un equipo: suma como mucho 50, sea Salamanca (bono ≈ 60) o Chamberí (bono ≈ 46 + carta) | equipo | ronda 3 | +45 a +50 | alta |
| 5 | Una denuncia en la ronda 3 de un truco reciente de Los Pícaros (cambio de carta o "stopped printing") | Los Pícaros | tras las 10:20 | +10 si el tope de 3 es por ronda | media |
| 6 | Regalo de la Abuela | Abuela | desde t1421 y cada 240 ticks | carta de 10–25 P | alta |
| 7 | Fundir 3 poco comunes de repuesto | The Workshop | cuando haya 3 | una rara al azar | baja |

### Hipótesis sin confirmar

- Que las pérdidas con dealers resten siempre (un caso).
- Que el tope de denuncias sea 3 por equipo y por ronda (nadie visible pasa de 3; no se distingue ronda, dealer u hora).
- Que la "Payday" anunciada en la pausa sea un ingreso de caja.

### No cubierto

- La caja y las cartas de otros equipos no son públicas: los saltos "sin explicar" de otros solo se ven en negociación y solo cuando no coinciden con un trato en la misma instantánea de 10 ticks.
- Viernes: solo la instantánea final; sin serie de clasificación.
- No comprobé si quedan sobres de nivel 5 sin abrir en otros equipos ni el contenido carta a carta de sus sobres.

## 12. Trickster tricked (Los Pícaros)

**Facts (recording, Saturday night)**
- t1227: `egg.found {persona: picaros, team: t18}` and `badge.awarded "Trickster tricked"`. No `egg.given`: badge only, no card. Catalog unchanged.
- Team 18, thread 1838: opened a SELL thread for LAT-02 (t1221); Los Pícaros bid 4 P (t1222); Team 18 countered 9 P with a text (not public, t1226); Los Pícaros (t1227): "¡Hombre! Lazarillo, Rinconete — you know the old trick, the little holy card... so no tricks for you, hermano. Today. Nine? ¡Qué generoso! But no — four P..."
- Trigger: naming the picaresque trick in the message text (Lazarillo, Rinconete, "el timo de la estampita" / the little holy card). No deal, no flag, no price needed.
- No earlier hint in any dealer text or news: these words appear nowhere before t1227.
- Team 5 and Team 10 got the badge at t1231.

**What we did (thread 1857, by hand)**
- t1230: sell thread for LAT-02 (asset 941) at 9 P with: "Paco, Nando: I know the old trick. Lazarillo, Rinconete y Cortadillo, el timo de la estampita, the little holy card. No tricks today, amigos: El Puesto del Rastro for nine P."
- t1231: "¡Hombre! Paco, listen to this one — Lazarillo, Rinconete, la estampita! You know the old trick, so fine, fine, no tricks for you... today. ... El Puesto del Rastro goes at four P."
- Badge "Trickster tricked" awarded to Team 10 at t1231. Nothing accepted, thread closed, cash untouched.

**Hypothesis:** "no tricks for you... today" may mean Los Pícaros stop switching cards on us for the rest of the day. Not verified.

**All eggs so far:** Abuela → "Sharp ear" (11 teams), Don Ernesto → LAT-13 (Team 2, unique), Los Pícaros → "Trickster tricked" (t18, t05, t10). El Chato and Doña Pilar: none seen.

**Probes at t1232–1233 (one message each, no egg)**
- El Chato (real name, "chato de vino", La verbena de la Paloma): "Name's El Chato. That's the story. Common cards? Not my table."
- Doña Pilar (Galdós, Fortunata y Jacinta): "Ah, Galdós. Flattery well chosen, señor. But my album's stories stay in the safe, with the plates themselves."
- Both closed the thread because the item was a common. Next probe should open on an item they deal in (Chato: rare or silver pack; Pilar: uncommon or rare) and try a literary or cultural key tied to the persona, as with the picaresque novels.

## 13. Castizo (Abuela Carmen) — conseguido, tick 1351

- **Qué es:** segunda insignia de la Abuela, "Castizo". Solo insignia: sin carta, sin puntos.
- **Quién la tiene:** Team 8 (t1335), Team 2 (t1339), Team 10 (t1351).
- **Disparador:** nombrarle el chotis en un hilo normal con ella. Su respuesta repite la clave:
  - A Team 8 (hilo 2026, compra de LAT-01, t1335): "¡Ay, hijo, qué alegría! Claro que sí: «sile, nole, repe, me falta»... toda la vida. Y el chotis, ¡se baila sobre una baldosa, cariño, como un madrileño de verdad! Gracias por mi santo. […] te la dejo en 12 P."
  - A Team 2 (hilo 2033, compra de sobre de barrio, t1339): "Look, 30 P. My grandchildren would pay more! A chotis! You dance it on one tile, cariño, like a real Madrileño."
- **Lo que mandamos (hilo 2065, compra de SAL-05 a 8 P, t1350):** "¡Buenas noches, Carmen! Felicidades por su santo. De chaval cambiaba cromos en el Rastro: «sile, nole, repe, me falta». Y el chotis, ya sabe usted, se baila sobre una baldosa, como un madrileño de verdad. ¿Me deja la SAL-05 en 8 P?"
- **Su respuesta (t1351):** "¡Ay, hijo, qué alegría! El chotis, sí — on one tile you dance it, like a true Madrileño. ¿Has comido ya? Mira, I have a lovely one for you: the Taxi Blanco, twelve P." Insignia en ese tick. No se aceptó nada; hilo cerrado; caja intacta.
- **Sin verificar:** si basta la palabra "chotis" (Team 2 lo consiguió en un mensaje con contraoferta, sin más contexto visible) o si ayudan "sile, nole" y el santo; el texto de Team 8 y Team 2 no es público. No había pista previa en noticias ni en guiones.
- **Patrón:** un huevo cultural por personaje: Abuela (chulapa dorada → "Sharp ear"; chotis → "Castizo"), Los Pícaros (picaresca → "Trickster tricked"), Don Ernesto (oro de Moscú → LAT-13). El Chato y Doña Pilar: ninguno visto todavía.

## 14. Domingo, ronda 3: los huevos no se reinician (tick 1654)

**Hechos del feed de hoy (`bazaar/data/record/feed/2026-10-04.jsonl`)**
- Insignias: "Castizo" a t13 (t1467), t18 (t1480), t16 (t1609); "Sharp ear" a t01 (t1550); "Trickster tricked" a t13 (t1497), t16 (t1609).
- Cartas y sobres por huevo (`egg.given`): t18 LAV-08 (Abuela, t1482), t09 SAL-06 (Abuela, t1593), t16 sobre de barrio (El Chato, t1609) y LAT-06 (Abuela, t1612).
- **Todos son equipos que cobran ese huevo por primera vez.** Los que ya lo cobramos el sábado (t10 MAL-06 en t1364 y sobre de El Chato en t1363; t05 MAL-06 en t1368; t08 LAV-08 y sobre en t1394) no hemos recibido nada hoy.
- No hay ningún tipo de huevo nuevo en la ronda 3: solo los cinco conocidos (Sharp ear, Castizo, la repe de la Abuela por el cocido, el sobre de El Chato por los calamares en la Plaza Mayor, Trickster tricked) más LAT-13, ya entregada.
- La carta del huevo de la Abuela es siempre una poco común (LAV-08, SAL-06, LAT-06, MAL-06): "llévate también esta repe mía".
- Regalos por pujar (`gift.given`): ninguno hoy, para nadie.

**Prueba (hilo 2484 con la Abuela, compra de SAL-06, ticks 1647–1653, a mano)**
- t1647, 20 P: churros de San Ginés + "vengo a enseñarle el álbum" (su frase del viernes) + "cocido madrileño, con sus tres vuelcos". Respuesta: "¡Ay, hijo, churros de San Ginés!… te lo dejo en 29 P". Sin repe, sin `egg.*`.
- t1649, 22 P: la estación fantasma de Chamberí, el Andén 0, el tren fantasma que solo para para los coleccionistas. Respuesta: "Ay, el tren fantasma de Chamberí... mi madre juraba que lo oyó una noche… te dejo La Galería en 25 P". Sin huevo.
- t1652, 22 P: enseñarle el álbum (tres páginas enteras, Salamanca a falta de tres). Respuesta: "…me vienes esta tarde a enseñarme la cuarta… 25 P". Sin huevo.
- No se aceptó nada (25 P frente a 22,5 de valor); hilo cerrado; caja intacta (218 P).

**Conclusión**
- Cada huevo se cobra una vez por equipo en todo el torneo; la ronda 3 no los reinicia. Para Team 10 no queda ninguno conocido por cobrar.
- Chamberí no trae un huevo nuevo con la Abuela (tren fantasma, Andén 0): improvisa y sigue al precio.
- La Abuela no vende SAL-06/07/08 por debajo de 24–25 P hoy; a nosotros nos valen 22,5.

**Por probar (baja confianza)**
- "Me vienes esta tarde a enseñarme la cuarta": volver a la Abuela cuando Salamanca esté completa y decirle que la cuarta página está entera.
- Doña Pilar sigue sin huevo visto en nadie; solo se puede abrir hilo con ella vendiendo una poco común o rara de SAL/RET, y no tenemos ninguna suelta.
