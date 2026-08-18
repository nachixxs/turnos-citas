# CLAUDE.md — Turnos / Citas

<!-- Reglas de agencia (commits, push, secretos, testing) viven en ~/.claude/CLAUDE.md global — acá solo lo específico de este repo. -->

## IMPORTANT: dato de ejemplo siempre ficticio

Este repo nunca nombra a un cliente real de Accelerate.ai. Todo dato de ejemplo (código, fixtures, config, comentarios) es del negocio ficticio de `SPECS.md` §4: Consultorio Odontológico Dr. Franco Aguilar.

## Alcance

Trabajás solo dentro de este repo (`turnos-citas/`). No toques el vault de Obsidian ni otros proyectos del portfolio.

## Comandos

Siempre con el Python del venv, nunca el global:

```powershell
.venv\Scripts\python.exe -m pytest              # tests: sin credenciales ni red
.venv\Scripts\python.exe scripts\verificar_sheets.py   # real, contra Google Sheets
.venv\Scripts\python.exe scripts\verificar_agente.py   # real, contra la Claude API

.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000  # servidor del webhook
.venv\Scripts\python.exe scripts\verificar_webhook.py  # real, contra el servidor
```

Los tres scripts de `scripts/` usan credenciales reales: los corre la persona, no Claude Code, salvo autorización explícita. Setup completo del entorno en `ESTADO.md`.

## Testing

Testing estructural en cada checkpoint (regla general: ver CLAUDE.md global). Qué testear en cada CP: `ROADMAP.md`.

## Commits

Formato: `tipo: descripción corta` — tipos y ejemplos en `CODESTYLE.md`.

## Dónde está cada cosa

- Qué se construye y por qué — `SPECS.md`
- Checkpoints y Definition of Done — `ROADMAP.md`
- Convenciones de código — `CODESTYLE.md`
- Estado actual del proyecto — `ESTADO.md`
