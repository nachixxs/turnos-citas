# ESTADO interno — Turnos / Citas (Portfolio Accelerate.ai)

**Este documento es de uso interno del equipo** (estado del proyecto). Distinto del README público del repo, que se genera recién en CP6 y está orientado a portfolio (ver `metodologia-general-accelerate-ai.md`, sección "README público de cada repo").

## Qué es esto

MVP de agendamiento de turnos por WhatsApp con IA, primera de las 4 automatizaciones genéricas del portfolio de Accelerate.ai. Motor genérico + configuración por negocio — este proyecto usa como demo un negocio ficticio (Consultorio Odontológico Dr. Franco Aguilar). Detalle completo del alcance en `SPECS.md`.

## Estado actual

**Fase:** CP4 cerrado — el MVP funciona de punta a punta por WhatsApp real. Los
cuatro caminos de SPECS §3 se probaron con mensajes de verdad desde un teléfono
al número de prueba de Meta, y el turno creado quedó en la Sheet. 127 tests
pasando. Próximo: CP5.

| CP | Nombre | Estado |
|---|---|---|
| CP1 | Setup + motor de datos | **Hecho** |
| CP2 | Agente Claude (tool use) y ruteo de 4 caminos | **Hecho** |
| CP3 | Endpoint FastAPI + parseo del webhook | **Hecho** |
| CP4 | Orquestación n8n + prueba end-to-end | **Hecho** |
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
│   ├── verificar_webhook.py  # Guion de verificación contra el servidor real
│   ├── configurar_n8n.py     # Renderiza el flujo desde .env, importa y publica
│   ├── configurar_meta.py    # Registra el callback y suscribe la app, por Graph API
│   └── verificar_n8n.py      # El flujo, contra un doble de la Graph API
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
│   └── flow.template.json    # El flujo, con placeholders en vez de secretos
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

Arrancar CP5: testing estructural de los bordes de SPECS §7 y §8, empezando por
el hallazgo abierto del final de este documento, que ya se confirmó en
producción. Ver `ROADMAP.md`.

## Lo que salió de la verificación de CP3 y condicionó CP4

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

## CP4 — lo que ya está preparado

Todo lo que no depende de Meta está armado y verificado. **El flujo completo se
probó de punta a punta sin Meta**: 6/6 casos, reemplazando solo a la Graph API
por un doble local que registra el POST que habría salido.

**Entorno, ya confirmado en esta máquina:**

| Pieza | Estado |
|---|---|
| ngrok 3.39.9 | instalado, authtoken configurado |
| n8n 2.6.3 | instalado global por npm, con `import:workflow` y `publish:workflow` |
| Docker | no instalado, y no hace falta |

**Archivos:**

| Archivo | Qué hace |
|---|---|
| `n8n/flow.template.json` | El workflow, con placeholders en vez de secretos |
| `scripts/configurar_n8n.py` | Renderiza con los valores de `.env`, importa y publica |
| `scripts/configurar_meta.py` | Registra el callback y crea `subscribed_apps`, por Graph API |
| `scripts/verificar_n8n.py` | Corre el flujo entero contra un doble de la Graph API |

`n8n/flow.local.json` es el renderizado con el token real y está gitignoreado.
Al repo solo va la plantilla.

**El flujo, 11 nodos:**

```
Webhook GET  → Verificar token → Responder challenge / Rechazar (403)
Webhook POST → Filtrar eventos de estado
                 ├─ hay messages → Llamar a FastAPI → ¿respuesta vacía?
                 │                                      ├─ no → Responder por WhatsApp
                 │                                      └─ sí → Nada para enviar
                 └─ statuses     → Ignorar evento de estado
```

**Las trampas de El Parador, ya resueltas de entrada** (cada una anotada en el
campo `notes` del nodo correspondiente):

| Trampa | Cómo quedó resuelta |
|---|---|
| `localhost` resuelve a IPv6 en Windows | El nodo llama a `http://127.0.0.1:8000` |
| El "9" de los números argentinos | `.replace(/^549(\d+)$/, '54$1')` antes de enviar |
| Expresiones `$json` implícitas | Se referencia el nodo por nombre: `$('Llamar a FastAPI')` |
| Nodos "resource mapper" solo configurables por UI | No hay ninguno: la Sheet la escribe FastAPI |
| Guardar no es publicar | `configurar_n8n.py` corre `publish:workflow` |
| Activar por API no registra el webhook | El guion avisa que hay que reiniciar n8n |
| El puerto 5678 abre antes de registrar los webhooks | `verificar_n8n.py` sondea la URL hasta que deja de dar 404 |
| El enlace invisible `subscribed_apps` | `configurar_meta.py` lo crea y lo verifica leyéndolo de vuelta |

