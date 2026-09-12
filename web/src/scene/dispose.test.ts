// disposeObject3D (spec-red-3d §8.3): libera geometrías, materiales y
// texturas del subárbol recorrido.

import { describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'
import { disposeObject3D } from './dispose'

describe('disposeObject3D', () => {
  it('disposea geometrías y materiales (incluidos los de arrays)', () => {
    const geometria = new THREE.BoxGeometry()
    const espiaGeo = vi.spyOn(geometria, 'dispose')
    const materialSimple = new THREE.MeshStandardMaterial()
    const espiaSimple = vi.spyOn(materialSimple, 'dispose')
    const materialArray = [new THREE.MeshBasicMaterial(), new THREE.MeshBasicMaterial()]
    const espiaArray = materialArray.map((m) => vi.spyOn(m, 'dispose'))

    const grupo = new THREE.Group()
    grupo.add(new THREE.Mesh(geometria, materialSimple))
    grupo.add(new THREE.Mesh(geometria, materialArray))

    disposeObject3D(grupo)

    expect(espiaGeo).toHaveBeenCalled()
    expect(espiaSimple).toHaveBeenCalled()
    espiaArray.forEach((espia) => expect(espia).toHaveBeenCalled())
  })

  it('disposea las texturas referidas por el material', () => {
    const textura = new THREE.Texture()
    const espiaTextura = vi.spyOn(textura, 'dispose')
    const material = new THREE.MeshStandardMaterial({ map: textura })
    const malla = new THREE.Mesh(new THREE.SphereGeometry(), material)

    disposeObject3D(malla)

    expect(espiaTextura).toHaveBeenCalled()
  })

  it('no falla con objetos sin geometría (luces, grupos)', () => {
    const grupo = new THREE.Group()
    grupo.add(new THREE.Group())
    expect(() => disposeObject3D(grupo)).not.toThrow()
  })
})
