# Spec — Red de agentes 3D: monitoreo, inspección y mutación en caliente

Estado: **v1 (propuesta)** · Fecha: 2026-09-09 · Sucede a: `spec-agentes-dinamicos.md`
y `spec-gestion-web.md` (las extiende, no las reemplaza)

## 1. Objetivo y principios rectores

Una interfaz web 3D interactiva para **monitorear, consultar y configurar** la red
de agentes de LangGraph de cada proyecto: canvas 3D con el grafo del flujo
efectivo, indicadores de estado en vivo por nodo y un panel de inspección que
permite mutar la configuración LLM de cada agente sin reiniciar el servicio.

**Principios rectores** (heredados del sistema):

- Los archivos TOML siguen siendo la única fuente de verdad; la mutación desde
  la 3D persiste en `<id>.toml` con la misma escritura atómica de hoy.
- Un job **congela el spec al arrancar**. La mutación es *configuración en
  caliente del servicio*, no de la corrida: aplica a la próxima corrida y la UI
  lo comunica explícitamente (§11.4).
- La topología mostrada se **deriva del grafo compilado** (`grafo.get_graph()`),
  nunca se re-declara en el cliente: el flujo efectivo —composición por fases,
  corte por `hasta`, compuerta y sus aristas condicionales— es la única forma
  posible del dibujo.
- Ningún artefacto circula sin contrato validado: streaming y tools (§7) se
  añaden **alrededor** del contrato existente, no lo relajan.
- El sistema es multi-proyecto: cambiar de proyecto re-hidrata la escena 3D
  completa con dispose estricto de recursos WebGL (§8.3).

## 2. Decisiones de arquitectura (validadas)

| Decisión | Elección | Consecuencia |
|---|---|---|
| Stack 3D + overlay | **React Three Fiber + Vite + TypeScript**, Tailwind + shadcn/ui para el overlay, Zustand para estado | Introduce `web/` con `package.json` y build (Vite) en el repo; primer componente JS del proyecto |
| Alcance backend | **Extensión completa**: eventos por nodo estructurados, streaming de tokens, tool calling, `top_p`/`max_tokens` | Extensión aditiva del puerto `StructuredGenerationPort` y del job store; compatibilidad estricta (§12) |
| Semántica de mutación | **Próxima corrida**: `PUT` persiste en TOML, el cambio aplica al próximo job | Se conserva la garantía de reproducibilidad por job; se añade indicador de spec desfasado (§11.4) |
| Relación con la web actual | **Reemplazo**: la app 3D se vuelve la UI principal del servidor | Transición con fallback (`web/dist` → `static/`); borrado de `index.html` solo tras paridad (§12.3) |

Stack frontend concreto: `react`, `react-dom`, `three`, `@react-three/fiber`,
`@react-three/drei` (OrbitControls, Line, Billboard, Text), `zustand`,
`tailwindcss` + `shadcn/ui`, `vite` + `typescript`. Testing: `vitest` +
`@testing-library/react`. Sin más dependencias.

## 3. Esquema TOML extendido

`[agentes.<rol>]` gana tres claves **opcionales**. Todo proyecto existente
sigue siendo válido sin cambios.

```toml
[agentes.scriptwriter]
reglas      = ["Cerrar siempre con un dato verificable"]
proveedor   = "openai"
modelo      = "gpt-4o"
temperatura = 0.8
top_p       = 0.95          # NUEVO: opcional, 0.0–1.0
max_tokens  = 4096          # NUEVO: opcional, > 0

[agentes.fact_checker]      # custom: hereda las claves de spec-agentes-dinamicos §8
tipo          = "contexto"
contrato      = "notas"
entradas      = ["capitulo", "lore"]
instrucciones = "Eres el verificador de datos de {marca}..."
tools         = ["buscar_lore"]   # NUEVO: opcional, contra el registro §7.3
```

### Semántica de las claves nuevas

| Campo | Significado | Default |
|---|---|---|
| `top_p` | Override de nucleus sampling del LLM del rol | default del proveedor (no se pasa) |
| `max_tokens` | Override de límite de tokens de salida | default del proveedor (no se pasa) |
| `tools` | Tools integradas habilitadas para el rol: loop previo a la generación estructurada (§7.3) | `[]` (comportamiento actual, sin tools) |

**Precedencia**: proyecto `[agentes.<rol>]` > defaults de `DEFAULT_ROLE_SPECS`
(heredada). Las variables de entorno siguen cubriendo solo `proveedor`/`modelo`
(`LLM_PROVIDER_<ROL>` / `LLM_MODEL_<ROL>`): `top_p`, `max_tokens` y `tools` no
tienen override de entorno (menos superficies que documentar).

### Validaciones nuevas (se suman a la lista acumulativa de §9 de `spec-agentes-dinamicos.md`)

11. `top_p` fuera de [0.0, 1.0] → error con el rango.
12. `max_tokens` ≤ 0 → error con el rango.
13. `tools` con nombres fuera del registro de tools integradas → error con la
    lista disponible (§7.3).
14. `tools` en un rol estructural sin LLM (no aplica: roles con `[agentes.<rol>]`
    siempre tienen LLM) — no se valida, se documenta.

`providers.py` sigue siendo el único módulo que conoce paquetes LangChain:
`build_provider_model(provider, model, temperature, top_p=None, max_tokens=None)`
pasa los parámetros a cada constructor (`ChatOllama` mapea `max_tokens` →
`num_predict`). Los parámetros ausentes **no se pasan** (rige el default del
proveedor, como hoy).

