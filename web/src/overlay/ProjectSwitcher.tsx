import type { ProjectSummary } from '../types'
import { useProjectStore } from '../stores/projectStore'
import { Select } from '../components/ui/select'

interface Props {
  proyectos: ProjectSummary[]
  valor: string | null
}

/** Selector de proyecto del TopBar: cambia el proyecto activo del store. */
export function ProjectSwitcher({ proyectos, valor }: Props) {
  const seleccionarProyecto = useProjectStore((s) => s.seleccionarProyecto)

  return (
    <label className="flex items-center gap-2 text-xs text-texto-suave">
      <span>Proyecto</span>
      <Select
        size="sm"
        value={valor ?? ''}
        onChange={(ev) => seleccionarProyecto(ev.target.value)}
        aria-label="Cambiar de proyecto"
        disabled={proyectos.length === 0}
      >
        {proyectos.length === 0 && <option value="">Cargando…</option>}
        {proyectos.map((p) => (
          <option key={p.project_id} value={p.project_id}>
            {p.brand_name} ({p.project_id})
          </option>
        ))}
      </Select>
    </label>
  )
}
