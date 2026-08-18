# ESTADO interno — Turnos / Citas (Portfolio Accelerate.ai)

**Este documento es de uso interno del equipo** (estado del proyecto). Distinto del README público del repo, que se genera recién en CP6 y está orientado a portfolio (ver `metodologia-general-accelerate-ai.md`, sección "README público de cada repo").

## Qué es esto

MVP de agendamiento de turnos por WhatsApp con IA, primera de las 4 automatizaciones genéricas del portfolio de Accelerate.ai. Motor genérico + configuración por negocio — este proyecto usa como demo un negocio ficticio (Consultorio Odontológico Dr. Franco Aguilar). Detalle completo del alcance en `SPECS.md`.

## Estado actual

**Fase:** CP3 cerrado — el endpoint expone el agente por HTTP, parsea el payload
de Meta, filtra los eventos de estado, persiste el turno confirmado y devuelve
el shape que consume n8n. 127 tests pasando y 7/7 casos del guion verificados
contra el servidor real, incluida la escritura efectiva en la Sheet. Próximo:
CP4.

| CP | Nombre | Estado |
|---|---|---|
| CP1 | Setup + motor de datos | **Hecho** |
| CP2 | Agente Claude (tool use) y ruteo de 4 caminos | **Hecho** |
| CP3 | Endpoint FastAPI + parseo del webhook | **Hecho** |
| CP4 | Orquestación n8n + prueba end-to-end | Pendiente |
| CP5 | Testing estructural completo | Pendiente |
| CP6 | README de portfolio + cierre | Pendiente |

Detalle de cada checkpoint (tareas, DoD, testing): ver `ROADMAP.md`.

## Stack técnico

- **Backend:** FastAPI + Claude API (tool use)
- **Orquestación:** n8n (Webhook → IF → Respond to Webhook)
- **Canal:** WhatsApp Cloud API (Meta) — número de prueba, sin verificación de negocio
- **Persistencia:** Google Sheets (turnos confirmados)
- **Configuración por negocio:** archivo JSON (`config/negocio.json`), nunca hardcodeado en el código

## Estructura del repo

Lo marcado con `(CPn)` todavía no existe: entra en ese checkpoint.

```
turnos-citas/
├── app/
│   ├── config_loader.py      # Carga y validación del JSON de config
│   ├── availability.py       # Motor de grilla de slots
│   ├── sheets_client.py      # Cliente Google Sheets
│   ├── agent.py              # Agente Claude: prompt, tools, decisión y ejecución
│   ├── formato.py            # Formateo de fechas, horas y precios en español
│   ├── webhook.py            # Parseo del payload de WhatsApp Cloud API
│   ├── respuestas.py         # Composición determinista del mensaje al paciente
│   └── main.py               # FastAPI app, endpoint del webhook
├── config/
│   └── negocio.json          # Configuración del negocio ficticio (SPECS §5)
├── scripts/
│   ├── verificar_sheets.py   # Verificación manual contra la Sheet real
│   ├── verificar_agente.py   # Guion de verificación contra la Claude API real
│   └── verificar_webhook.py  # Guion de verificación contra el servidor real
├── tests/
│   ├── conftest.py           # Fixtures, fechas ancla y cargador de payloads
│   ├── fixtures/             # Payloads reales de Meta (mensaje, estado, audio, roto)
│   ├── test_config_loader.py
│   ├── test_availability.py
│   ├── test_sheets_client.py
│   ├── test_agent_routing.py
│   ├── test_webhook.py       # Parseo del payload
│   ├── test_respuestas.py    # Composición del mensaje al paciente
│   └── test_endpoint.py      # El endpoint de punta a punta, con dobles de red
├── n8n/
│   └── flow.json             # (CP4) Export del flujo de n8n
├── .env.example
├── .gitignore
├── pytest.ini
├── requirements.txt
├── ESTADO.md                 # este archivo
├── README.md                 # (CP6) README público de portfolio
├── SPECS.md
├── ROADMAP.md
└── CODESTYLE.md
```

Esta estructura se ajusta si algo no encaja al construir — se actualiza este documento en ese caso, no se asume fija de antemano.

## Negocio ficticio de la demo

Consultorio Odontológico Dr. Franco Aguilar — un solo profesional, atención particular (sin obra social), 3 servicios (Control, Limpieza dental, Extracción). Datos completos en `SPECS.md` §4.

## Cómo correr el proyecto

Pasos verificados en Windows 11 con PowerShell y Python 3.14.

```powershell
# 1. Entorno virtual e instalación
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Configuración local (una sola vez)
Copy-Item .env.example .env
# completar en .env: GOOGLE_SHEETS_CREDENTIALS_PATH, SPREADSHEET_ID
# y ANTHROPIC_API_KEY

# 3. Tests — no necesitan credenciales ni red
python -m pytest

# 4. Verificación real contra Google Sheets
python scripts/verificar_sheets.py             # solo lectura
python scripts/verificar_sheets.py --escribir  # además escribe y relee

# 5. Verificación real del agente contra la Claude API (12 llamadas)
python scripts/verificar_agente.py             # el guion completo
python scripts/verificar_agente.py --caso 3    # un solo caso

# 6. Servidor del webhook, en una terminal aparte
python -m uvicorn app.main:app --reload --port 8000

# 7. Verificación real del endpoint, con el servidor levantado
python scripts/verificar_webhook.py            # no escribe en la Sheet
python scripts/verificar_webhook.py --con-turno  # además reserva de verdad
```

