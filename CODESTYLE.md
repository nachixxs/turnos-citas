# CODESTYLE — Turnos / Citas (Portfolio Accelerate.ai)

Convenciones de código para este proyecto. Objetivo: código legible para un lead/reclutador que abra el repo, y suficientemente prolijo para reusarse como motor en un cliente real más adelante — sin sobre-ingeniería para un MVP de 1-2 días.

## Lenguaje y versión

Python 3.11+. Type hints obligatorios en firmas de función (parámetros y retorno) — no opcional, incluso en un MVP chico.

## Estilo general

- PEP 8 como base.
- Funciones cortas, una responsabilidad por función. Si una función mezcla "extraer datos del payload" y "decidir qué tool llamar", se separa.
- Docstring corto en funciones que no son triviales a simple vista (una línea alcanza si el nombre de la función ya es claro).
- Nada de lógica de negocio hardcodeada en el código — todo lo que varíe por cliente vive en `config/negocio.json` (SPECS §5), nunca como constante en un `.py`.

## Validación de datos: Pydantic v2

Los modelos de datos (configuración del negocio, payload del webhook, argumentos de las tools) se definen como modelos de Pydantic v2, no como diccionarios sueltos. Esto da validación automática al cargar el JSON de configuración y al parsear el payload de WhatsApp, y evita bugs silenciosos por typos en claves de diccionario.

## Convención de nombres

**Dominio del negocio en español, infraestructura en inglés** — refleja la mezcla que ya define el propio SPECS (los nombres de tools y las claves del JSON de configuración son en español: `crear_turno`, `consulta_general`, `horario_atencion`, `duracion_slot_minutos`).

- Nombres de tools, campos de configuración, campos de negocio (servicio, turno, horario, paciente): **español**, igual que en `SPECS.md`. No se traducen a mitad de camino — si el SPECS dice `crear_turno`, el código dice `crear_turno`, no `create_appointment`.
- Nombres de archivos, funciones de infraestructura (cliente HTTP, parseo de payload, conexión a Sheets, endpoint), variables técnicas genéricas: **inglés**, como es estándar en el ecosistema Python/FastAPI.
- `snake_case` para funciones y variables, `PascalCase` para clases (incluidos los modelos Pydantic), `UPPER_SNAKE_CASE` para constantes.

## Estructura de configuración

- Un solo punto de carga del JSON (`config_loader.py`) — el resto del código nunca lee el archivo directo, siempre recibe el modelo ya cargado y validado.
- Si un campo no está en el JSON, el código no asume un default silencioso salvo que el default esté documentado explícitamente en `SPECS.md` (ej: `nombre_paciente` con default al perfil de WhatsApp, SPECS §6).

## Manejo de secretos

- Nunca en el código ni en commits: tokens de WhatsApp Cloud API, credenciales de Google Sheets, API key de Claude.
- Todo vía `.env`, con `.env.example` versionado (sin valores reales) como referencia de qué variables hacen falta.
- Cualquier comando que use una clave sensible real lo corre la persona en su propia terminal — Claude Code nunca ve el valor real (regla general de la agencia, ver documento de metodología).

## Testing

- `pytest`. Fixtures en `tests/fixtures/` para payloads de WhatsApp de ejemplo y escenarios de turnos precargados.
- Todo test verifica contra un dato concreto (id de servicio, slot devuelto, nombre de la tool llamada, argumentos exactos) — nunca contra si el texto de una respuesta "suena bien" o "parece coherente". Esto aplica en particular a los tests del agente (CP2): se verifica qué tool se llamó y con qué argumentos, no el contenido conversacional de la respuesta.
- Un test por caso de borde explícito del SPECS (slot ocupado, servicio inválido, turno para otra persona, etc.) — no un solo test genérico que intente cubrir todo.

## Logging

Logging básico (`logging` estándar de Python) en puntos clave: mensaje recibido, tool llamada, turno creado/rechazado. Nada de `print()` suelto en el código final.

## Commits

- Chicos, uno por cambio lógico — nunca un commit acumulado al final de un checkpoint.
- Formato sugerido: `tipo: descripción corta en español` (ej: `feat: lógica de grilla de slots`, `fix: validación de servicio inválido`, `test: casos de borde CP5`). Tipos: `feat`, `fix`, `test`, `docs`, `chore`.
- Nunca push sin listar los commits de la sesión y pedir confirmación explícita antes (regla de la agencia, ver documento de metodología y `CLAUDE.md` de este proyecto).

## Qué se evita deliberadamente en este MVP

- Abstracciones genéricas para "cualquier futuro caso" que el SPECS no pide — el motor ya es genérico donde el SPECS lo pide (config por JSON); no hace falta generalizar más allá de eso para un MVP de portfolio.
- Manejo de errores exhaustivo tipo producción (retries, circuit breakers) — alcanza con no romper el proceso ante un payload malformado o un dato faltante, documentado como tal en `SPECS.md` §10.
