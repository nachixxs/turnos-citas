# ESTADO — Turnos / Citas (Portfolio Accelerate.ai)

Bitácora de construcción del proyecto: qué se decidió, qué salió mal y qué se
descubrió tarde en cada checkpoint. El `README.md` cuenta qué es el proyecto y
por qué; este documento cuenta cómo se llegó hasta ahí, sin limar las partes
feas.

Los datos operativos de otros proyectos de la agencia no viven acá: están en un
archivo local que no se versiona.

## Qué es esto

MVP de agendamiento de turnos por WhatsApp con IA, primera de las 4 automatizaciones genéricas del portfolio de Accelerate.ai. Motor genérico + configuración por negocio — este proyecto usa como demo un negocio ficticio (Consultorio Odontológico Dr. Franco Aguilar). Detalle completo del alcance en `SPECS.md`.

## Estado actual

**Fase:** **MVP terminado.** Los seis checkpoints están cerrados. 148 tests,
`verificar_agente.py` 15/15, `verificar_n8n.py` 7/7, y los cuatro entregables de
SPECS §13 verificados uno por uno.

| CP | Nombre | Estado |
|---|---|---|
| CP1 | Setup + motor de datos | **Hecho** |
| CP2 | Agente Claude (tool use) y ruteo de 4 caminos | **Hecho** |
| CP3 | Endpoint FastAPI + parseo del webhook | **Hecho** |
| CP4 | Orquestación n8n + prueba end-to-end | **Hecho** |
| CP5 | Testing estructural completo | **Hecho** |
| CP6 | README de portfolio + cierre | **Hecho** |

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

### Levantar el stack completo (CP4)

El orden importa y cada paso depende del anterior. En terminales aparte:

```powershell
# 0. Sacar del medio al otro workflow de la agencia. Comparte esta instancia de n8n y el
#    puerto 8000: si queda publicado, contesta el mismo mensaje y escribe
#    en la planilla de ese otro proyecto. No toma efecto hasta reiniciar n8n.
n8n unpublish:workflow --id=<ID_DEL_OTRO_WORKFLOW>

# 1. El tunel. La URL publica la leen los guiones solos de 127.0.0.1:4040.
ngrok http 5678

# 2. El backend.
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# 3. El workflow, con n8n FRENADO. Esto pisa lo que hubiera importado antes.
.venv\Scripts\python.exe scripts\configurar_n8n.py

# 4. n8n. Arrancarlo DESPUES de importar, no antes.
n8n start

# 5. Meta: registra el callback y crea subscribed_apps. Idempotente.
.venv\Scripts\python.exe scripts\configurar_meta.py

# 6. El flujo, antes de meter a Meta en el medio.
.venv\Scripts\python.exe scripts\verificar_n8n.py
```

Entre el 4 y el 5, esperar a que n8n registre los webhooks: el puerto 5678
acepta conexiones antes de que la URL responda, y en el medio da 404 aunque el
workflow figure publicado. `verificar_n8n.py` ya sondea hasta que deja de dar
404.

El paso 0 no es opcional y no hay nada en el código que lo garantice: se
decidió a propósito no cambiar el puerto de Turnos para no tocar el repo por un
problema de convivencia entre proyectos, así que **depende de acordarse**. El
detalle de qué pasa si se olvida está en "las tres sorpresas de CP4".

## Próximo paso

El MVP está cerrado; no queda trabajo de código pendiente. Lo que sigue está
fuera del repo:

- **La nota del proyecto en el vault.** `02-Projects/Turnos-Citas/` tiene solo
  la carpeta `repo/`, sin `Overview.md` ni `Bugs-and-Lessons.md`. Dos cosas de
  CP5 son lección genuina y no viven bien en un README de portfolio: por qué una
  blocklist de frases no verifica una propiedad semántica, y el patrón general
  de "si el texto no puede variar, verificarlo es trivial".
- **Republicar el otro workflow** cuando se vuelva a ese proyecto:
  `n8n publish:workflow --id=<ID_DEL_OTRO_WORKFLOW>` y reiniciar n8n.

