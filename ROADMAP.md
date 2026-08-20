# ROADMAP — Turnos / Citas (Portfolio Accelerate.ai)

Plan de construcción del MVP, dividido en checkpoints verificables. Cada checkpoint se cierra con testing estructural (contra datos/constantes reales del código, nunca por si la respuesta "suena bien") y con commits chicos a medida que se avanza — el checkpoint marca el punto de verificación, no la unidad de commit.

Referencia de alcance y decisiones de producto: `SPECS.md`. Este documento no repite el "qué" ni el "por qué" — solo el orden de construcción.

## Resumen

| CP | Nombre | Depende de | Estado |
|---|---|---|---|
| CP1 | Setup + motor de datos | — | **Hecho** |
| CP2 | Agente Claude (tool use) y ruteo de 4 caminos | CP1 | **Hecho** |
| CP3 | Endpoint FastAPI + parseo del webhook | CP2 | **Hecho** |
| CP4 | Orquestación n8n + prueba end-to-end | CP3 | **Hecho** |
| CP5 | Testing estructural completo | CP4 | **Hecho** |
| CP6 | README de portfolio + cierre | CP5 | Pendiente |

Fecha objetivo total: **martes 18 de agosto de 2026** (SPECS §14).

---

## CP1 — Setup + motor de datos

**Objetivo:** dejar el motor de reservas funcionando de forma aislada, sin IA ni WhatsApp todavía.

**Tareas:**
- Estructura de carpetas del repo (ver `ESTADO.md` para el árbol propuesto).
- Entorno virtual + `requirements.txt` inicial.
- `.env.example` y `.gitignore` (incluye `.env`, `__pycache__/`, credenciales de Google).
- Carga y validación del JSON de configuración (SPECS §5) con un modelo tipado.
- Cliente de Google Sheets: leer turnos existentes, escribir turno nuevo.
- Lógica de grilla fija de slots de 30 min (SPECS §8): dado un conjunto de turnos ya tomados, devolver slots libres/ocupados y la lista de alternativas disponibles cuando el pedido no calza.

**Testing estructural:** con una Sheet de prueba precargada con turnos conocidos, la función de disponibilidad debe devolver exactamente el set de slots libres esperado — comparación directa contra una lista fija, no evaluación subjetiva.

**Definition of Done:**
- El JSON de configuración de SPECS §5 carga sin errores y valida su estructura.
- Dado un escenario de turnos fijo (fixture), la función de disponibilidad devuelve el resultado exacto esperado, incluyendo el caso de slot ocupado devolviendo alternativas.
- Nada de esto depende todavía de Claude API ni de WhatsApp.

**Commits esperados (ejemplos, chicos y separados):** setup de estructura y entorno · modelo de configuración + carga del JSON · cliente de Sheets (lectura) · cliente de Sheets (escritura) · lógica de grilla de slots · tests de disponibilidad.

---

## CP2 — Agente Claude (tool use) y ruteo de 4 caminos

**Objetivo:** el agente decide correctamente entre los 4 caminos de SPECS §3 y llama a las tools con los argumentos correctos.

**Tareas:**
- Prompt de sistema con la fecha real calculada en cada request (nunca cacheada).
- Definición de las tools `crear_turno` (SPECS §6) y `consulta_general` (SPECS §7).
- Conexión de `crear_turno` con el motor de CP1 (valida contra la grilla, confirma o devuelve alternativas).
- Camino de cancelación/reprogramación: sin tool, mensaje fijo (SPECS §9).
- Camino de repregunta: detecta dato faltante (servicio u horario) y lo pide antes de llamar a la tool.
- Lógica de `nombre_paciente`: default al nombre de perfil de WhatsApp, override si el mensaje indica que es para otra persona (SPECS §6).

**Testing estructural:** guion de mensajes de prueba, uno por camino como mínimo, verificado contra qué tool se llamó (o ninguna, en cancelación) y con qué argumentos exactos se extrajeron — no contra el texto de la respuesta.

**Definition of Done:**
- Los 4 caminos de SPECS §3 están cubiertos y cada uno dispara el comportamiento correcto (tool correcta, o ninguna tool en cancelación, o repregunta).
- Caso "turno para otra persona" extrae el nombre correcto, no el de perfil de WhatsApp.
- Caso de dato faltante repregunta antes de intentar crear el turno.

**Commits esperados:** prompt de sistema con fecha dinámica · definición de tool `crear_turno` · definición de tool `consulta_general` · integración de `crear_turno` con el motor de CP1 · camino de cancelación (mensaje fijo) · camino de repregunta · tests de ruteo.

---

## CP3 — Endpoint FastAPI + parseo del webhook

**Objetivo:** exponer el agente de CP2 como endpoint HTTP consumible por n8n.

