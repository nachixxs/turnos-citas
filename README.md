# Turnos / Citas — agendamiento por WhatsApp con IA

MVP funcional de un bot de WhatsApp que toma turnos para un negocio de servicios.
Un agente con Claude API (tool use) decide mensaje a mensaje entre cuatro
caminos, valida la disponibilidad real contra la agenda antes de confirmar, y
persiste el turno en Google Sheets.

El motor es genérico y la configuración por negocio vive en un JSON: nombre,
dirección, horarios, catálogo de servicios y precios. La demo usa un negocio
ficticio — **Consultorio Odontológico Dr. Franco Aguilar**, con todos sus datos
inventados.

```
Paciente → WhatsApp Cloud API → n8n → FastAPI → Claude API
                                        ↓
                                  Google Sheets
```

**Stack:** Python 3.11+ · FastAPI · Claude API (tool use) · n8n · WhatsApp Cloud
API · Google Sheets · Pydantic v2 · pytest

---

## Qué hace

Cuatro caminos, decididos por el modelo en una sola llamada por mensaje:

| El paciente escribe | El bot |
|---|---|
| "quiero una limpieza mañana a las 10" | llama a `crear_turno`, valida el slot y lo guarda |
| "¿cuánto sale una extracción?" | llama a `consulta_general`, responde del catálogo |
| "necesito cancelar el turno del jueves" | deriva al teléfono del consultorio, sin tool |
| "quiero un turno el jueves a las 11" | llama a `pedir_dato_faltante`: falta el servicio |

Y dos bordes que están fuera de alcance a propósito: un servicio que no existe en
el catálogo no se sustituye por otro, y una urgencia se deriva a un humano en vez
de intentar resolverse por chat.

---

## Dos decisiones técnicas

Esta es la parte interesante del repo. Las dos son casos donde la solución obvia
no era la correcta.

### 1. Grilla fija de slots, y no validación por solapamiento de intervalos

Los tres servicios tienen duraciones reales distintas: 20, 30 y 45 minutos. Eso
pide, en teoría, validar disponibilidad por superposición de rangos — que un
turno de 45 minutos a las 10:00 bloquee también las 10:30.

**Se descartó ese enfoque** a favor de una grilla fija de 30 minutos para todos
los servicios, por dos razones:

- **Refleja cómo funciona el negocio de verdad.** Si un turno se atrasa, el
  paciente siguiente espera. Nadie recalcula la agenda. La precisión que da el
  solapamiento de intervalos es precisión sobre un modelo que el consultorio no
  usa.
- **La garantía que importa se cumple igual.** Lo que no puede pasar es que dos
  personas reserven el mismo horario, y eso lo garantiza la grilla fija sin
  construir lógica de intervalos en un MVP de dos días.

El costo es explícito y está asumido: una extracción de 45 minutos ocupa un slot
de 30 y se superpone con el siguiente. En este negocio eso significa que el
odontólogo se atrasa un rato, no que se rompa nada.

Cuando el horario pedido no calza con la grilla o ya está tomado, el bot **nunca
redondea por su cuenta ni rechaza sin más**: devuelve los tres horarios libres
más cercanos para que el paciente elija.

```python
# 09:15 no se convierte en 09:00 ni en 09:30 — se ofrecen opciones.
resultado.estado        # "slot_no_disponible"
resultado.alternativas  # [09:00, 09:30, 10:00]
```

### 2. El bot afirmaba disponibilidad que nunca había verificado

Este apareció en producción, con un mensaje real por WhatsApp:

> **Paciente:** quiero un turno el jueves a las 11
> **Bot:** ¡Hola! Para el jueves 20 a las 11 tengo lugar 🙂 ¿Qué necesitás:
> control, limpieza dental o extracción?

El ruteo era correcto: falta el servicio, así que el modelo repregunta sin llamar
a ninguna tool. **Y ahí está el problema.** Si no se llamó a ninguna tool, la
agenda nunca se leyó. El modelo no tenía forma de saber si las 11 estaban libres,
y aun así lo afirmó. Esa vez acertó de casualidad — que es exactamente lo que
hace que un bug así pase desapercibido hasta que el horario esté ocupado y el bot
se contradiga en el mensaje siguiente.