## 4. Tipado TypeScript exhaustivo

Fuente única de tipos del frontend (`web/src/types/index.ts`). Cada tipo
documenta su origen (endpoint o sección TOML).

```ts
// ── Catálogos (GET /api/meta/catalogos, GET /api/meta/roles) ─────────────
export type ProveedorLlm = "anthropic" | "openai" | "google" | "ollama";

export interface Catalogos {
  proveedores: ProveedorLlm[];
  modelos: Record<ProveedorLlm, string[]>;      // sugeridos por proveedor
  tools: { nombre: string; descripcion: string }[];
  hitos: Hito[];                                 // plan…produccion (ALCANCES)
  tipos_custom: ("contexto" | "revisor" | "enriquecedor")[];
  contratos: ("notas" | "texto" | "dictamen")[];
  entradas_custom: string[];                     // CATALOGO_ENTRADAS
}

// ── Config LLM por agente ([agentes.<rol>] resuelto: proyecto > default) ──
export interface LLMConfig {
  proveedor: ProveedorLlm;
  modelo: string;
  temperatura: number;      // 0.0–2.0
  top_p?: number;           // 0.0–1.0, ausente = default del proveedor
  max_tokens?: number;      // > 0, ausente = default del proveedor
  tools: string[];          // registro §7.3; [] = sin tools
}

// ── Grafo efectivo (GET /api/projects/{id}/red) ───────────────────────────
export type TipoNodo =
  | "serie" | "contexto" | "escritor" | "transformador"
  | "revisor" | "enriquecedor" | "cierre";

export type FaseId =
  | "serie" | "contexto" | "escritura" | "transformacion"
  | "compuerta" | "enriquecimiento" | "cierre";

export interface AgentNode {
  id: string;               // nombre de nodo del grafo ("scriptwriter", "chief_critic", …)
  rol: string | null;       // rol del registro; null en commit/fail/consolidar
  tipo: TipoNodo;           // fija geometría y semántica visual (§9.2)
  fase: FaseId;             // columna del layout (§9.1)
  estructural: boolean;     // true: nodo escrito a mano (plan_series, compuerta, cierre)
  descripcion: string;      // del AGENT_REGISTRY
  esencial: boolean;
  llm: LLMConfig | null;    // null solo en nodos sin agente (cierre)
  custom?: {                // solo agentes custom del TOML
    contrato: string;
    entradas: string[];
    instrucciones: string;
  };
}

export interface EdgeTransition {
  id: string;               // "<from>-><to>"
  from: string;             // id de nodo, o "__start__"
  to: string;               // id de nodo, o "__end__"
  condicional: boolean;
  labels: string[];         // revise|approve|skip_chapter|next_chapter|series_complete
}

export interface EffectiveNetwork {
  project_id: string;
  declarado: boolean;       // ¿el TOML declara [flujo]?
  hasta: string;            // hito
  nodes: AgentNode[];
  edges: EdgeTransition[];
  limite_recursion: number;
}

// ── Proyectos (GET /api/projects, GET/PUT /api/projects/{id}) ─────────────
export interface ProjectSummary {
  id: string; marca: string; concepto: string; editable: boolean;
}

export interface FlowSpec {          // [flujo] en crudo (claves TOML)
  contexto?: string[];
  transformaciones?: string[];
  revisor?: string;
  enriquecimiento?: string[];
  hasta?: string;
}

export interface ProjectDetail {     // forma del dict TOML (claves en español)
  proyecto: Record<string, unknown>;
  voz?: Record<string, unknown>;
  visual?: Record<string, unknown>;
  formato?: Record<string, unknown>;
  agentes?: Record<string, Record<string, unknown>>;
  pipeline?: Record<string, unknown>;
  flujo?: FlowSpec;
  editable: boolean;
}

// ── Jobs y ejecución (GET /api/jobs/{id}, §6) ─────────────────────────────
export type JobStatus = "queued" | "running" | "completed" | "failed";

export interface Job {
  job_id: string;
  project_id: string;
  topic: string;
  num_chapters: number;
  max_critique_attempts: number;
  status: JobStatus;
  created_at: string;
  started_at?: string;
  finished_at?: string;
  error?: string;
  spec_desfasado?: boolean;  // §11.4: el TOML cambió desde que el job arrancó
}

export type RuntimeExecutionEvent =
  | { kind: "node_start"; ts: string; job_id: string; node: string; rol: string | null; paso: number }
  | { kind: "node_end";   ts: string; job_id: string; node: string; rol: string | null; paso: number; claves: string[] }
  | { kind: "token";      ts: string; job_id: string; node: string; rol: string; texto: string }
  | { kind: "tool_start"; ts: string; job_id: string; node: string; rol: string; tool: string; args: unknown }
  | { kind: "tool_end";   ts: string; job_id: string; node: string; rol: string; tool: string; resumen: string }
  | { kind: "progress" | "error" | "done"; ts: string; job_id: string; mensaje: string };

// ── Auditoría (GET /api/jobs/{id}/artifacts[/{n}]) ────────────────────────
export interface Artifact {
  n: number;                // número de paso (NNN_)
  paso: string;             // nombre del paso/nodo
  resumen: string;
  artefacto?: unknown;      // JSON del contrato (si lo hubo)
  prompts?: { sistema: string; usuario: string };  // §7.4
}
```

