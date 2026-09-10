// Subárbol 3D de un proyecto (spec-red-3d §8.2): se remonta completo al
// cambiar de proyecto (`<ProjectScene key={projectId}>`), que es el mecanismo
// de liberación de recursos WebGL — nada se comparte entre proyectos.

import { useMemo } from 'react'
import type { EffectiveNetwork } from '../types'
import { useSelectionStore } from '../stores/selectionStore'
import { AgentNode3D } from './AgentNode3D'
import { calcularLayout } from './layout'

interface Props {
  red: EffectiveNetwork
}

export function ProjectScene({ red }: Props) {
  const layout = useMemo(() => calcularLayout(red), [red])
  const seleccionado = useSelectionStore((s) => s.seleccionado)
  const hover = useSelectionStore((s) => s.hover)

  return (
    <group>
      {/* Piso de referencia sutil bajo la red. */}
      <gridHelper
        args={[110, 55, '#22304a', '#141c2c']}
        position={[layout.caja.centro.x, -0.02, layout.caja.centro.z]}
      />
      {red.nodes.map((nodo) => (
        <AgentNode3D
          key={nodo.id}
          nodo={nodo}
          posicion={layout.posiciones[nodo.id]}
          seleccionado={seleccionado === nodo.id}
          conHover={hover === nodo.id}
        />
      ))}
    </group>
  )
}
