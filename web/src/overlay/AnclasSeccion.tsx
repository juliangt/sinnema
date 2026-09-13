// Sección "Anclas" del drawer de proyectos (spec-recursos-ancla §9.2):
// biblioteca visual del proyecto activo. Grid de tarjetas con batería por rol,
// checklist de lock (batería mínima del catálogo), alta/edición, retiro con
// confirmación y upload de imágenes con drag & drop. El Inspector/3D quedan
// para fases 3–5.

import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { useProjectStore } from '../stores/projectStore'
import type { Ancla, EstadoDeAncla, ImagenAncla, TipoDeAncla } from '../types'

const TIPOS_DEFAULT: TipoDeAncla[] = ['personaje', 'lugar', 'objeto', 'estilo']

const COLOR_DE_ESTADO: Record<EstadoDeAncla, string> = {
  borrador: 'border-borde/60 bg-panel-alto text-texto-suave',
  propuesto: 'border-amber-500/40 bg-amber-500/20 text-amber-300',
  lockeado: 'border-emerald-500/40 bg-emerald-500/20 text-emerald-300',
  retirado: 'border-red-900/60 bg-red-950/40 text-red-300',
}

const EXTENSIONES_ACEPTADAS = '.png,.jpg,.jpeg,.webp'

/** URL de serving de una imagen de batería (content-type fijo por extensión). */
function urlDeImagen(projectId: string, anclaId: string, archivo: string): string {
  return (
    `/api/projects/${encodeURIComponent(projectId)}` +
    `/anclas/${encodeURIComponent(anclaId)}/imagenes/${encodeURIComponent(archivo)}`
  )
}

interface PropsDeTarjeta {
  ancla: Ancla
  projectId: string
  roles: string[]
  minimos: string[]
  onLockear: (anclaId: string) => void
  onRetirar: (anclaId: string) => void
  onEditar: (anclaId: string, cuerpo: { nombre: string; descripcion_canonica: string }) => void
  onSubir: (anclaId: string, rol: string, archivo: File) => void
}

