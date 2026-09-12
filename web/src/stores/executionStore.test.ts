// Reducer del executionStore (§10): máquina de estados visuales, buffers de
// tokens y log circular, con el nivel escena mutable (sin re-render).

import { beforeEach, describe, expect, it } from 'vitest'
import {
  avanzarPulsos,
  useExecutionStore,
  type NodeVisualState,
} from './executionStore'
import type { EdgeTransition, RuntimeExecutionEvent } from '../types'

function base(): { aristas: EdgeTransition[] } {
  return {
    aristas: [
      { id: 'a->b', from: 'a', to: 'b', condicional: false, labels: [] },
      { id: 'b->c', from: 'b', to: 'c', condicional: true, labels: ['revise'] },
    ],
  }
}

function evento(parcial: Partial<RuntimeExecutionEvent> & { kind: string }): RuntimeExecutionEvent {
  return {
    ts: '2026-09-09T12:00:00+00:00',
    job_id: 'j1',
    ...parcial,
  } as unknown as RuntimeExecutionEvent
}

describe('executionStore', () => {
  beforeEach(() => {
    useExecutionStore.getState().reset()
    useExecutionStore.getState().configurarRed(base().aristas)
  })

  function estadoDe(nodo: string): NodeVisualState | undefined {
    return useExecutionStore.getState().estadoNodos.get(nodo)?.estado
  }

  it('node_start marca processing y node_end marca done', () => {
    const store = useExecutionStore.getState()
    store.aplicarEvento(evento({ kind: 'node_start', node: 'a', rol: 'a', paso: 1 }))
    expect(estadoDe('a')).toBe('processing')
    store.aplicarEvento(evento({ kind: 'node_end', node: 'a', rol: 'a', paso: 1, claves: ['x'] }))
    expect(estadoDe('a')).toBe('done')
  })

  it('token acumula el buffer del nodo sin tocar el log reactivo', () => {
    const store = useExecutionStore.getState()
    const logAntes = store.log.length
    store.aplicarEvento(evento({ kind: 'token', node: 'b', rol: 'b', texto: 'Escena' }))
    store.aplicarEvento(evento({ kind: 'token', node: 'b', rol: 'b', texto: ' 1' }))
    expect(useExecutionStore.getState().tokens.get('b')).toBe('Escena 1')
    expect(estadoDe('b')).toBe('streaming')
    expect(useExecutionStore.getState().log.length).toBe(logAntes)
  })

  it('tool_start/tool_end alternan el estado de tool', () => {
    const store = useExecutionStore.getState()
    store.aplicarEvento(evento({ kind: 'tool_start', node: 'a', rol: 'a', tool: 'buscar_lore', args: {} }))
    expect(estadoDe('a')).toBe('tool')
    store.aplicarEvento(evento({ kind: 'tool_end', node: 'a', rol: 'a', tool: 'buscar_lore', resumen: 'ok' }))
    expect(estadoDe('a')).toBe('streaming')
  })

  it('error marca los nodos en vuelo y expone el mensaje', () => {
    const store = useExecutionStore.getState()
    store.aplicarEvento(evento({ kind: 'node_start', node: 'a', rol: 'a', paso: 1 }))
    store.aplicarEvento(evento({ kind: 'error', mensaje: 'boom' }))
    expect(estadoDe('a')).toBe('error')
    expect(useExecutionStore.getState().error).toBe('boom')
  })

  it('el log es circular: se acota a 500 entradas', () => {
    const store = useExecutionStore.getState()
    for (let i = 0; i < 520; i++) {
      store.aplicarEvento(evento({ kind: 'progress', mensaje: `paso ${i}` }))
    }
    const log = useExecutionStore.getState().log
    expect(log.length).toBe(500)
    expect(log[log.length - 1]!.texto).toBe('paso 519')
  })

  it('node_start dispara pulsos por las aristas A→B (§9.4)', () => {
    const store = useExecutionStore.getState()
    store.aplicarEvento(evento({ kind: 'node_start', node: 'a', rol: 'a', paso: 1 }))
    store.aplicarEvento(evento({ kind: 'node_start', node: 'b', rol: 'b', paso: 2 }))
    const pulsos = useExecutionStore.getState().pulsos
    expect(pulsos).toHaveLength(1)
    expect(pulsos[0]!.edgeId).toBe('a->b')
  })

  it('avanzarPulsos mata los pulsos al llegar al destino y siembra ambientales', () => {
    const store = useExecutionStore.getState()
    store.setStatus('running')
    store.aplicarEvento(evento({ kind: 'node_start', node: 'a', rol: 'a', paso: 1 }))
    store.aplicarEvento(evento({ kind: 'node_start', node: 'b', rol: 'b', paso: 2 }))
    const estado = useExecutionStore.getState()
    avanzarPulsos(estado, 2) // t += 1.1*2 → muere
    expect(estado.pulsos.length).toBeLessThanOrEqual(1)
  })

  it('los eventos legacy (sin payload) van al timeline como solo texto', () => {
    useExecutionStore.getState().aplicarEvento({ kind: 'legacy', texto: 'Paso 1: ...' })
    const log = useExecutionStore.getState().log
    expect(log).toHaveLength(1)
    expect(log[0]!.kind).toBe('legacy')
    expect(log[0]!.texto).toContain('Paso 1')
  })
})