`PipelineState` no se tipa completo en el cliente: el inspector muestra los
artefactos por paso (contratos ya validados) y las claves actualizadas por
`node_end`, no el TypedDict crudo.

## 5. API

Cambios y adiciones sobre `sinnema/infrastructure/api/app.py`:

| Método y ruta | Cambio |
|---|---|
| `GET /api/projects/{id}/red` | **Nuevo**. Hidratación completa de la escena: nodos + edges del grafo compilado con `_GatewayNulo` (mismo patrón que `flujo-efectivo`), anotados con el registro y el `LLMConfig` resuelto por rol |
| `GET /api/meta/catalogos` | **Nuevo**. Catálogos para los formularios: proveedores, modelos sugeridos, tools disponibles, hitos, tipos/contratos/entradas custom |
| `GET /api/jobs/{id}/artifacts` | **Nuevo**. Lista de pasos de auditoría del job (`auditoria/<project>/serie_<job>/NNN_<paso>.txt`) |
| `GET /api/jobs/{id}/artifacts/{n}` | **Nuevo**. Un paso parseado: resumen, artefacto JSON y prompts (§7.4) |
| `GET /api/jobs/{id}/events/history` | **Nuevo**. Timeline completa (`?since=`), mismos registros que el SSE |
| `GET /api/jobs/{id}/events` | **Modificado**. El SSE emite `data` JSON con payload (§6.3); `id:` y reconexión por Last-Event-id siguen nativos |
| `PUT /api/projects/{id}` | **Modificado**. Acepta `top_p`/`max_tokens`/`tools` en `agentes.<rol>` (validación §3) |
| `GET /api/jobs` · `GET /api/jobs/{id}` | **Modificado**. Suma `spec_desfasado` (§11.4) |

### 5.1 Ejemplo: `GET /api/projects/comida/red` (ilustrativo, flujo legacy completo)

```json
{
  "project_id": "comida",
  "declarado": false,
  "hasta": "produccion",
  "limite_recursion": 64,
  "nodes": [
    { "id": "plan_series", "rol": "planner", "tipo": "serie",
      "fase": "serie", "estructural": true, "esencial": true,
      "descripcion": "Planifica la serie…",
      "llm": { "proveedor": "anthropic", "modelo": "claude-3-5-sonnet-latest",
               "temperatura": 0.2, "tools": [] } },
    { "id": "continuity_master", "rol": "continuity", "tipo": "contexto",
      "fase": "contexto", "estructural": false, "esencial": false,
      "descripcion": "…",
      "llm": { "proveedor": "openai", "modelo": "gpt-4o-mini",
               "temperatura": 0.1, "tools": [] } },
    { "id": "scriptwriter", "rol": "scriptwriter", "tipo": "escritor",
      "fase": "escritura", "estructural": false, "esencial": true, "descripcion": "…",
      "llm": { "proveedor": "openai", "modelo": "gpt-4o", "temperatura": 0.8,
               "top_p": 0.95, "max_tokens": 4096, "tools": [] } },
    { "id": "persona_adapter", "rol": "adapter", "tipo": "transformador",
      "fase": "transformacion", "estructural": false, "esencial": false,
      "descripcion": "…",
      "llm": { "proveedor": "openai", "modelo": "gpt-4o-mini",
               "temperatura": 0.7, "tools": [] } },
    { "id": "chief_critic", "rol": "critic", "tipo": "revisor",
      "fase": "compuerta", "estructural": true, "esencial": false,
      "descripcion": "…",
      "llm": { "proveedor": "anthropic", "modelo": "claude-3-5-sonnet-latest",
               "temperatura": 0.0, "tools": [] } },
    { "id": "technical_director", "rol": "technical_director",
      "tipo": "enriquecedor", "fase": "enriquecimiento",
      "estructural": false, "esencial": false, "descripcion": "…",
      "llm": { "proveedor": "google", "modelo": "gemini-1.5-pro",
               "temperatura": 0.4, "tools": [] } },
    { "id": "commit_episode", "rol": null, "tipo": "cierre", "fase": "cierre",
      "estructural": true, "esencial": false, "descripcion": "Consolida el episodio",
      "llm": null },
    { "id": "fail_chapter", "rol": null, "tipo": "cierre", "fase": "cierre",
      "estructural": true, "esencial": false, "descripcion": "Registra capítulo fallido",
      "llm": null }
  ],
  "edges": [
    { "id": "__start__->plan_series", "from": "__start__", "to": "plan_series",
      "condicional": false, "labels": [] },
    { "id": "plan_series->continuity_master", "from": "plan_series",
      "to": "continuity_master", "condicional": false, "labels": [] },
    { "id": "persona_adapter->chief_critic", "from": "persona_adapter",
      "to": "chief_critic", "condicional": false, "labels": [] },
    { "id": "chief_critic->scriptwriter", "from": "chief_critic",
      "to": "scriptwriter", "condicional": true, "labels": ["revise"] },
    { "id": "chief_critic->technical_director", "from": "chief_critic",
      "to": "technical_director", "condicional": true, "labels": ["approve"] },
    { "id": "chief_critic->fail_chapter", "from": "chief_critic",
      "to": "fail_chapter", "condicional": true, "labels": ["skip_chapter"] },
    { "id": "technical_director->commit_episode", "from": "technical_director",
      "to": "commit_episode", "condicional": false, "labels": [] },
    { "id": "commit_episode->continuity_master", "from": "commit_episode",
      "to": "continuity_master", "condicional": true, "labels": ["next_chapter"] },
    { "id": "commit_episode->__end__", "from": "commit_episode", "to": "__end__",
      "condicional": true, "labels": ["series_complete"] }
  ]
}
```