function TarjetaAncla({
  ancla, projectId, roles, minimos, onLockear, onRetirar, onEditar, onSubir,
}: PropsDeTarjeta) {
  const [editando, setEditando] = useState(false)
  const [nombre, setNombre] = useState(ancla.nombre)
  const [descripcion, setDescripcion] = useState(ancla.descripcion_canonica)
  const [rolDeSubida, setRolDeSubida] = useState(roles[0] ?? '')
  const [arrastrando, setArrastrando] = useState(false)

  const presentes = new Set(ancla.bateria.map((i) => i.rol))
  const faltantes = minimos.filter((rol) => !presentes.has(rol))
  const puedeLockear = ancla.estado !== 'lockeado' && ancla.estado !== 'retirado' && faltantes.length === 0

  // Batería agrupada por rol, con exceso plegado ("+n").
  const porRol = new Map<string, ImagenAncla[]>()
  for (const imagen of ancla.bateria) {
    porRol.set(imagen.rol, [...(porRol.get(imagen.rol) ?? []), imagen])
  }

  const soltar = (e: React.DragEvent): void => {
    e.preventDefault()
    setArrastrando(false)
    const archivo = e.dataTransfer.files[0]
    if (archivo && rolDeSubida) onSubir(ancla.ancla_id, rolDeSubida, archivo)
  }

  return (
    <li data-testid={`ancla-${ancla.ancla_id}`} className="space-y-2 rounded border border-borde/60 p-2">
      <div className="flex items-center gap-1">
        <span className="min-w-0 flex-1 truncate text-texto" title={ancla.descripcion_canonica}>
          {ancla.nombre}
        </span>
        <span className="rounded border border-borde/60 bg-panel-alto px-1 text-[9px] text-texto-suave">
          {ancla.tipo}
        </span>
        <span className={`rounded border px-1 text-[9px] ${COLOR_DE_ESTADO[ancla.estado]}`}>
          {ancla.estado}
        </span>
        <span className="text-[9px] text-texto-suave" title="versión de la batería">
          v{ancla.version}
        </span>
      </div>

      {porRol.size > 0 && (
        <div className="space-y-1">
          {[...porRol.entries()].map(([rol, imagenes]) => (
            <div key={rol} className="flex items-center gap-1">
              <span className="w-28 shrink-0 truncate text-[9px] text-texto-suave" title={rol}>
                {rol}
              </span>
              {imagenes.slice(0, 4).map((imagen) => (
                <img
                  key={imagen.archivo}
                  src={urlDeImagen(projectId, ancla.ancla_id, imagen.archivo)}
                  alt={imagen.archivo}
                  className="h-9 w-9 rounded border border-borde/60 object-cover"
                />
              ))}
              {imagenes.length > 4 && (
                <span className="text-[9px] text-texto-suave">+{imagenes.length - 4}</span>
              )}
            </div>
          ))}
        </div>
      )}

      {ancla.estado !== 'lockeado' && ancla.estado !== 'retirado' && minimos.length > 0 && (
        <div className="rounded border border-borde/60 px-2 py-1">
          <span className="text-[9px] uppercase tracking-wider text-texto-suave">
            Batería mínima
          </span>
          <div className="flex flex-wrap gap-x-2">
            {minimos.map((rol) => (
              <span
                key={rol}
                className={`text-[9px] ${presentes.has(rol) ? 'text-emerald-300' : 'text-texto-suave'}`}
              >
                {presentes.has(rol) ? '✓' : '○'} {rol}
              </span>
            ))}
          </div>
        </div>
      )}

      {editando ? (
        <div className="space-y-1">
          <input
            aria-label="nombre a editar"
            value={nombre}
            onChange={(e) => setNombre(e.target.value)}
            className="w-full rounded border border-borde bg-panel-alto px-2 py-1"
          />
          <textarea
            aria-label="descripcion_canonica a editar"
            rows={3}
            value={descripcion}
            onChange={(e) => setDescripcion(e.target.value)}
            className="w-full rounded border border-borde bg-panel-alto px-2 py-1 font-mono text-[10px]"
          />
          <div className="flex gap-1">
            <button
              type="button"
              onClick={() => {
                onEditar(ancla.ancla_id, { nombre: nombre.trim(), descripcion_canonica: descripcion.trim() })
                setEditando(false)
              }}
              className="flex-1 rounded border border-acento/60 bg-acento/20 px-2 py-1 text-acento hover:bg-acento/30"
            >
              Guardar
            </button>
            <button
              type="button"
              onClick={() => setEditando(false)}
              className="flex-1 rounded border border-borde px-2 py-1 text-texto-suave hover:bg-panel-alto"
            >
              Cancelar
            </button>
          </div>
        </div>
      ) : (
        <div className="flex gap-1">
          {ancla.estado !== 'retirado' && (
            <>
              <button
                type="button"
                onClick={() => onLockear(ancla.ancla_id)}
                disabled={!puedeLockear}
                title={faltantes.length > 0 ? `Faltan: ${faltantes.join(', ')}` : 'Lock humano'}
                className="flex-1 rounded border border-acento/60 bg-acento/20 px-2 py-1 font-semibold text-acento hover:bg-acento/30 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Lock
              </button>
              <button
                type="button"
                onClick={() => setEditando(true)}
                className="rounded border border-borde px-2 py-1 text-texto-suave hover:bg-panel-alto"
              >
                Editar
              </button>
              <button
                type="button"
                onClick={() => onRetirar(ancla.ancla_id)}
                className="rounded border border-red-900/60 px-2 py-1 text-red-300 hover:bg-red-950/40"
              >
                Retirar
              </button>
            </>
          )}
          {ancla.estado === 'retirado' && (
            <span className="text-[9px] text-texto-suave">
              retirada: no participa del pipeline (el registro y sus archivos se conservan)
            </span>
          )}
        </div>
      )}

      {ancla.estado !== 'retirado' && (
        <div
          data-testid={`zona-subida-${ancla.ancla_id}`}
          onDragOver={(e) => {
            e.preventDefault()
            setArrastrando(true)
          }}
          onDragLeave={() => setArrastrando(false)}
          onDrop={soltar}
          className={`rounded border border-dashed px-2 py-1 text-center text-[9px] ${
            arrastrando ? 'border-acento bg-acento/10 text-acento' : 'border-borde/60 text-texto-suave'
          }`}
        >
          Soltá una imagen (png/jpg/webp) o
          <label className="ml-1 cursor-pointer text-acento hover:underline">
            elegí un archivo
            <input
              type="file"
              accept={EXTENSIONES_ACEPTADAS}
              className="hidden"
              onChange={(e) => {
                const archivo = e.target.files?.[0]
                if (archivo && rolDeSubida) onSubir(ancla.ancla_id, rolDeSubida, archivo)
                e.target.value = ''
              }}
            />
          </label>
          <select
            aria-label={`rol de subida de ${ancla.ancla_id}`}
            value={rolDeSubida}
            onChange={(e) => setRolDeSubida(e.target.value)}
            className="ml-1 rounded border border-borde bg-panel-alto px-1 py-0.5 text-[9px]"
          >
            {roles.map((rol) => (
              <option key={rol} value={rol}>
                {rol}
              </option>
            ))}
          </select>
        </div>
      )}
    </li>
  )
}

