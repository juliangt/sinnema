import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useProjectStore } from '../stores/projectStore'

interface Estado {
  cargando: boolean
  error: string | null
}

/**
 * Hidratación por proyecto (spec-red-3d §8.2): GET /red + GET /api/projects/{id}
 * en paralelo hacia el projectStore. El cambio de proyecto remonta la escena
 * (`<ProjectScene key={projectId}>`), así que aquí solo entra la data.
 */
export function useProjectNetwork(projectId: string | null): Estado {
  const [estado, setEstado] = useState<Estado>({ cargando: false, error: null })
  const version = useProjectStore((s) => s.version)

  useEffect(() => {
    if (projectId === null) {
      setEstado({ cargando: false, error: null })
      return
    }
    let cancelado = false
    setEstado({ cargando: true, error: null })
    Promise.all([api.red(projectId), api.proyecto(projectId)])
      .then(([red, detalle]) => {
        if (cancelado) return
        useProjectStore.getState().hidratar(red, detalle)
        setEstado({ cargando: false, error: null })
      })
      .catch((error: unknown) => {
        if (cancelado) return
        setEstado({ cargando: false, error: error instanceof Error ? error.message : String(error) })
      })
    return () => {
      cancelado = true
    }
  }, [projectId, version])

  return estado
}
