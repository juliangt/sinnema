// Nodos del grafo (spec-red-3d §9.2): geometría low-poly por tipo de agente,
// halo/anillo emisivo con el color del proveedor del LLMConfig y etiqueta
// Billboard+Text con rol y proveedor/modelo. Los nodos sin LLM (cierre) van
// en gris, a menor escala y sin halo.
//
// Estados visuales (§9.5): el componente NO se re-renderiza por eventos —
// lee el mapa mutable `estadoNodos` del executionStore en useFrame y
// interpola materiales/escalas hacia el objetivo (Idle/Processing/Streaming/
// Tool Call/Error/Done).

import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Billboard, Text } from '@react-three/drei'
import * as THREE from 'three'
import type { AgentNode, TipoNodo } from '../types'
import { useSelectionStore } from '../stores/selectionStore'
import { useExecutionStore, type NodeVisualState } from '../stores/executionStore'
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
    case 'media':
      // Panel de keyframe (recursos-ancla §9.2): placa vertical fina,
      // como un marco de película entre el enriquecimiento y el cierre.
      return <boxGeometry args={[1.3, 0.95, 0.14]} />
    case 'cierre':
      // Anillo fino a escala menor.
      return <torusGeometry args={[0.85, 0.08, 8, 48]} />
  }
}

const COLOR_AMBAR = '#f0b45f'
const COLOR_ERROR = '#f07a7a'
const COLOR_DONE = '#5ad19a'

// Fragment del anillo de streaming (§9.5): barrido radial con uniform time.
// vUv cubre el cuadrado delimitador: el centro es 0.5,0.5 y el anillo vive
// en el radio 0.34–0.5.
const SHADER_ANILLO_FRAGMENT = /* glsl */ `
  uniform float uTime;
  uniform vec3 uColor;
  varying vec2 vUv;
  void main() {
    vec2 centro = vUv - 0.5;
    float radio = length(centro);
    float banda = smoothstep(0.33, 0.36, radio) * (1.0 - smoothstep(0.47, 0.5, radio));
    float angulo = atan(centro.y, centro.x);
    float barrido = 0.5 + 0.5 * sin(angulo * 3.0 + uTime * 6.0);
    gl_FragColor = vec4(uColor, banda * (0.3 + 0.7 * barrido));
  }
`

const SHADER_ANILLO_VERTEX = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

