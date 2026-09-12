// Aristas dirigidas del grafo (spec-red-3d §9.3): curva bezier cuadrática por
// arista (punto medio elevado en Y para despejar los nodos), renderizada con
// `Line` de drei (Line2, grosor en píxeles) y cono flecha en t≈0.97 orientado
// por la tangente. Las condicionales van discontinuas (dash) con su label en
// un `Text` pequeño sobre el punto medio. El ciclo de crítica (compuerta →
// escritor) queda evidente por la curva de retorno elevada.

import { useMemo } from 'react'
import { Billboard, Line, Text } from '@react-three/drei'
import * as THREE from 'three'
import type { EdgeTransition } from '../types'
import type { Posicion } from './layout'

interface Props {
  edge: EdgeTransition
  desde: Posicion
  hacia: Posicion
}

/** Inicio/fin del muestreo: evita atravesar la geometría del nodo y al cono. */
const T_INICIO = 0.03
const T_FLECHA = 0.94
const T_FIN = 0.955
const SEGMENTOS = 40

const COLOR_ARISTA = '#8fa0bd'
const COLOR_CONDICIONAL = '#66748e'
const COLOR_FLECHA = '#a8b8d4'
const COLOR_LABEL = '#93a4c3'

function vec(p: Posicion): THREE.Vector3 {
  return new THREE.Vector3(p.x, p.y, p.z)
}

/** Curva bezier cuadrática de la arista: control = punto medio elevado en Y. */
export function curvaDeArista(desde: Posicion, hacia: Posicion): THREE.QuadraticBezierCurve3 {
  const inicio = vec(desde)
  const fin = vec(hacia)
  const distancia = inicio.distanceTo(fin)
  // La elevación despeja los nodos intermedios; el retorno (ciclo de crítica,
  // hacia atrás en X) se eleva más para hacer el ciclo legible.
  const retorno = hacia.x < desde.x
  const elevacion = THREE.MathUtils.clamp(distancia * 0.22, 1.0, 4.0) * (retorno ? 1.7 : 1)
  const control = inicio
    .clone()
    .add(fin)
    .multiplyScalar(0.5)
    .add(new THREE.Vector3(0, elevacion, 0))
  return new THREE.QuadraticBezierCurve3(inicio, control, fin)
}

export function EdgeLine({ edge, desde, hacia }: Props) {
  const curva = useMemo(() => curvaDeArista(desde, hacia), [desde, hacia])

  const puntos = useMemo(
    () =>
      curva
        .getPoints(SEGMENTOS)
        .filter((_, i) => {
          const t = i / SEGMENTOS
          return t >= T_INICIO && t <= T_FIN
        }),
    [curva],
  )

  const flecha = useMemo(() => {
    const posicion = curva.getPoint(T_FLECHA)
    const tangente = curva.getTangent(T_FLECHA).normalize()
    // El cono por defecto apunta a +Y: orientarlo según la tangente.
    const quaternion = new THREE.Quaternion().setFromUnitVectors(
      new THREE.Vector3(0, 1, 0),
      tangente,
    )
    return { posicion, quaternion }
  }, [curva])

  const puntoLabel = useMemo(() => curva.getPoint(0.5), [curva])

  return (
    <group>
      <Line
        points={puntos}
        color={edge.condicional ? COLOR_CONDICIONAL : COLOR_ARISTA}
        lineWidth={edge.condicional ? 1.4 : 1.8}
        transparent
        opacity={0.85}
        dashed={edge.condicional}
        dashSize={0.45}
        gapSize={0.3}
      />
      <mesh position={flecha.posicion} quaternion={flecha.quaternion}>
        <coneGeometry args={[0.16, 0.45, 10]} />
        <meshBasicMaterial color={COLOR_FLECHA} toneMapped={false} />
      </mesh>
      {edge.condicional && edge.labels.length > 0 && (
        <Billboard position={[puntoLabel.x, puntoLabel.y + 0.35, puntoLabel.z]}>
          <Text
            fontSize={0.26}
            anchorX="center"
            anchorY="bottom"
            color={COLOR_LABEL}
            outlineWidth={0.012}
            outlineColor="#0a0f1a"
          >
            {edge.labels.join(' | ')}
          </Text>
        </Billboard>
      )}
    </group>
  )
}
