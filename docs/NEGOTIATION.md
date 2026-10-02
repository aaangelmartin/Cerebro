# Técnicas de negociación del bot

Qué dice la investigación sobre negociación, humana y automática, y cómo lo usa el bot en El Bazaar. Las funciones están en `bot/tactics.py`, son puras y tienen tests en `bot/tests/test_tactics.py`. Los parámetros son puntos de partida: hay que ajustarlos con `bot.sim.practice` y contrastarlos con partidas reales.

Lo que el juego fija y condiciona todo lo demás:
- **Dealers.** Solo ceden si cedemos. Repetir precio no da nada y gasta paciencia. A pasos pequeños responden con pasos pequeños. Al final hacen una oferta final que hay que tomar o se van. Abuela premia la amabilidad, y algunos dealers nos dejan en cooloff si hacemos spam o trampas. Puntúa el porcentaje del rango del dealer que capturamos, contado en nuestros tres mejores tratos por nivel.
- **Duelos.** Cada lado tiene un límite privado y el pastel decrece entre un 6 y un 8 % por ronda. No cerrar puntúa 0 y cerrar fuera de nuestro límite resta. Más adelante entran los días de entrega, con un peso privado por día para cada lado.
- **Las palabras no mueven precios, la estructura sí.** El tono solo influye en la paciencia y el cooloff de los dealers, y en cómo reacciona un rival que sea un LLM.

## 1. Anclaje y primera oferta

**Evidencia.** Galinsky y Mussweiler (2001) vieron que quien hace la primera oferta obtiene mejor resultado, y en negociaciones distributivas la primera oferta explica hasta un 50 % de la varianza del precio final. Un meta-análisis reciente (OBHDP 2025) confirma la ventaja en negociaciones simples de un solo tema. Tiene dos límites: un ancla extrema puede romper la negociación (Schweinsberg et al. 2012), y el efecto desaparece si el otro piensa en su propio límite.

**En el bot.**
- *Dealers:* `anchor(their_price, limit, buying, ambition)`. Al comprar se abre al 40 % de su precio (rango permitido de 25 a 70 %). Al vender, a 2,2 veces su oferta (de 1,3 a 3). Nunca se abre al otro lado de nuestro límite. Son los `OPEN_FRACTION` y `OPEN_MULTIPLE` de `dealer.py`.
- *Duelos:* se abre con 1,25 veces el pastel estimado (`OPEN`), o con 0,95 cuando el pastel se conoce del escenario espejo. Al rival no le damos ancla: decidimos por nuestro límite y nuestro calendario, nunca por su número.

## 2. Límite del rival (ZOPA) y modelo del oponente

**Evidencia.** Los agentes que ganaron ANAC modelan al rival. Agent K (2010) estima lo que ofrecerá el rival a partir de su historial. HardHeaded (2011) usa un modelo de frecuencias. CUHKAgent (2012) estima cuánto cede el rival y fija a partir de ahí un punto en el que deja de ceder.

**En el bot.** `estimate_reservation(prices, they_sell)` toma los dos últimos pasos del rival y supone que encogen de forma geométrica: el ratio es q = c2/c1, con tope `q_cap = 0.75`, y lo que le queda por ceder es c2·q/(1−q). Si no se mueve en dos ofertas seguidas (`stall=2`), su último precio es su límite. `mirror_ratio(our_steps, their_steps)` mide qué parte de nuestro paso nos devuelve un dealer: si ese ratio cae a 0 aunque sigamos moviéndonos, ha llegado a su límite secreto.
- *Dealers:* en cuanto detectamos que se ha estancado, pasamos a pasos de 1 P y esperamos su oferta final, en lugar de seguir regalando margen.
- *Duelos:* `duels.estimate_pie` ya hace esta misma extrapolación en términos de excedente. Ver la propuesta de cambios más abajo.

## 3. Curvas de concesión: Boulware o conceder

**Evidencia.** Faratin, Sierra y Jennings (1998) proponen α(t) = k + (1−k)·t^(1/e). Con e < 1 (Boulware) se aguanta y se cede al final; con e > 1 (conceder) se cede pronto. HardHeaded ganó ANAC 2011 casi sin ceder hasta el final. Cuando hay descuento por tiempo, que es nuestro caso con el pastel decreciente, CUHKAgent y los ganadores de 2012 y 2013 cedían antes: aguantar sale caro.