**Tareas:**
- Endpoint FastAPI que recibe el payload de WhatsApp Cloud API.
- Parseo del payload: extracción directa de teléfono y nombre de perfil (nunca vía la IA — SPECS §6).
- **Filtrado de los eventos de estado de WhatsApp** (ver abajo).
- Invocación del agente de CP2 con el mensaje del cliente.
- Composición determinista del mensaje al paciente desde el `ResultadoAgente`: cuando el modelo llama a una tool no escribe texto (verificado en CP2), así que la confirmación de un turno no puede venir de la respuesta del modelo.
- Persistencia del turno confirmado en la Sheet.
- Formato de respuesta compatible con el nodo "Respond to Webhook" de n8n.

**Los tres payloads que manda Meta al mismo webhook.** WhatsApp entrega las
notificaciones de "enviado", "entregado" y "leído" a la misma URL que los
mensajes reales, y no son payloads malformados: son válidos y distintos. El
sobre es casi idéntico —`changes[].field` vale `"messages"` en los dos casos— y
lo único que los separa es qué lista viene poblada dentro de `value`. En la
práctica es el caso que más aparece, bastante más que el payload roto. Sin el
filtro, cada notificación dispara una llamada paga a la Claude API y produce
errores intermitentes.

| Qué llega | Dónde se ve | Qué hace el endpoint |
|---|---|---|
| Mensaje del paciente | `value.messages[]` | lo procesa |
| Notificación de entregado/leído | `value.statuses[]` | lo ignora, sin llamar a la API |
| Payload irreconocible | ninguno de los dos | lo ignora, sin romper el proceso |

**Testing estructural:** un fixture por cada uno de los tres casos y un test por
cada uno, verificados contra la estructura del JSON y los datos concretos
extraídos, nunca contra el contenido conversacional del mensaje. El test del
evento de estado además comprueba que no se llamó a la Claude API ni se leyó la
Sheet.

**Definition of Done:**
- El endpoint responde 200 con el shape esperado ante un payload fixture válido.
- Teléfono y nombre de perfil se resuelven del payload, nunca de la extracción de la IA.
- Un evento de estado se ignora sin llamar a la Claude API ni leer la Sheet.
- Manejo básico de payload malformado (no rompe el proceso).
- Un turno confirmado queda persistido en la Sheet; si la escritura falla, no se le confirma al paciente.

**Commits esperados:** endpoint base FastAPI · parseo de payload de WhatsApp · integración endpoint↔agente · composición del mensaje al paciente · formato de respuesta para n8n · tests del endpoint con fixture.

---

## CP4 — Orquestación n8n + prueba end-to-end

**Objetivo:** conectar el número de WhatsApp de prueba con el endpoint de CP3 a través de n8n y validar el flujo real de punta a punta.

**Tareas:**
- Flujo n8n (ver abajo: el patrón de SPECS §12 se quedaba corto).
- Configuración del número de prueba de WhatsApp Cloud API (Meta), en una app **nueva**.
- Conexión del Webhook de n8n al endpoint de CP3.

**Corrección al flujo de SPECS §12.** `Webhook → IF → Respond to Webhook` no
alcanza: "Respond to Webhook" le contesta a Meta, y **responder 200 no le envía
nada al paciente**. El mensaje sale por un POST aparte a
`graph.facebook.com/<version>/<phone_number_id>/messages`. Por eso el endpoint de
CP3 devuelve `telefono` además de `respuesta`: son los dos campos de ese POST.

Además hace falta un **segundo webhook, en GET**: Meta valida la URL mandando
`hub.mode`, `hub.verify_token` y `hub.challenge`, y espera el challenge devuelto
en texto plano. Sin eso no deja suscribir el webhook.

El flujo completo queda:

```
Webhook GET  → Verificar token → Responder challenge / Rechazar (403)
Webhook POST → Filtrar eventos de estado
                 ├─ hay messages → Llamar a FastAPI → ¿respuesta vacía?
                 │                                      ├─ no → Responder por WhatsApp
                 │                                      └─ sí → Nada para enviar
                 └─ statuses     → Ignorar evento de estado
```

El webhook POST responde 200 de inmediato en vez de esperar al final del flujo:
si esperara a Claude, Meta cortaría por timeout y reintentaría el mismo mensaje.

**Testing estructural, en dos etapas.** Primero el flujo sin Meta, con
`scripts/verificar_n8n.py`: corre el circuito completo —n8n → FastAPI → Claude →
Sheets → envío— reemplazando solo la Graph API por un doble local que registra el
POST que habría salido. Se verifica que salga, a qué número (con el "9" ya
sacado) y con qué texto exacto, comparado contra las constantes importadas del
código. Encontrar un error del workflow ahí sale mucho más barato que con Meta en
el medio.

Después sí, conversación real con el número de prueba cubriendo al menos un caso
de cada uno de los 4 caminos, verificado contra qué pasó realmente (turno
guardado en la Sheet, tool llamada, mensaje fijo de cancelación mostrado) — no
contra si "se sintió bien" la charla.

**Definition of Done:**
- [x] Al menos un mensaje real de cada camino (turno nuevo, FAQ, cancelación, repregunta) llega, se procesa y responde correctamente de punta a punta.
- [x] Un turno creado por este flujo aparece efectivamente en la Sheet.

