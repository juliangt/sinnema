// Disciplina de dispose (spec-red-3d §8.3): recorrido imperativo que libera
// geometrías, materiales y texturas de un subárbol Object3D. Se usa en los
// cleanups de useEffect y como red de seguridad al desmontar ProjectScene —
// el remount por `key` descarta el árbol declarativo y esto garantiza que los
// recursos GPU vuelvan al baseline al cambiar de proyecto.

import * as THREE from 'three'

function disponerMaterial(material: THREE.Material): void {
  material.dispose()
  // Las texturas referidas por el material no se liberan solas.
  for (const valor of Object.values(material) as unknown[]) {
    if (valor instanceof THREE.Texture) valor.dispose()
  }
}

/** Libera los recursos GPU de `raiz` y de todo su subárbol (§8.3). */
export function disposeObject3D(raiz: THREE.Object3D): void {
  raiz.traverse((objeto) => {
    const malla = objeto as THREE.Mesh
    if (malla.geometry !== undefined) malla.geometry.dispose()

    const { material } = malla
    if (Array.isArray(material)) material.forEach(disponerMaterial)
    else if (material !== undefined) disponerMaterial(material)
  })
}