La Sheet tiene que tener esta fila 1 exacta, y la columna `hora` formateada
como texto:

```
fecha | hora | servicio_id | nombre_paciente | telefono | creado_en
```

Además, hay que compartirla con el email de la service account con permiso de
Editor: sin eso, la API devuelve 403 aunque las credenciales sean válidas.

## Próximo paso

Arrancar CP4: flujo de n8n (Webhook → IF → Respond to Webhook), número de prueba
de WhatsApp Cloud API y prueba end-to-end. Ver `ROADMAP.md`.

Dos cosas que salen de la verificación de CP3 y condicionan CP4:

**El endpoint no envía el mensaje.** Responder 200 al webhook no hace que
WhatsApp le entregue nada al paciente: el envío es un POST aparte a
`graph.facebook.com/<version>/<phone_number_id>/messages` con el token de Meta.
Por eso la respuesta del endpoint trae `telefono` además de `respuesta` — n8n
tiene que armar ese POST con los dos campos.

**El nodo IF rutea por `estado`.** Cuando `respuesta` viene vacía
(`ignorado_evento_estado`, `payload_invalido`) no hay que enviar nada. Es el
filtro que evita contestarle a una notificación de "leído".

## Decisiones de CP3

**De dónde sale el texto que lee el paciente.** Verificado contra la API real en
CP2: cuando el modelo llama a una tool **no escribe texto**. Así que el mensaje
de un turno confirmado o de un slot ocupado se compone de forma determinista en
`app/respuestas.py`, desde el `ResultadoAgente` — no se le pide prosa al modelo.
El único camino donde el texto sí sale del modelo es `sin_tool` (cancelación y
repregunta), donde no hay ningún dato que confirmar.

**Quién persiste el turno.** Lo hace el endpoint, no n8n. La lectura de la Sheet
ya era obligatoria ahí —`aplicar_decision()` recibe los turnos ya leídos para
calcular disponibilidad—, así que dejar la escritura en el mismo proceso evita
una ventana entre validar el slot y ocuparlo. Si la escritura falla, el estado
es `error_al_guardar` y **no** se le confirma el turno al paciente: confirmarle
un turno que no quedó en la agenda es peor que avisarle que falló.

**Qué devuelve el endpoint.** `estado` + `respuesta` + `telefono` + `datos`. El
texto se compone en Python, cubierto por pytest, y no con expresiones en la UI
de n8n; `estado` es sobre lo que rutea el nodo IF. El `telefono` va explícito
porque responder 200 al webhook **no** envía un mensaje de WhatsApp: eso es un
POST aparte a la Graph API, que arma n8n en CP4.

**Siempre 200.** También ante un evento de estado o un payload roto. Un 4xx hace
que n8n marque la ejecución como fallida por notificaciones de "leído" que son
normales, y Meta reintenta ante cualquier respuesta que no sea 2xx.

**Los eventos de estado son el caso frecuente, no el borde.** WhatsApp manda
"enviado", "entregado" y "leído" a la misma URL que los mensajes reales, con un
sobre casi idéntico: `changes[].field` vale `"messages"` en los dos casos. La
única forma confiable de distinguirlos es mirar si viene poblado
`value.messages[]` o `value.statuses[]`. Sin ese filtro, cada notificación
dispara una llamada paga a la Claude API y una lectura de la planilla.

**Mensajes que no son de texto.** Un audio, una foto o un sticker devuelven
`tipo_no_soportado` con un mensaje fijo pidiendo que escriba. No se llama a la
API. Dejarlo sin respuesta haría que el bot parezca roto.

## Hallazgo abierto — para CP5

**En el camino de repregunta, el modelo afirma disponibilidad que no verificó.**
Apareció en el caso 6 del guion de CP3, en las dos corridas:

> "El 16/9 a las 10:00 lo tengo anotado. ¿Para qué servicio lo querés?"

En ese camino no se llama a ninguna tool, así que la Sheet nunca se leyó: el
modelo no tiene forma de saber si ese slot está libre, y "lo tengo anotado"
además sugiere que ya quedó reservado. Si el horario estaba ocupado, el paciente
contesta el servicio y el bot se contradice ofreciéndole alternativas.

No es un fallo del endpoint —el ruteo y el `estado` son correctos— sino del
texto que redacta el modelo. Se corrige en el prompt de sistema: al repreguntar,
no afirmar disponibilidad ni dar por tomado el turno. Queda para CP5, que es
donde viven los fixes que salen de los casos de borde.

## Documentos relacionados

- `SPECS.md` — qué se construye y por qué (cerrado).
- `ROADMAP.md` — plan de checkpoints con Definition of Done y testing.
- `CODESTYLE.md` — convenciones de código de este proyecto.