**Cerrado.** Los cuatro caminos se probaron con mensajes reales desde un teléfono
al número de prueba de Meta. Detalle de qué se verificó contra qué, y las tres
sorpresas que aparecieron (dominio de ngrok estático, El Parador compartiendo la
instancia de n8n y el puerto 8000, y la ventana de 24hs de WhatsApp): ver
`ESTADO.md`, sección "CP4 — cómo quedó cerrado".

**Commits esperados:** plantilla del flujo n8n versionada en el repo (con
placeholders, nunca con el token) · guiones de configuración de n8n y de Meta ·
guion de verificación del flujo · notas de troubleshooting si aparecen
(documentadas, no solo resueltas en la UI de n8n).

---

## CP5 — Testing estructural completo

**Objetivo:** cubrir los bordes explícitos del SPECS antes de dar por cerrado el MVP funcional.

**Casos a cubrir (guion de testing):**
- Slot ocupado → debe ofrecer alternativas, nunca redondear automático ni rechazar sin más (SPECS §8).
- Servicio que no matchea ningún `id` del catálogo.
- Turno "para otra persona" (nombre distinto al de perfil de WhatsApp).
- Consulta sobre obra social (respuesta: solo atención particular).
- Consulta de precios y horarios (FAQ básico).
- Intento de resolver una urgencia → confirmar que no se ofrece como opción ni se responde con info específica (fuera de alcance, SPECS §7).
- Repregunta que afirma disponibilidad sin verificarla → en el camino de repregunta no se llama a ninguna tool y la Sheet nunca se lee, así que el modelo no puede saber si el horario está libre. Detectado en el guion de CP3 y reproducido en producción en CP4; corregido acá, ver "Cerrado" más abajo.

**Testing estructural:** cada caso se verifica contra el dato real esperado (id de servicio devuelto, slot ofrecido, tool llamada o no llamada), documentado en el propio guion de testing — no evaluación subjetiva de la respuesta en texto.

**Definition of Done:**
- [x] Todos los casos de la lista están documentados en un guion de testing con input, comportamiento esperado y resultado real obtenido.
- [x] Ningún caso queda marcado como "parece que anda bien" sin verificación contra un dato concreto.

**Commits esperados:** guion de testing de bordes · fixes que salgan de los casos encontrados (cada uno en su propio commit, no agrupados).

**Cerrado.** `scripts/verificar_agente.py` pasó de 12 a 15 casos y dio **15/15**
contra la Claude API real. 148 tests en `pytest`. No hizo falta levantar el
stack: el checkpoint es casi todo de nivel agente.

Lo que costó de verdad no fue el fix del hallazgo sino **cómo verificarlo**: era
un bug de texto, y este proyecto no verifica si una respuesta "suena bien". Se
resolvió sacándole el texto libre al camino de repregunta —ahora es la tool
`pedir_dato_faltante` y el texto lo compone `respuestas.py` sin recibir la fecha
ni la hora pedidas—, con lo que el caso se verifica igual que los otros 14: qué
tool se llamó y con qué argumentos. El razonamiento completo, la corrida real y
las dos cosas que aparecieron y no se tocaron están en `ESTADO.md`, sección
"El hallazgo de CP4, y cómo se cerró en CP5" y "CP5 — cómo quedó cerrado".

Además, las urgencias pasaron a tener texto fijo derivando al teléfono del
consultorio: SPECS §7 dice qué no hacer pero no qué hacer, y sin una regla el
modelo improvisa justo donde no conviene.

---

## CP6 — README de portfolio + cierre

**Objetivo:** dejar el repo listo para mostrarse a un lead o reclutador.

**Tareas:**
- README público del repo, enfocado en la decisión técnica no obvia de SPECS §8 (grilla fija de 30 min vs. validación por solapamiento de intervalos) — por qué se descartó la alternativa, no solo qué hace el proyecto.
- Sección de limitaciones conocidas, con la firma del webhook sin verificar (SPECS §10) explicada como decisión y no como olvido: qué implica, por qué se aceptó en un MVP con número de prueba, y qué la vuelve obligatoria en producción.
- Confirmar que los datos de ejemplo del negocio ficticio están completos y consistentes con SPECS §4.
- Checklist final contra los entregables de SPECS §13.

**Testing estructural:** no aplica testing de código — el DoD es una checklist de entregables, verificada ítem por ítem.

**Definition of Done (checklist de SPECS §13):**
- [ ] Repo funcional con el código del MVP.
- [ ] README público orientado a portfolio, con la decisión de SPECS §8 explicada.
- [ ] Datos de ejemplo del negocio ficticio (Consultorio Odontológico Dr. Franco Aguilar) completos.
- [ ] Guiones de testing estructural documentados (de CP5) presentes en el repo.

**Commits esperados:** README público · ajustes finales de datos de ejemplo si hace falta.

---

## Fuera de alcance de este roadmap

Todo lo listado en SPECS §10 (urgencias, cancelación self-service, WhatsApp verificado, servidor de producción, recordatorios, Google Calendar, cobro de seña, panel visual de configuración) no tiene checkpoint propio — queda para cuando esto se venda a un cliente real (SPECS §11).
