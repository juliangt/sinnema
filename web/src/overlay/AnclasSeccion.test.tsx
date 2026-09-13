// Tests de la sección "Anclas" del drawer (spec-recursos-ancla §9.2):
// render de tarjetas, alta, checklist de lock y smoke de drag & drop.
// La API se mockea: los tests no requieren servicio ni red.

// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { AnclasSeccion } from './AnclasSeccion'
import { useProjectStore } from '../stores/projectStore'
import { api } from '../api/client'
import type { Ancla, Catalogos } from '../types'

vi.mock('../api/client', () => ({
  api: {
    anclas: vi.fn(),
    crearAncla: vi.fn(),
    editarAncla: vi.fn(),
    retirarAncla: vi.fn(),
    subirImagen: vi.fn(),
    lockearAncla: vi.fn(),
  },
}))

;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true

const CATALOGOS: Catalogos = {
  proveedores: [],
  modelos: {} as Catalogos['modelos'],
  tools: [],
  hitos: [],
  tipos_custom: [],
  contratos: [],
  entradas_custom: [],
  anclas: {
    tipos: ['personaje', 'lugar', 'objeto', 'estilo'],
    estados: ['borrador', 'propuesto', 'lockeado', 'retirado'],
    roles_por_tipo: {
      personaje: ['hero_portrait', 'turnaround_front', 'turnaround_side', 'turnaround_back'],
      lugar: ['establishing_shot'],
      objeto: ['prop_hero'],
      estilo: ['style_reference'],
    },
    bateria_minima: {
      personaje: ['hero_portrait', 'turnaround_front', 'turnaround_side', 'turnaround_back'],
      lugar: ['establishing_shot'],
      objeto: ['prop_hero'],
      estilo: ['style_reference'],
    },
  },
}

function ancla(sobre: Partial<Ancla> = {}): Ancla {
  return {
    ancla_id: 'protagonista',
    tipo: 'personaje',
    nombre: 'Nita la guía',
    descripcion_canonica: 'A friendly young guide with short dark hair and teal jacket',
    estado: 'borrador',
    bateria: [],
    version: 1,
    ...sobre,
  }
}

function montar(): void {
  useProjectStore.setState({ proyectoActivo: 'mi-show', catalogos: CATALOGOS })
  render(<AnclasSeccion />)
}

beforeEach(() => {
  vi.mocked(api.anclas).mockResolvedValue([])
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.restoreAllMocks()
})