Derivación: `build_pipeline_graph(_GatewayNulo, project, …)` →
`grafo.get_graph().nodes/.edges` (la misma fuente que usa `draw_mermaid()`),
anotando cada nodo con `AGENT_REGISTRY`/`definiciones_del_proyecto` y el
`LLMConfig` resuelto por `resolve_role_spec` + overrides del proyecto. El wiring
del grafo **nunca se duplica** en el endpoint ni en el cliente.

## 6. Protocolo de eventos

### 6.1 Store: `job_events` gana payload JSON

```sql
-- migración guardada (PRAGMA table_info): compatible con datos-servidor/ existentes
ALTER TABLE job_events ADD COLUMN payload TEXT;   -- JSON o NULL

-- columna nueva en jobs: huella del spec congelado (§11.4)
ALTER TABLE jobs ADD COLUMN spec_fingerprint TEXT;  -- sha256 del TOML al arrancar
```

`JobEvent` suma `payload: Optional[dict]`; `add_event(job_id, kind, message,
payload=None)` mantiene su firma actual para los kinds legacy. Los eventos
históricos (payload `NULL`) siguen legibles: el cliente los muestra como
`progress` de solo texto.

### 6.2 Catálogo de kinds

| Kind | Cuándo | Payload |
|---|---|---|
| `node_start` | el worker observa que un nodo arranca (`stream_mode="updates"`) | `{node, rol, paso}` |
| `node_end` | el nodo terminó | `{node, rol, paso, claves: [...]}` |
| `token` | chunk del LLM en streaming (§7.1) | `{node, rol, texto}` |
| `tool_start` | el loop de tools invoca una tool (§7.3) | `{node, rol, tool, args}` |
| `tool_end` | la tool devolvió | `{node, rol, tool, resumen}` |
| `progress` · `error` · `done` | como hoy (textos por superstep, fallo, cierre) | `null` |

### 6.3 Formato SSE resultante

```
id: 42
event: node_start
data: {"kind":"node_start","job_id":"a1b2c3","ts":"2026-09-09T12:00:03+00:00","node":"scriptwriter","rol":"scriptwriter","paso":7}

id: 43
event: token
data: {"kind":"token","job_id":"a1b2c3","ts":"…","node":"scriptwriter","rol":"scriptwriter","texto":"Escena 1:"}
```

El `event:` del frame sigue siendo el kind (compatibilidad con el cliente
`EventSource` actual); `data` pasa de texto plano a JSON con `kind` dentro. El
puente SSE→SQLite (polling interno de 0.5 s) se mantiene: la granularidad por
token no exige push —el rate real es el de generación del LLM, no por carácter—
y preserva el modelo de un solo proceso.

## 7. Streaming de tokens y tool calling

### 7.1 Extensión del puerto

`StructuredGenerationPort.generate` gana un callback opcional; `make_agent_node`
lo recibe del gateway y lo conecta al nodo en ejecución:

```python
EventoGeneracion = {"tipo": "token" | "tool_start" | "tool_end", ...}
EventCallback = Callable[[EventoGeneracion], None]

class StructuredGenerationPort(Protocol):
    def generate(self, rol, esquema, system_prompt, user_prompt,
                 *, on_event: Optional[EventCallback] = None) -> BaseModel: ...
```

`LangChainStructuredGateway.generate`: con `on_event`, itera
`self._structured[rol].stream(mensajes)` acumulando el objeto parcial y emitiendo
`{"tipo": "token", "texto": …}` por chunk; el valor final es el objeto completo
(igual validación `isinstance` que hoy). Si el proveedor no soporta streaming de
salida estructurada (excepción al iniciar el stream), **fallback al `invoke`
actual**: el rol solo emite `node_start`/`node_end`. La política de reintentos
se conserva. El CLI y los tests con gateway falso no pasan `on_event` →
comportamiento idéntico al actual.

`build_gateway(project, event_sink=None)` conecta el sink una vez por job: el
runner lo crea y cada evento termina en `job_events` con el nodo activo
contextualizado (el gateway sabe el rol; el nodo lo aporta el runner).

### 7.2 Granularidad de grafo: `updates`

`GenerateSeriesUseCase.stream` suma `stream_mode="updates"` (además de
`values`): el runner observa, por superstep, **qué nodo(s) corrieron** y emite
`node_start`/`node_end` con las claves actualizadas. El texto human-readable de
`describe_progress` se conserva como `progress` (los overlays legacy del log).

### 7.3 Tools integradas

Registro `sinnema/infrastructure/tools/` con tools **deterministas y locales**
(MVP):

| Tool | Qué hace |
|---|---|
| `buscar_lore` | Busca en el lore persistido del proyecto (`JsonLoreStore`) por consulta |
| `leer_formato` | Devuelve las cotas editoriales de `[formato]` del proyecto |

`[agentes.<rol>].tools` (§3) habilita el loop **dentro del nodo**, previo a la
generación estructurada — evita el conflicto `bind_tools` vs
`with_structured_output`:

