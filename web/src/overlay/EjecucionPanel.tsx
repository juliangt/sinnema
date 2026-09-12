// Panel de ejecución (esquina inferior izquierda): lanzar una corrida del
// proyecto activo, elegir el job a seguir y ver el timeline 2D de eventos.
// El timeline se alimenta del log reactivo del executionStore (frecuencia de
// UI); el streaming de tokens vive en los buffers mutables (§10).

import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useExecutionStore } from '../stores/executionStore'
import { useExecutionSync } from '../hooks/useExecutionSync'
import { useProjectStore } from '../stores/projectStore'
import type { Job } from '../types'

export function EjecucionPanel() {
  const proyectoActivo = useProjectStore((s) => s.proyectoActivo)
  const jobId = useExecutionStore((s) => s.jobId)
  const status = useExecutionStore((s) => s.status)
  const specDesfasado = useExecutionStore((s) => s.specDesfasado)
  const log = useExecutionStore((s) => s.log)
  const contadores = useExecutionStore((s) => s.contadores)

  const [jobs, setJobs] = useState<Job[]>([])
  const [lanzando, setLanzando] = useState(false)
  const [abierto, setAbierto] = useState(true)

  // El ciclo de vida del stream lo dueña el hook (§10).
  useExecutionSync(jobId)

  useEffect(() => {
    if (proyectoActivo === null) return
    api
      .jobs(proyectoActivo)
      .then(setJobs)
      .catch(() => setJobs([]))
  }, [proyectoActivo, jobId])

  const lanzar = async (): Promise<void> => {
    if (proyectoActivo === null || lanzando) return
    setLanzando(true)
    try {
      const { job_id } = await api.lanzarSerie({ project_id: proyectoActivo })
      useExecutionStore.getState().iniciar(job_id)
    } catch (error) {
      console.error('No se pudo lanzar la corrida:', error)
    } finally {
      setLanzando(false)
    }
  }

  return (
    <section className="absolute bottom-3 left-3 z-10 flex max-h-[45vh] w-96 flex-col rounded-lg border border-borde/70 bg-panel/90 text-xs backdrop-blur">
      <header className="flex items-center gap-2 border-b border-borde/70 px-3 py-2">
        <h2 className="font-semibold tracking-wide text-texto">Ejecución</h2>
        {jobId !== null && (
          <span className="rounded-full border border-borde px-2 py-0.5 text-[10px] text-texto-suave">
            {jobId} · {status}
          </span>
        )}
        {specDesfasado && (
          <span
            className="rounded-full border border-amber-700 bg-amber-900/40 px-2 py-0.5 text-[10px] text-amber-300"
            title="El TOML cambió desde que este job arrancó: corre con el spec congelado"
          >
            spec congelado
          </span>
        )}
        <button
          type="button"
          onClick={lanzar}
          disabled={lanzando || proyectoActivo === null}
          className="ml-auto rounded border border-borde px-2 py-0.5 text-[10px] text-texto-suave transition-colors hover:bg-panel-alto hover:text-texto disabled:opacity-40"
        >
          {lanzando ? 'Lanzando…' : 'Lanzar corrida'}
        </button>
        <button
          type="button"
          onClick={() => setAbierto((v) => !v)}
          className="rounded border border-borde px-2 py-0.5 text-[10px] text-texto-suave hover:bg-panel-alto"
        >
          {abierto ? '▾' : '▸'}
        </button>
      </header>

      {abierto && (
        <>
          {jobs.length > 0 && (
            <div className="flex gap-1 overflow-x-auto border-b border-borde/50 px-3 py-1.5">
              {jobs.slice(0, 6).map((job) => (
                <button
                  key={job.job_id}
                  type="button"
                  onClick={() => useExecutionStore.getState().iniciar(job.job_id)}
                  className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] transition-colors ${
                    job.job_id === jobId
                      ? 'border-acento text-acento'
                      : 'border-borde text-texto-suave hover:bg-panel-alto'
                  }`}
                  title={`${job.status} · ${job.topic}`}
                >
                  {job.job_id.slice(0, 6)}·{job.status === 'running' ? '▶' : job.status[0]}
                </button>
              ))}
            </div>
          )}
          <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
            {log.length === 0 ? (
              <p className="text-[11px] text-texto-suave">
                Lanzá una corrida o elegí un job para seguir sus eventos por nodo
                en vivo.
              </p>
            ) : (
              <ul className="space-y-0.5 font-mono text-[10px] leading-relaxed">
                {log.slice(-40).map((entrada) => (
                  <li
                    key={entrada.id}
                    className={
                      entrada.kind === 'error'
                        ? 'text-red-300'
                        : entrada.kind === 'done'
                          ? 'text-emerald-300'
                          : entrada.kind === 'node_start'
                            ? 'text-texto'
                            : 'text-texto-suave'
                    }
                    title={entrada.node}
                  >
                    {entrada.texto}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <footer className="flex gap-2 border-t border-borde/50 px-3 py-1 text-[10px] text-texto-suave">
            {Object.entries(contadores).map(([kind, n]) => (
              <span key={kind}>
                {kind}: {n}
              </span>
            ))}
          </footer>
        </>
      )}
    </section>
  )
}
