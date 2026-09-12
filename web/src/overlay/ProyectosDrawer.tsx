// Drawer de gestión de proyectos (paridad §12.3 con la web legacy): CRUD de
// proyectos (crear/duplicar/borrar), agentes custom (alta/baja), lore
// (ver/reiniciar) y preview de prompts compuestos. Lanzar corridas, jobs y
// timeline viven en el panel de ejecución; el visor enlaza desde ahí.

import { useState } from 'react'
import { api } from '../api/client'
import { useProjectStore } from '../stores/projectStore'
import type { ProjectDetail } from '../types'

function proyectoBase(id: string, marca: string): ProjectDetail {
  // Mínimo válido espejo del backend: [proyecto], [voz] y [visual].
  return {
    editable: true,
    proyecto: {
      id,
      marca,
      concepto: 'micro-videos verticales de 60 segundos',
      tema_por_defecto: 'Un tema interesante contado en 60 segundos',
      idioma: 'Español neutro latinoamericano',
    },
    voz: {
      audiencia: 'Público general curioso',
      contexto_cultural: 'Latinoamérica',
      tono: 'cercano y energético',
      guia_de_estilo: 'Frases cortas, datos verificables, sin tecnicismos.',
      restricciones: 'Sin contenido sensible.',
    },
    visual: {
      estilo_maestro: '3D isometric render, vertical 9:16 framing, clean environment',
    },
  }
}

