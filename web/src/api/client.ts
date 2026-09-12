import type { Artifact, Catalogos, EffectiveNetwork, Job, ProjectDetail, ProjectSummary } from '../types'

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

  // ─────────────────────── Jobs y ejecución (§5) ───────────────────────

  /** POST /api/series — lanza una corrida del proyecto (202 con job_id). */
  lanzarSerie(cuerpo: { project_id: string; topic?: string | null; num_chapters?: number }): Promise<{ job_id: string; status: string }> {
    return pedir('/api/series', { method: 'POST', body: JSON.stringify(cuerpo) })
  },

  /** GET /api/jobs?project_id= — jobs del usuario (X-Owner default: anon). */
  jobs(projectId?: string): Promise<Job[]> {
    const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''
    return pedir(`/api/jobs${query}`)
  },

  /** GET /api/jobs/{id} — estado del job (con spec_desfasado si corre). */
  job(id: string): Promise<Job> {
    return pedir(`/api/jobs/${encodeURIComponent(id)}`)
  },

  /** GET /api/jobs/{id}/events/history — timeline completa (?since=). */
  historiaEventos(id: string, since = 0): Promise<unknown[]> {
    return pedir(`/api/jobs/${encodeURIComponent(id)}/events/history?since=${since}`)
  },

  /** GET /api/jobs/{id}/artifacts — pasos de auditoría del job. */
  artefactos(id: string): Promise<Artifact[]> {
    return pedir(`/api/jobs/${encodeURIComponent(id)}/artifacts`)
  },

  /** GET /api/jobs/{id}/artifacts/{n} — un paso parseado (con prompts). */
  artefacto(id: string, n: number): Promise<Artifact> {
    return pedir(`/api/jobs/${encodeURIComponent(id)}/artifacts/${n}`)
  },
}