**Por qué el test obvio no sirve.** Todos los tests de este proyecto verifican
contra un dato concreto: qué tool se llamó, con qué argumentos, qué slot se
devolvió. Nunca contra si una respuesta "suena bien". Pero este es un bug *de
texto*, y "afirmar disponibilidad" es una propiedad semántica.

La tentación es buscar frases prohibidas: `"tengo lugar"`, `"está libre"`,
`"disponible"`. Eso no verifica nada. El modelo esquiva esa lista sin
proponérselo:

> ¡Perfecto! ¿Qué necesitás: control, limpieza o extracción?

Ese texto afirma exactamente lo mismo y no contiene ninguna de esas palabras. Una
blocklist atrapa la frase que ya viste, no la propiedad — es un test de regresión
de un string disfrazado de garantía.

**La solución fue sacarle el texto al modelo.** La repregunta dejó de ser prosa
libre y pasó a ser una tercera tool con vocabulario cerrado:

```python
pedir_dato_faltante(datos: ["servicio" | "fecha" | "hora"])
```

Y el texto pasó a componerse en código. **El fix está en la firma de la
función:**

```python
def _texto_dato_faltante(datos: list[DatoFaltante], config: ConfigNegocio) -> str:
```

No recibe la fecha ni la hora que pidió el paciente. **No puede afirmar que ese
horario esté libre porque no lo conoce.** Eso no es una regla que alguien tenga
que recordar respetar: es lo único que la función puede hacer.

Con el texto vuelto determinista, la verificación se vuelve trivial y exhaustiva.
Una afirmación sobre un horario tiene que nombrar el horario, y un horario
siempre lleva dígitos — "las 11", "el 20/8", "11:00":

```python
def test_la_repregunta_nunca_menciona_un_horario(config):
    """Las 7 combinaciones no vacías de datos faltantes, exhaustivas."""
    for tamanio in (1, 2, 3):
        for combinacion in combinations(DATOS_FALTANTES, tamanio):
            texto = _repregunta(config, *combinacion)
            assert not any(c.isdigit() for c in texto), (combinacion, texto)
```

Eso es exhaustivo justamente porque el texto ya no lo escribe el modelo: el
espacio de salidas es finito y está en el repo.