```text
cliente plano del rol + bind_tools(tools)
→ invocar con [System, Human]
→ ¿tool_calls? ejecutar la tool del registro (eventos tool_start/tool_end)
  y adjuntar ToolMessages → repetir (máx. 5 iteraciones, guard de costo)
→ generación estructurada final sobre la conversación extendida
  (with_structured_output + invoke, con streaming §7.1 si procede)
```

El loop no consume supersteps del grafo: `limite_de_recursion` no cambia. Sin
`tools` declaradas, el camino es exactamente el de hoy (cero overhead, cero
cambio en tests). Las tools se definen con `@tool` de LangChain y su docstring
es el `descripcion` que ve el modelo.

### 7.4 Auditoría ampliada

Cada paso de agente loguea además los prompts (fuente del inspector §11.3):
`NNN_<nodo>_prompts.txt` con `SystemMessage`, `HumanMessage` y los
`ToolMessage`/tool calls si los hubo, junto a la respuesta estructurada. La
pista existente no cambia de formato.

## 8. Arquitectura frontend

### 8.1 Estructura de `web/`

```text
web/
├── package.json · vite.config.ts (proxy /api → http://127.0.0.1:8000)
├── tsconfig.json · tailwind · shadcn/ui · index.html
└── src/
    ├── types/        # §4
    ├── api/          # cliente REST + SSE (fetch/EventSource, sin axios)
    ├── stores/       # zustand: projectStore · executionStore · selectionStore
    ├── scene/        # SceneCanvas · ProjectScene · AgentNode3D · EdgeLine ·
    │                 # EdgePulses · CameraRig · layout.ts · dispose.ts
    ├── overlay/      # TopBar/ProjectSwitcher · InspectorPanel ·
    │                 # LLMConfigForm · StateInspector · FlowEditor ·
    │                 # EventTimeline · JobsDrawer
    └── hooks/        # useExecutionSync · useProjectNetwork · useCatalogos
```

### 8.2 Hidratación por proyecto

`useProjectNetwork(projectId)` = `GET /red` + `GET /api/projects/{id}` en
paralelo → `projectStore`. El cambio de proyecto remonta todo el subárbol:
`<ProjectScene key={projectId} network={…} />` — React descarta el árbol 3D y
R3F disposea geometrías/materiales declarativos al desmontar.

### 8.3 Disciplina de dispose (memoria WebGL)

- Nada compartido entre proyectos: geometrías, materiales y texturas viven bajo
  `ProjectScene`; el remount por `key` es el mecanismo de liberación.
- Recursos imperativos (pool `InstancedMesh` de pulsos, `TubeGeometry` de
  aristas, `Text` de drei, render targets) se liberan en el `useEffect` cleanup
  correspondiente (`geometry.dispose()`, `material.dispose()`, `texture.dispose()`).
- `dispose.ts` expone `disposeObject3D(root)` que recorre y disposea, usado en
  los cleanups y como red de seguridad al desmontar `ProjectScene`.
- El `Canvas` de R3F **no** se desmonta al cambiar de proyecto (solo su
  contenido): se evita recrear el contexto WebGL. `gl.dispose()` /
  `forceContextLoss` solo al salir de la vista 3D completa.
- Verificación: cambiar entre proyectos N veces con `renderer.info.memory`
  visible en dev — geometrías/texturas vuelven al baseline tras cada cambio.

### 8.4 Servido y desarrollo

- Dev: `npm run dev` (Vite en :5173) con proxy de `/api`; `sinnema-server` en
  :8000 como hoy.
- Producción: `create_app` resuelve la UI en cascada `web/dist` (si existe) →
  `static/index.html` (legacy). `GET /` sirve el `index.html` del dist; los
  assets bajo `/assets/`. `web/dist` **no se commitea**: sin build JS, el
  fallback mantiene `sinnema-server` funcional (y la wheel empaqueta solo lo
  de siempre).

## 9. Canvas 3D (Three.js / R3F)

### 9.1 Layout determinista por fases

Columnas en **X** por fase, en el orden del pipeline; los agentes de una misma
fase se apilan en **Z**; **Y** eleva los nodos estructurales de cierre:

| Fase | Columna | Contenido |
|---|---|---|
| `serie` | 0 | `plan_series` |
| `contexto` | 1 | roles de `[flujo].contexto` (o `continuity` legacy) |
| `escritura` | 2 | `scriptwriter` |
| `transformacion` | 3 | transformadores en orden |
| `compuerta` | 4 | revisor (`chief_critic` o custom) |
| `enriquecimiento` | 5 | enriquecedores en orden |
| `cierre` | 6 | `commit_episode`, `fail_chapter` (y `consolidar_plan` en `hasta=plan`) |

`__start__`/`__end__` son anclas discretas a ambos extremos. El layout es
función pura de `EffectiveNetwork` (mismo input → mismo dibujo; testeable).
Un hito `hasta` menor simplemente deja columnas vacías: el grafo ya viene
truncado del backend.

### 9.2 Nodos: geometría por tipo, halo por proveedor

| Tipo | Geometría (primitiva low-poly) |
|---|---|
| `serie` | icosaedro |
| `contexto` | octaedro |
| `escritor` | dodecaedro |
| `transformador` | toro |
| `revisor` | prisma hexagonal (cilindro de 6 lados) |
| `enriquecedor` | esfera facetada |
| `cierre` | anillo fino gris, escala menor |

