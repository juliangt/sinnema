// Tipado exhaustivo del frontend (spec-red-3d §4).
// Fuente única de tipos: cada bloque documenta su origen (endpoint o sección
// TOML). `PipelineState` no se tipa completo: el inspector muestra artefactos
// por paso, no el TypedDict crudo.

// ── Catálogos (GET /api/meta/catalogos, GET /api/meta/roles) ─────────────
export type ProveedorLlm = 'anthropic' | 'openai' | 'google' | 'ollama'

/** Hitos del pipeline (`ALCANCES` del backend: plan…produccion). */
export type Hito = string

export interface Catalogos {
  proveedores: ProveedorLlm[]
  modelos: Record<ProveedorLlm, string[]> // sugeridos por proveedor
  tools: { nombre: string; descripcion: string }[]
  hitos: Hito[] // plan…produccion (ALCANCES)
  tipos_custom: ('contexto' | 'revisor' | 'enriquecedor')[]
  contratos: ('notas' | 'texto' | 'dictamen')[]
  entradas_custom: string[] // CATALOGO_ENTRADAS
}

// ── Config LLM por agente ([agentes.<rol>] resuelto: proyecto > default) ──
export interface LLMConfig {
  proveedor: ProveedorLlm
  modelo: string
  temperatura: number // 0.0–2.0
  top_p?: number // 0.0–1.0, ausente = default del proveedor
  max_tokens?: number // > 0, ausente = default del proveedor
  tools: string[] // registro §7.3; [] = sin tools
}

// ── Grafo efectivo (GET /api/projects/{id}/red) ───────────────────────────
export type TipoNodo =
  | 'serie'
  | 'contexto'
  | 'escritor'
  | 'transformador'
  | 'revisor'
  | 'enriquecedor'
  | 'cierre'

export type FaseId =
  | 'serie'
  | 'contexto'
  | 'escritura'
  | 'transformacion'
  | 'compuerta'
  | 'enriquecimiento'
  | 'cierre'

export interface AgentNode {
  id: string // nombre de nodo del grafo ("scriptwriter", "chief_critic", …)
  rol: string | null // rol del registro; null en commit/fail/consolidar
  tipo: TipoNodo // fija geometría y semántica visual (§9.2)
  fase: FaseId // columna del layout (§9.1)
  estructural: boolean // true: nodo escrito a mano (plan_series, compuerta, cierre)
  descripcion: string // del AGENT_REGISTRY
  esencial: boolean
  llm: LLMConfig | null // null solo en nodos sin agente (cierre)
  custom?: {
    // solo agentes custom del TOML
    contrato: string
    entradas: string[]
    instrucciones: string
  }
}

export interface EdgeTransition {
  id: string // "<from>-><to>"
  from: string // id de nodo, o "__start__"
  to: string // id de nodo, o "__end__"
  condicional: boolean
  labels: string[] // revise|approve|skip_chapter|next_chapter|series_complete
}

export interface EffectiveNetwork {
  project_id: string
  declarado: boolean // ¿el TOML declara [flujo]?
  hasta: string // hito
  nodes: AgentNode[]
  edges: EdgeTransition[]
  limite_recursion: number
}

// ── Proyectos (GET /api/projects, GET/PUT /api/projects/{id}) ─────────────
// Nota: el payload real de GET /api/projects usa project_id/brand_name (las
// claves del backend); la spec §4 los abrevia id/marca.
export interface ProjectSummary {
  project_id: string
  brand_name: string
  concepto: string
  default_topic: string
  audience: string
  language: string
  editable: boolean
}

export interface FlowSpec {
  // [flujo] en crudo (claves TOML)
  contexto?: string[]
  transformaciones?: string[]
  revisor?: string
  enriquecimiento?: string[]
  hasta?: string
}

export interface ProjectDetail {
  // forma del dict TOML (claves en español)
  proyecto: Record<string, unknown>
  voz?: Record<string, unknown>
  visual?: Record<string, unknown>
  formato?: Record<string, unknown>
  agentes?: Record<string, Record<string, unknown>>
  pipeline?: Record<string, unknown>
  flujo?: FlowSpec
  editable: boolean
}

// ── Jobs y ejecución (GET /api/jobs/{id}, §6) ─────────────────────────────
export type JobStatus = 'queued' | 'running' | 'completed' | 'failed'

export interface Job {
  job_id: string
  project_id: string
  topic: string
  num_chapters: number
  max_critique_attempts: number
  status: JobStatus
  created_at: string
  started_at?: string
  finished_at?: string
  error?: string
  spec_desfasado?: boolean // §11.4: el TOML cambió desde que el job arrancó
}

export type RuntimeExecutionEvent =
  | {
      kind: 'node_start'
      ts: string
      job_id: string
      node: string
      rol: string | null
      paso: number
    }
  | {
      kind: 'node_end'
      ts: string
      job_id: string
      node: string
      rol: string | null
      paso: number
      claves: string[]
    }
  | { kind: 'token'; ts: string; job_id: string; node: string; rol: string; texto: string }
  | {
      kind: 'tool_start'
      ts: string
      job_id: string
      node: string
      rol: string
      tool: string
      args: unknown
    }
  | { kind: 'tool_end'; ts: string; job_id: string; node: string; rol: string; tool: string; resumen: string }
  | { kind: 'progress' | 'error' | 'done'; ts: string; job_id: string; mensaje: string }

// ── Auditoría (GET /api/jobs/{id}/artifacts[/{n}]) ────────────────────────
export interface Artifact {
  n: number // número de paso (NNN_)
  paso: string // nombre del paso/nodo
  resumen: string
  artefacto?: unknown // JSON del contrato (si lo hubo)
  prompts?: string // contenido del NNN_<nodo>_prompts.txt (§7.4)
}
