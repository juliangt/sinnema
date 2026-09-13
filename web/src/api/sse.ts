// Utilidades SSE (§6.3): parser incremental de frames y decodificador del
// `data` que tolera el formato legacy (texto plano) y el JSON con payload.
// El `event:` del frame es el kind; `id:` numera para Last-Event-ID.

import type { RuntimeExecutionEvent } from '../types'

/** Frame SSE crudo tal como llega del stream. */
export interface FrameSSE {
  id?: number
  evento: string
  datos: string
}

/** Kinds que el backend emite como `event:` del frame (§6.2). */
export const KINDS_EVENTOS = [
  'node_start',
  'node_end',
  'token',
  'tool_start',
  'tool_end',
  'media_start',
  'media_end',
  'progress',
  'error',
  'done',
  'end',
] as const

/**
 * Parser incremental de un stream SSE: se alimenta con chunks (que pueden
 * cortar frames en cualquier byte) y devuelve los frames completos.
 */
export function crearParserSSE(): (chunk: string) => FrameSSE[] {
  let buffer = ''
  return (chunk: string): FrameSSE[] => {
    buffer += chunk.replace(/\r\n/g, '\n')
    const frames: FrameSSE[] = []
    let corte = buffer.indexOf('\n\n')
    while (corte !== -1) {
      const bloque = buffer.slice(0, corte)
      buffer = buffer.slice(corte + 2)
      const frame = parsearBloque(bloque)
      if (frame !== null) frames.push(frame)
      corte = buffer.indexOf('\n\n')
    }
    return frames
  }
}

function parsearBloque(bloque: string): FrameSSE | null {
  let id: number | undefined
  let evento = 'message'
  const lineasDatos: string[] = []
  for (const linea of bloque.split('\n')) {
    if (linea.startsWith('id:')) {
      const numero = Number(linea.slice(3).trim())
      if (Number.isFinite(numero)) id = numero
    } else if (linea.startsWith('event:')) {
      evento = linea.slice(6).trim()
    } else if (linea.startsWith('data:')) {
      lineasDatos.push(linea.slice(5).trim())
    }
  }
  if (lineasDatos.length === 0 && id === undefined) return null
  return { id, evento, datos: lineasDatos.join('\n') }
}

/** Evento ya decodificado: runtime con payload JSON o legacy de solo texto. */
export type EventoDecodificado =
  | { kind: 'runtime'; evento: RuntimeExecutionEvent }
  | { kind: 'legacy'; texto: string }

/**
 * Decodifica el `data` de un frame: JSON con `kind` dentro (§6.3) o texto
 * plano legacy (los eventos históricos sin payload, §6.1).
 */
export function decodificarDatos(frame: FrameSSE): EventoDecodificado {
  try {
    const parsed = JSON.parse(frame.datos) as Record<string, unknown>
    if (typeof parsed.kind === 'string') {
      return { kind: 'runtime', evento: parsed as unknown as RuntimeExecutionEvent }
    }
  } catch {
    // sin JSON: formato legacy de texto plano
  }
  return { kind: 'legacy', texto: frame.datos }
}

/**
 * Suscripción SSE de un job con EventSource nativo (la reconexión y el
 * Last-Event-ID los gestiona el navegador). Devuelve el cierre.
 */
export function suscribirEventosJob(jobId: string, alRecibir: (frame: FrameSSE) => void): () => void {
  const fuente = new EventSource(`/api/jobs/${encodeURIComponent(jobId)}/events`)
  const manejador = (ev: MessageEvent<string>): void => {
    alRecibir({ evento: ev.type, datos: ev.data })
  }
  const escucha = manejador as EventListener
  for (const kind of KINDS_EVENTOS) fuente.addEventListener(kind, escucha)
  return () => {
    for (const kind of KINDS_EVENTOS) fuente.removeEventListener(kind, escucha)
    fuente.close()
  }
}