**Ojo:** el workflow que quedó cargado en n8n tiene **valores de mentira** (token
falso y la Graph API apuntando al doble local). Correr `configurar_n8n.py` con el
`.env` real lo pisa; hasta entonces no manda nada a WhatsApp de verdad.

## CP4 — el estado de Meta

La app ya está creada y los seis valores están cargados en `.env`, verificados
contra la Graph API. Ningún valor real se versiona: acá se describe qué es cada
cosa, no cuánto vale.

| Qué | Estado |
|---|---|
| App de Meta | creada, **nueva**, separada de la de El Parador |
| Token | **de usuario de sistema, permanente** — no vence, no hay que renovarlo |
| Permisos del token | `whatsapp_business_management`, `whatsapp_business_messaging` |
| Acceso del token al WABA | confirmado (lee `subscribed_apps` sin 403) |
| Número de prueba | el que Meta asigna, con su `phone_number_id` en `.env` |
| Callback registrado en Meta | **no** — lo hace `scripts/configurar_meta.py` |
| App suscrita al WABA | **no** — lo hace el mismo guion |

**El WABA de prueba es compartido, y no hay forma de que no lo sea.** Meta da un
solo "Test WhatsApp Business Account" por cuenta de desarrollador, así que el
mismo WABA que usa Turnos ya tiene suscrita la app de El Parador
(`Accelerate Restaurant Bot`). Eso está bien y no rompe nada: la **URL del
webhook se configura por app**, y como la app de Turnos es nueva, tiene la suya
propia y la de El Parador queda intacta.

La consecuencia práctica sí importa: **los dos bots reciben los mensajes de ese
número**. Mientras se trabaje en Turnos, no levantar el stack de El Parador, o
los dos van a contestar el mismo mensaje.

**Por qué un token de sistema y no el temporal.** El temporal del panel dura
24hs, y cuando vence el síntoma es que todo funcionaba y de golpe los envíos
fallan con un error de permisos que no apunta al token — el bug que en El Parador
apareció una y otra vez. El de sistema se crea en business.facebook.com →
Business settings → Users → System users, y hay que darle acceso a **dos**
activos, no uno: la app y la WhatsApp Account. Si falta el segundo, el token se
genera igual pero después tira 403 al tocar el WABA.

## CP4 — el orden exacto

Lo único manual es el paso 1: no existe Graph API para crear apps.

1. ~~Crear la app de Meta y cargar `.env`~~ — **hecho**, ver "el estado de
   Meta" arriba. Lo único que puede faltar es tener tu número cargado como
   destinatario de prueba en el panel (WhatsApp → API Setup → desplegable "To").
2. `ngrok http 5678` — la URL pública la leen los guiones solos.
3. `configurar_n8n.py`, y **reiniciar n8n**.
4. `configurar_meta.py` — registra el callback y crea `subscribed_apps`.
5. `verificar_n8n.py` — el flujo, antes de meter a Meta en el medio.
6. Conversación real por WhatsApp, un mensaje por cada camino de SPECS §3.

Si algo falla en el paso 6, el orden de sospecha es: `subscribed_apps` primero
(es invisible y fue lo más caro en El Parador), después si reiniciaste n8n, y
recién al final la lógica del workflow.

## CP4 — cómo quedó cerrado

El orden de arriba se siguió tal cual y funcionó. Los cuatro caminos de SPECS §3
se probaron con mensajes reales desde un teléfono al número de prueba, y cada uno
se verificó contra el dato concreto, no contra el texto:

| Camino | `estado` | Tool | Verificado contra |
|---|---|---|---|
| Turno nuevo | `turno_confirmado` | `crear_turno` | fila nueva en la Sheet: `2026-08-20 · 10:00 · limpieza` |
| FAQ | `consulta_general` | `consulta_general {tema: precios}` | texto idéntico a `respuesta_faq("precios", config)` |
| Cancelación | `sin_tool` | ninguna | texto idéntico a `mensaje_cancelacion(config)` |
| Repregunta | `sin_tool` | ninguna | pidió el servicio faltante sin inventar ninguno |

Los dos textos comparables salieron **carácter por carácter** iguales a la
constante del código. El de cancelación lo redacta el modelo, y aun así respetó
la plantilla palabra por palabra con el teléfono tomado de `negocio.json`.