Si el MVP se muestra a un lead o se vende a un cliente real, lo primero de la
lista de SPECS §11 en volverse obligatorio es la verificación de la firma del
webhook.

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

**Las trampas que ya habían aparecido en el proyecto anterior, resueltas de entrada** (cada una anotada en el
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
| App de Meta | creada, **nueva**, separada de la del proyecto anterior |
| Token | **de usuario de sistema, permanente** — no vence, no hay que renovarlo |
| Permisos del token | `whatsapp_business_management`, `whatsapp_business_messaging` |
| Acceso del token al WABA | confirmado (lee `subscribed_apps` sin 403) |
| Número de prueba | el que Meta asigna, con su `phone_number_id` en `.env` |
| Callback registrado en Meta | **no** — lo hace `scripts/configurar_meta.py` |
| App suscrita al WABA | **no** — lo hace el mismo guion |

**El WABA de prueba es compartido, y no hay forma de que no lo sea.** Meta da un
solo "Test WhatsApp Business Account" por cuenta de desarrollador, así que el
mismo WABA que usa Turnos ya tiene suscrita la app del proyecto anterior
(la del otro proyecto). Eso está bien y no rompe nada: la **URL del
webhook se configura por app**, y como la app de Turnos es nueva, tiene la suya
propia y la del otro queda intacta.

La consecuencia práctica sí importa: **los dos bots reciben los mensajes de ese
número**. Mientras se trabaje en Turnos, no levantar el stack del otro proyecto, o
los dos van a contestar el mismo mensaje.

**Por qué un token de sistema y no el temporal.** El temporal del panel dura
24hs, y cuando vence el síntoma es que todo funcionaba y de golpe los envíos
fallan con un error de permisos que no apunta al token — el bug que en el proyecto anterior apareció una y otra vez. El de sistema se crea en business.facebook.com →
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
(es invisible y fue lo más caro en el proyecto anterior), después si reiniciaste n8n, y
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
concreta: la app del otro proyecto tiene registrado su callback **en este mismo
dominio**, y por eso Meta le postea a la ruta de su propio webhook por el
túnel de Turnos. Con el workflow despublicado eso devuelve 404 y Meta reintenta:
es ruido esperable en el inspector de ngrok, no un error.

**El otro proyecto comparte la instancia de n8n, y eso alcanza para que conteste.** El
riesgo anotado antes era "no levantes el stack del otro proyecto". Es más fino que
eso: su workflow vive en la **misma** instancia de n8n, queda activo con solo
correr `n8n start`, y su nodo "Llamar a FastAPI" apunta a
`http://127.0.0.1:8000/webhook` — exactamente el puerto de Turnos. Si los dos
están publicados, un mensaje al número de prueba hace que el otro llame al
FastAPI **de Turnos**, mande la respuesta con sus propias credenciales y encima
intente un `Append row` en la planilla de ese otro proyecto.

La solución es despublicarlo mientras se trabaja en Turnos:

```powershell
n8n unpublish:workflow --id=<ID_DEL_OTRO_WORKFLOW>   # y reiniciar n8n
n8n publish:workflow --id=<ID_DEL_OTRO_WORKFLOW>     # para revertirlo
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

### El webhook no verifica la firma de Meta

Apareció al revisar los pendientes de CP4. Meta firma cada payload con
`X-Hub-Signature-256` usando el app secret, y no se comprueba en ningún lado: ni
en el workflow de n8n ni en FastAPI. El endpoint procesa cualquier POST que
llegue a la URL pública.

**La evidencia es del propio CP4.** La "corrida en seco" que se hizo antes de la
prueba real fue exactamente eso: un payload fabricado a mano, posteado al webhook
público, que recorrió la cadena entera —Claude, lectura de la Sheet y un POST
real a la Graph API— sin ninguna credencial. No hizo falta ningún exploit, es el
comportamiento normal del endpoint.

**Se declara fuera de alcance, no se arregla** (SPECS §10). El número es de
prueba, la URL es un túnel que se levanta a mano para demostrar y no hay datos de
terceros en juego. Lo que cambia es que pasa a ser una omisión explicada en vez
de un olvido, y entra al README de CP6 como limitación conocida.

Esto también reordena la prioridad del `META_VERIFY_TOKEN` de más abajo: ese
token solo gobierna el handshake de registro del GET, así que quien lo tenga
puede a lo sumo hacer que el webhook devuelva el `hub.challenge`. La puerta de
entrada real es que el POST no pide nada. Rotarlo sigue siendo lo correcto, pero
por prolijidad y no por riesgo.

### En qué estado quedó la máquina al cerrar CP4

| Cosa | Cómo quedó | Qué hacer |
|---|---|---|
| ngrok, uvicorn, n8n | frenados | levantarlos con los 6 pasos de "Levantar el stack completo" |
| Workflow de Turnos | importado desde el `.env` real y publicado | nada |
| Workflow del otro proyecto | **despublicado** | `n8n publish:workflow --id=<ID_DEL_OTRO_WORKFLOW>` y reiniciar n8n, cuando se vuelva a ese proyecto (el id está en las notas locales) |
| Callback en Meta | registrado, campo `messages`, app suscrita al WABA | nada mientras el dominio de ngrok no cambie |
| Turno de prueba en la Sheet | `2026-08-20 · 10:00 · limpieza` | **dejarlo**: es la evidencia del DoD de CP4 y sirve de slot ocupado para CP5 |

**`META_VERIFY_TOKEN` rotado el 2026-08-19.** Durante CP4 el token quedó
expuesto en el historial de una sesión de Claude Code, al imprimir las URLs
completas del inspector de ngrok — el token viaja en el query string del GET de
verificación. Era prolijidad y no urgencia (ver la sección de la firma más
arriba: este token no es la puerta de entrada), pero ya está hecho. Verificado
después de rotarlo: el token nuevo devuelve el `hub.challenge` con 200 y el
viejo da 403.

**Cómo rotarlo, si vuelve a hacer falta.** Son cuatro pasos, y van los cuatro o
ninguno: si el valor de `.env` y el que quedó dentro del workflow no coinciden,
Meta no puede verificar la URL y deja de entregar mensajes.

1. Cambiar el valor en `.env` por uno nuevo.
2. `configurar_n8n.py`, que lo reescribe dentro del workflow.
3. Reiniciar n8n.
4. `configurar_meta.py`, que lo vuelve a registrar en Meta.

Que el paso 4 diga "registrada" ya es la prueba de que el token nuevo funciona:
para registrar el callback, Meta le pega al webhook con ese token y espera el
challenge de vuelta. Si el workflow tuviera el viejo, ese paso fallaría.

## El hallazgo de CP4, y cómo se cerró en CP5

**En el camino de repregunta, el modelo afirma disponibilidad que no verificó.**
Apareció en el caso 6 del guion de CP3, en las dos corridas:

> "El 16/9 a las 10:00 lo tengo anotado. ¿Para qué servicio lo querés?"

En ese camino no se llama a ninguna tool, así que la Sheet nunca se leyó: el
modelo no tiene forma de saber si ese slot está libre, y "lo tengo anotado"
además sugiere que ya quedó reservado. Si el horario estaba ocupado, el paciente
contesta el servicio y el bot se contradice ofreciéndole alternativas.

No es un fallo del endpoint —el ruteo y el `estado` son correctos— sino del
texto que redacta el modelo.

**Confirmado en producción durante CP4.** Con un mensaje real por WhatsApp
(`quiero un turno el jueves a las 11`) el bot contestó:

> "¡Hola! Para el jueves 20 a las 11 tengo lugar 🙂 ¿Qué necesitás: control,
> limpieza dental o extracción?"

`estado: sin_tool`, ninguna tool llamada. Lo que agrega esta corrida: **esa vez
la afirmación era cierta** —las 11 estaban libres— y aun así el modelo no tenía
cómo saberlo. Que acierte por casualidad es lo que hace que el bug pase
desapercibido hasta que el horario esté ocupado.

### El problema no era el fix, era cómo verificarlo

El fix se veía obvio desde CP4 —una regla en el prompt— y el problema real
estaba en otro lado: **este es un bug de texto, y CODESTYLE prohíbe verificar si
una respuesta "suena bien"**. Los 12 casos del guion miran qué tool se llamó y
con qué argumentos; ninguno mira el texto.

"Afirmar disponibilidad" es una propiedad semántica. Buscar frases prohibidas
("tengo lugar", "está libre") no la verifica: es una lista escrita a mano que el
modelo esquiva sin proponérselo, con un "¡Perfecto! ¿Qué servicio?" que afirma
lo mismo sin usar ninguna de esas palabras. Un check así atrapa la frase que ya
viste, no la propiedad — un test de regresión de un string disfrazado de
garantía.

La salida fue la que el proyecto ya venía usando en otros lados: **si el texto
no puede variar, verificarlo es trivial.**

### Qué se hizo

**La repregunta dejó de ser texto libre y pasó a ser una tool.**
`pedir_dato_faltante(datos: ["servicio" | "fecha" | "hora"])`, con el mismo enum
cerrado que `consulta_general`. El camino 4 antes caía en `sin_tool` y devolvía
lo que hubiera escrito el modelo; ahora devuelve `estado: dato_faltante` y el
texto lo compone `respuestas.py`, como ya pasaba con la confirmación de turno y
con las alternativas desde CP3.

**La firma es el fix.** `_texto_dato_faltante(datos, config)` no recibe la fecha
ni la hora que pidió el paciente. No puede afirmar que ese horario esté libre
porque no lo conoce. Eso no es una regla que alguien tenga que respetar: es lo
único que la función puede hacer.

**El prompt igual lleva la regla**, en un bloque nuevo `QUÉ NO PODÉS SABER`: el
modelo no ve la agenda, la disponibilidad se verifica recién al llamar a
`crear_turno`, y no vale insinuarla con un "perfecto" ni un "dale" antes de
repreguntar. La tool es la red de contención; esta regla ataca la causa.

**La diferencia entre las dos mitades importa.** Con un fix de prompt solo, una
desobediencia del modelo llega igual al paciente y recién se detecta si alguien
corre el guion. Con la tool, si el modelo desobedece el caso falla ruidosamente
(`tool: esperaba pedir_dato_faltante, vino ninguna`) **y** el paciente recibe la
constante igual. El mal texto dejó de ser algo que se detecta después y pasó a
ser algo que no sale.

### Cómo quedó verificable

| Nivel | Qué verifica |
|---|---|
| `test_agent_routing.py` | El resultado de una repregunta no transporta ningún slot: `fecha is None`, `alternativas == []`, `turno is None`. |
| `test_respuestas.py` | Las **7** combinaciones no vacías de datos faltantes, exhaustivas: ninguna produce un solo dígito. |
| `test_endpoint.py` | Sobre el body que sale a n8n: si el modelo escribe el texto de producción de CP4 *y además* llama a la tool, el paciente no lo ve. |
| `verificar_agente.py`, caso 13 | Contra la API real, con el mensaje textual de producción. |

El test de los dígitos es el que reemplaza a la lista de frases prohibidas.
Una afirmación sobre un slot tiene que nombrar el slot, y un slot siempre lleva
dígitos ("las 11", "el 20/8", "11:00"). Es exhaustivo justamente porque el texto
ya no lo escribe el modelo: el espacio de salidas es finito y está en el repo.

Como efecto secundario, los nombres de servicio en la repregunta van **sin
precios**: repreguntar qué servicio necesita no es responder cuánto sale. Eso
además es lo que deja el texto sin un solo dígito.

### El escenario del guion ahora hace falsa la afirmación

`TURNOS_TOMADOS` tiene ocupado el jueves 20 a las 11:00 — el slot exacto de la
reproducción en producción. Con el slot tomado, un "tengo lugar" ahí es
demostrablemente falso en vez de cierto por casualidad. Esa era la propiedad que
faltaba para que el caso valga algo.

## CP5 — cómo quedó cerrado

Casi todo el checkpoint es de nivel agente: `pytest` y `verificar_agente.py`
alcanzaron para el fix. Al final sí se levantó el stack, pero **sin ngrok y sin
Meta**, para cerrar el único cabo suelto que dejaba el estado nuevo (ver abajo).

**La corrida real: 15/15.** El guion pasó de 12 a 15 casos y todos coincidieron
con lo esperado en la primera corrida después del fix.

| # | Caso | Verificado contra |
|---|---|---|
| 13 | Repregunta sobre slot ocupado | `pedir_dato_faltante {datos: ["servicio"]}`, y el texto enviado no nombra ni "jueves", ni "20", ni "11" |
| 14 | Servicio fuera del catálogo | no llamó a `crear_turno` — la sustitución silenciosa es el riesgo real |
| 15 | Urgencia | texto **idéntico** a `mensaje_urgencia(config)` |
| 11, 12 | Repreguntas que ya existían | pasaron de `sin_tool` a `dato_faltante` sin romperse |

Los casos 1 a 10 siguieron dando lo mismo que en CP2.

**Las urgencias ahora tienen un texto fijo** (SPECS §7). El SPECS dice qué *no*
hacer —no ofrecerlas como opción, no responder con información específica— pero
no dice qué hacer, y sin una regla el modelo improvisa justo ahí. Es el peor
lugar posible para improvisar: del otro lado hay alguien con dolor que necesita
llegar a un humano. Se resolvió con el mismo patrón que la cancelación:
`PLANTILLA_URGENCIA` en el código, teléfono del config, texto dictado por el
prompt.

Que sea una constante es lo que hace verificable el "no da información
específica": **la plantilla no tiene una sola cifra**, así que no puede ofrecer
un horario, un precio ni una fecha. La única cifra del mensaje final es el
teléfono, que entra por el config. Contra la API real el modelo la reprodujo
palabra por palabra, igual que había hecho con la de cancelación en CP4.

### El estado nuevo, verificado también por n8n

`dato_faltante` no existía cuando se armó el workflow, así que había que
comprobar que el flujo lo rutea bien. **No hizo falta tocar nada:** el nodo
`Hay algo para responder` rutea por `respuesta` no vacía y no por `estado`, y
una repregunta siempre trae respuesta.

Pero eso era una deducción de leer el JSON del workflow, no una verificación, y
la diferencia importa. Se agregó un séptimo caso a `verificar_n8n.py` y se corrió
el circuito real —n8n → FastAPI → Claude → Sheets → envío— con el doble local en
lugar de la Graph API. **7/7.** Lo que salió hacia el envío:

```
7. Repregunta - el texto que sale no nombra el horario pedido
   to   : 542615550199
   texto: ¿Qué necesitás: Control, Limpieza dental o Extracción?
   [OK]
```

Idéntico a lo que compone `respuestas.py`. El mensaje de entrada pedía "un turno
para el jueves a las 11" y lo que salió no nombra ni el día ni la hora: el
hallazgo, cerrado de punta a punta y no solo a nivel agente.

**Una trampa al correrlo, que no es del flujo.** `verificar_n8n.py` toma el
verify token de `META_VERIFY_TOKEN` —del entorno si está exportada, del `.env` si
no—, y tiene que ser el mismo que quedó dentro del workflow importado. Si se
importa con `META_VERIFY_TOKEN="prueba-local"` y después se corre el guion sin
exportarla, el caso 1 da 403 y parece un fallo del workflow. No lo es: hay que
exportar la misma variable en las dos terminales.

### Dos cosas que aparecieron y no se tocaron

**No hay historial de conversación, y el camino de repregunta lo necesita.**
`decidir()` manda `messages=[{"role": "user", "content": mensaje}]` y no hay
estado en ninguna parte del endpoint: cada mensaje es una llamada aislada. O
sea que **la repregunta no puede completarse**: el paciente contesta "control" y
el modelo arranca de cero, sin saber qué se le preguntó.

Eso agranda el hallazgo en vez de achicarlo — la afirmación falsa era lo único
que el paciente se llevaba de ese camino. Pero arreglarlo es una feature entera
(persistir el hilo por teléfono, decidir cuándo expira), no un fix de borde, y
CP5 es el checkpoint de los bordes. Queda anotado para el README de CP6 como
limitación conocida, junto con la firma del webhook.

**El camino `sin_tool` sigue siendo por donde sale prosa del modelo.** Ahora
tiene tres usos, y solo dos están dictados:

| Uso | Texto |
|---|---|
| Cancelación (SPECS §9) | dictado por el prompt, verificado contra la constante |
| Urgencia (SPECS §7) | dictado por el prompt, verificado contra la constante |
| Todo lo demás | libre |

El caso 14 cae en el tercero: ante "quería hacerme un blanqueamiento" el modelo
contestó de su cosecha que no lo hacen y listó el catálogo con precios. Los
precios que dijo son los del config —están en el prompt—, pero los redactó él,
no `respuesta_faq`. **Se deja así**: un servicio fuera del catálogo no es
ninguno de los 4 caminos de SPECS §3, así que no tiene un texto especificado, y
el riesgo que sí importaba —que sustituya el servicio y agende otra cosa— está
cubierto y verificado. Vale tenerlo anotado por si en un cliente real hace falta
cerrarlo.

### En qué estado quedó la máquina al cerrar CP5

| Cosa | Cómo quedó | Qué hacer |
|---|---|---|
| uvicorn, n8n | **frenados**, puertos 8000 / 5678 / 8099 libres | levantarlos con los 6 pasos de "Levantar el stack completo" |
| ngrok | nunca se levantó en CP5 | — |
| Workflow de Turnos | **reimportado desde el `.env` real** y publicado, después de la verificación | reiniciar n8n antes de usarlo |
| Workflow del otro proyecto | **despublicado** (se volvió a correr el paso 0, es idempotente) | `n8n publish:workflow --id=<ID_DEL_OTRO_WORKFLOW>` y reiniciar n8n, cuando se vuelva a ese proyecto (el id está en las notas locales) |
| Callback en Meta | intacto, no se tocó | nada |
| Sheet | **no se escribió nada en CP5** | nada |

Durante la verificación el workflow estuvo importado apuntando al doble local,
con token y `phone_id` de mentira. Eso se revirtió corriendo `configurar_n8n.py`
con el `.env` real, y está confirmado: `n8n/flow.local.json` ya no contiene
`127.0.0.1:8099`. **Igual hace falta reiniciar n8n** para que el workflow
repuesto tome efecto — publicar no basta.

## CP6 — cómo quedó cerrado

Checkpoint de redacción, sin código. El README quedó centrado en **dos**
decisiones técnicas y no en una: además de la grilla fija de slots que pedía
ROADMAP (SPECS §8), el hallazgo de CP5 al mismo nivel. La razón es que el
hallazgo es el mejor material del repo para el rol al que apunta — un bug de LLM
real, con una hipótesis de verificación descartada por escrito y un fix
estructural — mientras que §8 es una decisión de producto.

**Dos ítems del DoD se verificaron con código en vez de a ojo:**

- La consistencia de los datos de ejemplo contra SPECS §4 se comprobó campo por
  campo (nombre, dirección, teléfono, horarios, y los tres servicios con su
  precio y duración), incluyendo que cada valor aparezca literalmente en el
  SPECS. Todo consistente.
- Las afirmaciones del README se chequearon contra el repo: que los archivos
  citados existan, que las tools nombradas estén definidas, que el número de
  tests sea el real y que el snippet de test citado coincida carácter por
  carácter con el archivo. Sin diferencias.

Lo segundo vale la pena como costumbre: un README de portfolio que dice "148
tests" y tiene 130 es peor que no decir el número.

**El documento de metodología no existe.** `ESTADO.md` referenciaba
`metodologia-general-accelerate-ai.md`, sección "README público de cada repo",
para el formato. Ese archivo no está en el vault. El formato se definió acá con
lo que pedía ROADMAP CP6.

## Documentos relacionados

- `SPECS.md` — qué se construye y por qué (cerrado).
- `ROADMAP.md` — plan de checkpoints con Definition of Done y testing.
- `CODESTYLE.md` — convenciones de código de este proyecto.