export function ProyectosDrawer({ abierto, onCerrar }: { abierto: boolean; onCerrar: () => void }) {
  const proyectos = useProjectStore((s) => s.proyectos)
  const activo = useProjectStore((s) => s.proyectoActivo)
  const detalle = useProjectStore((s) => s.detalle)
  const catalogos = useProjectStore((s) => s.catalogos)
  const seleccionarProyecto = useProjectStore((s) => s.seleccionarProyecto)

  const [seccion, setSeccion] = useState<'proyectos' | 'customs' | 'lore'>('proyectos')
  const [nuevoId, setNuevoId] = useState('')
  const [nuevaMarca, setNuevaMarca] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [lore, setLore] = useState<{ term: string; definition: string }[] | null>(null)
  const [promptsPreview, setPromptsPreview] = useState<string | null>(null)

  // Alta de agente custom
  const [rol, setRol] = useState('')
  const [tipo, setTipo] = useState<'contexto' | 'revisor' | 'enriquecedor'>('contexto')
  const [contrato, setContrato] = useState<'notas' | 'texto' | 'dictamen'>('notas')
  const [entradas, setEntradas] = useState<string[]>([])
  const [instrucciones, setInstrucciones] = useState('')

  if (!abierto) return null

  const refrescar = (): void => {
    api.proyectos().then(useProjectStore.getState().setProyectos).catch(() => undefined)
    useProjectStore.getState().recargar()
  }

  const crear = async (): Promise<void> => {
    setError(null)
    const id = nuevoId.trim().toLowerCase()
    if (!/^[a-z0-9_-]+$/.test(id)) {
      setError('id: solo minúsculas, números, guiones y guiones bajos')
      return
    }
    try {
      await api.crearProyecto(proyectoBase(id, nuevaMarca.trim() || id))
      setNuevoId('')
      setNuevaMarca('')
      refrescar()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const duplicar = async (origen: string): Promise<void> => {
    setError(null)
    try {
      const datos = structuredClone(await api.proyecto(origen))
      const id = `${origen}-copia`
      ;(datos.proyecto as Record<string, unknown>)['id'] = id
      ;(datos.proyecto as Record<string, unknown>)['marca'] =
        `${String(datos.proyecto?.marca ?? origen)} (copia)`
      await api.crearProyecto(datos)
      refrescar()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const borrar = async (id: string): Promise<void> => {
    if (!window.confirm(`¿Borrar el proyecto '${id}'? Se elimina su TOML.`)) return
    setError(null)
    try {
      await api.borrarProyecto(id)
      refrescar()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const altaCustom = async (): Promise<void> => {
    if (detalle === null || activo === null) return
    setError(null)
    const nombre = rol.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_')
    if (nombre === '' || instrucciones.trim() === '') {
      setError('rol e instrucciones son obligatorios')
      return
    }
    try {
      const datos = structuredClone(detalle)
      datos.agentes ??= {}
      datos.agentes[nombre] = {
        tipo,
        contrato,
        entradas,
        instrucciones: instrucciones.trim(),
      }
      // Alta en el flujo según su tipo (si hay [flujo] o se crea acá).
      datos.flujo ??= {}
      const fase =
        tipo === 'contexto' ? 'contexto' : tipo === 'revisor' ? undefined : 'enriquecimiento'
      if (fase !== undefined) {
        const lista = datos.flujo[fase] ?? []
        if (!lista.includes(nombre)) datos.flujo[fase] = [...lista, nombre]
      } else if (datos.flujo.revisor === undefined) {
        datos.flujo.revisor = nombre
      }
      await api.actualizarProyecto(activo, datos)
      useProjectStore.getState().recargar()
      setRol('')
      setInstrucciones('')
      setEntradas([])
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const bajaCustom = async (nombre: string): Promise<void> => {
    if (detalle === null || activo === null) return
    if (!window.confirm(`¿Eliminar el agente custom '${nombre}' del proyecto?`)) return
    const datos = structuredClone(detalle)
    delete datos.agentes?.[nombre]
    try {
      await api.actualizarProyecto(activo, datos)
      useProjectStore.getState().recargar()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const verLore = async (): Promise<void> => {
    if (activo === null) return
    try {
      const respuesta = await api.lore(activo)
      setLore(respuesta.entradas ?? [])
    } catch {
      setLore([])
    }
  }

  const reiniciarLore = async (): Promise<void> => {
    if (activo === null || !window.confirm('¿Reiniciar la memoria de continuidad?')) return
    await api.reiniciarLore(activo)
    setLore([])
  }

  const verPrompts = async (): Promise<void> => {
    if (activo === null) return
    const p = await api.prompts(activo)
    setPromptsPreview(
      Object.entries(p)
        .map(([clave, contenido]) => `── ${clave} ──\n${String(contenido)}`)
        .join('\n\n'),
    )
  }

  const customs = Object.entries(detalle?.agentes ?? {}).filter(
    ([, config]) => config !== null && typeof config === 'object' && 'tipo' in config,
  )

  return (
    <div className="absolute left-3 top-16 z-20 flex max-h-[calc(100%-5rem)] w-96 flex-col rounded-lg border border-borde/70 bg-panel/95 text-xs backdrop-blur">
      <header className="flex items-center gap-2 border-b border-borde/70 px-3 py-2">
        <h2 className="font-semibold tracking-wide text-texto">Proyectos</h2>
        <div className="flex gap-1">
          {(['proyectos', 'customs', 'lore'] as const).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setSeccion(s)}
              className={`rounded px-2 py-0.5 text-[10px] capitalize transition-colors ${
                seccion === s ? 'bg-acento/20 text-acento' : 'text-texto-suave hover:bg-panel-alto'
              }`}
            >
              {s}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={onCerrar}
          className="ml-auto rounded border border-borde px-2 py-0.5 text-[10px] text-texto-suave hover:bg-panel-alto"
        >
          cerrar
        </button>
      </header>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-2">
        {error !== null && <p className="text-[10px] text-red-300">Error: {error}</p>}

        {seccion === 'proyectos' && (
          <>
            <ul className="space-y-1">
              {proyectos.map((p) => (
                <li
                  key={p.project_id}
                  className={`flex items-center gap-2 rounded border px-2 py-1 ${
                    p.project_id === activo ? 'border-acento/60' : 'border-borde/60'
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => seleccionarProyecto(p.project_id)}
                    className="min-w-0 flex-1 truncate text-left"
                    title={p.concepto}
                  >
                    <span className="text-texto">{p.project_id}</span>
                    {!p.editable && (
                      <span className="ml-1 text-[9px] text-texto-suave">(solo lectura)</span>
                    )}
                  </button>
                  <button type="button" onClick={() => void duplicar(p.project_id)} className="px-1 text-texto-suave hover:text-texto" title="Duplicar">⧉</button>
                  {p.editable && (
                    <button type="button" onClick={() => void borrar(p.project_id)} className="px-1 text-red-300 hover:text-red-200" title="Borrar">×</button>
                  )}
                </li>
              ))}
            </ul>
            <div className="space-y-1 rounded border border-borde/60 p-2">
              <h4 className="text-[10px] font-semibold uppercase tracking-wider text-texto-suave">
                Nuevo proyecto
              </h4>
              <input
                placeholder="id (mi-show)"
                value={nuevoId}
                onChange={(e) => setNuevoId(e.target.value)}
                className="w-full rounded border border-borde bg-panel-alto px-2 py-1"
              />
              <input
                placeholder="marca"
                value={nuevaMarca}
                onChange={(e) => setNuevaMarca(e.target.value)}
                className="w-full rounded border border-borde bg-panel-alto px-2 py-1"
              />
              <button
                type="button"
                onClick={crear}
                className="w-full rounded border border-acento/60 bg-acento/20 px-2 py-1 font-semibold text-acento hover:bg-acento/30"
              >
                Crear
              </button>
            </div>
          </>
        )}

        {seccion === 'customs' && (
          <>
            {activo === null && <p className="text-[10px] text-texto-suave">Elegí un proyecto.</p>}
            {activo !== null && (
              <>
                <ul className="space-y-1">
                  {customs.map(([nombre]) => (
                    <li key={nombre} className="flex items-center rounded border border-borde/60 px-2 py-1">
                      <span className="flex-1 truncate text-texto">{nombre}</span>
                      <button type="button" onClick={() => void bajaCustom(nombre)} className="px-1 text-red-300 hover:text-red-200">×</button>
                    </li>
                  ))}
                  {customs.length === 0 && (
                    <li className="text-[10px] text-texto-suave">— sin agentes custom —</li>
                  )}
                </ul>
                <div className="space-y-1 rounded border border-borde/60 p-2">
                  <h4 className="text-[10px] font-semibold uppercase tracking-wider text-texto-suave">
                    Nuevo agente custom
                  </h4>
                  <input
                    placeholder="rol (verificador)"
                    value={rol}
                    onChange={(e) => setRol(e.target.value)}
                    className="w-full rounded border border-borde bg-panel-alto px-2 py-1"
                  />
                  <div className="flex gap-1">
                    <select value={tipo} onChange={(e) => setTipo(e.target.value as typeof tipo)} className="flex-1 rounded border border-borde bg-panel-alto px-1 py-1">
                      {(catalogos?.tipos_custom ?? []).map((t) => <option key={t} value={t}>{t}</option>)}
                    </select>
                    <select value={contrato} onChange={(e) => setContrato(e.target.value as typeof contrato)} className="flex-1 rounded border border-borde bg-panel-alto px-1 py-1">
                      {(catalogos?.contratos ?? []).map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {(catalogos?.entradas_custom ?? []).map((e) => (
                      <label key={e} className="flex items-center gap-1 text-[10px] text-texto-suave">
                        <input
                          type="checkbox"
                          checked={entradas.includes(e)}
                          onChange={(ev) =>
                            setEntradas((previas) =>
                              ev.target.checked ? [...previas, e] : previas.filter((x) => x !== e),
                            )
                          }
                        />
                        {e}
                      </label>
                    ))}
                  </div>
                  <textarea
                    placeholder="instrucciones…"
                    rows={3}
                    value={instrucciones}
                    onChange={(e) => setInstrucciones(e.target.value)}
                    className="w-full rounded border border-borde bg-panel-alto px-2 py-1 font-mono text-[10px]"
                  />
                  <button
                    type="button"
                    onClick={altaCustom}
                    className="w-full rounded border border-acento/60 bg-acento/20 px-2 py-1 font-semibold text-acento hover:bg-acento/30"
                  >
                    Agregar custom
                  </button>
                </div>
              </>
            )}
          </>
        )}

        {seccion === 'lore' && (
          <>
            {activo === null && <p className="text-[10px] text-texto-suave">Elegí un proyecto.</p>}
            {activo !== null && (
              <>
                <div className="flex gap-1">
                  <button type="button" onClick={verLore} className="flex-1 rounded border border-borde px-2 py-1 text-texto-suave hover:bg-panel-alto">
                    Ver lore
                  </button>
                  <button type="button" onClick={reiniciarLore} className="flex-1 rounded border border-red-900/60 px-2 py-1 text-red-300 hover:bg-red-950/40">
                    Reiniciar
                  </button>
                  <button type="button" onClick={verPrompts} className="flex-1 rounded border border-borde px-2 py-1 text-texto-suave hover:bg-panel-alto">
                    Ver prompts
                  </button>
                </div>
                {lore !== null && (
                  <ul className="space-y-1">
                    {lore.map((e) => (
                      <li key={e.term} className="rounded border border-borde/60 px-2 py-1">
                        <span className="text-texto">{e.term}</span>
                        <span className="text-texto-suave"> — {e.definition}</span>
                      </li>
                    ))}
                    {lore.length === 0 && (
                      <li className="text-[10px] text-texto-suave">— sin entradas —</li>
                    )}
                  </ul>
                )}
                {promptsPreview !== null && (
                  <details open>
                    <summary className="cursor-pointer text-[10px] text-acento">Prompts compuestos</summary>
                    <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap rounded border border-borde/60 bg-panel-alto/60 p-2 text-[9px] text-texto-suave">
                      {promptsPreview}
                    </pre>
                  </details>
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}