Halo/anillo emisivo con color del proveedor del `LLMConfig` (diferenciación
"instantánea" de heterogeneidad de modelos):

| Proveedor | Color |
|---|---|
| anthropic | `#D97757` (arcilla) |
| openai | `#10A37F` (esmeralda) |
| google | `#4285F4` (azul) |
| ollama | `#7C3AED` (violeta) |

Etiqueta `Billboard + Text` (drei) sobre el nodo: rol (grande) y
`proveedor/modelo` (pequeño, color del halo). Nodos estructurales sin LLM
(`commit_episode`, `fail_chapter`) van en gris sin halo.

### 9.3 Aristas dirigidas

Curva bezier cuadrática por arista (punto medio elevado en Y para despejar los
nodos), renderizada con `Line` de drei (Line2, grosor en píxeles) y **cono
flecha** en `t≈0.97` orientado por la tangente. Las condicionales van
discontinuas (dash) con su `label` (`revise`, `approve`, `skip_chapter`,
`next_chapter`, `series_complete`) en un `Text` pequeño sobre el punto medio.
El ciclo de crítica (compuerta → escritor) queda visualmente evidente por la
curva de retorno.

### 9.4 Pulsos: mensajes viajando por las aristas

Pool único de `InstancedMesh` (esferas, ~64 instancias) compartido por la
escena; cada pulso activo es `{edgeId, t, velocidad}` avanzado en `useFrame`
sobre la curva de su arista. Activación:

- **Dirigida por eventos**: `node_end(A)` seguido de `node_start(B)` dispara un
  pulso por las aristas `A→B` (mensaje transmitido).
- **Ambiental**: mientras un job corre, flujo lento y tenue sobre el camino
  activo (la secuencia de nodos ya visitados en el capítulo corriente).

### 9.5 Estados visuales por nodo

| Estado | Disparador | Técnica |
|---|---|---|
| Idle | sin actividad | emissive tenue estático |
| Processing | `node_start`, sin tokens aún | respiración de escala + pulso lento de `emissiveIntensity` (seno en `useFrame`) |
| Streaming | eventos `token` llegando | anillo con `shaderMaterial` propio (uniform `time`, barrido radial) + emissive alta |
| Tool Call | `tool_start`…`tool_end` | halo cambia a ámbar + glifo de tool en la etiqueta |
| Error | fallo del nodo / `error` del job | parpadeo rojo que decae a los 5 s |
| Done | `node_end` | destello único y decaimiento a glow suave |

La máquina de estados la calcula `executionStore` (§10) en el mapa
`nodo → NodeVisualState`; el componente 3D solo interpola hacia el estado
objetivo (transiciones suaves, nunca saltos).

### 9.6 Cámara, controles y selección

- `OrbitControls` (drei): rotación/zoom/pan; damping habilitado.
- **CameraRig**: al cambiar la selección, amortigua (lerp ~0.08 por frame, en
  `useFrame`) `controls.target` hacia el nodo y la posición de cámara hacia un
  encuadre que **conserva el contexto global** (distancia proporcional al
  bounding box de la red, no un primer plano). Botón "reencuadrar" y `Escape`
  devuelven la vista general.
- Selección/hover por **raycasting nativo de R3F**: `onPointerOver`/
  `onClick`/`onPointerOut` en el grupo del nodo (precisión de mesh, sin
  raycaster manual). Hover: halo expandido + cursor pointer. Click: selección →
  sincroniza `selectionStore` → el `InspectorPanel` (§11) y el CameraRig.
- Doble click: enfocar. La selección también es programable desde el overlay
  (click en un evento del timeline selecciona el nodo emisor).

## 10. Pipeline de sincronización

`useExecutionSync(jobId)` (hook dueño del ciclo de vida del stream):

1. Abre `EventSource(/api/jobs/{id}/events)`; el navegador gestiona
   reconexión + `Last-Event-ID` (el endpoint ya numera con `id:`).
2. Dispacha cada frame al `executionStore` (zustand): log circular (últimos
   ~500 eventos, para el timeline), mapa `nodo → NodeVisualState`, buffer de
   tokens por nodo (para el inspector), contadores por kind.
3. Respaldo: polling `GET /api/jobs/{id}` cada 2 s para el badge de status (ya
   existe en la web actual) — cubre SSE bloqueado por proxy.
4. Al llegar a status terminal (`completed`/`failed`), cierra el EventSource y
   consolida (`GET …/artifacts` para el inspector).

**Rendimiento — suscripciones transitorias**: los componentes de la escena no
usan hooks de estado por evento (un ráfaga de `token` re-renderizaría React a
esa frecuencia). Patrón: `executionStore.subscribe` escribe en un mapa mutable
`Map<nodeId, NodeVisualState>` + contadores; los `useFrame` de cada nodo leen
ese mapa y animan. Los overlays (timeline, buffers) sí se suscriben normal:
frecuencia de UI, no de render.

## 11. Panel de inspección y mutación (overlay 2D)

Panel lateral derecho sincronizado con la selección 3D (`selectionStore`);
tres pestañas.

### 11.1 Pestaña Agente (mutación)

