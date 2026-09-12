import { create } from 'zustand'

/**
 * Solicitud de encuadre de cámara disparada desde la selección (§9.6):
 * la selección pide un encuadre que conserva contexto; el doble click,
 * un primer plano.
 */
export interface FocoCamara {
  nodoId: string
  cercano: boolean
}

interface EstadoSeleccion {
  seleccionado: string | null
  hover: string | null
  foco: FocoCamara | null
  reencuadres: number

  /** Click en un nodo: selecciona y pide encuadre con contexto. */
  seleccionar: (nodoId: string | null) => void
  /** Doble click: selecciona y pide primer plano. */
  enfocar: (nodoId: string) => void
  setHover: (nodoId: string | null) => void
  /** Botón "reencuadrar" / Escape: volver a la vista general. */
  solicitarReencuadre: () => void
}

/** Selección/hover de nodos del grafo, sincronizada con el overlay (§9.6). */
export const useSelectionStore = create<EstadoSeleccion>()((set) => ({
  seleccionado: null,
  hover: null,
  foco: null,
  reencuadres: 0,

  seleccionar: (nodoId) =>
    set((estado) => {
      if (nodoId === null) return { seleccionado: null, foco: null }
      // Re-seleccionar el mismo nodo no vuelve a mover la cámara.
      if (estado.seleccionado === nodoId) return estado
      return { seleccionado: nodoId, foco: { nodoId, cercano: false } }
    }),

  enfocar: (nodoId) => set({ seleccionado: nodoId, foco: { nodoId, cercano: true } }),

  setHover: (nodoId) => set({ hover: nodoId }),

  solicitarReencuadre: () => set((estado) => ({ reencuadres: estado.reencuadres + 1, foco: null })),
}))