export function AgentNode3D({ nodo, posicion, seleccionado, conHover }: Props) {
  const haloRef = useRef<THREE.Mesh>(null)
  const mallaRef = useRef<THREE.Mesh>(null)
  const glifoToolRef = useRef<THREE.Group>(null)
  const anilloRef = useRef<THREE.Mesh>(null)
  const seleccionar = useSelectionStore((s) => s.seleccionar)
  const enfocar = useSelectionStore((s) => s.enfocar)
  const setHover = useSelectionStore((s) => s.setHover)

  const colorHalo: string | null = nodo.llm ? COLOR_PROVEEDOR[nodo.llm.proveedor] : null

  const colorProveedor = useMemo(() => new THREE.Color(colorHalo ?? '#000000'), [colorHalo])
  const colorAmbar = useMemo(() => new THREE.Color(COLOR_AMBAR), [])
  const colorError = useMemo(() => new THREE.Color(COLOR_ERROR), [])
  const colorDone = useMemo(() => new THREE.Color(COLOR_DONE), [])

  // Uniforms del anillo de streaming (uno por nodo, se disposea al desmontar
  // por el recorrido de disposeObject3D sobre materiales).
  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uColor: { value: new THREE.Color(colorHalo ?? '#93a4c3') },
    }),
    [colorHalo],
  )

  // Último estado visto: para detectar transiciones (destello de Done).
  const estadoPrevio = useRef<NodeVisualState>('idle')
  const instanteDone = useRef(-10)

  useFrame((estado, delta) => {
    const marca = useExecutionStore.getState().estadoNodos.get(nodo.id)
    const visual: NodeVisualState = marca?.estado ?? 'idle'
    const tiempo = estado.clock.elapsedTime
    if (visual === 'done' && estadoPrevio.current !== 'done') {
      instanteDone.current = tiempo
    }
    estadoPrevio.current = visual

    const malla = mallaRef.current
    const halo = haloRef.current
    if (malla === null) return
    const material = malla.material as THREE.MeshStandardMaterial

    // Objetivos por estado (§9.5); todo llega interpolado, nunca a saltos.
    let escalaObjetivo = seleccionado ? 1.45 : conHover ? 1.22 : 1
    let emissiveObjetivo = 0.18
    let colorObjetivo = colorProveedor
    let haloVisible = colorHalo !== null

    switch (visual) {
      case 'processing':
        // Respiración de escala + pulso lento de emissive.
        escalaObjetivo *= 1 + 0.06 * Math.sin(tiempo * 3.2)
        emissiveObjetivo = 0.55 + 0.25 * Math.sin(tiempo * 2.1)
        break
      case 'streaming':
        emissiveObjetivo = 1.15
        break
      case 'tool':
        emissiveObjetivo = 0.9
        colorObjetivo = colorAmbar
        break
      case 'error': {
        // Parpadeo rojo que decae a los 5 s.
        const transcurrido = (performance.now() - (marca?.desde ?? performance.now())) / 1000
        const decaimiento = Math.max(0, 1 - transcurrido / 5)
        emissiveObjetivo = decaimiento > 0 ? (0.4 + 1.1 * Math.abs(Math.sin(tiempo * 8))) * decaimiento : 0.18
        if (decaimiento <= 0) {
          colorObjetivo = colorProveedor
          haloVisible = colorHalo !== null
        } else {
          colorObjetivo = colorError
          haloVisible = true
        }
        break
      }
      case 'done': {
        // Destello único y decaimiento a glow suave verdoso.
        const desdeFlash = tiempo - instanteDone.current
        emissiveObjetivo = 1.4 * Math.exp(-desdeFlash * 2.5) + 0.35
        colorObjetivo = desdeFlash < 1.2 ? colorDone : colorProveedor
        break
      }
      case 'idle':
        break
    }

    const factor = Math.min(1, delta * 6)
    malla.scale.setScalar(THREE.MathUtils.lerp(malla.scale.x, escalaObjetivo, factor))
    material.emissiveIntensity = THREE.MathUtils.lerp(
      material.emissiveIntensity, emissiveObjetivo, factor,
    )
    material.emissive.lerp(colorObjetivo, factor)

    if (halo !== null) {
      halo.visible = haloVisible
      const haloMaterial = halo.material as THREE.MeshBasicMaterial
      haloMaterial.color.lerp(colorObjetivo, factor)
    }

    // Glifo de tool en la etiqueta y anillo de streaming: visibilidad en
    // useFrame, sin re-render de React (§10).
    if (glifoToolRef.current !== null) {
      glifoToolRef.current.visible = visual === 'tool'
    }
    if (anilloRef.current !== null) {
      const activo = visual === 'streaming'
      anilloRef.current.visible = activo
      if (activo) {
        uniforms.uTime.value = tiempo
        anilloRef.current.scale.setScalar(
          THREE.MathUtils.lerp(anilloRef.current.scale.x, 1.9, Math.min(1, delta * 8)),
        )
      }
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
      onDoubleClick={(e) => {
        e.stopPropagation()
        enfocar(nodo.id)
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

      {/* Anillo de streaming: shaderMaterial con barrido radial (§9.5). */}
      <mesh ref={anilloRef} rotation={[Math.PI / 2, 0, 0]} visible={false}>
        <ringGeometry args={[1.7, 2.1, 48]} />
        <shaderMaterial
          vertexShader={SHADER_ANILLO_VERTEX}
          fragmentShader={SHADER_ANILLO_FRAGMENT}
          uniforms={uniforms}
          transparent
          side={THREE.DoubleSide}
        />
      </mesh>

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
        {/* Glifo de Tool Call: visible solo en ese estado (useFrame). */}
        <group ref={glifoToolRef} position={[0.75, -0.42, 0]} visible={false}>
          <Text fontSize={0.34} anchorX="center" anchorY="middle" color={COLOR_AMBAR}
            outlineWidth={0.015} outlineColor="#0a0f1a">
            ⚙
          </Text>
        </group>
      </Billboard>
    </group>
  )
}
