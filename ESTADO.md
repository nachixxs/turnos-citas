# ESTADO interno — Turnos / Citas (Portfolio Accelerate.ai)

**Este documento es de uso interno del equipo** (estado del proyecto). Distinto del README público del repo, que se genera recién en CP6 y está orientado a portfolio (ver `metodologia-general-accelerate-ai.md`, sección "README público de cada repo").

## Qué es esto

MVP de agendamiento de turnos por WhatsApp con IA, primera de las 4 automatizaciones genéricas del portfolio de Accelerate.ai. Motor genérico + configuración por negocio — este proyecto usa como demo un negocio ficticio (Consultorio Odontológico Dr. Franco Aguilar). Detalle completo del alcance en `SPECS.md`.

## Estado actual

**Fase:** planificación cerrada — `SPECS.md` y `ROADMAP.md` listos, código todavía sin empezar (CP1 pendiente).

| CP | Nombre | Estado |
|---|---|---|
| CP1 | Setup + motor de datos | Pendiente |
| CP2 | Agente Claude (tool use) y ruteo de 4 caminos | Pendiente |
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

## Estructura de repo propuesta

```
turnos-citas/
├── app/
│   ├── main.py               # FastAPI app, endpoint del webhook
│   ├── agent.py              # Agente Claude, prompt de sistema, tools
│   ├── availability.py       # Motor de grilla de slots (CP1)
│   ├── sheets_client.py      # Cliente Google Sheets
│   └── config_loader.py      # Carga y validación del JSON de config
├── config/
│   └── negocio.json          # Configuración del negocio ficticio (SPECS §5)
├── tests/
│   ├── fixtures/             # Payloads de ejemplo, turnos precargados
│   ├── test_availability.py
│   ├── test_agent_routing.py
│   └── test_webhook.py
├── n8n/
│   └── flow.json             # Export del flujo de n8n (CP4)
├── .env.example
├── .gitignore
├── requirements.txt
├── ESTADO.md                 # este archivo
├── README.md                 # README público de portfolio (se genera en CP6)
├── SPECS.md
├── ROADMAP.md
└── CODESTYLE.md
```

Esta estructura se ajusta si algo no encaja al construir — se actualiza este documento en ese caso, no se asume fija de antemano.

## Negocio ficticio de la demo

Consultorio Odontológico Dr. Franco Aguilar — un solo profesional, atención particular (sin obra social), 3 servicios (Control, Limpieza dental, Extracción). Datos completos en `SPECS.md` §4.

## Cómo correr el proyecto

Pendiente de documentar — se completa al cerrar CP1 (setup) con los pasos reales verificados, no antes.

## Próximo paso

Arrancar CP1: setup del repo y motor de datos. Ver `ROADMAP.md`.

## Documentos relacionados

- `SPECS.md` — qué se construye y por qué (cerrado).
- `ROADMAP.md` — plan de checkpoints con Definition of Done y testing.
- `CODESTYLE.md` — convenciones de código de este proyecto.
