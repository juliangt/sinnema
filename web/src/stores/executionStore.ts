// Estado de ejecución (spec-red-3d §10): recibe los eventos del stream del
// job y mantiene DOS niveles de estado.
//
// - Nivel UI (reactivo, frecuencia de interfaz): log circular de eventos no
//   token, status del job, contadores. Solo estos disparan re-render.
// - Nivel escena (MUTABLE, leído en useFrame): mapa nodo → NodeVisualState,
//   buffers de tokens por nodo, pulsos y camino activo. Se muta in place
//   SIN set(): una ráfaga de tokens nunca re-renderiza React (§10).
//
// La máquina de estados visuales por nodo (§9.5) se calcula acá; los
// componentes 3D solo interpolan hacia el estado objetivo.

import { create } from 'zustand'
import type { Artifact, EdgeTransition, JobStatus, RuntimeExecutionEvent } from '../types'

export type NodeVisualState =
  | 'idle'
  | 'processing'
  | 'streaming'
  | 'tool'
  | 'error'
  | 'done'

/** Entrada del log circular del timeline (últimos ~500 eventos). */
export interface EntradaLog {
  id: number
  ts: string
  kind: RuntimeExecutionEvent['kind'] | 'legacy'
  texto: string
  node?: string
}

export interface Pulso {
  edgeId: string
  t: number
  velocidad: number
}

const TAMANIO_LOG = 500
/** Pulsos dirigidos por eventos (mensaje viajando A→B). */
const VELOCIDAD_PULSO = 1.1
/** Flujo ambiental lento sobre el camino activo. */
const VELOCIDAD_AMBIENTAL = 0.35
const MAX_PULSOS = 64

interface EstadoEjecucion {
  // ── Nivel UI (reactivo) ────────────────────────────────────────────────
  jobId: string | null
  status: JobStatus | 'idle'
  specDesfasado: boolean
  log: EntradaLog[]
  contadores: Record<string, number>
  error: string | null
  artefactos: Artifact[] | null

  // ── Nivel escena (MUTABLE: no pasa por set()) ─────────────────────────
  estadoNodos: Map<string, { estado: NodeVisualState; desde: number }>
  tokens: Map<string, string>
  pulsos: Pulso[]
  caminoActivo: string[]
  /** Aristas del proyecto hidratado: sobre ellas viajan los pulsos (§9.4). */
  aristas: EdgeTransition[]

  iniciar: (jobId: string | null) => void
  /** Hidrata las aristas del proyecto activo (ProjectScene lo llama). */
  configurarRed: (edges: EdgeTransition[]) => void
  aplicarEvento: (evento: RuntimeExecutionEvent | { kind: 'legacy'; texto: string }) => void
  setStatus: (status: JobStatus, specDesfasado?: boolean) => void
  consolidar: (artefactos: Artifact[]) => void
  reset: () => void
}

let secuenciaLog = 0

