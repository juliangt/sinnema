// useExecutionSync (spec-red-3d §10): dueño del ciclo de vida del stream de
// un job. Abre el EventSource (reconexión y Last-Event-ID nativas), despacha
// cada frame al executionStore, respalda el badge de status con polling cada
// 2 s (cubre SSE bloqueado por proxy) y, al llegar a un status terminal,
// cierra el stream y consolida los artefactos para el inspector.

import { useEffect } from 'react'
import { api } from '../api/client'
import { decodificarDatos, suscribirEventosJob } from '../api/sse'
import { useExecutionStore } from '../stores/executionStore'
import type { Artifact, JobStatus } from '../types'

const INTERVALO_POLLING_MS = 2000

export function useExecutionSync(jobId: string | null): void {
  useEffect(() => {
    if (jobId === null) return
    const store = useExecutionStore.getState()
    store.iniciar(jobId)
    let cerrado = false

    const cerrarSSE = suscribirEventosJob(jobId, (frame) => {
      if (frame.evento === 'end') return
      const decodificado = decodificarDatos(frame)
      useExecutionStore.getState().aplicarEvento(
        decodificado.kind === 'runtime'
          ? decodificado.evento
          : { kind: 'legacy', texto: decodificado.texto },
      )
    })

    const poller = window.setInterval(async () => {
      try {
        const job = await api.job(jobId)
        useExecutionStore.getState().setStatus(
          job.status as JobStatus,
          job.spec_desfasado === true,
        )
        if (TERMINALES.has(job.status as JobStatus) && !cerrado) {
          cerrado = true
          cerrarSSE()
          window.clearInterval(poller)
          try {
            const pasos = await api.artefactos(jobId)
            useExecutionStore.getState().consolidar(pasos as Artifact[])
          } catch {
            useExecutionStore.getState().consolidar([])
          }
        }
      } catch {
        // El polling es respaldo: un fallo puntual no tumba la sincronización.
      }
    }, INTERVALO_POLLING_MS)

    return () => {
      cerrado = true
      cerrarSSE()
      window.clearInterval(poller)
    }
  }, [jobId])
}

const TERMINALES: Set<string> = new Set(['completed', 'failed'])
