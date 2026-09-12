import { useState } from 'react'
import { useProjectStore } from '../stores/projectStore'
import { ProjectSwitcher } from './ProjectSwitcher'
import { ProyectosDrawer } from './ProyectosDrawer'

/** Barra superior del overlay: cambio de proyecto y contexto de la red. */
export function TopBar() {
  const [drawer, setDrawer] = useState(false)
  const proyectos = useProjectStore((s) => s.proyectos)
  const activo = useProjectStore((s) => s.proyectoActivo)
  const red = useProjectStore((s) => s.red)

  const summary = proyectos.find((p) => p.project_id === activo)

  return (
    <header className="absolute inset-x-0 top-0 z-10 flex items-center gap-4 border-b border-borde/70 bg-panel/80 px-4 py-2.5 backdrop-blur">
      <h1 className="text-sm font-semibold tracking-wide text-texto">
        Sinnema <span className="font-normal text-texto-suave">· red de agentes</span>
      </h1>
      <button
        type="button"
        onClick={() => setDrawer((v) => !v)}
        className="rounded border border-borde px-2 py-0.5 text-[10px] text-texto-suave transition-colors hover:bg-panel-alto hover:text-texto"
      >
        Gestionar proyectos
      </button>
      <ProjectSwitcher proyectos={proyectos} valor={activo} />
      {summary && (
        <p className="hidden min-w-0 flex-1 truncate text-xs text-texto-suave md:block">
          {summary.brand_name} — {summary.concepto}
        </p>
      )}
      {red && (
        <div className="ml-auto flex shrink-0 items-center gap-2 text-[11px] text-texto-suave">
          <span className="rounded-full border border-borde px-2 py-0.5">
            hasta: <span className="text-texto">{red.hasta}</span>
          </span>
          <span className="hidden rounded-full border border-borde px-2 py-0.5 sm:inline">
            {red.declarado ? '[flujo] declarado' : 'flujo por defecto'}
          </span>
          <span className="hidden rounded-full border border-borde px-2 py-0.5 lg:inline">
            recursión: {red.limite_recursion}
          </span>
        </div>
      )}
      <ProyectosDrawer abierto={drawer} onCerrar={() => setDrawer(false)} />
    </header>
  )
}