- Formulario `LLMConfig`: select de proveedor (catálogo), modelo (input +
  sugerencias por proveedor), sliders **temperatura** (0.0–2.0, paso 0.05) y
  **top_p** (0.0–1.0, paso 0.01), **max_tokens** (number input > 0),
  checkboxes de **tools** (catálogo), editor de **reglas** (una por línea) y —
  para customs — editor de `instrucciones` con preview de placeholders
  (reusa `GET /api/projects/{id}/prompts`).
- Rangos y validaciones espejo del backend (§3): el formulario nunca deja
  armar un payload que el backend rechazaría.
- Guardar = `PUT /api/projects/{id}` con el dict completo (forma TOML en
  claves españolas, igual que la web actual) → re-hidratación de `/red` (los
  halos/etiquetas reflejan el cambio al instante en la escena, que es
  configuración, no corrida).

### 11.2 Pestaña Estado (inspección en vivo)

- Por job activo o seleccionado: timeline de artefactos (§5 `/artifacts`) con
  resumen y JSON colapsable; historial de mensajes (prompts §7.4); scratchpad
  de tools (args/resultados); stream de tokens del nodo seleccionado en vivo.
- Claves actualizadas por paso (de `node_end`) como vista "diff" del estado.

### 11.3 Pestaña Flujo

Editor de `[flujo]` (fases ordenables, revisor, `hasta`) — reemplaza funcional
de `construirEditorFlujo` de la web actual, con los mismos validadores.

### 11.4 Semántica de mutación y spec desfasado

- Toda mutación persiste en TOML y muestra el aviso persistente: **"Guardado:
  aplica a la próxima corrida"** (el servicio no se reinicia; el grafo del job
  en curso no cambia).
- `spec_desfasado`: al arrancar, el runner registra `spec_fingerprint`
  (sha256 del TOML congelado) en el job. `GET /api/jobs` lo compara contra el
  fingerprint vigente: si hay job RUNNING del proyecto y el TOML cambió desde
  su arranque, la UI muestra el badge **"job activo con spec congelado"** sobre
  el proyecto y por job.

## 12. Compatibilidad y migración

1. **`job_events`/`jobs`**: ALTER TABLEs guardados con `PRAGMA table_info`
   (idempotentes). Bases existentes de `datos-servidor/` siguen operativas;
   eventos viejos (sin payload) se renderizan como texto.
2. **Contrato del puerto**: `on_event` es opcional con default `None` → CLI,
   tests con gateway falso y uso actual quedan intactos.
3. **Reemplazo de la web**: `web/dist` → fallback `static/`. `index.html` se
   elimina solo al cierre (Fase 6) con esta **lista de paridad**: CRUD de
   proyectos, editor de flujo/alcance, agentes custom, lanzar corridas
   (`POST /api/series`), lista de jobs + SSE + viewer (enlace) + deliverable,
   lore (ver/reiniciar), prompts preview.
4. **Empaquetado**: la wheel no incluye `web/` ni `dist`; sin build JS el
   fallback legacy mantiene `sinnema-server` útil. El build queda documentado
   en README (`cd web && npm install && npm run build`).
5. **CLI**: sin cambios (los flags existentes no se tocan).

## 13. Pruebas

- **pytest (backend)**: validaciones §3 (top_p/max_tokens/tools + TOML
  round-trip), `/red` refleja flujo efectivo y `hasta` (nodos/edges por
  configuración, como hoy testea `flujo-efectivo`), migración SQLite sobre una
  base vieja fixture, eventos por nodo con gateway falso que emite tokens/tools,
  `spec_fingerprint`/`spec_desfasado`, endpoints de artefactos, fallback de
  streaming (proveedor sin stream → invoke).
- **vitest (frontend)**: parsers SSE (kinds, payload legacy sin JSON), reducers
  del executionStore (mapa de estados visuales, buffers, log circular), layout
  determinista (snapshot), formularios (rangos espejo del backend).
- **Manual/visual**: verificación de dispose (§8.3), states 3D con corrida real
  en un proyecto de prueba, teclado/focus del overlay.
- La suite actual (~365 tests) debe estar verde al cierre de cada fase.

## 14. Plan de desarrollo

Rama: `feature/red-3d`. Cada fase = PR(s) independables con suite verde y
README/spec actualizados.

### Fase 1 — Config LLM completa + red como recurso

> **Implementada** (2026-09-09): claves `top_p`/`max_tokens`/`tools` con
> round-trip `PUT`/`GET` y llegada a los constructores LangChain; `/red` y
> `/api/meta/catalogos` operativos. El vocabulario de tools integradas vive en
> `sinnema/application/tools.py` (las implementaciones `@tool` llegan en la
> Fase 4 y se registran contra ese catálogo).

1. `projects.py`: `top_p`/`max_tokens`/`tools` en `AgentConfig`,
   `_CLAVES_AGENTE` y validaciones §3.12–13.
2. `providers.py`: firma extendida de `build_provider_model` (mapeo
   `num_predict` en Ollama) y propagación desde `resolve_role_spec`.
3. `GET /api/projects/{id}/red`: derivación desde `grafo.get_graph()` con
   `_GatewayNulo`, anotación de registro + `LLMConfig` resuelto.
4. `GET /api/meta/catalogos`.

PRs sugeridos: **1a** config+providers (1–2), **1b** endpoints (3–4).

