import { create } from 'zustand'
import type { Catalogos, EffectiveNetwork, ProjectDetail, ProjectSummary } from '../types'

interface EstadoProyecto {
  proyectos: ProjectSummary[]
  proyectoActivo: string | null
  red: EffectiveNetwork | null
  detalle: ProjectDetail | null
  catalogos: Catalogos | null
  /** Incrementa al guardar: useProjectNetwork re-hidrata (§11.1). */
  version: number

  setProyectos: (proyectos: ProjectSummary[]) => void
  /** Cambia de proyecto: la red/detalle se re-hidratan (remount de la escena). */
  seleccionarProyecto: (id: string) => void
  hidratar: (red: EffectiveNetwork, detalle: ProjectDetail) => void
  setCatalogos: (catalogos: Catalogos) => void
  recargar: () => void
}

/** Estado de dominio de proyectos (spec-red-3d §8.1). */
export const useProjectStore = create<EstadoProyecto>()((set) => ({
  proyectos: [],
  proyectoActivo: null,
  red: null,
  detalle: null,
  catalogos: null,
  version: 0,

  setProyectos: (proyectos) => set({ proyectos }),

  seleccionarProyecto: (id) =>
    set((estado) =>
      estado.proyectoActivo === id ? estado : { proyectoActivo: id, red: null, detalle: null },
    ),

  hidratar: (red, detalle) => set({ red, detalle }),

  setCatalogos: (catalogos) => set({ catalogos }),

  recargar: () => set((estado) => ({ version: estado.version + 1 })),
}))
