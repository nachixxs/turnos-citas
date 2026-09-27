# turnos-citas

WhatsApp appointment booking agent: a Claude tool-use agent behind FastAPI and n8n that checks real availability before confirming and stores bookings in Google Sheets.

The engine is generic; everything about the business (name, address, opening hours, services, prices) lives in `config/negocio.json`. The demo uses a fictional dental clinic with made-up data. The bot talks to patients in Spanish.

## What it does

- Routes each incoming message in a single Claude API call to one of four paths:
  - **Book:** `crear_turno` validates the requested slot against the calendar and saves it.
  - **Ask:** `consulta_general` answers price and service questions from the catalog.
  - **Missing data:** `pedir_dato_faltante` asks for whatever is missing (service, date or time).
  - **Cancel or reschedule:** no tool; the patient is referred to the clinic's phone number.
- Never rounds or silently rejects a requested time: if it is off-grid or taken, it offers the three nearest free slots.
- Uses a fixed 30-minute slot grid (a deliberate choice over interval-overlap checks; reasoning in `SPECS.md` and `ESTADO.md`).
- Refers urgent cases to a human with a fixed message, and never substitutes a service that is not in the catalog.
- Composes every patient-facing confirmation in code from the stored result, so the message matches what was written to the sheet.

## Tech stack

Python, FastAPI, Anthropic Python SDK (Claude tool use), Pydantic v2, n8n, WhatsApp Cloud API, Google Sheets (gspread + service account), pytest.

## How it works

```
Patient → WhatsApp Cloud API → n8n → FastAPI → Claude API (tool use)
                                       ↕
                                 Google Sheets

FastAPI reply → n8n → Graph API → Patient
```

1. n8n receives the Meta webhook (and handles the verification handshake), drops status events and forwards messages to FastAPI.
2. FastAPI parses the payload, reads existing bookings from the sheet and calls `decidir()`, which returns the tool the model chose and its arguments.
3. `aplicar_decision()`, a pure function, applies that decision against the availability engine; confirmed bookings are written to the sheet.
4. `respuestas.py` composes the reply text; n8n sends it back through the Graph API.

Splitting the decision (`decidir`, needs the API) from its execution (`aplicar_decision`, pure) is what lets most of the logic be tested without credentials or network.

```
app/
├── config_loader.py   # loads and validates the business JSON (Pydantic v2)
├── availability.py    # slot grid, free/taken slots, alternatives
├── sheets_client.py   # Google Sheets
├── agent.py           # prompt, tools, decision and execution
├── respuestas.py      # deterministic composition of the reply
├── formato.py         # Spanish date, time and price formatting
├── webhook.py         # WhatsApp payload parsing
└── main.py            # FastAPI app and webhook endpoint
```

## Engineering highlight: a text bug made structurally impossible

In a live end-to-end test over real WhatsApp, a patient asked for "a slot on Thursday at 11" without naming a service. The model correctly asked which service they wanted, but also said the slot was free. On that path no tool was called, so the calendar was never read: it happened to be right, which is exactly what hides this kind of bug.

A phrase blocklist ("available", "I have a slot") cannot test this: "Perfect! Which service do you need?" makes the same claim without any blocked word. The fix was to take the text away from the model. The follow-up question became a tool, `pedir_dato_faltante(datos: ["servicio" | "fecha" | "hora"])`, and the text is built in code by `_texto_dato_faltante(datos, config)`, whose signature has no access to the requested date or time. With a finite output space, `test_la_repregunta_nunca_menciona_un_horario` checks all 7 combinations and asserts none contains a digit, since naming a time always needs one. The prompt still states the rule, but the guarantee comes from the code. Full write-up in `ESTADO.md`.

## Getting started

Tested on Windows 11 with PowerShell and Python 3.14.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

Copy-Item .env.example .env
# fill in the values described in .env.example (Claude API key, Google service account, sheet ID, Meta/WhatsApp settings)

python -m pytest                                        # no credentials or network needed
python -m uvicorn app.main:app --reload --port 8000     # webhook server
```

The sheet needs this exact header row, with the `hora` column formatted as text, and must be shared with the service account as Editor:

```
fecha | hora | servicio_id | nombre_paciente | telefono | creado_en
```

The n8n workflow is in `n8n/flow.template.json` and is imported with `scripts/configurar_n8n.py`; `scripts/configurar_meta.py` registers the Meta webhook through the Graph API. Setup details for n8n and Meta are in `ESTADO.md` (Spanish).

## Tests

`python -m pytest` runs **148 tests** that need no credentials or network. They assert concrete data (which tool was called, with which exact arguments, which slot came back), never whether a reply "sounds right".

Separate verification scripts in `scripts/` run against real services and are run by hand:

| Script | What it checks |
|---|---|
| `verificar_agente.py` | 15 cases against the real Claude API, with a pinned date and fixed bookings; last run 15/15 |
| `verificar_n8n.py` | the full n8n → FastAPI → Claude → Sheets flow, replacing only the Graph API with a local double; last run 7/7 |
| `verificar_webhook.py` | the running FastAPI endpoint with real HTTP traffic |
| `verificar_sheets.py` | read (and optionally write) against the real spreadsheet |

## Project status

MVP complete, built across six checkpoints documented in `ROADMAP.md`, with decisions and what went wrong recorded in `ESTADO.md` (both in Spanish). Known limitations, accepted on purpose for a demo:

- The webhook does not verify Meta's `X-Hub-Signature-256` signature, so anyone who knows the URL can trigger it. This is the first thing to fix before real patient data.
- No conversation history: each message is an isolated call, so the follow-up question cannot be completed across messages yet.
- Cancellation and rescheduling are not self-service.

## License

MIT, see `LICENSE`.