export const useExecutionStore = create<EstadoEjecucion>()((set, get) => ({
  jobId: null,
  status: 'idle',
  specDesfasado: false,
  log: [],
  contadores: {},
  error: null,
  artefactos: null,

  estadoNodos: new Map(),
  tokens: new Map(),
  pulsos: [],
  caminoActivo: [],
  aristas: [],

  iniciar: (jobId) => {
    secuenciaLog = 0
    set({
      jobId,
      status: jobId === null ? 'idle' : 'queued',
      specDesfasado: false,
      log: [],
      contadores: {},
      error: null,
      artefactos: null,
      estadoNodos: new Map(),
      tokens: new Map(),
      pulsos: [],
      caminoActivo: [],
    })
  },

  configurarRed: (edges) => set({ aristas: edges }),

  setStatus: (status, specDesfasado = false) => set({ status, specDesfasado }),

  consolidar: (artefactos) => set({ artefactos }),

  reset: () => get().iniciar(null),

  aplicarEvento: (evento) => {
    const estado = get()
    if (evento.kind !== 'legacy') {
      const ev = evento
      estado.contadores[ev.kind] = (estado.contadores[ev.kind] ?? 0) + 1

      switch (ev.kind) {
        case 'node_start': {
          marcarNodo(estado, ev.node, 'processing')
          avanzarCamino(estado, ev.node)
          // Pulso dirigido: el mensaje llega por las aristas A→B (§9.4),
          // donde A es el nodo visitado inmediatamente antes de B.
          dispararPulsos(estado, ev.node, VELOCIDAD_PULSO)
          empujarLog(set, estado, {
            id: ++secuenciaLog, ts: ev.ts, kind: 'node_start',
            texto: `▶ ${ev.node} (${ev.rol ?? '—'}) · paso ${ev.paso}`, node: ev.node,
          })
          break
        }
        case 'node_end': {
          marcarNodo(estado, ev.node, 'done')
          empujarLog(set, estado, {
            id: ++secuenciaLog, ts: ev.ts, kind: 'node_end',
            texto: `✔ ${ev.node} · claves: ${ev.claves.join(', ')}`, node: ev.node,
          })
          break
        }
        case 'token': {
          // Nivel escena: buffer acumulado sin re-render (§10).
          const previo = estado.tokens.get(ev.node) ?? ''
          estado.tokens.set(ev.node, previo + ev.texto)
          marcarNodo(estado, ev.node, 'streaming')
          break
        }
        case 'tool_start': {
          marcarNodo(estado, ev.node, 'tool')
          empujarLog(set, estado, {
            id: ++secuenciaLog, ts: ev.ts, kind: 'tool_start',
            texto: `🔧 ${ev.node}: ${ev.tool}`, node: ev.node,
          })
          break
        }
        case 'tool_end': {
          marcarNodo(estado, ev.node, 'streaming')
          empujarLog(set, estado, {
            id: ++secuenciaLog, ts: ev.ts, kind: 'tool_end',
            texto: `🔧 ${ev.node}: ${ev.tool} → ${ev.resumen}`, node: ev.node,
          })
          break
        }
        case 'media_start': {
          // Media (recursos-ancla §6/§9.2): progreso de keyframes en el
          // stream, igual que los tokens de los agentes.
          empujarLog(set, estado, {
            id: ++secuenciaLog, ts: ev.ts, kind: 'media_start',
            texto: `🎬 render_keyframes: escena ${ev.escena} (${ev.proveedor})…`,
            node: 'render_keyframes',
          })
          break
        }
        case 'media_end': {
          const texto = ev.error !== undefined
            ? `✖ escena ${ev.escena} queda sin keyframe: ${ev.error}`
            : `✔ keyframe escena ${ev.escena}: ${ev.archivo ?? ''}` +
              (ev.qa !== undefined ? ` · QA ${ev.qa} (${ev.intentos ?? 1} intento/s)` : '')
          empujarLog(set, estado, {
            id: ++secuenciaLog, ts: ev.ts, kind: 'media_end',
            texto, node: 'render_keyframes',
          })
          break
        }
        case 'error': {
          // El job falló: los nodos en vuelo pasan a error (parpadeo 5 s).
          for (const marca of estado.estadoNodos.values()) {
            if (marca.estado !== 'idle' && marca.estado !== 'done') {
              marca.estado = 'error'
              marca.desde = performance.now()
            }
          }
          set({ error: ev.mensaje })
          empujarLog(set, estado, {
            id: ++secuenciaLog, ts: ev.ts, kind: 'error', texto: `✖ ${ev.mensaje}`,
          })
          break
        }
        case 'progress':
          empujarLog(set, estado, {
            id: ++secuenciaLog, ts: ev.ts, kind: 'progress', texto: ev.mensaje,
          })
          break
        case 'done':
          empujarLog(set, estado, {
            id: ++secuenciaLog, ts: ev.ts, kind: 'done', texto: ev.mensaje,
          })
          break
      }
      return
    }

    // Evento legacy (payload NULL): solo texto en el timeline (§6.1).
    empujarLog(set, estado, {
      id: ++secuenciaLog, ts: new Date().toISOString(), kind: 'legacy',
      texto: evento.texto,
    })
  },
}))

// ------------------------------ internals ------------------------------

function marcarNodo(estado: EstadoEjecucion, nodo: string, visual: NodeVisualState): void {
  estado.estadoNodos.set(nodo, { estado: visual, desde: performance.now() })
}

function avanzarCamino(estado: EstadoEjecucion, nodo: string): void {
  // El capítulo corriente se reinicia cuando el ciclo vuelve a un nodo ya
  // visitado (revise → escritor): el camino se trunca desde ahí.
  if (estado.caminoActivo.includes(nodo)) {
    estado.caminoActivo = estado.caminoActivo.slice(estado.caminoActivo.indexOf(nodo))
  }
  estado.caminoActivo.push(nodo)
}

function empujarLog(
  set: (parcial: Partial<EstadoEjecucion>) => void,
  estado: EstadoEjecucion,
  entrada: EntradaLog,
): void {
  const log = [...estado.log, entrada]
  if (log.length > TAMANIO_LOG) log.splice(0, log.length - TAMANIO_LOG)
  set({ log })
}

function dispararPulsos(estado: EstadoEjecucion, hacia: string, velocidad: number): void {
  const origen = estado.caminoActivo[estado.caminoActivo.length - 2]
  if (origen === undefined) return
  const nuevos = estado.aristas
    .filter((e) => e.from === origen && e.to === hacia)
    .map((e) => ({ edgeId: e.id, t: 0, velocidad }))
  if (nuevos.length > 0) {
    estado.pulsos = [...estado.pulsos, ...nuevos].slice(-MAX_PULSOS)
  }
}

/**
 * Avance de pulsos por frame (lo llama EdgePulses en useFrame): los pulsos
 * mueren al llegar a t=1 y, mientras el job corre, se siembran pulsos
 * ambientales lentos sobre el tramo activo del camino (§9.4).
 */
export function avanzarPulsos(estado: EstadoEjecucion, delta: number): void {
  const vivos: Pulso[] = []
  for (const pulso of estado.pulsos) {
    pulso.t += pulso.velocidad * delta
    if (pulso.t <= 1) vivos.push(pulso)
  }
  if (estado.status === 'running' && estado.caminoActivo.length >= 2) {
    const camino = estado.caminoActivo
    const desde = camino[camino.length - 2]
    const hacia = camino[camino.length - 1]
    const arista =
      estado.aristas.find((e) => e.from === desde && e.to === hacia) ??
      estado.aristas.find((e) => e.from === hacia)
    if (arista !== undefined && Math.random() < delta * 2) {
      vivos.push({ edgeId: arista.id, t: 0, velocidad: VELOCIDAD_AMBIENTAL })
    }
  }
  estado.pulsos = vivos.slice(-MAX_PULSOS)
}
