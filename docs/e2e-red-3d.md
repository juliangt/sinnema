# Recorrido e2e — red 3D (spec-red-3d §13, manual/visual)

Verificación de punta a punta del monitor 3D con `sinnema-server` + `web/`.
Los pasos automáticos (suites pytest y vitest) corren en el CI; este
recorrido cubre lo que solo se valida mirando: estados 3D en vivo, streaming
de tokens, mutación en caliente y disciplina de dispose.

## 0. Preparación

```bash
cd web && npm install && npm run build   # genera web/dist
cd .. && uv sync --extra dev
sinnema-server                           # http://127.0.0.1:8000
```

`GET /` debe mostrar la UI 3D ("Sinnema · red de agentes") con el proyecto
activo hidratado: nodos con geometría por tipo, halo del color del proveedor
y aristas curvas con flechas; las condicionales van discontinuas con su
label (`revise`, `approve`, `skip_chapter`…).

Requiere claves del proveedor en el entorno (`ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, …) según el proyecto elegido.

## 1. Re-hidratación sin fuga (dispose §8.3)

1. Alternar entre los 7 proyectos con el selector (p. ej. `comida` ↔
   `motores`) unas 10 veces.
2. Con las DevTools abiertas, verificar en consola (la app loguea
   `renderer.info.memory` en modo dev; alternativa: pestaña de memory) que
   geometrías/texturas vuelven al baseline tras cada cambio y que el contexto
   WebGL no se recrea (un solo `WebGLRenderingContext`).
3. Evidencia esperada: sin crecimiento sostenido de memoria entre
   alternancias; la escena remonta completa en cada proyecto.

## 2. Corrida seguida en la 3D (estados y pulsos §9.4–9.5)

1. Elegir un proyecto y presionar **Lanzar corrida** (panel Ejecución).
2. Seguir la secuencia: `plan_series` entra en *Processing* (respiración),
   pasa a *Done* (destello) y un pulso recorre la arista hacia el nodo de
   contexto; el capítulo enciende `scriptwriter` → *Streaming* (anillo con
   barrido radial) mientras llegan tokens; la compuerta `chief_critic`
   dictamina y, con `revise`, el ciclo de crítica vuelve al escritor (curva
   de retorno + pulso).
3. El timeline 2D del panel Ejecución debe listar los mismos eventos en el
   mismo orden (`node_start`/`node_end` por nodo, `progress` textual) y los
   contadores por kind al pie.
4. Evidencia esperada: la secuencia del timeline coincide con los estados
   visuales; sin saltos bruscos (todo interpolado).

## 3. Streaming de tokens y tools (§7)

1. Configurar `tools = ["buscar_lore"]` en un rol (p. ej. `scriptwriter`)
   antes de la corrida (inspector → Agente → Guardar).
2. Lanzar la corrida: durante el nodo con tools debe verse el halo ámbar y el
   glifo ⚙, con `tool_start`/`tool_end` en el timeline y el scratchpad de la
   pestaña Estado.
3. En la pestaña Estado, el bloque "Tokens en vivo" del nodo seleccionado
   debe ir creciendo (buffer que se reemplaza por chunks JSON del parcial).
4. Evidencia esperada: eventos `tool_*` con nodo/rol correctos y tokens
   visibles sin re-render de toda la escena.

## 4. Mutación en caliente y spec desfasado (§11.4)

1. Con un job **en curso**, cambiar proveedor/modelo/temperatura de un agente
   (inspector → Agente) y guardar.
2. Verificar: aviso persistente "Guardado: aplica a la próxima corrida", los
   halos/etiquetas de la escena reflejan el cambio al re-hidratar, y aparece
   el badge **spec congelado** sobre el job activo (`spec_desfasado`).
3. Al terminar la corrida, abrir auditoría (pestaña Estado → Artefactos →
   paso del agente mutado → Prompts): el job usó el proveedor/modelo
   anteriores; la próxima corrida usa los nuevos.
4. Evidencia esperada: el TOML (`proyectos/<id>.toml`) persiste el cambio;
   la auditoría demuestra el congelamiento.

## 5. Teclado/focus del overlay

1. Click en un nodo → click en **Reencuadrar**: la cámara vuelve a la vista
   general con suavizado.
2. `Escape` sin selección previa: mismo comportamiento.
3. Doble click en un nodo: primer plano conservando orientación.
4. Navegar el formulario con Tab: los controles son alcanzables y operables
   por teclado (sliders con flechas, checkboxes con espacio).

## 6. Sin build JS (degradación §12.3)

```bash
mv web/dist /tmp/web-dist && curl -s http://127.0.0.1:8000/ | grep "npm run build"
mv /tmp/web-dist web/dist
```

`GET /` muestra la página indicando cómo construir la UI; la API sigue
completa (`/docs`).
