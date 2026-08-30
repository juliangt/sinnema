# Spec — MVP de gestión web de proyectos y configuración de agentes

Estado: **v1 (aprobada)** · Fecha: 2026-08-30 · Alcance: MVP acotado, sin sobre-ingeniería.

## 1. Objetivo

Gestionar proyectos (shows) desde la web: crearlos, editarlos, duplicarlos,
eliminarlos y lanzarles corridas. Cada proyecto configura además el
comportamiento de sus seis agentes: reglas de instrucciones propias,
proveedor/modelo/temperatura y activación/desactivación.

**Principio rector**: los archivos TOML son la única fuente de verdad. La web
los lee y los escribe; el pipeline carga el spec desde disco al iniciar cada
corrida, así que todo cambio aplica a la próxima corrida sin reiniciar el
servicio.

## 2. Esquema TOML extendido

Se agregan dos secciones **opcionales** a los `<id>.toml` de `proyectos/`.
Todo proyecto existente sigue siendo válido sin cambios.

```toml
[proyecto]                         # igual que hoy
[voz]                              # igual que hoy
[visual]                           # igual que hoy
# [formato]                        # igual que hoy (opcional)

# --- NUEVO: configuración por agente (opcional) ---

[agentes.scriptwriter]             # roles válidos: planner, continuity,
reglas = [                         #   scriptwriter, adapter, critic,
  "Evitar preguntas retóricas",    #   technical_director
  "Cerrar siempre con un dato verificable",
]
temperatura = 0.9                  # opcional, 0.0–2.0
# proveedor = "openai"             # opcional: anthropic|openai|google|ollama
# modelo = "gpt-4o"                # opcional

[agentes.adapter]
activo = false                     # desactiva el agente en el pipeline

# --- NUEVO: política del pipeline (opcional) ---

[pipeline]
# intentos_maximos_de_critica = 3        # default cuando la corrida no lo fija
# politica_al_agotar = "aceptar_forzado" # o "saltar_capitulo"
```

### Semántica de los campos

| Campo | Significado | Default |
|---|---|---|
| `activo` | `false` cortocircuita el nodo sin llamar al LLM | `true` |
| `reglas` | Lista de instrucciones que se apendan al final del prompt del sistema del rol, en un bloque `REGLAS ADICIONALES DEL PROYECTO` | `[]` |
| `proveedor` | Override de proveedor para ese rol | default global |
| `modelo` | Override de modelo para ese rol | default global |
| `temperatura` | Override de temperatura | default global |
| `intentos_maximos_de_critica` | Default por proyecto cuando `POST /api/series` no lo especifica | `2` |
| `politica_al_agotar` | `aceptar_forzado` o `saltar_capitulo` al agotar reintentos de crítica | `aceptar_forzado` |

**Precedencia LLM**: proyecto > variables de entorno (`LLM_PROVIDER_<ROL>`,
`LLM_MODEL_<ROL>`) > defaults globales de `DEFAULT_ROLE_SPECS`.

### Desactivación por rol

Los nodos siguen existiendo en el grafo (topología estable, compatible con el
checkpointer); el nodo se cortocircuita sin gastar LLM:

| Rol desactivado | Comportamiento |
|---|---|
| `continuity` | `continuity_directives = None`; el guionista recibe un bloque "sin directivas"; el lore se sigue extrayendo de los conceptos clave del capítulo |
| `adapter` | Adaptación identidad determinista: el `AdaptedScript` se construye del borrador (conserva escenas y pasa las validaciones de coherencia) |
| `critic` | `qa_verdict = None` → el router aprueba directo; el episodio queda sin auditoría |
| `technical_director` | `technical_package = None`; el episodio queda sin specs visuales |
| `planner`, `scriptwriter` | **No desactivables**: son la columna vertebral del pipeline; la validación los rechaza con error accionable |

### Validaciones (todas se reportan juntas)

- Rol desconocido en `[agentes.<x>]` → error con la lista de roles válidos.
- `activo = false` para `planner`/`scriptwriter` → error.
- `proveedor` fuera de {anthropic, openai, google, ollama} → error.
- `temperatura` fuera de [0.0, 2.0] → error.
- `politica_al_agotar` fuera de {aceptar_forzado, saltar_capitulo} → error.
- `intentos_maximos_de_critica` fuera de 1–5 → error.

