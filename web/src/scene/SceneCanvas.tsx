// Canvas raíz de R3F (spec-red-3d §8.3): el <Canvas> NO se desmonta al
// cambiar de proyecto (solo su contenido vía <ProjectScene key={projectId}>),
// para no recrear el contexto WebGL.

import { Canvas } from '@react-three/fiber'
import { useProjectStore } from '../stores/projectStore'
import { ProjectScene } from './ProjectScene'

function Contenido() {
  const proyectoActivo = useProjectStore((s) => s.proyectoActivo)
  const red = useProjectStore((s) => s.red)

  if (proyectoActivo === null || red === null) return null
  if (red.project_id !== proyectoActivo) return null // hidratación en curso
  return <ProjectScene key={proyectoActivo} red={red} />
}

export function SceneCanvas() {
  return (
    <div className="absolute inset-0">
      <Canvas
        dpr={[1, 2]}
        camera={{ position: [24, 26, 44], fov: 50, near: 0.1, far: 500 }}
        gl={{ antialias: true, powerPreference: 'high-performance' }}
      >
        <color attach="background" args={['#0a0f1a']} />
        <ambientLight intensity={0.55} />
        <directionalLight position={[18, 30, 12]} intensity={1.15} />
        <directionalLight position={[-16, 14, -10]} intensity={0.35} color="#7aa2f7" />
        <Contenido />
      </Canvas>
    </div>
  )
}
