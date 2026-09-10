// Nodos del grafo (spec-red-3d §9.2): geometría low-poly por tipo de agente,
// halo/anillo emisivo con el color del proveedor del LLMConfig y etiqueta
// Billboard+Text con rol y proveedor/modelo. Los nodos sin LLM (cierre) van
// en gris, a menor escala y sin halo.

import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Billboard, Text } from '@react-three/drei'
import * as THREE from 'three'
import type { AgentNode, TipoNodo } from '../types'
import { useSelectionStore } from '../stores/selectionStore'
import { COLOR_NODO, COLOR_NODO_SIN_LLM, COLOR_PROVEEDOR } from './colores'
import type { Posicion } from './layout'

interface Props {
  nodo: AgentNode
  posicion: Posicion
  seleccionado: boolean
  conHover: boolean
}

/** Geometría low-poly por tipo de agente (tabla §9.2). */
function GeometriaPorTipo({ tipo }: { tipo: TipoNodo }) {
  switch (tipo) {
    case 'serie':
      return <icosahedronGeometry args={[1.05, 0]} />
    case 'contexto':
      return <octahedronGeometry args={[1.05]} />
    case 'escritor':
      return <dodecahedronGeometry args={[1.05]} />
    case 'transformador':
      return <torusGeometry args={[0.72, 0.34, 12, 28]} />
    case 'revisor':
      // Prisma hexagonal: cilindro de 6 lados.
      return <cylinderGeometry args={[1.0, 1.0, 1.5, 6]} />
    case 'enriquecedor':
      // Esfera facetada: segmentos bajos + flatShading.
      return <sphereGeometry args={[1.0, 12, 9]} />
    case 'cierre':
      // Anillo fino a escala menor.
      return <torusGeometry args={[0.85, 0.08, 8, 48]} />
  }
}

export function AgentNode3D({ nodo, posicion, seleccionado, conHover }: Props) {
  const haloRef = useRef<THREE.Mesh>(null)
  const mallaRef = useRef<THREE.Mesh>(null)
  const seleccionar = useSelectionStore((s) => s.seleccionar)
  const setHover = useSelectionStore((s) => s.setHover)

  const colorHalo: string | null = nodo.llm ? COLOR_PROVEEDOR[nodo.llm.proveedor] : null

  // Interpolaciones visuales suaves (nunca saltos): el halo se expande con
  // hover/selección y la emissive sube su intensidad.
  useFrame((_estado, delta) => {
    const escalaObjetivo = seleccionado ? 1.45 : conHover ? 1.22 : 1
    if (haloRef.current !== null) {
      const escala = THREE.MathUtils.lerp(haloRef.current.scale.x, escalaObjetivo, 0.16)
      haloRef.current.scale.setScalar(escala)
    }
    if (mallaRef.current !== null) {
      const material = mallaRef.current.material as THREE.MeshStandardMaterial
      const intensidadObjetivo = seleccionado ? 0.6 : conHover ? 0.42 : 0.18
      material.emissiveIntensity = THREE.MathUtils.lerp(
        material.emissiveIntensity,
        intensidadObjetivo,
        Math.min(1, delta * 6),
      )
    }
  })

  return (
    <group
      position={[posicion.x, posicion.y, posicion.z]}
      onPointerOver={(e) => {
        e.stopPropagation()
        setHover(nodo.id)
        document.body.style.cursor = 'pointer'
      }}
      onPointerOut={(e) => {
        e.stopPropagation()
        setHover(null)
        document.body.style.cursor = 'auto'
      }}
      onClick={(e) => {
        e.stopPropagation()
        seleccionar(nodo.id)
      }}
    >
      <mesh ref={mallaRef} scale={nodo.tipo === 'cierre' ? 0.75 : 1}>
        <GeometriaPorTipo tipo={nodo.tipo} />
        <meshStandardMaterial
          color={nodo.llm ? COLOR_NODO : COLOR_NODO_SIN_LLM}
          emissive={colorHalo ?? '#000000'}
          emissiveIntensity={0.18}
          flatShading
          roughness={0.55}
          metalness={0.15}
        />
      </mesh>

      {colorHalo !== null && (
        <mesh ref={haloRef} rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[1.55, 0.045, 8, 64]} />
          <meshBasicMaterial color={colorHalo} toneMapped={false} transparent opacity={0.9} />
        </mesh>
      )}

      <Billboard position={[0, 2.0, 0]}>
        <Text
          fontSize={0.42}
          anchorX="center"
          anchorY="bottom"
          color="#e7edf7"
          outlineWidth={0.02}
          outlineColor="#0a0f1a"
        >
          {nodo.rol ?? nodo.id}
        </Text>
        {nodo.llm !== null && (
          <Text
            position={[0, -0.4, 0]}
            fontSize={0.22}
            anchorX="center"
            anchorY="top"
            color={colorHalo ?? '#ffffff'}
            outlineWidth={0.015}
            outlineColor="#0a0f1a"
          >
            {nodo.llm.proveedor}/{nodo.llm.modelo}
          </Text>
        )}
      </Billboard>
    </group>
  )
}
