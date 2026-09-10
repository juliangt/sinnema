// Layout determinista por fases (spec-red-3d §9.1): columnas en X por fase
// en el orden del pipeline, agentes de la misma fase apilados en Z, Y eleva
// los nodos estructurales de cierre. `__start__`/`__end__` son anclas
// discretas a ambos extremos. Función pura de EffectiveNetwork: mismo input →
// mismo dibujo (testeable).

import type { EffectiveNetwork, FaseId } from '../types'

/** Posición 3D de un nodo del grafo. */
export interface Posicion {
  x: number
  y: number
  z: number
}

/** id de nodo → posición (incluye las anclas `__start__`/`__end__`). */
export type Posiciones = Record<string, Posicion>

/** Caja delimitadora de la red: base de los encuadres de cámara (§9.6). */
export interface CajaDeRed {
  min: Posicion
  max: Posicion
  centro: Posicion
  /** Mitad de la diagonal: escala de la red para distancias de encuadre. */
  radio: number
}

export interface LayoutRed {
  posiciones: Posiciones
  caja: CajaDeRed
}

/** Orden de columnas en X por fase (§9.1). */
export const ORDEN_FASES: readonly FaseId[] = [
  'serie',
  'contexto',
  'escritura',
  'transformacion',
  'compuerta',
  'enriquecimiento',
  'cierre',
]

/** Separación entre columnas de fase (X). */
export const SEPARACION_COLUMNAS = 6
/** Apilado de agentes dentro de una fase (Z). */
export const SEPARACION_FILAS = 4
/** Elevación Y de los nodos estructurales de cierre. */
export const ALTURA_CIERRE = 2.5

/** Ancla de inicio: una columna antes de la fase serie. */
export const POSICION_START: Posicion = { x: -SEPARACION_COLUMNAS, y: 0, z: 0 }
/** Ancla de fin: una columna después del cierre (extremo del pipeline). */
export const POSICION_END: Posicion = { x: ORDEN_FASES.length * SEPARACION_COLUMNAS, y: 0, z: 0 }

/**
 * Calcula el layout de la red efectiva. Un hito `hasta` menor simplemente
 * deja columnas vacías: el grafo ya viene truncado del backend.
 */
export function calcularLayout(red: EffectiveNetwork): LayoutRed {
  // Agrupar por fase preservando el orden de red.nodes (orden declarativo
  // del flujo: transformadores/enriquecedores "en orden", §9.1).
  const porFase = new Map<FaseId, string[]>()
  for (const nodo of red.nodes) {
    const ids = porFase.get(nodo.fase) ?? []
    ids.push(nodo.id)
    porFase.set(nodo.fase, ids)
  }

  const posiciones: Posiciones = {
    __start__: { ...POSICION_START },
    __end__: { ...POSICION_END },
  }

  for (const [fase, ids] of porFase) {
    const columna = Math.max(0, ORDEN_FASES.indexOf(fase))
    ids.forEach((id, indice) => {
      posiciones[id] = {
        x: columna * SEPARACION_COLUMNAS,
        y: fase === 'cierre' ? ALTURA_CIERRE : 0,
        z: (indice - (ids.length - 1) / 2) * SEPARACION_FILAS,
      }
    })
  }

  return { posiciones, caja: calcularCaja(posiciones) }
}

function calcularCaja(posiciones: Posiciones): CajaDeRed {
  const valores = Object.values(posiciones)
  const min: Posicion = {
    x: Math.min(...valores.map((p) => p.x)),
    y: Math.min(...valores.map((p) => p.y)),
    z: Math.min(...valores.map((p) => p.z)),
  }
  const max: Posicion = {
    x: Math.max(...valores.map((p) => p.x)),
    y: Math.max(...valores.map((p) => p.y)),
    z: Math.max(...valores.map((p) => p.z)),
  }
  return {
    min,
    max,
    centro: {
      x: (min.x + max.x) / 2,
      y: (min.y + max.y) / 2,
      z: (min.z + max.z) / 2,
    },
    radio: Math.hypot(max.x - min.x, max.y - min.y, max.z - min.z) / 2,
  }
}