describe('AnclasSeccion', () => {
  it('renderiza el grid de tarjetas con tipo, estado, versión y miniaturas por rol', async () => {
    vi.mocked(api.anclas).mockResolvedValue([
      ancla({
        estado: 'lockeado',
        version: 3,
        bateria: [
          { rol: 'hero_portrait', archivo: 'hero_portrait_1.png', origen: 'subida' },
          { rol: 'hero_portrait', archivo: 'hero_portrait_2.png', origen: 'subida' },
        ],
      }),
    ])
    montar()

    const tarjeta = await screen.findByTestId('ancla-protagonista')
    expect(within(tarjeta).getByText('Nita la guía')).toBeTruthy()
    expect(within(tarjeta).getByText('personaje')).toBeTruthy()
    expect(within(tarjeta).getByText('lockeado')).toBeTruthy()
    expect(within(tarjeta).getByText('v3')).toBeTruthy()
    // Miniaturas agrupadas por rol, con el nombre del servidor en la URL.
    const miniaturas = within(tarjeta).getAllByRole('img')
    expect(miniaturas).toHaveLength(2)
    expect(miniaturas[0].getAttribute('src')).toContain(
      '/api/projects/mi-show/anclas/protagonista/imagenes/hero_portrait_1.png',
    )
  })

  it('da de alta un ancla y refresca la biblioteca', async () => {
    vi.mocked(api.crearAncla).mockResolvedValue(ancla())
    montar()

    fireEvent.change(await screen.findByPlaceholderText('id (nita)'), {
      target: { value: 'nita' },
    })
    fireEvent.change(screen.getByPlaceholderText('nombre visible'), {
      target: { value: 'Nita la guía' },
    })
    fireEvent.change(
      screen.getByPlaceholderText(/descripcion_canonica EN inglés/),
      { target: { value: 'A friendly young guide with short dark hair' } },
    )
    fireEvent.click(screen.getByText('Crear ancla'))

    await waitFor(() => {
      expect(api.crearAncla).toHaveBeenCalledWith('mi-show', {
        ancla_id: 'nita',
        tipo: 'personaje',
        nombre: 'Nita la guía',
        descripcion_canonica: 'A friendly young guide with short dark hair',
      })
    })
    await waitFor(() => expect(api.anclas).toHaveBeenCalledTimes(2))
  })

  it('muestra el checklist de batería mínima y deshabilita el lock hasta cumplirla', async () => {
    vi.mocked(api.anclas).mockResolvedValue([
      ancla({ bateria: [{ rol: 'hero_portrait', archivo: 'hero_portrait_1.png', origen: 'subida' }] }),
      ancla({
        ancla_id: 'look-principal',
        tipo: 'estilo',
        nombre: 'Look principal',
        descripcion_canonica: 'A clean isometric 3D style with pastel palette and soft light',
        bateria: [{ rol: 'style_reference', archivo: 'style_reference_1.png', origen: 'subida' }],
      }),
    ])
    vi.mocked(api.lockearAncla).mockResolvedValue(ancla({ estado: 'lockeado' }))
    montar()

    const incompleta = await screen.findByTestId('ancla-protagonista')
    const lockIncompleto = within(incompleta).getByText('Lock')
    expect((lockIncompleto as HTMLButtonElement).disabled).toBe(true)
    // Checklist: el rol presente marca ✓; los faltantes aparecen listados.
    expect(within(incompleta).getByText('✓ hero_portrait')).toBeTruthy()
    expect(within(incompleta).getByText('○ turnaround_front')).toBeTruthy()

    const completa = screen.getByTestId('ancla-look-principal')
    const lockCompleto = within(completa).getByText('Lock')
    expect((lockCompleto as HTMLButtonElement).disabled).toBe(false)
    fireEvent.click(lockCompleto)
    await waitFor(() => expect(api.lockearAncla).toHaveBeenCalledWith('mi-show', 'look-principal'))
  })

  it('sube imágenes por drag & drop con el rol elegido', async () => {
    vi.mocked(api.anclas).mockResolvedValue([
      ancla({ bateria: [{ rol: 'hero_portrait', archivo: 'hero_portrait_1.png', origen: 'subida' }] }),
    ])
    vi.mocked(api.subirImagen).mockResolvedValue(ancla())
    montar()

    const tarjeta = await screen.findByTestId('ancla-protagonista')
    const selector = within(tarjeta).getByLabelText('rol de subida de protagonista')
    fireEvent.change(selector, { target: { value: 'turnaround_side' } })

    const zona = screen.getByTestId('zona-subida-protagonista')
    const archivo = new File(['bytes'], 'lado.png', { type: 'image/png' })
    fireEvent.dragOver(zona)
    fireEvent.drop(zona, { dataTransfer: { files: [archivo] } })

    await waitFor(() => {
      expect(api.subirImagen).toHaveBeenCalledWith('mi-show', 'protagonista', 'turnaround_side', archivo)
    })
  })

  it('retira con confirmación (no borra) y cancela sin llamar a la API', async () => {
    vi.mocked(api.anclas).mockResolvedValue([ancla()])
    vi.mocked(api.retirarAncla).mockResolvedValue({
      project_id: 'mi-show', ancla_id: 'protagonista', estado: 'retirado', retirado: true,
    })
    const confirmar = vi.spyOn(window, 'confirm')
    montar()

    const tarjeta = await screen.findByTestId('ancla-protagonista')

    confirmar.mockReturnValue(false)
    fireEvent.click(within(tarjeta).getByText('Retirar'))
    expect(api.retirarAncla).not.toHaveBeenCalled()

    confirmar.mockReturnValue(true)
    fireEvent.click(within(tarjeta).getByText('Retirar'))
    await waitFor(() => expect(api.retirarAncla).toHaveBeenCalledWith('mi-show', 'protagonista'))
  })
})

  it('muestra el badge de QA medio de la tarjeta cuando hay muestras (Fase 4)', async () => {
    vi.mocked(api.anclas).mockResolvedValue([
      ancla({ estado: 'lockeado', qa_medio: 0.41, qa_muestras: 3 }),
      ancla({ ancla_id: 'degradada', nombre: 'Villano', qa_medio: 0.12, qa_muestras: 2 }),
      ancla({ ancla_id: 'sin-qa', nombre: 'Sin QA' }),
    ])
    montar()

    const buena = await screen.findByTestId('ancla-protagonista')
    expect(within(buena).getByText('QA 0.41')).toBeTruthy()
    const degradada = screen.getByTestId('ancla-degradada')
    expect(within(degradada).getByText('QA 0.12')).toBeTruthy()
    // Sin muestras de QA: la tarjeta no lleva badge.
    expect(within(screen.getByTestId('ancla-sin-qa')).queryByText(/QA \d/)).toBeNull()
  })
