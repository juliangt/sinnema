// Parsers SSE (spec-red-3d §6.3 / §13): parser incremental tolerante a
// chunks cortados y decodificador del data (JSON con kind / legacy texto).

import { describe, expect, it } from 'vitest'
import { crearParserSSE, decodificarDatos } from './sse'

describe('crearParserSSE', () => {
  it('parsea frames completos con id, event y data', () => {
    const parsear = crearParserSSE()
    const frames = parsear(
      'id: 42\nevent: node_start\ndata: {"kind":"node_start","node":"plan_series"}\n\n',
    )
    expect(frames).toHaveLength(1)
    expect(frames[0]).toEqual({
      id: 42,
      evento: 'node_start',
      datos: '{"kind":"node_start","node":"plan_series"}',
    })
  })

  it('reensambla frames que llegan cortados entre chunks', () => {
    const parsear = crearParserSSE()
    expect(parsear('id: 1\nev')).toEqual([])
    expect(parsear('ent: token\nda')).toEqual([])
    const frames = parsear('ta: {"kind":"token"}\n\n')
    expect(frames).toEqual([{ id: 1, evento: 'token', datos: '{"kind":"token"}' }])
  })

  it('tolera CRLF y múltiples frames por chunk', () => {
    const parsear = crearParserSSE()
    const frames = parsear(
      'event: progress\r\ndata: paso 1\r\n\r\nevent: done\r\ndata: fin\r\n\r\n',
    )
    expect(frames.map((f) => f.evento)).toEqual(['progress', 'done'])
  })
})

describe('decodificarDatos', () => {
  it('reconoce el JSON runtime con kind dentro (§6.3)', () => {
    const resultado = decodificarDatos({
      evento: 'token',
      datos: '{"kind":"token","node":"a","texto":"hola"}',
    })
    expect(resultado).toEqual({
      kind: 'runtime',
      evento: { kind: 'token', node: 'a', texto: 'hola' },
    })
  })

  it('clasifica como legacy el texto plano sin JSON (§6.1)', () => {
    expect(decodificarDatos({ evento: 'progress', datos: 'Paso 1: planificando...' })).toEqual({
      kind: 'legacy',
      texto: 'Paso 1: planificando...',
    })
  })

  it('un JSON sin kind también es legacy (tolerante)', () => {
    expect(decodificarDatos({ evento: 'progress', datos: '{"otro": 1}' })).toEqual({
      kind: 'legacy',
      texto: '{"otro": 1}',
    })
  })
})