## 3. Contratos de dominio que se relajan

Para soportar agentes desactivados sin sintetizar artefactos falsos:

- `ApprovedEpisode.audit` y `ApprovedEpisode.technical` pasan a `Optional` (default `None`).
- `FinalScene.image_prompt` / `negative_prompt` / `motion_direction` aceptan `""` (escena sin spec visual).
- `assemble_episode` tolera `audit`/`package` ausentes; `forced_acceptance` solo aplica con auditoría presente.
- `SeriesDeliverable.average_quality_score` promedia solo los episodios con auditoría (0.0 si ninguno).
- El viewer HTML muestra el badge `sin auditoría` y omite los bloques de imagen vacíos.

## 4. API

| Método y ruta | Descripción |
|---|---|
| `GET /api/projects` | Listado (existente); suma `concepto` y `editable` |
| `GET /api/projects/{id}` | Dict crudo con la forma del TOML (claves en español) + `editable` |
| `POST /api/projects` | Crea; valida todo junto → `400` con la lista de problemas; `409` si ya existe |
| `PUT /api/projects/{id}` | Sobreescribe; el `proyecto.id` del cuerpo debe coincidir con la ruta (`400` si no) |
| `DELETE /api/projects/{id}` | `409` si hay jobs en cola/corriendo del proyecto; los históricos se conservan |
| `GET /api/projects/{id}/prompts` | Vista previa de los prompts del sistema compuestos (con reglas) |
| `GET /api/projects/{id}/lore` | Entradas actuales de la memoria de continuidad |
| `DELETE /api/projects/{id}/lore` | Reinicia la memoria de continuidad |
| `GET /api/meta/roles` | Catálogo de roles para el formulario (desactivable, defaults LLM) |
| `GET /api/jobs?project_id=` | Listado de jobs filtrado por proyecto |

`POST /api/series`: `max_critique_attempts` pasa a opcional (resolución
request > proyecto > 2).

## 5. Almacenamiento de archivos

- Nuevo adaptador `ProjectFileStore` (`sinnema/infrastructure/projects/store.py`):
  `exists / read_raw / create / update / delete / is_editable / list_merged`.
- Escritura atómica: archivo temporal + `os.replace`. Serialización con `tomli-w`.
- Directorio escribible: `SINNEMA_PROJECTS_DIR` (se crea si falta) →
  `proyectos/` del repo → `<SINNEMA_DATA_DIR>/proyectos`.
- El listado fusiona directorio escribible + shows empaquetados (el escribible
  gana por id). Solo los archivos del directorio escribible se editan/borran.

## 6. UI web

Extensión del SPA existente (`static/index.html`, vanilla JS, mismo tema
oscuro), en tres pestañas:

- **Generar**: formulario actual, con prefills desde el proyecto.
- **Proyectos**: listado con badges de agentes desactivados; nuevo / editar /
  duplicar / eliminar / ver prompts / ver-reiniciar lore. Editor con todas las
  secciones del TOML y un bloque por agente (activo — bloqueado con hint en
  planner/scriptwriter —, reglas una por línea, proveedor, modelo, temperatura).
- **Trabajos**: jobs con estado y enlaces al viewer y al JSON.

## 7. Fuera de alcance (MVP)

Autenticación real y multiusuario (sigue el header `X-Owner`), historial o
versionado de proyectos, edición manual del lore, topología del grafo
configurable (nodos nuevos), herramientas extra por agente, concurrencia
multi-servidor sobre los mismos TOML.

## 8. Limitaciones conocidas

- Un job en curso usa el spec que cargó al arrancar: editar el TOML durante una
  corrida no la afecta (aplica a la siguiente).
- Sin lock de archivos entre procesos: apto para un solo servidor/servicio.
- Borrar un proyecto no borra su lore ni su auditoría histórica; el lore
  huérfano se limpia a mano o se reutiliza si se recrea el id.