**El prompt igual lleva la regla** ("no ves la agenda; la disponibilidad se
verifica recién al llamar a `crear_turno`"), pero como causa, no como garantía.
La diferencia entre las dos mitades es el punto:

|  | Solo la regla del prompt | Con la tool además |
|---|---|---|
| Si el modelo desobedece | el texto malo llega al paciente | el paciente recibe la constante igual |
| Cuándo te enterás | si alguien corre el guion | el caso falla ruidosamente |

El mal texto dejó de ser algo que se detecta después y pasó a ser algo que no
sale.

---

## Cómo está armado

Tres separaciones que sostienen el testing:

**Decisión y ejecución, separadas.** `decidir()` habla con la Claude API y
devuelve qué tool eligió el modelo y con qué argumentos. `aplicar_decision()` es
una función pura que aplica esa decisión contra el motor de disponibilidad. La
segunda se testea entera sin credenciales, sin red y sin gastar un peso.

**El texto que lee el paciente lo compone el código, no el modelo.** Verificado
contra la API real: cuando el modelo llama a una tool, no escribe texto. Así que
una confirmación de turno —que tiene que decir exactamente lo que quedó guardado
en la Sheet— se arma en Python desde el resultado. Solo dos caminos usan texto
del modelo, y en los dos el prompt le dicta la plantilla palabra por palabra.

**Nada del negocio está en el código.** Precios, horarios, dirección, teléfono y
catálogo salen de `config/negocio.json`. Los literales del código son plantillas.

```
app/
├── config_loader.py   # carga y valida el JSON (Pydantic v2)
├── availability.py    # grilla de slots, libres/ocupados, alternativas
├── sheets_client.py   # Google Sheets
├── agent.py           # prompt, tools, decisión y ejecución
├── formato.py         # fechas, horas y precios en español
├── webhook.py         # parseo del payload de WhatsApp
├── respuestas.py      # composición determinista del mensaje al paciente
└── main.py            # FastAPI, endpoint del webhook
```

---

## Testing

**148 tests** que corren sin credenciales ni red, más dos guiones de verificación
contra los servicios reales.

| Qué | Cómo se verifica |
|---|---|
| `pytest` (148) | contra datos concretos: tool llamada, argumentos exactos, slot devuelto |
| `verificar_agente.py` (15/15) | contra la Claude API real, con fecha anclada y turnos fijos propios |
| `verificar_n8n.py` (7/7) | el circuito completo, reemplazando solo la Graph API por un doble local |
| `verificar_sheets.py` | contra la planilla real |

La regla es una sola y no tiene excepciones: **cada caso se verifica contra un
dato concreto, nunca contra si el texto "suena bien".** Cuando un caso es
genuinamente sobre texto —como el de la sección anterior— la respuesta no es
relajar la regla: es hacer que el texto deje de ser variable.

Los guiones tienen sus escenarios armados para que un fallo sea demostrable. En
`verificar_agente.py`, el horario del caso del hallazgo está **ocupado** a
propósito: si el bot dijera "tengo lugar", sería falso y no cierto de casualidad.

---

## Limitaciones conocidas

Todas son decisiones explícitas de alcance de un MVP de portfolio, no olvidos.

**No se verifica la firma del webhook.** Meta firma cada payload con
`X-Hub-Signature-256` usando el app secret, y este proyecto no la comprueba: el
endpoint procesa cualquier POST que llegue a la URL. La consecuencia conviene
tenerla clara — **cualquiera que conozca la URL puede hacer que el bot envíe
mensajes y escriba turnos en la planilla**.

Se aceptó porque el número es de prueba, la URL es un túnel que se levanta a mano
para demostrar, y no hay datos de terceros en juego. Es lo primero de esta lista
que se vuelve obligatorio: en cuanto la URL deje de ser efímera y haya turnos de
pacientes reales, un endpoint que procesa cualquier POST deja de ser una
simplificación aceptable.

**No hay historial de conversación.** Cada mensaje es una llamada aislada a la
API, sin estado entre uno y otro. Eso significa que **el camino de repregunta no
puede completarse**: el bot pregunta qué servicio necesita, el paciente contesta
"control", y el modelo arranca de cero sin saber qué se le preguntó. Resolverlo
es persistir el hilo por número de teléfono y decidir cuándo expira — una feature
propia, no un arreglo.

**Cancelación y reprogramación no son self-service.** El bot deriva al teléfono
del consultorio con un mensaje fijo. Es una decisión de producto: reprogramar
implica encontrar el turno existente, liberarlo y reservar otro, con una ventana
donde el paciente se puede quedar sin ninguno.

**Fuera de alcance, sin más vuelta:** manejo de urgencias, número de WhatsApp
verificado, servidor de producción, recordatorios automáticos, sincronización con
Google Calendar, cobro de seña, y panel visual de configuración (la config es el
JSON, editado a mano).

---

## Cómo correrlo

Verificado en Windows 11 con PowerShell y Python 3.14.

```powershell
# Entorno
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Configuración local
Copy-Item .env.example .env
# completar: ANTHROPIC_API_KEY, GOOGLE_SHEETS_CREDENTIALS_PATH, SPREADSHEET_ID

# Tests — sin credenciales ni red
python -m pytest

# El servidor del webhook
python -m uvicorn app.main:app --reload --port 8000
```

La planilla necesita esta fila 1 exacta, con la columna `hora` formateada como
texto, y compartida con el email de la service account con permiso de Editor:

```
fecha | hora | servicio_id | nombre_paciente | telefono | creado_en
```

Los guiones de `scripts/` usan credenciales reales y llaman a la Claude API.
El detalle del stack completo con n8n y Meta está en `ESTADO.md`.

---

## Documentación del proyecto

Este repo se construyó en seis checkpoints verificables, con la documentación
versionada junto al código:

| Documento | Qué tiene |
|---|---|
| `SPECS.md` | qué se construye y por qué, con las decisiones de producto |
| `ROADMAP.md` | los seis checkpoints, con Definition of Done y qué se testea en cada uno |
| `ESTADO.md` | estado real del proyecto, incluidos los errores y las sorpresas de cada checkpoint |
| `CODESTYLE.md` | convenciones de código |

`ESTADO.md` es el más honesto de los cuatro: incluye lo que salió mal, lo que se
descubrió tarde y lo que se decidió no arreglar.

---

*Proyecto de portfolio de Accelerate.ai. Todos los datos del negocio son
ficticios.*
