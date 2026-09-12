// Subárbol 3D de un proyecto (spec-red-3d §8.2): se remonta completo al
// cambiar de proyecto (`<ProjectScene key={projectId}>`), que es el mecanismo
// de liberación de recursos WebGL — nada se comparte entre proyectos.
//
// Este componente es la fuente única de las posiciones (layout) y de las
// curvas de las aristas: EdgeLine y EdgePulses reciben las ya calculadas.

import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { EffectiveNetwork } from '../types'
import { useSelectionStore } from '../stores/selectionStore'
import { useExecutionStore } from '../stores/executionStore'
import { AgentNode3D } from './AgentNode3D'
import { EdgeLine } from './EdgeLine'
import { EdgePulses } from './EdgePulses'
import { CameraRig } from './CameraRig'
import { calcularLayout } from './layout'
import { curvaDeArista } from './EdgeLine'
import { disposeObject3D } from './dispose'

interface Props {
  red: EffectiveNetwork
}

export function ProjectScene({ red }: Props) {
  const layout = useMemo(() => calcularLayout(red), [red])
  const seleccionado = useSelectionStore((s) => s.seleccionado)
  const hover = useSelectionStore((s) => s.hover)
  const raizRef = useRef<THREE.Group>(null)

  // Curvas por arista: una sola fuente para el dibujo (EdgeLine) y los
  // pulsos (EdgePulses), para que el mensaje viaje exactamente sobre la línea.
  const curvas = useMemo(() => {
    const mapa = new Map<string, THREE.QuadraticBezierCurve3>()
    for (const edge of red.edges) {
      const desde = layout.posiciones[edge.from]
      const hacia = layout.posiciones[edge.to]
      if (desde === undefined || hacia === undefined) continue
      mapa.set(edge.id, curvaDeArista(desde, hacia))
    }
    return mapa
  }, [red, layout])

  // Los pulsos viajan sobre las aristas del proyecto activo (§9.4).
  useEffect(() => {
    useExecutionStore.getState().configurarRed(red.edges)
  }, [red])

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
        const curva = curvas.get(edge.id)
        // Una arista con extremo fuera del layout no se dibuja (defensivo).
        if (curva === undefined) return null
        return <EdgeLine key={edge.id} edge={edge} curva={curva} />
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
      <EdgePulses curvas={curvas} />
      <CameraRig layout={layout} />
    </group>
  )
}
