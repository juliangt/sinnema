// Validaciones del formulario LLMConfig (spec-red-3d §11.1): rangos ESPEJO
// del backend (§3). Función pura para que el formulario nunca pueda armar un
// payload que el backend rechazaría y para que la regla sea testeable.

export interface ConfigAValidar {
  modelo: string
  temperatura: number
  topPActivado: boolean
  topP: number
  maxTokensActivado: boolean
  maxTokens: number
  tools: string[]
  toolsDisponibles: string[]
}

export const TEMPERATURA_MIN = 0
export const TEMPERATURA_MAX = 2
export const PASO_TEMPERATURA = 0.05
export const TOP_P_MIN = 0
export const TOP_P_MAX = 1
export const PASO_TOP_P = 0.01

/** Errores de validación; lista vacía = el payload sería aceptado. */
export function validarConfigLLM(c: ConfigAValidar): string[] {
  const errores: string[] = []
  if (c.modelo.trim() === '') errores.push('modelo: no puede estar vacío')
  if (c.temperatura < TEMPERATURA_MIN || c.temperatura > TEMPERATURA_MAX) {
    errores.push(`temperatura: fuera de [${TEMPERATURA_MIN}, ${TEMPERATURA_MAX}]`)
  }
  if (c.topPActivado && (c.topP < TOP_P_MIN || c.topP > TOP_P_MAX)) {
    errores.push(`top_p: fuera de [${TOP_P_MIN}, ${TOP_P_MAX}]`)
  }
  if (c.maxTokensActivado && (!Number.isInteger(c.maxTokens) || c.maxTokens <= 0)) {
    errores.push('max_tokens: debe ser un entero > 0')
  }
  const disponibles = new Set(c.toolsDisponibles)
  const desconocidas = c.tools.filter((t) => !disponibles.has(t))
  if (desconocidas.length > 0) {
    errores.push(`tools fuera del registro: ${desconocidas.join(', ')}`)
  }
  return errores
}
