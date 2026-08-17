# ESTADO interno — Turnos / Citas (Portfolio Accelerate.ai)

**Este documento es de uso interno del equipo** (estado del proyecto). Distinto del README público del repo, que se genera recién en CP6 y está orientado a portfolio (ver `metodologia-general-accelerate-ai.md`, sección "README público de cada repo").

## Qué es esto

MVP de agendamiento de turnos por WhatsApp con IA, primera de las 4 automatizaciones genéricas del portfolio de Accelerate.ai. Motor genérico + configuración por negocio — este proyecto usa como demo un negocio ficticio (Consultorio Odontológico Dr. Franco Aguilar). Detalle completo del alcance en `SPECS.md`.

## Estado actual

**Fase:** CP2 cerrado — el agente rutea correctamente los 4 caminos de SPECS §3
y llama a las tools con los argumentos correctos, verificado contra la Claude
API real (12/12 casos del guion). Próximo: CP3.

| CP | Nombre | Estado |
|---|---|---|
| CP1 | Setup + motor de datos | **Hecho** |
| CP2 | Agente Claude (tool use) y ruteo de 4 caminos | **Hecho** |
| CP3 | Endpoint FastAPI + parseo del webhook | Pendiente |
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
│   └── main.py               # (CP3) FastAPI app, endpoint del webhook
├── config/
│   └── negocio.json          # Configuración del negocio ficticio (SPECS §5)
├── scripts/
│   ├── verificar_sheets.py   # Verificación manual contra la Sheet real
│   └── verificar_agente.py   # Guion de verificación contra la Claude API real
├── tests/
│   ├── conftest.py           # Fixtures y fechas ancla
│   ├── test_config_loader.py
│   ├── test_availability.py
│   ├── test_sheets_client.py
│   ├── test_agent_routing.py
│   └── test_webhook.py       # (CP3)
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
```

La Sheet tiene que tener esta fila 1 exacta, y la columna `hora` formateada
como texto:

```
fecha | hora | servicio_id | nombre_paciente | telefono | creado_en
```

Además, hay que compartirla con el email de la service account con permiso de
Editor: sin eso, la API devuelve 403 aunque las credenciales sean válidas.

## Próximo paso

Arrancar CP3: endpoint FastAPI y parseo del payload del webhook de WhatsApp.
Ver `ROADMAP.md`.

Dato que sale de la verificación de CP2 y condiciona CP3: cuando el modelo
llama a una tool **no escribe texto**. El mensaje que se le devuelve al
paciente hay que componerlo desde el `ResultadoAgente` (turno confirmado,
alternativas, tema del FAQ), no esperarlo de la respuesta del modelo. Es lo
correcto: una confirmación de turno tiene que ser determinista.

## Documentos relacionados

- `SPECS.md` — qué se construye y por qué (cerrado).
- `ROADMAP.md` — plan de checkpoints con Definition of Done y testing.
- `CODESTYLE.md` — convenciones de código de este proyecto.
