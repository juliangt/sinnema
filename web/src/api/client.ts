import type {
  Ancla,
  Artifact,
  Catalogos,
  EffectiveNetwork,
  Job,
  ProjectDetail,
  ProjectSummary,
} from '../types'

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
  // Con FormData el Content-Type lo fija el navegador (boundary del multipart):
  // el default JSON se omite para no romperlo.
  const esFormData = typeof FormData !== 'undefined' && init?.body instanceof FormData
  const respuesta = await fetch(ruta, {
    ...init,
    headers: esFormData
      ? init?.headers
      : { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
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

  /** PUT /api/projects/{id} — persiste el dict TOML completo (§11.1). */
  actualizarProyecto(id: string, datos: ProjectDetail): Promise<{ actualizado: boolean }> {
    return pedir(`/api/projects/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: JSON.stringify(datos),
    })
  },

  /** GET /api/projects/{id}/prompts — preview de prompts compuestos. */
  prompts(id: string): Promise<Record<string, unknown>> {
    return pedir(`/api/projects/${encodeURIComponent(id)}/prompts`)
  },

  /** POST /api/projects — crea un proyecto (dict TOML completo). */
  crearProyecto(datos: ProjectDetail): Promise<{ project_id: string }> {
    return pedir('/api/projects', { method: 'POST', body: JSON.stringify(datos) })
  },

  /** DELETE /api/projects/{id} — borra el TOML (409 si hay jobs activos). */
  borrarProyecto(id: string): Promise<void> {
    return pedir(`/api/projects/${encodeURIComponent(id)}`, { method: 'DELETE' })
  },

  /** GET /api/projects/{id}/lore — memoria de continuidad. */
  lore(id: string): Promise<{ project_id: string; entradas: { term: string; definition: string; chapter_id: string }[] }> {
    return pedir(`/api/projects/${encodeURIComponent(id)}/lore`)
  },

  /** DELETE /api/projects/{id}/lore — reinicia la memoria de continuidad. */
  reiniciarLore(id: string): Promise<void> {
    return pedir(`/api/projects/${encodeURIComponent(id)}/lore`, { method: 'DELETE' })
  },

  // ─────────────── Anclas: biblioteca visual (§9.1) ───────────────

  /** GET /api/projects/{id}/anclas — biblioteca completa del proyecto. */
  anclas(id: string): Promise<Ancla[]> {
    return pedir(`/api/projects/${encodeURIComponent(id)}/anclas`)
  },

  /** POST /api/projects/{id}/anclas — alta en borrador (409 si duplica). */
  crearAncla(
    id: string,
    cuerpo: { ancla_id: string; tipo: string; nombre: string; descripcion_canonica: string },
  ): Promise<Ancla> {
    return pedir(`/api/projects/${encodeURIComponent(id)}/anclas`, {
      method: 'POST',
      body: JSON.stringify(cuerpo),
    })
  },

  /** PUT /api/projects/{id}/anclas/{a} — edita nombre y descripcion_canonica. */
  editarAncla(
    id: string,
    anclaId: string,
    cuerpo: { nombre?: string; descripcion_canonica?: string },
  ): Promise<Ancla> {
    return pedir(
      `/api/projects/${encodeURIComponent(id)}/anclas/${encodeURIComponent(anclaId)}`,
      { method: 'PUT', body: JSON.stringify(cuerpo) },
    )
  },

  /** DELETE /api/projects/{id}/anclas/{a} — retiro: no borra nada, el
   * registro queda en estado 'retirado'. */
  retirarAncla(
    id: string,
    anclaId: string,
  ): Promise<{ project_id: string; ancla_id: string; estado: string; retirado: boolean }> {
    return pedir(
      `/api/projects/${encodeURIComponent(id)}/anclas/${encodeURIComponent(anclaId)}`,
      { method: 'DELETE' },
    )
  },

  /** POST .../anclas/{a}/imagenes — upload multipart a la batería; devuelve
   * el ancla actualizada (con la ImagenAncla nueva). */
  subirImagen(id: string, anclaId: string, rol: string, archivo: File): Promise<Ancla> {
    const datos = new FormData()
    datos.append('rol', rol)
    datos.append('archivo', archivo)
    return pedir(
      `/api/projects/${encodeURIComponent(id)}/anclas/${encodeURIComponent(anclaId)}/imagenes`,
      { method: 'POST', body: datos },
    )
  },

  /** POST .../anclas/{a}/lock — lock humano (400 con los roles faltantes si
   * la batería mínima no alcanza). */
  lockearAncla(id: string, anclaId: string): Promise<Ancla> {
    return pedir(
      `/api/projects/${encodeURIComponent(id)}/anclas/${encodeURIComponent(anclaId)}/lock`,
      { method: 'POST' },
    )
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
