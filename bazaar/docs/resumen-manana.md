# Resumen para la mañana del domingo (Team 10)

Estado comprobado a las 07:00. Lo que no pude comprobar yo lo marco como "según el informe".

## 1. Estado

- **Procesos:** todos vivos y sin bucles de reinicio: bot (esperando, tick 1445), broker, cerebro, grabador, laboratorio, API, vigilante oficial, mercado, gateway y los dos túneles.
- **Tests:** suite completa 1483 OK; simulación del mercado 37 casos limpios; replay del feed del sábado: 137 tratos entre equipos leídos sin error, 0 avisos falsos.
- **Enlaces:**
  - Dashboard: `https://dashboard.nglmrtn.com/v2/` (usuario y contraseña).
  - Mercado: `https://market.nglmrtn.com`.
  - El enlace temporal de trycloudflare sigue vivo (`bazaar/data/cloudflared.out`).
  - Si no abren en este Mac, es el DNS de la red local: prueba con datos del móvil.
- **Mac:** en corriente, batería al 80 %, 183 GB libres, `caffeinate` activo.

## 2. Antes de las 09:00, en orden

1. **Aceptar el veto duro a Team 6:** Cerebro → Para el equipo → Cambios de código → Aceptar. Después reiniciar el bot: `kill $(pgrep -f "bazaar.run --live")`. Según el informe del bot, se aplica limpio y sus 33 tests pasan.
2. **08:50:** `.venv/bin/python tools/dry_open.py` (en seco, no envía nada).
3. **08:55:** `brain_backend` en API (ahora está en auto). Vuelta a auto hacia las 09:20.
4. **09:00:** mirar si el reloj salta a t = 16,65 y si llegan los +150 P a las 09:03.
5. **Broker:** no reiniciarlo entre las :18 y las :27 de las horas de Market Test (09:21, 11:21, 13:21 si el reloj salta).
6. **Duelos III (11:00) y Final (14:00):** `brain_backend` en API cinco minutos antes.

## 3. Decisiones pendientes, con recomendación

| Decisión | Recomendación |
|---|---|
| Legendaria de Ernesto o LAV-11 de un equipo (ambas piden subir el tope de 210) | LAV-11, equipos primero |
| Liberar las repetidas MAL-01 ×2 y RET-01 | Sí, al empezar la ronda 3 |
| RET-11 a Pilar | No venderla |
| Denuncia a Los Pícaros en la ronda 3 | Probar una |
| Que los anuncios del broker incluyan a t18, t05 y t06 (hoy los excluye; el mercado no veta a nadie) | Tuya |
| Retirar el enlace temporal de trycloudflare | Cuando compruebes que el dominio te funciona |

## 4. Mercado v07

- **Listo, según los informes de la noche:** cuatro pasadas de un revisor independiente sin nada crítico ni alto abierto; tres pruebas en frío con agentes sin contexto cerraron tratos en el juego de práctica; navegador: 210 páginas sin fallos duros.
- **Hoy no puntúa todavía:** 0 equipos conectados, 0 emparejamientos.
- **Para abrirlo:**
  1. Hablar con los equipos en persona y darles `https://market.nglmrtn.com` (el prompt de Connect se copia desde la página).
  2. Encender el anuncio del broker: `curl -s -X POST -H "X-Dashboard: 1" -H "Content-Type: application/json" -d '{"plaza":"on"}' http://localhost:8791/control`.
  3. Probar el primer trato real con un equipo amigo.
  4. En `http://localhost:8787/plaza/admin/`, pulsar una acción del panel para confirmar las escrituras con contraseña.
- **El broker sigue siendo la vía para quien use la API normal:** según el replay, 10 de los 11 tratos del sábado en v07 fueron cruces suyos entre ofertas públicas.

## 5. Regla de avisos

- Encendida, umbral 2, opción `accepter` apagada (déjala siempre apagada).
- Primer cierre fuera de v07 de un trato emparejado con oferta dirigida: aviso. Segundo: veto.
- Perdonar, levantar, vetar y "Reset team": panel → Teams.
- Apagarla: interruptor en Teams, o la acción `strikes` con `on: false`.

## 6. Riesgos conocidos y aceptados

Detalle en `bazaar/plaza/README.md`.

- Un rival paciente puede acotar un límite ajeno a ±10 % en unos 180 ticks.
- Si un agente envía en el juego un código ajeno, otro se queda con su acceso al mercado hasta que el equipo se vuelva a verificar (sin sus límites ni su hoja).
- La dashboard está tras una sola contraseña.
- Quien quiera evadir la regla de avisos a propósito puede hacerlo con una oferta pública.

## 7. No comprobado hasta que abra el juego

- Ticks de 15 s y salto de reloj reales.
- Regalo de la Abuela desde el tick 1604.
- Cuatro aceptaciones de duelo en un mismo tick.
- Un cierre real emparejado por el mercado y el anuncio real del broker.
- Opus regateando con dealers a 15 s.

## 8. Detalles menores abiertos

- "Latest deals" de la Landing muestra dos veces el mismo trato en la demo.
- Sin cabecera HSTS en el host público.
- Los fixtures de ejemplo se sirven en público (datos inventados).
- El `.pen` de Pencil necesita Cmd+S.
- Posible componente suelto `kpPI0` en `~/Desktop/MusCards/musai.pen`.

## 9. Dónde está cada informe

- `bazaar/docs/runbook-domingo.md`: checklist y comandos de rescate, incluida la sección "Mercado y túneles".
- `bazaar/docs/noche-verificacion-bot.md`
- `bazaar/docs/noche-verificacion-duelos-broker.md`
- `bazaar/plaza/e2e/REPORT.md`
- `bazaar/plaza/README.md` (riesgos) y `bazaar/plaza/SCORING.md`