/** Sección "Anclas" del drawer: requiere proyecto activo. */
export function AnclasSeccion() {
  const activo = useProjectStore((s) => s.proyectoActivo)
  const catalogos = useProjectStore((s) => s.catalogos)
  const rolesPorTipo = catalogos?.anclas?.roles_por_tipo
  const bateriaMinima = catalogos?.anclas?.bateria_minima

  const [anclas, setAnclas] = useState<Ancla[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Alta
  const [nuevoId, setNuevoId] = useState('')
  const [nuevoTipo, setNuevoTipo] = useState<TipoDeAncla>('personaje')
  const [nuevoNombre, setNuevoNombre] = useState('')
  const [nuevaDescripcion, setNuevaDescripcion] = useState('')

  const refrescar = useCallback((): void => {
    if (activo === null) return
    api
      .anclas(activo)
      .then(setAnclas)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [activo])

  useEffect(() => {
    setAnclas(null)
    refrescar()
  }, [refrescar])

  if (activo === null) {
    return <p className="text-[10px] text-texto-suave">Elegí un proyecto.</p>
  }

  const crear = async (): Promise<void> => {
    setError(null)
    const id = nuevoId.trim().toLowerCase()
    if (!/^[a-z0-9-]+$/.test(id)) {
      setError('ancla_id: solo minúsculas, números y guiones')
      return
    }
    try {
      await api.crearAncla(activo, {
        ancla_id: id,
        tipo: nuevoTipo,
        nombre: nuevoNombre.trim(),
        descripcion_canonica: nuevaDescripcion.trim(),
      })
      setNuevoId('')
      setNuevoNombre('')
      setNuevaDescripcion('')
      refrescar()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const conRefresco = async (accion: () => Promise<unknown>): Promise<void> => {
    setError(null)
    try {
      await accion()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      refrescar()
    }
  }

  return (
    <>
      {error !== null && <p className="text-[10px] text-red-300">Error: {error}</p>}
      <ul className="space-y-2">
        {(anclas ?? []).map((ancla) => (
          <TarjetaAncla
            key={ancla.ancla_id}
            ancla={ancla}
            projectId={activo}
            roles={rolesPorTipo?.[ancla.tipo] ?? []}
            minimos={bateriaMinima?.[ancla.tipo] ?? []}
            onLockear={(anclaId) => void conRefresco(() => api.lockearAncla(activo, anclaId))}
            onRetirar={(anclaId) => {
              // Retirar es irreversible en la práctica: pedimos confirmación.
              if (!window.confirm(`¿Retirar '${anclaId}'? No borra el registro ni los archivos, pero ya no participa del pipeline.`)) return
              void conRefresco(() => api.retirarAncla(activo, anclaId))
            }}
            onEditar={(anclaId, cuerpo) => void conRefresco(() => api.editarAncla(activo, anclaId, cuerpo))}
            onSubir={(anclaId, rol, archivo) => void conRefresco(() => api.subirImagen(activo, anclaId, rol, archivo))}
          />
        ))}
        {anclas !== null && anclas.length === 0 && (
          <li className="text-[10px] text-texto-suave">— sin anclas —</li>
        )}
      </ul>

      <div className="space-y-1 rounded border border-borde/60 p-2">
        <h4 className="text-[10px] font-semibold uppercase tracking-wider text-texto-suave">
          Nueva ancla
        </h4>
        <div className="flex gap-1">
          <input
            placeholder="id (nita)"
            value={nuevoId}
            onChange={(e) => setNuevoId(e.target.value)}
            className="w-full rounded border border-borde bg-panel-alto px-2 py-1"
          />
          <select
            aria-label="tipo del ancla"
            value={nuevoTipo}
            onChange={(e) => setNuevoTipo(e.target.value as TipoDeAncla)}
            className="rounded border border-borde bg-panel-alto px-1 py-1"
          >
            {(catalogos?.anclas?.tipos ?? TIPOS_DEFAULT).map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <input
          placeholder="nombre visible"
          value={nuevoNombre}
          onChange={(e) => setNuevoNombre(e.target.value)}
          className="w-full rounded border border-borde bg-panel-alto px-2 py-1"
        />
        <textarea
          placeholder="descripcion_canonica EN inglés (≥40 caracteres): es el texto que citarán los modelos de imagen"
          rows={3}
          value={nuevaDescripcion}
          onChange={(e) => setNuevaDescripcion(e.target.value)}
          className="w-full rounded border border-borde bg-panel-alto px-2 py-1 font-mono text-[10px]"
        />
        <button
          type="button"
          onClick={crear}
          className="w-full rounded border border-acento/60 bg-acento/20 px-2 py-1 font-semibold text-acento hover:bg-acento/30"
        >
          Crear ancla
        </button>
      </div>
    </>
  )
}
