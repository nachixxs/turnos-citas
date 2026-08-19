# SPECS — Turnos / Citas (Portfolio Accelerate.ai)

## 1. Qué se construye

MVP de agendamiento de turnos por WhatsApp con IA, para negocios de servicios con modelo de cita (peluquerías, consultorios, gimnasios, talleres). Se construye como motor genérico + configuración por negocio — este documento fija la configuración usada para la demo de portfolio, no la de un cliente real de la agencia.

**Negocio ficticio de la demo:** Consultorio Odontológico Dr. Franco Aguilar. Un solo profesional (sin ruteo entre varios odontólogos en esta versión).

## 2. Problema que resuelve

Un negocio de servicios con modelo de turno pierde tiempo y a veces clientes gestionando turnos a mano (llamados, agenda de papel, mensajes que se cruzan). Este sistema automatiza la toma de turnos por WhatsApp con IA, sin que el negocio cambie cómo atiende a sus clientes.

**No aplica a:** negocios de venta directa sin concepto de turno.

## 3. Cómo funciona — ruteo del agente

Un cliente escribe al WhatsApp del negocio. Un agente con Claude API (tool use) decide, mensaje a mensaje, entre **cuatro caminos**:

1. **Crear turno** — llama a la tool `crear_turno`.
2. **Consulta general (FAQ)** — llama a la tool `consulta_general`.
3. **Cancelación / reprogramación** — no dispara ninguna tool. Responde con un mensaje fijo derivando al contacto directo del consultorio (ver sección 7). Explícitamente fuera de alcance como flujo self-service en este MVP.
4. **Repregunta** — si falta un dato para crear el turno (ej: no especificó servicio u horario), pide el dato faltante antes de llamar a la tool.

## 4. Datos de la demo (negocio ficticio)

- **Nombre:** Consultorio Odontológico Dr. Franco Aguilar
- **Dirección:** Av. San Martín 850
- **Teléfono de contacto:** +54 9 261 555-0134 (ficticio, como todo el resto de los datos)
- **Horario de atención:** Lunes a viernes 9:00–13:00 y 15:00–19:00
- **Obra social:** Atiende solo de forma particular (no trabaja con obras sociales) — simplificación deliberada para no meter lógica de cobertura por plan en el FAQ del MVP.

**Servicios** (duración informativa, no usada por el motor de reservas — ver sección 8):

| Servicio | Precio | Duración (informativa) |
|---|---|---|
| Control | $32.000 | 20 min |
| Limpieza dental | $110.000 | 30 min |
| Extracción | $160.000 | 45 min |

Precios ajustados contra valores de referencia de la zona de Mendoza para atención particular (marzo 2026); se toman como punto de partida creíble para la demo, no como un arancel exacto vigente al momento de mostrarla.

## 5. Configuración del negocio — archivo JSON

Estructura de referencia (motor genérico, config por cliente):

```json
{
  "negocio": {
    "nombre": "Consultorio Odontológico Dr. Franco Aguilar",
    "direccion": "Av. San Martín 850",
    "telefono_contacto": "+54 9 261 555-0134",
    "atiende_obra_social": false
  },
  "horario_atencion": {
    "lunes_a_viernes": ["09:00-13:00", "15:00-19:00"]
  },
  "duracion_slot_minutos": 30,
  "servicios": [
    { "id": "control", "nombre": "Control", "precio": 32000, "duracion_min": 20 },
    { "id": "limpieza", "nombre": "Limpieza dental", "precio": 110000, "duracion_min": 30 },
    { "id": "extraccion", "nombre": "Extracción", "precio": 160000, "duracion_min": 45 }
  ]
}
```

## 6. Tool: `crear_turno`

| Campo | Origen | Notas |
|---|---|---|
| `fecha` | Extraído del mensaje | — |
| `hora` | Extraído del mensaje | Debe calzar con la grilla de slots (ver sección 8) |
| `servicio` | Extraído del mensaje | Debe matchear uno de los `id` del catálogo |
| `nombre_paciente` | Extraído del mensaje, con default | Default: nombre de perfil de WhatsApp de quien escribe. Si el mensaje indica que el turno es para otra persona (ej: "para mi hijo Tomás"), se usa ese nombre en su lugar |

