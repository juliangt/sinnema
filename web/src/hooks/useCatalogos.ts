import { useEffect } from 'react'
import { api } from '../api/client'
import { useProjectStore } from '../stores/projectStore'

/** Carga los catálogos del backend (una vez por sesión; spec-red-3d §5). */
export function useCatalogos(): void {
  useEffect(() => {
    let cancelado = false
    api
      .catalogos()
      .then((catalogos) => {
        if (!cancelado) useProjectStore.getState().setCatalogos(catalogos)
      })
      .catch(() => {
        // Los formularios llegan en Fase 6; si falla, se reintenta al remontar.
      })
    return () => {
      cancelado = true
    }
  }, [])
}
