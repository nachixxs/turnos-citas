# ROADMAP — Turnos / Citas (Portfolio Accelerate.ai)

Plan de construcción del MVP, dividido en checkpoints verificables. Cada checkpoint se cierra con testing estructural (contra datos/constantes reales del código, nunca por si la respuesta "suena bien") y con commits chicos a medida que se avanza — el checkpoint marca el punto de verificación, no la unidad de commit.

Referencia de alcance y decisiones de producto: `SPECS.md`. Este documento no repite el "qué" ni el "por qué" — solo el orden de construcción.

## Resumen

| CP | Nombre | Depende de | Estado |
|---|---|---|---|
| CP1 | Setup + motor de datos | — | **Hecho** |
| CP2 | Agente Claude (tool use) y ruteo de 4 caminos | CP1 | **Hecho** |
| CP3 | Endpoint FastAPI + parseo del webhook | CP2 | Pendiente |
| CP4 | Orquestación n8n + prueba end-to-end | CP3 | Pendiente |
| CP5 | Testing estructural completo | CP4 | Pendiente |
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
- Invocación del agente de CP2 con el mensaje del cliente.
- Formato de respuesta compatible con el nodo "Respond to Webhook" de n8n.

**Testing estructural:** con un payload fixture (ejemplo real de la estructura de Meta), el endpoint debe extraer teléfono y nombre correctamente y devolver el shape de respuesta esperado — verificado contra la estructura del JSON, no contra el contenido del mensaje.

**Definition of Done:**
- El endpoint responde 200 con el shape esperado ante un payload fixture válido.
- Teléfono y nombre de perfil se resuelven del payload, nunca de la extracción de la IA.
- Manejo básico de payload malformado (no rompe el proceso).

**Commits esperados:** endpoint base FastAPI · parseo de payload de WhatsApp · integración endpoint↔agente · formato de respuesta para n8n · tests del endpoint con fixture.

---

## CP4 — Orquestación n8n + prueba end-to-end

**Objetivo:** conectar el número de WhatsApp de prueba con el endpoint de CP3 a través de n8n y validar el flujo real de punta a punta.

**Tareas:**
- Flujo n8n: Webhook → IF → Respond to Webhook.
- Configuración del número de prueba de WhatsApp Cloud API (Meta).
- Conexión del Webhook de n8n al endpoint de CP3.

**Testing estructural:** conversación real con el número de prueba cubriendo al menos un caso de cada uno de los 4 caminos, verificado contra qué pasó realmente (turno guardado en la Sheet, tool llamada, mensaje fijo de cancelación mostrado) — no contra si "se sintió bien" la charla.

**Definition of Done:**
- Al menos un mensaje real de cada camino (turno nuevo, FAQ, cancelación, repregunta) llega, se procesa y responde correctamente de punta a punta.
- Un turno creado por este flujo aparece efectivamente en la Sheet.

**Commits esperados:** export del flujo n8n versionado en el repo · ajustes de configuración de conexión · notas de troubleshooting si aparecen (documentadas, no solo resueltas en la UI de n8n).

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

**Testing estructural:** cada caso se verifica contra el dato real esperado (id de servicio devuelto, slot ofrecido, tool llamada o no llamada), documentado en el propio guion de testing — no evaluación subjetiva de la respuesta en texto.

**Definition of Done:**
- Todos los casos de la lista están documentados en un guion de testing con input, comportamiento esperado y resultado real obtenido.
- Ningún caso queda marcado como "parece que anda bien" sin verificación contra un dato concreto.

**Commits esperados:** guion de testing de bordes · fixes que salgan de los casos encontrados (cada uno en su propio commit, no agrupados).

---

## CP6 — README de portfolio + cierre

**Objetivo:** dejar el repo listo para mostrarse a un lead o reclutador.

**Tareas:**
- README público del repo, enfocado en la decisión técnica no obvia de SPECS §8 (grilla fija de 30 min vs. validación por solapamiento de intervalos) — por qué se descartó la alternativa, no solo qué hace el proyecto.
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