El `telefono` **no** es campo de la tool: se resuelve directo del payload del webhook de WhatsApp y se usa recién al persistir en la Sheet — no tiene sentido pedirle a la IA que lo "extraiga" de un dato que ya llega resuelto.

## 7. Tool: `consulta_general` (FAQ)

Cubre exclusivamente:
- Horarios y días de atención
- Dirección / ubicación
- Precios de los servicios
- Obra social / formas de pago (respuesta: solo atención particular)

**Explícitamente fuera del FAQ:** manejo de urgencias — no es algo que un flujo de reserva por slots pueda resolver bien en un MVP; no se ofrece como opción ni se responde con información específica.

## 8. Validación de disponibilidad — decisión técnica

**Decisión:** grilla fija de slots de 30 minutos para *todos* los servicios, independientemente de su duración real. Antes de confirmar, el motor lee los turnos ya tomados en la Sheet y valida que el slot pedido esté libre.

**Por qué (para el README de portfolio):** los servicios tienen duraciones reales distintas (20/30/45 min), lo que en teoría pide una validación por superposición de rangos. Se descartó ese enfoque a favor de slots fijos porque: (a) refleja cómo funciona el negocio en la práctica — si un turno se atrasa, el paciente espera, no se recalcula la agenda; y (b) evita construir lógica de solapamiento de intervalos en un MVP de 1-2 días, sin sacrificar la garantía real que importa (que nadie reserve el mismo horario dos veces).

**Si el horario pedido no calza con la grilla o ya está ocupado:** el bot responde mostrando los horarios disponibles para que el cliente elija uno — nunca redondea automático ni rechaza sin alternativa.

## 9. Cancelación / reprogramación

No es un flujo resuelto por el bot en este MVP. Si el agente detecta intención de cancelar o reprogramar un turno existente, responde con un mensaje fijo derivando al `telefono_contacto` del negocio (sección 5) — no intenta resolverlo como si fuera una tool de turno nuevo, y no llama a ninguna tool en ese camino.

El teléfono sale del JSON de configuración y no está hardcodeado en el código: es un dato que cambia con cada cliente. El mensaje se verifica de forma estructural comparándolo contra la constante del código, no evaluando si "suena bien".

## 10. Explícitamente fuera de alcance de este MVP

- Manejo de urgencias (ni como servicio reservable, ni en el FAQ)
- Cancelación / reprogramación self-service (respuesta fija, ver sección 9)
- Número de WhatsApp verificado
- Servidor de producción
- Recordatorios automáticos antes del turno
- Integración con calendario externo (Google Calendar)
- Cobro de seña al confirmar
- Panel de configuración visual (la configuración es el JSON de la sección 5, editado a mano)

## 11. Escalamiento — de MVP a proyecto completo

Cuando esto se venda a un cliente real: recordatorios automáticos antes del turno, sincronización con Google Calendar, cobro de seña al confirmar, reprogramación self-service sin pasar por un humano, verificación de negocio de Meta y servidor de producción real.

## 12. Stack técnico

- **Backend:** FastAPI + Claude API (tool use)
- **Orquestación:** n8n (Webhook → IF → Respond to Webhook)
- **Canal:** WhatsApp Cloud API (Meta) — número de prueba, sin verificación de negocio
- **Persistencia:** Google Sheets (turnos confirmados)
- **Configuración por negocio:** archivo JSON/YAML (sección 5), nunca hardcodeado en el código

> **Corrección posterior (CP4).** El flujo de n8n de arriba se quedó corto y se
> deja tal cual como registro de lo que se planeó. `Webhook → IF → Respond to
> Webhook` no alcanza por dos motivos que aparecieron al construirlo:
> responder 200 al webhook **no** le envía nada al paciente —el mensaje sale por
> un POST aparte a la Graph API— y Meta exige un segundo webhook en GET para
> validar la URL devolviendo su `hub.challenge`. El flujo real tiene 11 nodos y
> está en `ROADMAP.md`, sección CP4. El resto de esta sección sigue vigente.

## 13. Entregables esperados

- Repo funcional con el código del MVP
- README público orientado a portfolio, enfocado en decisiones técnicas no obvias (ver sección 8 como ejemplo directo de ese tipo de contenido)
- Datos de ejemplo del negocio ficticio (este documento)
- Guiones de testing verificados de forma estructural — nunca por si la respuesta "suena bien"

## 14. Fecha objetivo

Martes 18 de agosto de 2026.
