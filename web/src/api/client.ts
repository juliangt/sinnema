import type { Catalogos, EffectiveNetwork, ProjectDetail, ProjectSummary } from '../types'

/** Error de API con el status HTTP (distingue 404/400 de fallos de red). */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, mensaje: string) {
    super(mensaje)
    this.name = 'ApiError'
    this.status = status
  }
}

async function pedir<T>(ruta: string, init?: RequestInit): Promise<T> {
  const respuesta = await fetch(ruta, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!respuesta.ok) {
    let detalle = `${respuesta.status} ${respuesta.statusText}`
    try {
      const cuerpo = (await respuesta.json()) as { detail?: unknown }
      if (cuerpo?.detail !== undefined) detalle = String(cuerpo.detail)
    } catch {
      // respuesta sin cuerpo JSON: nos quedamos con el status
    }
    throw new ApiError(respuesta.status, detalle)
  }
  return (await respuesta.json()) as T
}

/** Cliente REST del servicio Sinnema (fetch, sin axios; §8.1). */
export const api = {
  /** GET /api/projects */
  proyectos(): Promise<ProjectSummary[]> {
    return pedir<ProjectSummary[]>('/api/projects')
  },

  /** GET /api/projects/{id} — dict TOML en crudo (claves en español). */
  proyecto(id: string): Promise<ProjectDetail> {
    return pedir<ProjectDetail>(`/api/projects/${encodeURIComponent(id)}`)
  },

  /** GET /api/projects/{id}/red — hidratación de la escena 3D (§5.1). */
  red(id: string): Promise<EffectiveNetwork> {
    return pedir<EffectiveNetwork>(`/api/projects/${encodeURIComponent(id)}/red`)
  },

  /** GET /api/meta/catalogos — catálogos para los formularios. */
  catalogos(): Promise<Catalogos> {
    return pedir<Catalogos>('/api/meta/catalogos')
  },
}