**Criterio de aceptación**: un TOML con `top_p`/`max_tokens`/`tools` hace
round-trip por `PUT`/`GET` y llega a los constructores LangChain;
`/red` de cada proyecto empaquetado coincide en nodos con su Mermaid de
`flujo-efectivo`.

### Fase 2 — Scaffold web + canvas estático

1. `web/` con Vite+R3F+TS+Tailwind/shadcn, proxy y lint.
2. Tipos §4, cliente REST, `projectStore`/`selectionStore`, `ProjectSwitcher`.
3. `ProjectScene`: layout §9.1, nodos §9.2 (geometrías, halos, etiquetas),
   aristas §9.3 (curvas, flechas, condicionales).
4. Selección/hover por raycasting + `CameraRig` con lerp y reencuadre (§9.6).
5. Dispose §8.3 + servido `web/dist` con fallback (§8.4).

PRs: **2a** scaffold+layout+nodos, **2b** aristas+cámara+selección, **2c**
dispose+servido.

**Criterio de aceptación**: cambiar entre los 7 proyectos empaquetados
re-hidrata la escena sin fuga de memoria (§8.3); la selección enfoca con suavizado
y el overlay muestra los metadatos del nodo; `sinnema-server` sirve el build.

### Fase 3 — Eventos por nodo

1. Migración `job_events.payload` + `jobs.spec_fingerprint` (§6.1) y `add_event`
   extendido.
2. `stream_mode="updates"` en el use case (§7.2); el runner emite
   `node_start`/`node_end` + `progress` textual como hoy.
3. SSE con `data` JSON (§6.3) + `GET …/events/history` + `spec_desfasado`.

PRs: **3a** store+migración, **3b** runner+SSE.

**Criterio de aceptación**: con un gateway falso que corre el grafo, el timeline
muestra la secuencia real de nodos (incluida la compuerta y el ciclo de crítica)
y una base `jobs.sqlite` pre-migración sigue legible.

### Fase 4 — Tokens y tools

1. `on_event` en el puerto + `generate` con streaming y fallback (§7.1);
   `build_gateway(event_sink=…)`.
2. Registro de tools `buscar_lore`/`leer_formato` + loop `bind_tools` con guard
   de iteraciones (§7.3).
3. Auditoría con prompts por paso (§7.4) + endpoints `/artifacts`.

PRs: **4a** tokens, **4b** tools, **4c** auditoría+artefactos.

**Criterio de aceptación**: con proveedor real, un rol con tools completa una
corrida con eventos `tool_start/tool_end` y tokens visibles; sin `tools` y sin
`on_event`, los tests actuales pasan sin edición.

### Fase 5 — Sincronización + estados visuales

1. `useExecutionSync` + `executionStore` (suscripciones transitorias §10).
2. Máquina de estados visuales §9.5 en los materiales de los nodos.
3. Pulsos dirigidos por eventos + flujo ambiental (§9.4).

PRs: **5a** hook+stores, **5b** estados, **5c** pulsos.

**Criterio de aceptación**: una corrida real se sigue en la 3D de punta a punta
(planner → capítulos → compuerta → commit) sin drops de framerate medibles y con
el timeline 2D consistente con los eventos.

### Fase 6 — Inspector, mutación y reemplazo

1. `InspectorPanel`: pestaña Agente con formulario LLM completo + flujo de
   guardado §11.1 (PUT, re-hidratación, aviso).
2. Pestaña Estado (artefactos, prompts, scratchpad, tokens) y pestaña Flujo
   (§11.2–11.3).
3. Paridad §12.3 (CRUD, customs, jobs, lore, viewer) y borrado de
   `static/index.html`.

PRs: **6a** inspector agente, **6b** inspector estado+flujo, **6c** paridad,
**6d** reemplazo.

**Criterio de aceptación**: cambiar proveedor/modelo/temperatura/tools de un
agente desde la 3D persiste en el TOML, la próxima corrida lo usa (verificable
en auditoría) y la lista de paridad §12.3 está completa antes de borrar la UI
vieja.

## 15. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Streaming de salida estructurada variable por proveedor | Fallback documentado a `invoke` (solo node_start/node_end); el contrato final se valida igual |
| `bind_tools` incompatible con `with_structured_output` | Loop de tools separado, previo a la generación estructurada final (§7.3) |
| Migración SQLite rompe bases existentes | ALTERs idempotentes con `PRAGMA table_info` + test con fixture vieja |
| Ráfaga de tokens re-renderiza React | Suscripciones transitorias + estado mutable leído en `useFrame` (§10) |
| Fugas WebGL al alternar proyectos | Remount por `key` + cleanups imperativos + verificación con `renderer.info.memory` (§8.3) |
| Deuda de paridad al reemplazar la web | Lista de paridad explícita (§12.3) como criterio del borrado; fallback hasta entonces |
| Costo/latencia por tools descontroladas | Guard de iteraciones (5) y tools deterministas locales en el MVP |
| Falso sensación de "en caliente" en corrida activa | Indicador `spec_desfasado` + aviso persistente "aplica a la próxima corrida" (§11.4) |

## 16. Fuera de alcance

Mutación en vuelo de un job en curso (re-resolver specs por nodo), topología
libre o edges declarables desde la UI, ejecución de nodos sueltos, edición del
grafo arrastrando nodos (el layout es derivado), multiusuario/autenticación
real (sigue `X-Owner`), tools externas (search, código, red), versionado de
proyectos, y persistencia backend de preferencias de cámara/layout.
