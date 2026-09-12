// Colores del canvas 3D (spec-red-3d §9.2): el halo/anillo emisivo de cada
// nodo usa el color de su proveedor LLM para leer la heterogeneidad de
// modelos de un vistazo.

import type { ProveedorLlm } from '../types'

export const COLOR_PROVEEDOR: Record<ProveedorLlm, string> = {
  anthropic: '#D97757', // arcilla
  openai: '#10A37F', // esmeralda
  google: '#4285F4', // azul
  ollama: '#7C3AED', // violeta
}

/** Color neutro de la malla base (los nodos toman el tinte del halo). */
export const COLOR_NODO = '#93a4c3'
/** Nodos estructurales sin LLM (cierre): gris, sin halo. */
export const COLOR_NODO_SIN_LLM = '#5b6577'
