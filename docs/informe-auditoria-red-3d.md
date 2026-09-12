# Informe de auditoría — red-3d: implementación vs spec v1

Fecha: 2026-09-12 · Alcance: `docs/spec-red-3d.md` §3–§14 contra el código en
`feature/red-3d-fase1` (Fases 1–6 implementadas). Cada sección mapea a sus
archivos y pruebas; todo desvío queda corregido (→ 7b) o documentado como
decisión aceptada.

## §3 Esquema TOML extendido — ✓ CONFORME

- `sinnema/application/projects.py`: `AgentConfig` con `top_p`/`max_tokens`/
  `tools`; validaciones 11–13 (rango `top_p`, `max_tokens > 0`, tools contra
  `TOOLS_INTEGRADAS`); la 14 documentada como no aplica.
- `sinnema/infrastructure/llm/providers.py`: `build_provider_model(provider,
  model, temperature, top_p=None, max_tokens=None)`; Ollama mapea
  `max_tokens → num_predict`; parámetros ausentes no se pasan.
- Pruebas: `tests/test_projects.py`, `tests/test_providers.py`.

## §4 Tipado TypeScript — ✓ CONFORME con 1 desvío (corregido en 7b)

- `web/src/types/index.ts` con todos los tipos del contrato.
- **Desvío D1** (menor, omisión): `Artifact.prompts` tipaba
  `{sistema, usuario}` pero la implementación devuelve el texto renderizado
  del archivo `NNN_<nodo>_prompts.txt`. Corregido: la spec pasa a `prompts?:
  string` (7b), que refleja la fuente real (§7.4).

## §5 API — ✓ CONFORME

`/red`, `/meta/catalogos`, `/jobs/{id}/artifacts[/{n}]`, `/events/history`,
SSE con `data` JSON, `PUT` con las claves nuevas, `spec_desfasado` en jobs —
todo operativo. Pruebas: `tests/test_api.py` (incluye cascada de servido,
artefactos, timeline, spec desfasado).

- Nota (aclaración, no desvío): `spec_desfasado` solo se expone en jobs
  `running` (§11.4 lo define para "job RUNNING"); en otros estados la clave
  no aparece.

## §6 Protocolo de eventos — ✓ CONFORME

- Migración idempotente con `PRAGMA table_info` (`job_events.payload`,
  `jobs.spec_fingerprint`); base vieja legible (test `test_migracion_sobre_base_vieja`).
- `add_event(job_id, kind, message, payload=None)` sin romper la firma legacy.
- Kinds §6.2 completos; SSE §6.3 con `id:`/`event: <kind>`/`data` JSON.
- **Desvío D2** (menor, decisión implícita): eventos legacy se serializan
  como `{"kind","job_id","ts","mensaje"}` (el message vive en `mensaje`,
  clave en español, coherente con el resto del dict TOML). Documentado en
  spec §6.3 (7b).

## §7 Streaming y tools — ✓ CONFORME con 1 desvío aceptado

- Puerto con `on_event` opcional (§12.2: CLI y tests sin editar ✓, suite
  verde en cada commit).
- Streaming con fallback a `invoke` si el proveedor no soporta stream
  estructurado (test `test_streaming_sin_soporte_cae_a_invoke`).
- `build_gateway(event_sink=…)` una vez por job; runner publica
  `token`/`tool_start`/`tool_end` al store.
- Tools `buscar_lore`/`leer_formato` con `@tool` sobre `JsonLoreStore` y
  `[formato]`; loop `bind_tools` con guard de 5 iteraciones fuera del
  `recursion_limit`.
- Auditoría §7.4: `NNN_<nodo>_prompts.txt` emparejado por NNN con su paso.
- **Desvío D3** (medio, decisión aceptada): el `texto` de cada evento
  `token` es el render JSON del objeto parcial acumulado (el cliente
  reemplaza el buffer), no deltas por carácter: la salida estructurada
  streamea objetos parciales, no texto plano. Documentado en §7.1 (7b).

## §8 Arquitectura frontend — ✓ CONFORME con renombres y 1 desvío aceptado

- Estructura §8.1 presente (`types/ api/ stores/ scene/ overlay/ hooks/`).
  **Desvío D4** (menor, decisión aceptada): nombres concretos difieren —
  `StateInspector → PanelEstado`, `FlowEditor → PanelFlujo`, `EventTimeline +
  JobsDrawer` integrados en `EjecucionPanel`. La spec lo registra (7b).
