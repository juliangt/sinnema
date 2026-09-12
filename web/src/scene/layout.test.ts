// Layout determinista (spec-red-3d §9.1): mismo EffectiveNetwork → mismas
// posiciones. Snapshot por proyecto de referencia.

import { describe, expect, it } from 'vitest'
import { calcularLayout, ORDEN_FASES } from './layout'
import type { EffectiveNetwork } from '../types'

function redDeEjemplo(): EffectiveNetwork {
  return {
    project_id: 'comida',
    declarado: false,
    hasta: 'produccion',
    limite_recursion: 64,
    nodes: [
      { id: 'plan_series', rol: 'planner', tipo: 'serie', fase: 'serie', estructural: true, descripcion: '', esencial: true, llm: null },
      { id: 'continuity_master', rol: 'continuity', tipo: 'contexto', fase: 'contexto', estructural: false, descripcion: '', esencial: false, llm: null },
      { id: 'scriptwriter', rol: 'scriptwriter', tipo: 'escritor', fase: 'escritura', estructural: false, descripcion: '', esencial: true, llm: null },
      { id: 'chief_critic', rol: 'critic', tipo: 'revisor', fase: 'compuerta', estructural: true, descripcion: '', esencial: false, llm: null },
      { id: 'commit_episode', rol: null, tipo: 'cierre', fase: 'cierre', estructural: true, descripcion: '', esencial: false, llm: null },
      { id: 'fail_chapter', rol: null, tipo: 'cierre', fase: 'cierre', estructural: true, descripcion: '', esencial: false, llm: null },
    ],
    edges: [],
  }
}

describe('calcularLayout', () => {
  it('es determinista: mismo input → mismo output', () => {
    const a = calcularLayout(redDeEjemplo())
    const b = calcularLayout(redDeEjemplo())
    expect(b).toEqual(a)
  })

  it('asigna columnas X crecientes en el orden de fases §9.1', () => {
    const { posiciones } = calcularLayout(redDeEjemplo())
    const xDe = (id: string) => posiciones[id]!.x
    expect(xDe('plan_series')).toBeLessThan(xDe('continuity_master'))
    expect(xDe('continuity_master')).toBeLessThan(xDe('scriptwriter'))
    expect(xDe('scriptwriter')).toBeLessThan(xDe('chief_critic'))
    expect(xDe('chief_critic')).toBeLessThan(xDe('commit_episode'))
  })

  it('eleva los nodos de cierre en Y y apila la fase en Z', () => {
    const { posiciones } = calcularLayout(redDeEjemplo())
    // commit_episode y fail_chapter comparten fase 'cierre': misma X/Y, Z opuestos.
    expect(posiciones['commit_episode']!.y).toBeGreaterThan(0)
    expect(posiciones['fail_chapter']!.y).toBe(posiciones['commit_episode']!.y)
    expect(posiciones['commit_episode']!.z).not.toBe(posiciones['fail_chapter']!.z)
  })

  it('incluye las anclas __start__ y __end__ en los extremos', () => {
    const { posiciones } = calcularLayout(redDeEjemplo())
    expect(posiciones['__start__']!.x).toBeLessThan(posiciones['plan_series']!.x)
    expect(posiciones['__end__']!.x).toBeGreaterThan(
      ORDEN_FASES.length === 0 ? 0 : posiciones['commit_episode']!.x,
    )
  })
})
