import { useEffect } from 'react'
import { api } from './api/client'
import { useProjectStore } from './stores/projectStore'
import { useCatalogos } from './hooks/useCatalogos'
import { useProjectNetwork } from './hooks/useProjectNetwork'
import { SceneCanvas } from './scene/SceneCanvas'
import { TopBar } from './overlay/TopBar'
import { InspectorPanel } from './overlay/InspectorPanel'
import { EjecucionPanel } from './overlay/EjecucionPanel'

export default function App() {
  const proyectoActivo = useProjectStore((s) => s.proyectoActivo)
  const { cargando, error } = useProjectNetwork(proyectoActivo)
  useCatalogos()

  // Arranque: lista de proyectos y selección inicial.
  useEffect(() => {
    api
      .proyectos()
      .then((proyectos) => {
        useProjectStore.getState().setProyectos(proyectos)
        const actual = useProjectStore.getState().proyectoActivo
        if (actual === null && proyectos.length > 0) {
          useProjectStore.getState().seleccionarProyecto(proyectos[0].project_id)
        }
      })
      .catch((error: unknown) => console.error('No se pudo cargar los proyectos:', error))
  }, [])

  return (
    <div className="relative h-full w-full overflow-hidden bg-fondo">
      <SceneCanvas />
      <TopBar />
      <InspectorPanel />
      <EjecucionPanel />
      {cargando && (
        <div className="pointer-events-none absolute inset-x-0 top-16 z-10 flex justify-center">
          <span className="rounded-full border border-borde bg-panel/90 px-4 py-1 text-xs text-texto-suave">
            Hidratando la red…
          </span>
        </div>
      )}
      {error !== null && (
        <div className="pointer-events-none absolute inset-x-0 top-16 z-10 flex justify-center">
          <span className="rounded-full border border-red-900 bg-panel/90 px-4 py-1 text-xs text-red-300">
            Error al hidratar: {error}
          </span>
        </div>
      )}
    </div>
  )
}
