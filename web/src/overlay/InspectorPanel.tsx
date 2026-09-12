// Panel lateral de inspección y mutación (spec-red-3d §11): sincronizado con
// la selección 3D (selectionStore), tres pestañas — Agente (mutación §11.1),
// Estado (inspección en vivo §11.2) y Flujo (editor §11.3).

import { useState } from 'react'
import { useSelectionStore } from '../stores/selectionStore'
import { useProjectStore } from '../stores/projectStore'
import { COLOR_PROVEEDOR } from '../scene/colores'
import { LLMConfigForm } from './LLMConfigForm'

type Pestaña = 'agente'

function Fila({ etiqueta, children }: { etiqueta: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <span className="shrink-0 text-[10px] uppercase tracking-wider text-texto-suave">
        {etiqueta}
      </span>
      <span className="min-w-0 truncate text-right text-xs text-texto">{children}</span>
    </div>
  )
}

export function InspectorPanel() {
  const seleccionado = useSelectionStore((s) => s.seleccionado)
  const solicitarReencuadre = useSelectionStore((s) => s.solicitarReencuadre)
  const red = useProjectStore((s) => s.red)

  const [pestaña, setPestaña] = useState<Pestaña>('agente')
  const nodo = red?.nodes.find((n) => n.id === seleccionado) ?? null

  return (
    <aside className="absolute right-3 top-16 z-10 flex w-80 max-h-[calc(100%-5rem)] flex-col rounded-lg border border-borde/70 bg-panel/90 backdrop-blur">
      <div className="flex items-center gap-2 border-b border-borde/70 px-3 py-2">
        <h2 className="text-xs font-semibold tracking-wide text-texto">Inspector</h2>
        {nodo !== null && (
          <div className="flex gap-1">
            {(['agente'] as const).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setPestaña(p)}
                className={`rounded px-2 py-0.5 text-[10px] capitalize transition-colors ${
                  pestaña === p
                    ? 'bg-acento/20 text-acento'
                    : 'text-texto-suave hover:bg-panel-alto'
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        )}
        <button
          type="button"
          onClick={solicitarReencuadre}
          className="ml-auto rounded border border-borde px-2 py-0.5 text-[10px] text-texto-suave transition-colors hover:bg-panel-alto hover:text-texto"
          title="Volver a la vista general (Escape)"
        >
          Reencuadrar
        </button>
      </div>

      {nodo === null ? (
        <p className="px-3 py-4 text-xs text-texto-suave">
          Click en un nodo del grafo para inspeccionarlo. Doble click para enfocarlo.
        </p>
      ) : pestaña === 'agente' ? (
        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
          <div className="mb-2 flex items-center gap-2">
            {nodo.llm && (
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: COLOR_PROVEEDOR[nodo.llm.proveedor] }}
                title={nodo.llm.proveedor}
              />
            )}
            <h3 className="truncate text-sm font-semibold text-texto">
              {nodo.rol ?? nodo.id}
            </h3>
            <span className="ml-auto rounded border border-borde px-1.5 py-0.5 text-[9px] text-texto-suave">
              {nodo.tipo} · {nodo.fase}
            </span>
          </div>
          <p className="mb-3 text-[11px] leading-relaxed text-texto-suave">
            {nodo.descripcion}
          </p>

          {nodo.llm === null ? (
            <p className="text-[11px] text-texto-suave">
              Nodo estructural sin agente LLM (cierre del pipeline): no tiene
              configuración editable.
            </p>
          ) : (
            <LLMConfigForm nodo={nodo} onGuardado={() => undefined} />
          )}

          <details className="mt-3">
            <summary className="cursor-pointer text-[10px] uppercase tracking-wider text-texto-suave">
              Metadatos
            </summary>
            <div className="mt-1 divide-y divide-borde/40">
              <Fila etiqueta="nodo">{nodo.id}</Fila>
              <Fila etiqueta="estructural">{nodo.estructural ? 'sí' : 'no'}</Fila>
              <Fila etiqueta="esencial">{nodo.esencial ? 'sí' : 'no'}</Fila>
              {nodo.custom && (
                <Fila etiqueta="contrato">{nodo.custom.contrato}</Fila>
              )}
              {nodo.custom && (
                <Fila etiqueta="entradas">{nodo.custom.entradas.join(', ')}</Fila>
              )}
            </div>
          </details>
        </div>
      ) : (
        <p className="px-3 py-4 text-xs text-texto-suave">Pestaña en construcción.</p>
      )}
    </aside>
  )
}