**En el bot.** `faratin_alpha`, `concession_target` y `utility_target`, con los presets de `CURVES`: hardheaded 0.1, boulware 0.3, linear 1, conceder 3.
- *Duelos:* el pastel decrece, así que nada de Boulware puro. El calendario actual (`TARGET 0.62` al 40 % del tiempo y `BETA 0.8`) ya es casi linear-conceder, y hay que mantenerlo así.
- *Dealers:* aquí no hay descuento, pero sí paciencia. La curva sirve como guía del tiempo dentro de `blended_step`, con e = 3 y t = mensajes / 8, porque la paciencia que vemos en el simulado va de 5 a 11.

## 4. Reciprocidad: tit-for-tat en el tamaño de la concesión

**Evidencia.** Faratin y otros describen tácticas que dependen del comportamiento del rival: imitar su última concesión. En personas, Kwon y Weingart (2004) vieron que conceder de golpe genera menos satisfacción y más desconfianza que conceder de forma gradual. La reciprocidad es la norma más robusta de la negociación.

**En el bot.** `reciprocal_step(their_step, gap, ratio=1.0, min_step=1, cap_frac=0.35)`: nos movemos lo mismo que se movió el rival, con un ratio menor que 1 si queremos quedar por delante en el reparto. Si el rival no se movió, damos solo 1 P: nunca 0, porque repetir es spam y gasta paciencia, y nunca un salto grande sin contrapartida. Además, nunca damos más del 35 % del hueco. `blended_step` mezcla tiempo y reciprocidad al 50 %, como las combinaciones lineales de Faratin. `next_offer` garantiza que nunca repetimos precio, nunca pasamos de su precio y nunca de nuestro límite.

## 5. Plazos y aceptación

**Evidencia.** Roth, Murnighan y Schoumaker (1988) observaron que los acuerdos se acumulan en los últimos segundos (*deadline effect*). Baarslag, Hindriks y Jonker (2013) compararon condiciones de aceptación: AC_next acepta si la oferta del rival es al menos tan buena como la que pensábamos hacer, y AC_combi añade al final aceptar lo mejor que se ha visto, porque ya no va a mejorar. En el modelo de Rubinstein con ofertas alternas y descuento δ, quien propone primero se lleva 1/(1+δ).

**En el bot.** `should_accept(offered_u, planned_u, decay, lookahead, ticks_left, last_ticks, reservation_u, best_seen_u, late_frac, t, final)` decide en este orden:
1. Nunca por debajo de nuestro límite.
2. Si es su oferta final y está dentro de nuestro límite, aceptar: la alternativa es que se vaya y eso vale 0.
3. AC_next descontado: aceptar si la oferta ≥ nuestra próxima oferta × (1−decay)^lookahead. Usamos `lookahead=2`, igual que `LOOKAHEAD` en duelos.
4. AC_time: aceptar cualquier oferta dentro del límite si quedan `last_ticks` ticks o menos. En duelos son 2.
5. AC_combi: a partir de `late_frac=0.8` del tiempo, aceptar si iguala la mejor oferta vista.

`rubinstein_share(decay)` sirve de comprobación: con decay 0,06 el reparto de equilibrio es 0,515. Pedir mucho más de la mitad cuando el duelo va avanzado solo quema pastel. Con nuestro `END 0.20` y `TARGET 0.62` estamos en esa línea.

## 6. Negociación integrativa: dos temas, precio y días

**Evidencia.** Logrolling: ceder en lo que nos importa poco para ganar en lo que nos importa mucho (Thompson). Las ofertas en paquete funcionan mejor que negociar tema a tema. MESO (Medvec et al.): ofrecer varios paquetes que valen lo mismo para nosotros sube la aceptación del 59 al 78 % y lleva a acuerdos óptimos de Pareto el 67 % de las veces, frente al 28 % con un solo paquete.

**En el bot.**
- `joint_day(w_ours, w_rival)`: como la utilidad es lineal en los días, el día que maximiza el pastel conjunto es un extremo (0 o 10). Lo fija el signo de la suma de los dos pesos: gana el tema quien más lo valora. Es lo mismo que `duels.choose_days`.
- `equivalent_packages(role, limit, u, w, days_options=(0,5,10))`: genera paquetes (precio, días) con la misma utilidad para nosotros. La API solo admite una oferta por mensaje, así que hacemos un *MESO en el tiempo*: en las primeras rondas probamos días distintos con la misma utilidad, y su contraoferta nos dice el signo y el tamaño de su peso. Así `rival_weight` estima mejor que adivinando por la media de días que pide.

## 7. Encuadre, rapport y tono

