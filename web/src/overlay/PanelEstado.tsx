// Pestaña Estado del inspector (spec-red-3d §11.2): inspección en vivo del
// job activo — timeline de artefactos con JSON colapsable, prompts por paso,
// scratchpad de tools, stream de tokens del nodo seleccionado y las claves
// que cada node_end actualizó como vista diff del estado.

import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useExecutionStore } from '../stores/executionStore'
import type { Artifact } from '../types'

interface Props {
  nodoId: string | null
}

/** Lee el buffer mutable de tokens a frecuencia de UI (§10: el inspector sí
 * suscribe normal — un tick de 300 ms, no por token). */
function useBufferTokens(nodoId: string | null): string {
  const [buffer, setBuffer] = useState('')
  useEffect(() => {
    if (nodoId === null) return
    const tick = window.setInterval(() => {
      setBuffer(useExecutionStore.getState().tokens.get(nodoId) ?? '')
    }, 300)
    return () => window.clearInterval(tick)
  }, [nodoId])
  return buffer
}

export function PanelEstado({ nodoId }: Props) {
  const jobId = useExecutionStore((s) => s.jobId)
  const artefactos = useExecutionStore((s) => s.artefactos)
  const log = useExecutionStore((s) => s.log)
  const [detalle, setDetalle] = useState<Artifact | null>(null)
  const tokens = useBufferTokens(nodoId)

  const pasosTool = log.filter(
    (e) => e.kind === 'tool_start' || e.kind === 'tool_end',
  )
  const clavesPorPaso = log.filter((e) => e.kind === 'node_end')

  const abrir = async (n: number): Promise<void> => {
    if (jobId === null) return
    try {
      setDetalle(await api.artefacto(jobId, n))
    } catch {
      setDetalle(null)
    }
  }

  return (
    <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-2 text-xs">
      <section>
        <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-texto-suave">
          Tokens en vivo {nodoId !== null && <span className="text-texto">· {nodoId}</span>}
        </h4>
        <pre className="max-h-28 overflow-y-auto whitespace-pre-wrap rounded border border-borde/60 bg-panel-alto/60 p-2 text-[10px] text-texto">
          {tokens !== '' ? tokens : '— sin tokens del nodo seleccionado —'}
        </pre>
      </section>

      <section>
        <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-texto-suave">
          Claves actualizadas por paso
        </h4>
        {clavesPorPaso.length === 0 ? (
          <p className="text-[10px] text-texto-suave">— sin nodos completados —</p>
        ) : (
          <ul className="space-y-0.5 font-mono text-[10px] text-texto-suave">
            {clavesPorPaso.slice(-8).map((e) => (
              <li key={e.id}>
                <span className="text-texto">{e.node}</span>: {e.texto.split('claves: ')[1] ?? ''}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-texto-suave">
          Scratchpad de tools
        </h4>
        {pasosTool.length === 0 ? (
          <p className="text-[10px] text-texto-suave">— sin llamadas a tools —</p>
        ) : (
          <ul className="space-y-0.5 font-mono text-[10px]">
            {pasosTool.slice(-8).map((e) => (
              <li key={e.id} className={e.kind === 'tool_start' ? 'text-amber-300' : 'text-texto-suave'}>
                {e.texto}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-texto-suave">
          Artefactos del job
        </h4>
        {artefactos === null || artefactos.length === 0 ? (
          <p className="text-[10px] text-texto-suave">
            — se consolidan al terminar el job (§10) —
          </p>
        ) : (
          <ul className="space-y-1">
            {artefactos.map((a) => (
              <li key={a.n}>
                <button
                  type="button"
                  onClick={() => void abrir(a.n)}
                  className="w-full truncate rounded border border-borde/60 px-2 py-1 text-left text-[10px] text-texto-suave hover:bg-panel-alto"
                  title={a.resumen}
                >
                  <span className="text-texto">{a.paso}</span> — {a.resumen}
                </button>
              </li>
            ))}
          </ul>
        )}
        {detalle !== null && (
          <div className="mt-2 rounded border border-borde/60 bg-panel-alto/60 p-2">
            <h5 className="text-[10px] font-semibold text-texto">
              {detalle.paso}
            </h5>
            {detalle.prompts !== null && detalle.prompts !== undefined && (
              <details className="mt-1">
                <summary className="cursor-pointer text-[10px] text-acento">Prompts</summary>
                <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-[9px] text-texto-suave">
                  {detalle.prompts}
                </pre>
              </details>
            )}
            {detalle.artefacto !== null && detalle.artefacto !== undefined && (
              <details className="mt-1">
                <summary className="cursor-pointer text-[10px] text-acento">Artefacto (JSON)</summary>
                <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-[9px] text-texto-suave">
                  {JSON.stringify(detalle.artefacto, null, 2)}
                </pre>
              </details>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
