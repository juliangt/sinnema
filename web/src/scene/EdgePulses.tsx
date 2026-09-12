// Pulsos: mensajes viajando por las aristas (spec-red-3d §9.4). Pool único
// de InstancedMesh (esferas, 64 instancias) compartido por la escena; cada
// pulso activo es {edgeId, t, velocidad} avanzado en useFrame sobre la curva
// de su arista. La activación la calcula executionStore (dirigidos por
// node_end→node_start y flujo ambiental), acá solo se renderizan.

import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { avanzarPulsos, useExecutionStore } from '../stores/executionStore'

const CAPACIDAD = 64

interface Props {
  curvas: Map<string, THREE.QuadraticBezierCurve3>
}

export function EdgePulses({ curvas }: Props) {
  const mallaRef = useRef<THREE.InstancedMesh>(null)
  const matriz = useMemo(() => new THREE.Matrix4(), [])
  const escalaCero = useMemo(() => new THREE.Matrix4().makeScale(0, 0, 0), [])

  // Instancias fuera de uso: fuera de la escena (escala 0).
  useEffect(() => {
    const malla = mallaRef.current
    if (malla === null) return
    for (let i = 0; i < CAPACIDAD; i++) malla.setMatrixAt(i, escalaCero)
    malla.instanceMatrix.needsUpdate = true
    return () => {
      malla.geometry.dispose()
      ;(malla.material as THREE.Material).dispose()
    }
  }, [escalaCero])

  useFrame((_estado, delta) => {
    const malla = mallaRef.current
    if (malla === null) return
    const store = useExecutionStore.getState()
    avanzarPulsos(store, Math.min(delta, 0.1))

    let instancia = 0
    for (const pulso of store.pulsos) {
      if (instancia >= CAPACIDAD) break
      const curva = curvas.get(pulso.edgeId)
      if (curva === undefined) continue
      const punto = curva.getPoint(Math.min(pulso.t, 1))
      const escala = pulso.velocidad > 0.8 ? 0.28 : 0.16 // dirigido vs ambiental
      matriz.makeScale(escala, escala, escala)
      matriz.setPosition(punto)
      malla.setMatrixAt(instancia++, matriz)
    }
    for (let i = instancia; i < CAPACIDAD; i++) malla.setMatrixAt(i, escalaCero)
    malla.instanceMatrix.needsUpdate = true
  })

  return (
    <instancedMesh ref={mallaRef} args={[undefined, undefined, CAPACIDAD]} frustumCulled={false}>
      <sphereGeometry args={[1, 10, 8]} />
      <meshBasicMaterial color="#ffd479" toneMapped={false} transparent opacity={0.95} />
    </instancedMesh>
  )
}