**Evidencia.** Van Kleef y otros (2004) vieron que la gente cede más ante un rival enfadado, pero solo si tiene poco poder, y que el enfado genera miedo e impasses. La emoción positiva y el rapport (Drolet y Morris 2000) favorecen los acuerdos integrativos. En El Bazaar, además, Abuela premia la amabilidad y algunos dealers castigan las trampas con cooloff.

**En el bot.** `tone(t, their_step, final, gap, our_step, kind_counterpart)` devuelve uno de tres tonos:
- `closing` si hay oferta final, si va el 80 % del tiempo, o si el hueco cabe en dos de nuestros pasos.
- `firm` si el rival no se movió en la última ronda. Con Abuela (`kind_counterpart=True`) nunca: ahí se convierte en `warm`.
- `warm` en el resto de casos.

`TONE_HINTS[tone]` es una frase para el prompt de `llm.py`. Nunca hay enfado ni amenazas: la ganancia sería pequeña y arriesgaríamos un cooloff.

## 8. Lo que ganó ANAC, resumido

1. Ceder poco al principio y ajustar al final (HardHeaded, Agent K). **Con descuento por tiempo, ceder antes** (CUHKAgent, Fawkes).
2. Modelar al rival: su ritmo de concesión y sus preferencias por tema.
3. Separar tres piezas: cómo pujar, cómo modelar al rival y cuándo aceptar (arquitectura BOA de Baarslag). La condición de aceptación pesa tanto como la estrategia de puja.

Nuestra estructura sigue esa separación: la curva y la reciprocidad deciden la puja, `estimate_reservation` modela al rival y `should_accept` decide cuándo aceptar.

## Mercado

En el mercado no hay regateo, son ofertas publicadas. Aplican dos ideas:
- **Anclaje.** Publicar por encima de lo que perdemos, como ya hace el bot, pero empezar alto y bajar el precio de los anuncios que no se venden, usando una curva conceder en función de cuántas horas lleva publicado (`concession_target(start, floor, horas/6, e=1)`).
- **Ganancia mutua.** Solo aceptamos ofertas que nos dan ≥ max(3 P, 25 %) en valor privado.

## Experimento rápido

Contra el modelo de Abuela del simulado (3000 tratos), la captura media del rango fue:
- Regateo actual, 22 % del hueco por mensaje: **0,839**.
- `blended_step` con e = 3 y detección de estancamiento: **0,847**.
- 30 % del hueco con detección de estancamiento: **0,842**.

La mejora es pequeña: el simulado ya responde bien al regateo actual. La ventaja real de estas tácticas está en los dealers reales, que no conocemos, en reaccionar al estancamiento y en los duelos.

## Fuentes

- Faratin, Sierra y Jennings (1998), *Negotiation decision functions for autonomous agents*. https://jmvidal.cse.sc.edu/library/faratin98a.pdf
- Baarslag, Hindriks y Jonker (2013), *Effective acceptance conditions in real-time automated negotiation*. https://homepages.cwi.nl/~baarslag/pub/Effective_Acceptance_Conditions_in_Real-time_Automated_Negotiation.pdf
- Baarslag et al., *Optimal non-adaptive concession strategies with incomplete information*. https://homepages.cwi.nl/~baarslag/pub/Optimal_Non-adaptive_Concession_Strategies_with_Incomplete_Information.pdf
- ANAC 2010-2015 (Agent K, HardHeaded, CUHKAgent, Fawkes). https://www.researchgate.net/publication/292551541_The_Automated_Negotiating_Agents_Competition_2010-2015
- Galinsky y Mussweiler (2001), *First offers as anchors*. https://www.semanticscholar.org/paper/First-offers-as-anchors:-the-role-of-and-negotiator-Galinsky-Mussweiler/4593e56e2f94f5ffc75789ddacdfbe3670481cbe
- *The power and peril of first offers* (meta-análisis, OBHDP 2025). https://www.sciencedirect.com/science/article/pii/S0749597825000603
- Roth, Murnighan y Schoumaker (1988), *The deadline effect in bargaining*. https://www.researchgate.net/publication/4721076_The_Deadline_Effect_in_Bargaining_Some_Experimental_Evidence
- Kwon y Weingart (2004), *Unilateral concessions from the other party*. https://pubmed.ncbi.nlm.nih.gov/15065974/
- MESO. https://en.wikipedia.org/wiki/Multiple_Equivalent_Simultaneous_Offers
- Van Kleef et al. (2004), *The interpersonal effects of anger and happiness in negotiations*. https://www.researchgate.net/publication/8922924_The_Interpersonal_Effects_of_Anger_and_Happiness_in_Negotiations
