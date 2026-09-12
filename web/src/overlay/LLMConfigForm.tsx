// Formulario LLMConfig del inspector (spec-red-3d §11.1): proveedor/modelo,
// sliders temperatura/top_p, max_tokens, checkboxes de tools, reglas e
// instrucciones de customs con preview de placeholders. Los rangos y las
// validaciones son espejo del backend (§3): el formulario nunca deja armar
// un payload que el backend rechazaría.

import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { useProjectStore } from '../stores/projectStore'
import type { AgentNode } from '../types'

interface Props {
  nodo: AgentNode
  onGuardado: () => void
}

const TEMPERATURA_MIN = 0
const TEMPERATURA_MAX = 2
const PASO_TEMPERATURA = 0.05
const TOP_P_MIN = 0
const TOP_P_MAX = 1
const PASO_TOP_P = 0.01

export function LLMConfigForm({ nodo, onGuardado }: Props) {
  const proyectoActivo = useProjectStore((s) => s.proyectoActivo)
  const detalle = useProjectStore((s) => s.detalle)
  const catalogos = useProjectStore((s) => s.catalogos)

  const llm = nodo.llm
  const [proveedor, setProveedor] = useState(llm?.proveedor ?? 'openai')
  const [modelo, setModelo] = useState(llm?.modelo ?? '')
  const [temperatura, setTemperatura] = useState(llm?.temperatura ?? 0.7)
  const [topPActivado, setTopPActivado] = useState(llm?.top_p !== undefined)
  const [topP, setTopP] = useState(llm?.top_p ?? 1)
  const [maxTokensActivado, setMaxTokensActivado] = useState(
    llm?.max_tokens !== undefined,
  )
  const [maxTokens, setMaxTokens] = useState(llm?.max_tokens ?? 4096)
  const [tools, setTools] = useState<string[]>(llm?.tools ?? [])
  const [reglas, setReglas] = useState('')

  // Estado del guardado (§11.4): el aviso es persistente hasta el próximo cambio.
  const [guardando, setGuardando] = useState(false)
  const [guardado, setGuardado] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<string | null>(null)

  // (Re)inicialización al cambiar el nodo inspeccionado.
  useEffect(() => {
    setProveedor(llm?.proveedor ?? 'openai')
    setModelo(llm?.modelo ?? '')
    setTemperatura(llm?.temperatura ?? 0.7)
    setTopPActivado(llm?.top_p !== undefined)
    setTopP(llm?.top_p ?? 1)
    setMaxTokensActivado(llm?.max_tokens !== undefined)
    setMaxTokens(llm?.max_tokens ?? 4096)
    setTools(llm?.tools ?? [])
    setGuardado(false)
    setError(null)
  }, [llm, nodo.id])

  // Reglas del TOML en crudo (una por línea en el editor).
  useEffect(() => {
    const config = detalle?.agentes?.[nodo.rol ?? nodo.id]
    const crudas = (config?.reglas as string[] | undefined) ?? []
    setReglas(crudas.join('\n'))
  }, [detalle, nodo.rol, nodo.id])

  const esCustom = nodo.custom !== undefined
  useEffect(() => {
    if (!esCustom) {
      setPreview(null)
      return
    }
    api
      .prompts(proyectoActivo ?? '')
      .then((p) => {
        const clave = Object.keys(p).find((k) => k.includes(nodo.rol ?? nodo.id))
        setPreview(clave !== undefined ? String(p[clave]) : null)
      })
      .catch(() => setPreview(null))
  }, [esCustom, proyectoActivo, nodo.rol, nodo.id])

  // Validaciones espejo del backend (§3).
  const errores = useMemo(() => {
    const lista: string[] = []
    if (modelo.trim() === '') lista.push('modelo: no puede estar vacío')
    if (temperatura < TEMPERATURA_MIN || temperatura > TEMPERATURA_MAX) {
      lista.push(`temperatura: fuera de [${TEMPERATURA_MIN}, ${TEMPERATURA_MAX}]`)
    }
    if (topPActivado && (topP < TOP_P_MIN || topP > TOP_P_MAX)) {
      lista.push(`top_p: fuera de [${TOP_P_MIN}, ${TOP_P_MAX}]`)
    }
    if (maxTokensActivado && (!Number.isInteger(maxTokens) || maxTokens <= 0)) {
      lista.push('max_tokens: debe ser un entero > 0')
    }
    const disponibles = new Set(catalogos?.tools.map((t) => t.nombre) ?? [])
    const desconocidas = tools.filter((t) => !disponibles.has(t))
    if (desconocidas.length > 0) {
      lista.push(`tools fuera del registro: ${desconocidas.join(', ')}`)
    }
    return lista
  }, [modelo, temperatura, topPActivado, topP, maxTokensActivado, maxTokens, tools, catalogos])

  const guardar = async (): Promise<void> => {
    if (proyectoActivo === null || detalle === null || errores.length > 0) return
    setGuardando(true)
    setError(null)
    try {
      const datos = structuredClone(detalle)
      const rol = nodo.rol ?? nodo.id
      const agentes = (datos.agentes ??= {})
      const config = (agentes[rol] ??= {})
      config.proveedor = proveedor
      config.modelo = modelo.trim()
      config.temperatura = temperatura
      // Ausente = default del proveedor: la clave no se escribe (§3).
      if (topPActivado) config.top_p = topP
      else delete config.top_p
      if (maxTokensActivado) config.max_tokens = maxTokens
      else delete config.max_tokens
      config.tools = tools
      const reglasLimpias = reglas
        .split('\n')
        .map((r) => r.trim())
        .filter((r) => r !== '')
      if (reglasLimpias.length > 0) config.reglas = reglasLimpias
      else delete config.reglas

      await api.actualizarProyecto(proyectoActivo, datos)
      setGuardado(true)
      onGuardado() // re-hidrata /red: halos y etiquetas reflejan el cambio
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setGuardando(false)
    }
  }

  const modelosSugeridos = catalogos?.modelos[proveedor] ?? []

  return (
    <div className="space-y-3 text-xs">
      <div>
        <label className="mb-1 block text-[10px] uppercase tracking-wider text-texto-suave">
          Proveedor
        </label>
        <select
          value={proveedor}
          onChange={(e) => {
            setProveedor(e.target.value as typeof proveedor)
            setGuardado(false)
          }}
          className="w-full rounded border border-borde bg-panel-alto px-2 py-1 text-texto"
        >
          {(catalogos?.proveedores ?? []).map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="mb-1 block text-[10px] uppercase tracking-wider text-texto-suave">
          Modelo
        </label>
        <input
          list={`modelos-${proveedor}`}
          value={modelo}
          onChange={(e) => {
            setModelo(e.target.value)
            setGuardado(false)
          }}
          className="w-full rounded border border-borde bg-panel-alto px-2 py-1 text-texto"
        />
        <datalist id={`modelos-${proveedor}`}>
          {modelosSugeridos.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
      </div>

      <div>
        <label className="mb-1 flex justify-between text-[10px] uppercase tracking-wider text-texto-suave">
          <span>Temperatura</span>
          <span className="text-texto">{temperatura.toFixed(2)}</span>
        </label>
        <input
          type="range"
          min={TEMPERATURA_MIN}
          max={TEMPERATURA_MAX}
          step={PASO_TEMPERATURA}
          value={temperatura}
          onChange={(e) => {
            setTemperatura(Number(e.target.value))
            setGuardado(false)
          }}
          className="w-full"
        />
      </div>

      <div>
        <label className="mb-1 flex items-center gap-2 text-[10px] uppercase tracking-wider text-texto-suave">
          <input
            type="checkbox"
            checked={topPActivado}
            onChange={(e) => {
              setTopPActivado(e.target.checked)
              setGuardado(false)
            }}
          />
          top_p {topPActivado && <span className="normal-case text-texto">{topP.toFixed(2)}</span>}
        </label>
        {topPActivado && (
          <input
            type="range"
            min={TOP_P_MIN}
            max={TOP_P_MAX}
            step={PASO_TOP_P}
            value={topP}
            onChange={(e) => {
              setTopP(Number(e.target.value))
              setGuardado(false)
            }}
            className="w-full"
          />
        )}
      </div>

      <div>
        <label className="mb-1 flex items-center gap-2 text-[10px] uppercase tracking-wider text-texto-suave">
          <input
            type="checkbox"
            checked={maxTokensActivado}
            onChange={(e) => {
              setMaxTokensActivado(e.target.checked)
              setGuardado(false)
            }}
          />
          max_tokens
        </label>
        {maxTokensActivado && (
          <input
            type="number"
            min={1}
            step={1}
            value={maxTokens}
            onChange={(e) => {
              setMaxTokens(Number(e.target.value))
              setGuardado(false)
            }}
            className="w-full rounded border border-borde bg-panel-alto px-2 py-1 text-texto"
          />
        )}
      </div>

      <div>
        <label className="mb-1 block text-[10px] uppercase tracking-wider text-texto-suave">
          Tools integradas
        </label>
        <div className="space-y-1">
          {(catalogos?.tools ?? []).map((t) => (
            <label key={t.nombre} className="flex items-start gap-2 text-[11px] text-texto-suave">
              <input
                type="checkbox"
                checked={tools.includes(t.nombre)}
                onChange={(e) => {
                  setTools((previas) =>
                    e.target.checked
                      ? [...previas, t.nombre]
                      : previas.filter((x) => x !== t.nombre),
                  )
                  setGuardado(false)
                }}
                className="mt-0.5"
              />
              <span>
                <span className="text-texto">{t.nombre}</span> — {t.descripcion}
              </span>
            </label>
          ))}
        </div>
      </div>

      <div>
        <label className="mb-1 block text-[10px] uppercase tracking-wider text-texto-suave">
          Reglas (una por línea)
        </label>
        <textarea
          rows={3}
          value={reglas}
          onChange={(e) => {
            setReglas(e.target.value)
            setGuardado(false)
          }}
          className="w-full rounded border border-borde bg-panel-alto px-2 py-1 font-mono text-[11px] text-texto"
        />
      </div>

      {esCustom && nodo.custom && (
        <div className="rounded border border-borde/60 bg-panel-alto/60 p-2">
          <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-texto-suave">
            Instrucciones del custom
          </h4>
          <p className="whitespace-pre-wrap text-[10px] leading-relaxed text-texto-suave">
            {nodo.custom.instrucciones}
          </p>
          {preview !== null && (
            <details className="mt-1">
              <summary className="cursor-pointer text-[10px] text-acento">
                Preview del prompt compuesto
              </summary>
              <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-[9px] text-texto-suave">
                {preview}
              </pre>
            </details>
          )}
        </div>
      )}

      {errores.length > 0 && (
        <ul className="space-y-0.5 text-[10px] text-amber-300">
          {errores.map((e) => (
            <li key={e}>· {e}</li>
          ))}
        </ul>
      )}

      <button
        type="button"
        onClick={guardar}
        disabled={guardando || errores.length > 0}
        className="w-full rounded border border-acento/60 bg-acento/20 px-2 py-1.5 font-semibold text-acento transition-colors hover:bg-acento/30 disabled:opacity-40"
      >
        {guardando ? 'Guardando…' : 'Guardar agente'}
      </button>

      {error !== null && <p className="text-[10px] text-red-300">Error: {error}</p>}
      {guardado && (
        <p className="rounded border border-emerald-800 bg-emerald-900/30 px-2 py-1 text-[10px] text-emerald-300">
          Guardado: aplica a la próxima corrida (el job en curso sigue con su spec
          congelado).
        </p>
      )}
    </div>
  )
}
