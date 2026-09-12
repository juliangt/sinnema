// Validaciones del formulario LLMConfig (§13: formularios con rangos espejo
// del backend §3).

import { describe, expect, it } from 'vitest'
import { validarConfigLLM } from './validaciones'

const base = {
  modelo: 'gpt-4o',
  temperatura: 0.8,
  topPActivado: false,
  topP: 1,
  maxTokensActivado: false,
  maxTokens: 4096,
  tools: [],
  toolsDisponibles: ['buscar_lore', 'leer_formato'],
}

describe('validarConfigLLM', () => {
  it('acepta una configuración válida', () => {
    expect(validarConfigLLM(base)).toEqual([])
  })

  it('rechaza modelo vacío', () => {
    const errores = validarConfigLLM({ ...base, modelo: '  ' })
    expect(errores).toContain('modelo: no puede estar vacío')
  })

  it('rechaza temperatura fuera de [0, 2]', () => {
    expect(validarConfigLLM({ ...base, temperatura: 2.05 })).toContain(
      'temperatura: fuera de [0, 2]',
    )
    expect(validarConfigLLM({ ...base, temperatura: -0.05 })).toContain(
      'temperatura: fuera de [0, 2]',
    )
  })

  it('rechaza top_p fuera de [0, 1] solo si está activado', () => {
    expect(validarConfigLLM({ ...base, topPActivado: true, topP: 1.01 })).toContain(
      'top_p: fuera de [0, 1]',
    )
    // Desactivado = no se envía: el valor ignorado no invalida.
    expect(validarConfigLLM({ ...base, topPActivado: false, topP: 42 })).toEqual([])
  })

  it('rechaza max_tokens no entero o ≤ 0 solo si está activado', () => {
    expect(validarConfigLLM({ ...base, maxTokensActivado: true, maxTokens: 0 })).toContain(
      'max_tokens: debe ser un entero > 0',
    )
    expect(validarConfigLLM({ ...base, maxTokensActivado: true, maxTokens: 3.5 })).toContain(
      'max_tokens: debe ser un entero > 0',
    )
    expect(validarConfigLLM({ ...base, maxTokensActivado: false, maxTokens: 0 })).toEqual([])
  })

  it('rechaza tools fuera del registro con la lista disponible', () => {
    const errores = validarConfigLLM({
      ...base,
      tools: ['buscar_lore', 'navegar_web'],
    })
    expect(errores).toEqual(['tools fuera del registro: navegar_web'])
  })
})
