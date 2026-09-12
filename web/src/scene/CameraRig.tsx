// Cámara, controles y selección (spec-red-3d §9.6): OrbitControls con
// damping; al cambiar la selección, el rig amortigua (lerp) controls.target
// hacia el nodo y la posición de cámara hacia un encuadre que conserva el
// contexto global (distancia proporcional al bounding box de la red). El
// botón "reencuadrar" y Escape devuelven la vista general.

import { useEffect, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'
import * as THREE from 'three'
import { useSelectionStore } from '../stores/selectionStore'
import type { LayoutRed } from './layout'

/** Factor de amortiguación por frame (lerp ~0.08). */
const LERP = 0.08
/** Distancia de primer plano (doble click), en radios de nodo. */
const DISTANCIA_CERCA = 4.5
/** Distancia con contexto, proporcional al bounding box de la red. */
const DISTANCIA_CONTEXTO = 2.4

interface Props {
  layout: LayoutRed
}

function encuadre(
  objetivo: THREE.Vector3,
  distancia: number,
  layout: LayoutRed,
): THREE.Vector3 {
  // Vista general: cenital ligeramente frontal respecto del centro de la red.
  const escala = Math.max(layout.caja.radio, 6)
  return new THREE.Vector3(
    objetivo.x + escala * 0.35,
    objetivo.y + escala * distancia * 0.75,
    objetivo.z + escala * distancia,
  )
}

export function CameraRig({ layout }: Props) {
  const controlsRef = useRef<OrbitControlsImpl>(null)
  const camera = useThree((s) => s.camera)

  const foco = useSelectionStore((s) => s.foco)
  const reencuadres = useSelectionStore((s) => s.reencuadres)

  // Destinos actuales del amortiguado (target y posición de cámara).
  const destinoTarget = useRef<THREE.Vector3 | null>(null)
  const destinoPosicion = useRef<THREE.Vector3 | null>(null)

  // Vista general al montar la escena del proyecto y al pedir reencuadre.
  useEffect(() => {
    const centro = new THREE.Vector3(layout.caja.centro.x, layout.caja.centro.y, layout.caja.centro.z)
    destinoTarget.current = centro.clone()
    destinoPosicion.current = encuadre(centro, DISTANCIA_CONTEXTO, layout)
  }, [layout, reencuadres])

  // Al cambiar selección/foco: encuadre del nodo (contexto o primer plano).
  useEffect(() => {
    if (foco === null) return
    const posicion = layout.posiciones[foco.nodoId]
    if (posicion === undefined) return
    const objetivo = new THREE.Vector3(posicion.x, posicion.y, posicion.z)
    destinoTarget.current = objetivo.clone()
    destinoPosicion.current = encuadre(
      objetivo,
      foco.cercano ? DISTANCIA_CERCA : DISTANCIA_CONTEXTO,
      layout,
    )
  }, [foco, layout])

  // Escape: soltar selección y volver a la vista general.
  useEffect(() => {
    const alPresionar = (e: KeyboardEvent) => {
      if (e.key === 'Escape') useSelectionStore.getState().solicitarReencuadre()
    }
    window.addEventListener('keydown', alPresionar)
    return () => window.removeEventListener('keydown', alPresionar)
  }, [])

  useFrame(() => {
    const controls = controlsRef.current
    if (controls === null) return
    if (destinoTarget.current !== null) {
      controls.target.lerp(destinoTarget.current, LERP)
    }
    if (destinoPosicion.current !== null) {
      camera.position.lerp(destinoPosicion.current, LERP)
      // Convergió: dejar de amortiguar para no pelear con el usuario.
      if (camera.position.distanceTo(destinoPosicion.current) < 0.05) {
        destinoPosicion.current = null
        destinoTarget.current = null
      }
    }
    controls.update()
  })

  return (
    <OrbitControls
      ref={controlsRef}
      makeDefault
      enableDamping
      dampingFactor={0.08}
      maxPolarAngle={Math.PI / 2.05}
      minDistance={2}
      maxDistance={200}
    />
  )
}
