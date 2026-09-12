// Panel lateral de inspección (spec-red-3d §11): en la Fase 2 es de solo
// lectura — muestra los metadatos del nodo seleccionado (rol, tipo, fase,
// descripción, LLMConfig resuelto y custom si aplica). Las pestañas de
// mutación llegan en la Fase 6.

import { useSelectionStore } from '../stores/selectionStore'
import { useProjectStore } from '../stores/projectStore'
import { COLOR_PROVEEDOR } from '../scene/colores'

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

/** Metadatos del nodo seleccionado, sincronizado con la selección 3D (§9.6). */
export function InspectorPanel() {
  const seleccionado = useSelectionStore((s) => s.seleccionado)
  const solicitarReencuadre = useSelectionStore((s) => s.solicitarReencuadre)
  const red = useProjectStore((s) => s.red)

  const nodo = red?.nodes.find((n) => n.id === seleccionado) ?? null

  return (
    <aside className="absolute right-3 top-16 z-10 flex w-72 max-h-[calc(100%-5rem)] flex-col rounded-lg border border-borde/70 bg-panel/90 backdrop-blur">
      <div className="flex items-center justify-between border-b border-borde/70 px-3 py-2">
        <h2 className="text-xs font-semibold tracking-wide text-texto">Inspector</h2>
        <button
          type="button"
          onClick={solicitarReencuadre}
          className="rounded border border-borde px-2 py-0.5 text-[10px] text-texto-suave transition-colors hover:bg-panel-alto hover:text-texto"
          title="Volver a la vista general (Escape)"
        >
          Reencuadrar
        </button>
      </div>

      {nodo === null ? (
        <p className="px-3 py-4 text-xs text-texto-suave">
          Click en un nodo del grafo para inspeccionarlo. Doble click para enfocarlo.
        </p>
      ) : (
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
          </div>
          <p className="mb-3 text-[11px] leading-relaxed text-texto-suave">{nodo.descripcion}</p>

          <div className="divide-y divide-borde/40">
            <Fila etiqueta="nodo">{nodo.id}</Fila>
            <Fila etiqueta="tipo">{nodo.tipo}</Fila>
            <Fila etiqueta="fase">{nodo.fase}</Fila>
            <Fila etiqueta="estructural">{nodo.estructural ? 'sí' : 'no'}</Fila>
            <Fila etiqueta="esencial">{nodo.esencial ? 'sí' : 'no'}</Fila>
            {nodo.llm !== null && (
              <>
                <Fila etiqueta="proveedor">{nodo.llm.proveedor}</Fila>
                <Fila etiqueta="modelo">{nodo.llm.modelo}</Fila>
                <Fila etiqueta="temperatura">{nodo.llm.temperatura}</Fila>
                {nodo.llm.top_p !== undefined && <Fila etiqueta="top_p">{nodo.llm.top_p}</Fila>}
                {nodo.llm.max_tokens !== undefined && (
                  <Fila etiqueta="max_tokens">{nodo.llm.max_tokens}</Fila>
                )}
                <Fila etiqueta="tools">
                  {nodo.llm.tools.length > 0 ? nodo.llm.tools.join(', ') : '—'}
                </Fila>
              </>
            )}
          </div>

          {nodo.custom && (
            <div className="mt-3 rounded border border-borde/60 bg-panel-alto/60 p-2">
              <h4 className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-texto-suave">
                Agente custom
              </h4>
              <Fila etiqueta="contrato">{nodo.custom.contrato}</Fila>
              <Fila etiqueta="entradas">{nodo.custom.entradas.join(', ')}</Fila>
              <p className="mt-1 line-clamp-4 whitespace-pre-wrap text-[10px] leading-relaxed text-texto-suave">
                {nodo.custom.instrucciones}
              </p>
            </div>
          )}
        </div>
      )}
    </aside>
  )
}