- Hidratación §8.2 por remount con `key` ✓; dispose §8.3 (`disposeObject3D`
  + cleanups, tests vitest) ✓.
- **Desvío D5** (medio, decisión aceptada — §2 "Reemplazo"): el fallback
  legacy `static/index.html` fue eliminado en la Fase 6d al completar la
  lista de paridad §12.3, en lugar de mantenerlo indefinido. Sin build JS,
  `GET /` sirve una página que indica cómo construir la UI y la API queda
  completa (`/docs`). Spec §8.4/§12.3 actualizadas (7b).

## §9 Canvas 3D — ✓ CONFORME con 1 simplificación aceptada

- Layout §9.1 determinista (función pura, snapshot test), geometrías/halos/
  etiquetas §9.2, aristas §9.3 (bezier, flechas, condicionales dash con
  labels), cámara §9.6 (OrbitControls + lerp + reencuadre + Escape).
- **Desvío D6** (menor, decisión aceptada): el flujo ambiental §9.4 siembra
  pulsos lentos sobre el tramo activo (últimos dos nodos del camino
  corriente) en lugar de recorrer todo el camino visitado. Visualmente
  equivalente en la práctica; documentado (7b).

## §10 Pipeline de sincronización — ✓ CONFORME

- `useExecutionSync` (EventSource + polling 2 s + consolidación de
  artefactos al terminar) y `executionStore` con dos niveles: reactivo (log
  circular, status, contadores) y mutable (estados por nodo, buffers de
  tokens, pulsos) leído en `useFrame` — una ráfaga de tokens no re-renderiza
  React (test vitest `token acumula… sin tocar el log reactivo`).
- **Desvío D7** (menor, decisión aceptada): el log circular excluye los
  eventos `token` (viven en el buffer por nodo y en los contadores) para que
  el timeline mantenga frecuencia de UI. Documentado (7b).

## §11 Inspector y mutación — ✓ CONFORME (D1 corregido en 7b)

- Pestaña Agente §11.1: formulario completo con validaciones espejo, `PUT`
  del dict completo, re-hidratación de `/red`, aviso persistente "aplica a
  la próxima corrida".
- Pestaña Estado §11.2 y pestaña Flujo §11.3 (reorder, revisor, `hasta`).
- `spec_desfasado` con badge "spec congelado" sobre el job activo.

## §12 Compatibilidad — ✓ CONFORME

ALTERs idempotentes ✓, puerto opcional ✓, reemplazo §12.3 ejecutado con
paridad completa (D5) ✓, wheel sin `web/` ✓ (force-include solo `proyectos`),
CLI sin cambios ✓.

## §14 Criterios de aceptación — evidencia

| Fase | Criterio | Evidencia |
|---|---|---|
| 1 | Round-trip TOML + LangChain + `/red` ≡ Mermaid | `tests/test_projects.py`, `tests/test_providers.py`, `tests/test_ver_grafo.py` |
| 2 | Re-hidratación sin fuga + selección + servido | vitest layout/dispose; `test_home_cascada_web_dist_o_sin_build`; `renderer.info` verificable en dev (disposeObject3D) |
| 3 | Timeline real con compuerta y ciclo + base vieja | `test_eventos_por_nodo_en_timeline`, `test_migracion_sobre_base_vieja` |
| 4 | Tools con eventos y tokens; sin tools/on_event tests intactos | `tests/test_gateway.py`, `tests/test_tools.py`, `test_tokens_del_stream_llegan_al_store` |
| 5 | Corrida punta a punta sin drops + timeline consistente | nivel escena mutable (§10) + pulsos; verificación visual e2e (Fase 8) |
| 6 | Mutación desde la 3D persiste y aplica a la próxima corrida | flujo de guardado §11.1 + `spec_desfasado`; verificación e2e (Fase 8) |

## Correcciones aplicadas en 7b

1. **D1**: spec §4 — `Artifact.prompts: string`.
2. **Instrucciones de customs editables** en `LLMConfigForm` (§11.1 pedía
   editor; estaban en solo lectura).
3. Spec §14: Fases 2–6 marcadas como implementadas con sus commits.
4. Documentación de las decisiones aceptadas D2–D7 en las secciones
   correspondientes.
