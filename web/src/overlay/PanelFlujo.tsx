// Pestaña Flujo del inspector (spec-red-3d §11.3): editor de [flujo] — fases
// ordenables (contexto, transformaciones, enriquecimiento), revisor y alcance
// (hasta). Reemplaza funcional de construirEditorFlujo de la web legacy con
// validaciones espejo del backend: solo roles conocidos (registro + customs
// del proyecto) y hitos del catálogo.

import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { useProjectStore } from '../stores/projectStore'
import type { FlowSpec } from '../types'

type FaseEditable = 'contexto' | 'transformaciones' | 'enriquecimiento'

const FASES: { clave: FaseEditable; titulo: string }[] = [
  { clave: 'contexto', titulo: 'Contexto' },
  { clave: 'transformaciones', titulo: 'Transformación' },
  { clave: 'enriquecimiento', titulo: 'Enriquecimiento' },
]

export function PanelFlujo() {
  const proyectoActivo = useProjectStore((s) => s.proyectoActivo)
  const detalle = useProjectStore((s) => s.detalle)
  const red = useProjectStore((s) => s.red)
  const catalogos = useProjectStore((s) => s.catalogos)

  const flujo: FlowSpec = detalle?.flujo ?? {}
  const [guardando, setGuardando] = useState(false)
  const [guardado, setGuardado] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Copia editable local: se reinicia al cambiar de proyecto o al
  // re-hidratar el detalle (p. ej. tras guardar el inspector Agente).
  const [copia, setCopia] = useState<FlowSpec>(() => structuredClone(flujo))
  useEffect(() => {
    setCopia(structuredClone(flujo))
    setGuardado(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detalle, red?.project_id])

  const cambiar = (mutar: (f: FlowSpec) => void): void => {
    setGuardado(false)
    const siguiente = structuredClone(copia)
    mutar(siguiente)
    setCopia(siguiente)
  }

  // Roles disponibles: los del registro (aparecen en la red) + customs del TOML.
  const rolesDisponibles = useMemo(() => {
    const deRed = (red?.nodes ?? [])
      .map((n) => n.rol)
      .filter((r): r is string => r !== null)
    const declarados = Object.keys(detalle?.agentes ?? {})
    return [...new Set([...deRed, ...declarados])]
  }, [red, detalle])

  const rolesDeFase = (fase: FaseEditable): string[] => (copia[fase] ?? [])

  const mover = (fase: FaseEditable, i: number, delta: -1 | 1): void => {
    const lista = [...rolesDeFase(fase)]
    const j = i + delta
    if (j < 0 || j >= lista.length) return
    ;[lista[i], lista[j]] = [lista[j]!, lista[i]!]
    cambiar((f) => {
      f[fase] = lista
    })
  }

  const quitar = (fase: FaseEditable, rol: string): void => {
    cambiar((f) => {
      f[fase] = (f[fase] ?? []).filter((r) => r !== rol)
    })
  }

  const agregar = (fase: FaseEditable, rol: string): void => {
    if (rol === '' || rolesDeFase(fase).includes(rol)) return
    cambiar((f) => {
      f[fase] = [...(f[fase] ?? []), rol]
    })
  }

  const guardar = async (): Promise<void> => {
    if (proyectoActivo === null || detalle === null) return
    setGuardando(true)
    setError(null)
    try {
      const datos = structuredClone(detalle)
      const limpio: FlowSpec = {}
      if (copia.contexto?.length) limpio.contexto = copia.contexto
      if (copia.transformaciones?.length) limpio.transformaciones = copia.transformaciones
      if (copia.enriquecimiento?.length) limpio.enriquecimiento = copia.enriquecimiento
      if (copia.revisor) limpio.revisor = copia.revisor
      if (copia.hasta) limpio.hasta = copia.hasta
      if (Object.keys(limpio).length > 0) datos.flujo = limpio
      else delete datos.flujo
      await api.actualizarProyecto(proyectoActivo, datos)
      useProjectStore.getState().recargar()
      setGuardado(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setGuardando(false)
    }
  }

  const listaRoles = rolesDisponibles.filter((r) => r !== 'planner' && r !== 'scriptwriter')

  return (
    <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-2 text-xs">
      {!red?.declarado && (
        <p className="rounded border border-borde/60 bg-panel-alto/60 px-2 py-1 text-[10px] text-texto-suave">
          El proyecto no declara [flujo]: lo que guardes acá lo agrega (y pasa a
          mando explícito).
        </p>
      )}

      {FASES.map(({ clave, titulo }) => (
        <section key={clave}>
          <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-texto-suave">
            {titulo}
          </h4>
          <ul className="space-y-1">
            {rolesDeFase(clave).map((rol, i) => (
              <li key={rol} className="flex items-center gap-1 rounded border border-borde/60 px-2 py-1">
                <span className="flex-1 truncate text-texto">{rol}</span>
                <button type="button" onClick={() => mover(clave, i, -1)} className="px-1 text-texto-suave hover:text-texto">↑</button>
                <button type="button" onClick={() => mover(clave, i, 1)} className="px-1 text-texto-suave hover:text-texto">↓</button>
                <button type="button" onClick={() => quitar(clave, rol)} className="px-1 text-red-300 hover:text-red-200">×</button>
              </li>
            ))}
          </ul>
          <select
            value=""
            onChange={(e) => agregar(clave, e.target.value)}
            className="mt-1 w-full rounded border border-borde bg-panel-alto px-2 py-1 text-[10px] text-texto-suave"
          >
            <option value="">+ agregar rol a {titulo.toLowerCase()}…</option>
            {listaRoles
              .filter((r) => !rolesDeFase(clave).includes(r))
              .map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
          </select>
        </section>
      ))}

      <section>
        <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-texto-suave">
          Revisor (compuerta)
        </h4>
        <select
          value={copia.revisor ?? ''}
          onChange={(e) => cambiar((f) => { f.revisor = e.target.value || undefined })}
          className="w-full rounded border border-borde bg-panel-alto px-2 py-1 text-texto"
        >
          <option value="">— default del registro (chief_critic) —</option>
          {listaRoles.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </section>

      <section>
        <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-texto-suave">
          Alcance (hasta)
        </h4>
        <select
          value={copia.hasta ?? ''}
          onChange={(e) => cambiar((f) => { f.hasta = e.target.value || undefined })}
          className="w-full rounded border border-borde bg-panel-alto px-2 py-1 text-texto"
        >
          <option value="">— default del proyecto —</option>
          {(catalogos?.hitos ?? []).map((h) => (
            <option key={h} value={h}>
              {h}
            </option>
          ))}
        </select>
      </section>

      <button
        type="button"
        onClick={guardar}
        disabled={guardando}
        className="w-full rounded border border-acento/60 bg-acento/20 px-2 py-1.5 font-semibold text-acento transition-colors hover:bg-acento/30 disabled:opacity-40"
      >
        {guardando ? 'Guardando…' : 'Guardar flujo'}
      </button>
      {error !== null && <p className="text-[10px] text-red-300">Error: {error}</p>}
      {guardado && (
        <p className="rounded border border-emerald-800 bg-emerald-900/30 px-2 py-1 text-[10px] text-emerald-300">
          Guardado: aplica a la próxima corrida.
        </p>
      )}
    </div>
  )
}