**De dónde salió cada dato.** Los textos exactos que se enviaron no se leyeron
del teléfono: están en la base de n8n (`~/.n8n/database.sqlite`, tablas
`execution_entity` y `execution_data`), que guarda la salida de cada nodo. El
formato es `flatted` —un array plano donde los strings numéricos son referencias
a otras posiciones—, así que hay que rehidratarlo antes de poder leerlo. La
entrega se confirmó con los eventos de estado que Meta devuelve al propio
webhook: `sent` y después `delivered`.

**La trampa del "9", confirmada.** Meta respondió `input: 542625634845` a un
`telefono: 5492625634845`, así que el `.replace()` del nodo de envío hizo lo suyo
contra la Graph API real, no solo contra el doble.

### Las tres sorpresas de CP4

**El dominio de ngrok es estático, no cambia.** La cuenta gratuita de ngrok da un
dominio fijo, así que la URL pública sobrevive a los reinicios del túnel. Eso
contradice lo que decía la nota de `configurar_meta.py` y tiene una consecuencia
concreta: la app de El Parador tiene registrado su callback **en este mismo
dominio**, y por eso Meta le postea a `/webhook/restaurante-colo-dia2` por el
túnel de Turnos. Con el workflow despublicado eso devuelve 404 y Meta reintenta:
es ruido esperable en el inspector de ngrok, no un error.

**El Parador comparte la instancia de n8n, y eso alcanza para que conteste.** El
riesgo anotado antes era "no levantes el stack de El Parador". Es más fino que
eso: su workflow vive en la **misma** instancia de n8n, queda activo con solo
correr `n8n start`, y su nodo "Llamar a FastAPI" apunta a
`http://127.0.0.1:8000/webhook` — exactamente el puerto de Turnos. Si los dos
están publicados, un mensaje al número de prueba hace que El Parador llame al
FastAPI **de Turnos**, mande la respuesta con sus propias credenciales y encima
intente un `Append row` en la Sheet del restaurante.

La solución es despublicarlo mientras se trabaja en Turnos:

```powershell
n8n unpublish:workflow --id=PtRTAyRQc8o19Zg7   # y reiniciar n8n
n8n publish:workflow --id=PtRTAyRQc8o19Zg7     # para revertirlo
```

Despublicar tiene la misma trampa que publicar: **no toma efecto hasta reiniciar
n8n**.

**No se le puede escribir primero al paciente.** WhatsApp solo deja mandar un
mensaje libre dentro de las 24hs desde que la persona escribió. Fuera de esa
ventana Meta acepta el POST y devuelve un `wamid` —parece que salió bien— pero
después reporta `failed` con `131047 Re-engagement message` en el webhook de
estado. Consecuencia práctica: `configurar_meta.py --enviar` solo sirve si el
destinatario escribió hace poco, y toda prueba real arranca con un mensaje
entrante. No es un bug del proyecto y no hay nada que arreglar en el MVP.

Ojo con no confundirlo con `131030 Recipient phone number not in allowed list`,
que sí significa que falta cargar el número en el panel. En esta cuenta el
número ya está cargado.

### Cambio en `verificar_n8n.py`

El guion se escribió para correr contra el doble de la Graph API y no servía tal
cual contra el workflow real: tenía el verify token fijo en `"prueba-local"` y
los casos de envío esperaban que el POST cayera en el doble. Ahora el token sale
de `META_VERIFY_TOKEN` y, si el workflow importado apunta a Meta, los cuatro
casos de envío quedan **omitidos** en vez de fallar — medirían cómo está
configurado el flujo, no el flujo. Contra el workflow real da `2/2 (4 omitidos)`;
contra el doble sigue dando 6/6.

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

**Confirmado en producción durante CP4.** Con un mensaje real por WhatsApp
(`quiero un turno el jueves a las 11`) el bot contestó:

> "¡Hola! Para el jueves 20 a las 11 tengo lugar 🙂 ¿Qué necesitás: control,
> limpieza dental o extracción?"

`estado: sin_tool`, ninguna tool llamada. Lo que agrega esta corrida: **esa vez
la afirmación era cierta** —las 11 estaban libres— y aun así el modelo no tenía
cómo saberlo. Que acierte por casualidad es lo que hace que el bug pase
desapercibido hasta que el horario esté ocupado.

## Documentos relacionados

- `SPECS.md` — qué se construye y por qué (cerrado).
- `ROADMAP.md` — plan de checkpoints con Definition of Done y testing.
- `CODESTYLE.md` — convenciones de código de este proyecto.
