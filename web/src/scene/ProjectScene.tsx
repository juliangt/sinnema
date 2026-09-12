// Subárbol 3D de un proyecto (spec-red-3d §8.2): se remonta completo al
// cambiar de proyecto (`<ProjectScene key={projectId}>`), que es el mecanismo
// de liberación de recursos WebGL — nada se comparte entre proyectos.

import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { EffectiveNetwork } from '../types'
import { useSelectionStore } from '../stores/selectionStore'
import { AgentNode3D } from './AgentNode3D'
import { EdgeLine } from './EdgeLine'
import { CameraRig } from './CameraRig'
import { calcularLayout } from './layout'
import { disposeObject3D } from './dispose'

interface Props {
  red: EffectiveNetwork
}

export function ProjectScene({ red }: Props) {
  const layout = useMemo(() => calcularLayout(red), [red])
  const seleccionado = useSelectionStore((s) => s.seleccionado)
  const hover = useSelectionStore((s) => s.hover)
  const raizRef = useRef<THREE.Group>(null)

  // Red de seguridad de dispose (§8.3): el remount por `key` descarta el
  // árbol declarativo; este cleanup garantiza la liberación GPU completa.
  useEffect(() => {
    const raiz = raizRef.current
    return () => {
      if (raiz !== null) disposeObject3D(raiz)
    }
  }, [])

  return (
    <group ref={raizRef}>
      {/* Piso de referencia sutil bajo la red. */}
      <gridHelper
        args={[110, 55, '#22304a', '#141c2c']}
        position={[layout.caja.centro.x, -0.02, layout.caja.centro.z]}
      />
      {red.edges.map((edge) => {
        const desde = layout.posiciones[edge.from]
        const hacia = layout.posiciones[edge.to]
        // Una arista con extremo fuera del layout no se dibuja (defensivo).
        if (desde === undefined || hacia === undefined) return null
        return <EdgeLine key={edge.id} edge={edge} desde={desde} hacia={hacia} />
      })}
      {red.nodes.map((nodo) => (
        <AgentNode3D
          key={nodo.id}
          nodo={nodo}
          posicion={layout.posiciones[nodo.id]}
          seleccionado={seleccionado === nodo.id}
          conHover={hover === nodo.id}
        />
      ))}
      <CameraRig layout={layout} />
    </group>
  )
}
