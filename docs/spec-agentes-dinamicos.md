# Spec — Agentes dinámicos: flujo y alcance por proyecto

Estado: **v1 (propuesta)** · Fecha: 2026-08-30 · Sucede a: `spec-gestion-web.md` (la extiende, no la reemplaza)

## 1. Objetivo

Que cada proyecto (show) defina **qué agentes participan de su pipeline, en qué
orden y hasta dónde llega**, sin tocar código. Tres grados de libertad sobre el
mismo núcleo:

1. **Registro de agentes** (código): añadir un agente nuevo deja de tocar 7
   archivos y pasa a ser 1 definición + 1 módulo de prompts.
2. **Flujo por proyecto** (TOML `[flujo]`): qué agentes usa este show y en qué
   orden dentro de cada fase del capítulo.
3. **Alcance por proyecto** (TOML `[flujo].hasta`): dónde corta la cadena —
   p. ej. un show que entrega **solo el guion final** (sin specs de video) y
   otro que llega **hasta el prompt final de producción** (comportamiento
   actual), o incluso uno que solo planifica la serie.

**Principios rectores** (heredados del sistema):

- Los archivos TOML siguen siendo la única fuente de verdad; el pipeline carga
  el spec al arrancar cada corrida.
- Ningún artefacto de un LLM circula sin contrato validado. La dinámica es de
  **composición**, nunca de ejecución arbitraria: la semántica de cada nodo la
  fija su `tipo` en el registro, no el TOML.
- La topología sigue siendo auditable y acotada: el límite de recursión se
  calcula desde el flujo resuelto del proyecto.
- Todo proyecto existente sigue siendo válido sin cambios y produce exactamente
  lo mismo que hoy (compatibilidad estricta en Fase 0/1).

## 2. Registro de agentes (código)

### 2.1 `AgentDefinition`

Un único objeto declarativo en `application` consolida lo que hoy vive esparcido
(constantes + `ROLE_SCHEMAS` + catálogo de prompts + `ROLES_CONFIGURABLES` +
nodo del grafo + `RoleSpec`):

```python
@dataclass(frozen=True)
class AgentDefinition:
    rol: str                      # "scriptwriter", "fact_checker", ...
    tipo: TipoAgente              # ver 2.2
    esquema: Type[BaseModel]      # contrato que devuelve
    prompts: PromptModule         # build_system_prompt / build_user_message
    consume: Tuple[str, ...]      # slots del estado que lee
    produce: str                  # slot donde escribe
    validadores: Tuple[Callable, ...]  # validación de dominio post-generación
    nodo: str                     # nombre de nodo del grafo (estable p/ checkpointer)
    esencial: bool = False        # no se puede omitir del flujo
    descripcion: str = ""         # para GET /api/meta/roles y la web
```

Catálogo: `AGENT_REGISTRY: Dict[str, AgentDefinition]` en
`sinnema/application/registry.py` (nuevo). Los seis roles actuales se migran a
definiciones conservando sus nombres de nodo (`persona_adapter`, `chief_critic`,
...) para no romper threads de jobs en curso.

### 2.2 Tipos de agente y fases del capítulo

El `tipo` fija cómo se enchufa cada agente al grafo. El capítulo tiene cinco
fases en orden fijo (la semántica del pipeline no se negocia por TOML):

| Tipo | Fase | Qué hace | Equivalente hoy |
|---|---|---|---|
| `contexto` | pre-escritura | Produce notas/directivas que informan al escritor | `continuity` |
| `escritor` | escritura | Produce el guion canónico; **destino del feedback** de la compuerta | `scriptwriter` |
| `transformador` | transformación | Consume el guion vigente y produce una versión nueva | `adapter` |
| `revisor` | compuerta | Aprueba o devuelve feedback al escritor | `critic` |
| `enriquecedor` | post-aprobación | Añade adjuntos al episodio (specs, assets) | `technical_director` |

Invariantes por capítulo: **exactamente un `escritor`** (estructural) y **a lo
sumo un `revisor`** (sin compuerta = aprobación directa, episodios sin score —
semántica ya existente). `contexto`, `transformador` y `enriquecedor` son
encadenables en el orden declarado. A nivel de serie: `planner` es el único
agente de serie y es estructural.

### 2.3 Defaults LLM

`DEFAULT_ROLE_SPECS` (`infrastructure/llm/providers.py`) pasa a resolverse por
rol contra el registro, con un default genérico para roles sin asignación
(`openai` / `gpt-4o-mini` / `0.3`). La precedencia se mantiene:
**proyecto `[agentes.<rol>]` > entorno > default**. El registro vive en
`application` (no conoce proveedores); `providers.py` sigue siendo el único
módulo que sabe de paquetes LangChain concretos.

## 3. Estado: slots canónicos + pizarra

`PipelineState` generaliza sus artefactos de capítulo:

- **Slots canónicos** (los que la estructura necesita):
  `series_plan`, `guion_actual` (el artefacto de guion vigente, del tipo que
  sea — hoy el crítico ya consume "el último"), `guion_base` (la salida del
  escritor, para que `commit` conserve el borrador original),
  `continuity_directives`, `qa_verdict`.
- **Pizarra genérica**: `artefactos: Annotated[Dict[str, BaseModel],
  fusionar_por_clave]` — todo lo demás: adjuntos de enriquecedores, notas de
  agentes custom. Reducer de fusión por clave (no append): cada agente escribe
  su slot y gana el último.

Fase de transición: en Fase 0/1 las claves actuales (`draft_script`,
`adapted_script`, `technical_package`) se mantienen como alias de los slots
nuevos para que los tests y el checkpointer no rompan; la migración interna es
mecánica.

## 4. Flujo por proyecto — `[flujo]`

Sección **opcional** del TOML del proyecto. Sin ella: topología actual
(los seis roles, en el orden de hoy, menos los desactivados por
`activo = false` — semántica legacy de `spec-gestion-web.md` preservada).

```toml
[flujo]
contexto        = ["continuity"]                # fase pre-escritura, en orden
transformaciones = ["fact_checker", "adapter"]  # tras el escritor, en orden
revisor          = "critic"                     # opcional (sin él: aprobación directa)
enriquecimiento  = ["technical_director"]       # post-aprobación, en orden
hasta            = "produccion"                 # alcance (ver §5)
```

Reglas:

- `scriptwriter` y `planner` no se listan: son estructurales y siempre están.
- Un rol puede aparecer **una sola vez** en todo el flujo.
- Roles desconocidos → error con la lista de disponibles (del registro).
- Si el proyecto declara `[flujo]`, la participación en la lista es la fuente
  de verdad y `activo` queda obsoleto para ese proyecto: `activo = false` en
  un rol listado → error accionable ("quítalo del flujo"); `activo` en roles
  no listados se ignora.
- Si el proyecto declara `[flujo]` sin alguna clave de fase, esa fase queda
  vacía (p. ej. sin `revisor` ni `enriquecimiento`).

## 5. Alcance por proyecto — `hasta`

Define **el último hito del pipeline que este proyecto alcanza**. Vocabulario
cerrado de hitos, alineado con las fases del capítulo:

| Hito | Qué corre por capítulo | Qué entrega | Caso de uso |
|---|---|---|---|
| `plan` | nada (solo el planner, a nivel de serie) | Plan de serie con capítulos y curva | "modo outline": validar la idea antes de gastar en guiones |
| `guion` | contextos → escritor | Borradores (`ScriptDraft`) por capítulo | guion puro, sin reescrituras |
| `guion_final` | contextos → escritor → transformaciones | Guion final listo para producir, **sin specs de video** | **"todo el script sin llegar al video, sin prompt de imagen"** |
| `auditado` | ... → revisor | Guion final + dictamen/score | series con control de calidad pero sin producción |
| `produccion` | ... → enriquecedores | Paquete completo con prompts finales de imagen/video | **comportamiento actual** ("solo el prompt final", sin render) |

Semántica:

- `hasta` **trunca** el flujo del capítulo en el hito indicado. Los agentes
  declarados más allá del hito no corren (permitido: el flujo puede declararse
  completo y compartirse entre shows; la UI muestra siempre el **flujo
  efectivo** resultante).
- Default: `produccion` (= hoy).
- Coherencia: `hasta = "auditado"` con flujo sin `revisor` → error
  ("el hito auditado exige declarar revisor"). `guion_final` con cero
  transformaciones es válido (≡ `guion`).
- El hito queda **congelado por job**: el worker ya carga el spec al arrancar;
  editar `hasta` aplica a la próxima corrida.
- El lore solo crece si hay capítulos (un `plan` no toca la memoria).
- La compuerta exhausta aplica igual en `auditado`+`produccion`
  (`force_accept` / `skip_chapter`, sin cambios).

## 6. Construcción del grafo

### 6.1 Fábrica genérica de nodos

`graph.py` deja de escribir nodos a mano. Un nodo por definición:

```python
def make_agent_node(definicion, project, system_prompt, audit) -> Callable:
    def node(state):
        entradas = {slot: state.get(slot) for slot in definicion.consume}
        mensaje = definicion.prompts.build_user_message(project, **entradas)
        artefacto = gateway.generate(definicion.rol, definicion.esquema, ...)
        for validar in definicion.validadores:
            validar(artefacto, ...)
        audit.log_step(definicion.rol, ...)
        return {definicion.produce: artefacto}
    return node
```

Los nodos **estructurales quedan escritos a mano** (son semántica del
pipeline, no agentes): `plan_series`, `commit_episode`, `fail_chapter`, y la
compuerta de revisión (el nodo del `revisor` + su arista condicional
revise/approve/skip).

### 6.2 Topología resuelta

`build_pipeline_graph(gateway, project, ...)` resuelve el flujo
(composición + corte por `hasta`) y cablea:

```text
START → plan_series
      → [contexto]* → escritor → [transformacion]*
      → (revisor: revise→escritor | approve | skip→fail_chapter)?
      → [enriquecedor]* → commit_episode
commit_episode / fail_chapter → siguiente capítulo | END
```

Con `hasta = "plan"`: `START → plan_series → END` (commit final consolida un
entregable sin episodios).

### 6.3 Límite de recursión

La fórmula actual (`use_cases.py:82`) se generaliza desde el flujo efectivo:

```text
pasos_por_capitulo = len(contextos) + 1 + len(transformaciones)
                   + (1 si revisor) + len(enriquecedores) + 1  # commit
extra_por_reintento = 1 + len(transformaciones) + 1            # escritor→...→revisor
limite = 10 + num_chapters * pasos_por_capitulo
       + num_chapters * (attempts + 1) * extra_por_reintento
```

El flujo resuelto (y el límite) se calculan una vez por corrida y quedan
registrados en auditoría paso "solicitud".

## 7. Commit, entregable y visor

### 7.1 `commit_episode` generalizado

- **Guion final**: el artefacto de `guion_actual` al momento del commit. Si no
  corrieron transformaciones, se aplica **adaptación identidad** (patrón ya
  existente: `identity_adaptation`) para construir las escenas finales desde el
  borrador.
- **Adjuntos**: los artefactos de `enriquecedores` marcados como integrables
  viajan en el episodio. `ApprovedEpisode` gana `adjuntos:
  List[ArtefactoAdjunto]` donde `ArtefactoAdjunto = {rol: str, artefacto:
  dict}` (JSON). `technical` y `audit` se mantienen como campos propios
  (compatibilidad) y además figuran en `adjuntos` cuando existen.

### 7.2 `SeriesDeliverable` v1.1

- `schema_version` pasa a `"1.1"`; se añade `alcance: Literal["plan",
  "guion", "guion_final", "auditado", "produccion"]`.
- Con `alcance = "plan"`: `episodes = []` es válido (las invariantes actuales
  ya lo permiten: 0 episodios ≤ total planificado; `average_quality_score`
  0.0 sin auditorías).
- `failed_chapters` solo puede existir con `alcance` ≥ `auditado` (nuevo
  chequeo de coherencia: si hay fallos, hubo compuerta).

### 7.3 Visor HTML y auditoría

- El viewer muestra el badge de alcance (`plan` / `guion` / `guion final` /
  `auditado` / `producción`) y omite los bloques sin artefacto (mismo patrón
  que `sin auditoría`).
- Los adjuntos se renderizan como acordeones JSON por rol.
- La pista de auditoría registra el flujo efectivo y el hito en el paso
  inicial, y cada nodo loguea su rol.

## 8. Agentes custom desde el TOML (Fase 2)

Objetivo: crear agentes nuevos **desde la web sin deploy**, con límites
honestos. Extensión de `[agentes.<rol>]`:

```toml
[agentes.fact_checker]
instrucciones = """Eres el verificador de datos de "{marca}". Cada afirmación
del guion debe tener origen verificable..."""   # system prompt base del agente
tipo          = "contexto"        # contexto | revisor | enriquecedor (MVP)
entradas      = ["capitulo", "guion_actual", "lore"]   # bloques del contexto
contrato      = "notas"           # contrato genérico (ver abajo)
# proveedor / modelo / temperatura / reglas: ya existen hoy
```

- El flujo referencia al rol igual que a uno de código (`contexto =
  ["continuity", "fact_checker"]`).
- **Contratos genéricos predefinidos** (validados como cualquier Pydantic):
  - `notas`: `{nota_principal: str, puntos_clave: List[str]}` — para
    `contexto`/`enriquecedor`.
  - `dictamen`: `{aprobado: bool, score: int 0-10, hallazgos: List[str],
    feedback: str}` — único contrato permitido para `tipo = "revisor"`: la
    compuerta depende de esa semántica.
  - `texto`: `{contenido: str}` — el más simple.
- El mensaje de usuario se compone renderizando los bloques de `entradas`
  (mismo formato de bloques etiquetados que usan los prompts de código hoy).
- `instrucciones` admite placeholders del spec (`{marca}`, `{audiencia}`,
  `{tono}`, ...) + el bloque `REGLAS ADICIONALES` existente.
- **Límites documentados**: sin validación cruzada de dominio (solo el
  contrato genérico), sin `tipo = "escritor"` ni `"transformador"` (requieren
  contratos de guion tipados — se quedan en código), longitud máxima de
  `instrucciones` (2000 chars).

## 9. Validaciones (todas se reportan juntas, al cargar el proyecto)

De flujo:

1. Rol desconocido en cualquier fase → error con los roles del registro.
2. Rol repetido entre fases → error.
3. `activo = false` en rol listado en `[flujo]` → error ("quítalo del flujo").
4. Rol esencial ausente (`planner`, `scriptwriter` — estructurales, no se
   listan) → no aplica por construcción; se valida en resolución.

De alcance:

5. `hasta` fuera del vocabulario → error con la lista y el default.
6. `hasta = "auditado"` (o superior) sin `revisor` declarado → error.
7. `hasta` por debajo de una fase declarada → **válido** (trunca); la
   resolución expone el flujo efectivo (web/auditoría/preview).

De agentes custom (Fase 2):

8. `tipo` fuera de {contexto, revisor, enriquecedor} → error.
9. `contrato` incompatible con `tipo` (p. ej. revisor sin `dictamen`) → error.
10. `instrucciones` vacía o > 2000 chars, `entradas` fuera del catálogo de
    bloques, placeholders desconocidos → error.

## 10. API y UI

API:

| Método y ruta | Cambio |
|---|---|
| `GET /api/meta/roles` | Lee el registro: `rol`, `tipo`, `descripcion`, `esencial`, defaults LLM, `custom` (si viene del TOML) |
| `GET /api/projects/{id}` | Incluye `[flujo]` y `hasta` en la forma cruda |
| `POST/PUT /api/projects` | Validación de flujo/alcance/custom junto al resto (400 con la lista completa) |
| `GET /api/projects/{id}/flujo-efectivo` | **Nuevo**: fases resueltas + hito + diagrama Mermaid (reusa `ver_grafo.py`) + límite de recursión estimado |

UI (pestaña Proyectos):

- Editor de **flujo**: listas ordenables por fase (drag & drop simple) con los
  roles del registro, selector de revisor, y selector de **alcance** con
  descripción de cada hito.
- **Preview de topología**: render Mermaid del flujo efectivo, con los nodos
  cortados por `hasta` en gris.
- Fase 2: creación de agentes custom desde el formulario (instrucciones,
  tipo, contrato, entradas) con los mismos validadores que el backend.
- La pestaña Generar muestra el alcance del proyecto elegido antes de lanzar.

## 11. Compatibilidad y migración

- **Proyectos existentes**: sin `[flujo]` → topología actual menos
  desactivados. Output idéntico al de hoy (criterio de aceptación de Fase 1).
- **Checkpointer**: nombres de nodo estables (los actuales se conservan;
  agentes nuevos usan su `rol`). Un job congela flujo+alcance al arrancar;
  editar el TOML durante una corrida no la afecta (ya documentado en
  `spec-gestion-web.md` §8). Reanudar un thread tras cambiar el flujo del
  proyecto queda fuera de garantía (se documenta; opcional: el job store
  guarda el flujo congelado para diagnóstico).
- **Deliverable 1.0 → 1.1**: campo nuevo `alcance` y `adjuntos`; consumidores
  estrictos de 1.0 deben tolerar el bump (se avisa en el CHANGELOG/README).
- **CLI**: `--hasta` opcional en `python main.py` para sobreescribir el hito
  por corrida (precedencia: flag > proyecto > `produccion`), mismo patrón que
  `-m` con `intentos_maximos_de_critica`.

## 12. Pruebas

- **Registro**: catálogo completo, un agente por tipo, wiring gateway↔registro
  (roles desconocidos, esquema intercambiado — migra los casos actuales de
  `test_gateway.py`/`test_providers.py`).
- **Resolución de flujo**: matriz de `[flujo]` válidos/inválidos (las 10
  validaciones de §9), truncado por `hasta`, semántica legacy sin `[flujo]`.
- **Grafo**: topología efectiva por configuración (nodos y aristas),
  identidad de nodos con la topología actual (Fase 0), límite de recursión
  calculado.
- **Pipeline completo** (gateway falso, ya existente): corrida por cada hito
  (`plan` sin episodios, `guion` con adaptación identidad, `produccion`
  completo), revisor ausente, agentes custom en cada tipo permitido.
- **Dominio**: `SeriesDeliverable` 1.1 (alcance coherente con fallos/adjuntos),
  `ArtefactoAdjunto`, invariantes intactas.
- **Infra/web**: API de flujo-efectivo, CRUD de proyectos con `[flujo]`,
  worker con flujo congelado, `ver_grafo diagrama` por proyecto.

## 13. Plan de desarrollo

Rama: `feature/agentes-dinamicos`. Cada fase = PR(s) independables con la
suite verde y README/spec actualizados.

### Fase 0 — Registro y fábrica (refactor, cero cambio de comportamiento) — **IMPLEMENTADA** ✓

1. `sinnema/application/registry.py`: `AgentDefinition`, `TipoAgente`,
   `AGENT_REGISTRY` con los 6 roles actuales (nodos y slots actuales),
   validación de wiring al importar y helper `capitulo_actual`.
2. `graph.py`: `make_agent_node` genera los nodos de
   continuity/scriptwriter/adapter/director desde el registro; quedan a mano
   `plan_series`, la compuerta `chief_critic`, `commit_episode` y
   `fail_chapter` (semántica estructural del pipeline).
3. `prompts/__init__.py` delega `build_role_system_prompts` en el registro
   (import diferido para evitar el ciclo registro → prompts → projects);
   `ver_grafo.py` arma `ROL_NODO` desde el registro.
4. Tests: `tests/test_registry.py` nuevo (catálogo, tipos, fábrica); la suite
   preexistente pasó sin ninguna edición.

**Desviaciones registradas** (por el ciclo de imports `projects → registry →
prompts → projects`): `ROLE_SCHEMAS` permanece en `ports.py` y
`ROLES_CONFIGURABLES` en `projects.py`, ambos pinneados por test contra el
registro (`test_el_registro_cubre_exactamente_los_roles_conocidos`); su
consolidación definitiva ocurre en Fase 1 junto con `FlowSpec`. El gateway y
`providers.py` no cambiaron: consumen los catálogos pinneados.

**Criterio de aceptación — verificado**: suite completa verde (302 tests, la
preexistente sin ediciones); el diagrama Mermaid de `ver_grafo.py` es byte a
byte idéntico al capturado antes del refactor; añadir un agente nuevo toca
definición (registro) + prompts + contrato de dominio.

### Fase 1 — Flujo y alcance por proyecto

1. `projects.py`: parseo/validación de `[flujo]` (composición + `hasta`) y
   `FlowSpec` resuelto (fases efectivas, semántica legacy sin `[flujo]`).
2. `state.py`: slots canónicos + pizarra (alias de compatibilidad).
3. `graph.py`/`use_cases.py`: builder desde `FlowSpec`, límite de recursión
   dinámico, `hasta = "plan"` sin bucle de capítulos.
4. Dominio: `identity_adaptation` generalizada, `ArtefactoAdjunto`,
   `SeriesDeliverable` 1.1 con `alcance`, coherencia fallos↔alcance.
5. Infra: CLI `--hasta`, worker/gateway con roles efectivos, auditoría del
   flujo, viewer con badges/adjuntos.
6. API/UI: `flujo-efectivo`, editor de flujo + selector de alcance + preview.

PRs sugeridos: **1a** núcleo (1–4), **1b** CLI/worker/viewer (5), **1c** API/UI (6).

**Criterio de aceptación**: proyecto sin `[flujo]` produce entregable 1.1
idéntico en contenido al 1.0 de hoy (salvo version/alcance); proyecto con
`hasta = "guion_final"` entrega series sin specs de video validadas de punta a
punta; `hasta = "plan"` entrega outline sin episodios.

### Fase 2 — Agentes custom desde TOML/web

1. Contratos genéricos (`notas`, `dictamen`, `texto`) y render de bloques de
   contexto.
2. `[agentes.<rol>]` extendido: `instrucciones`, `tipo`, `entradas`,
   `contrato` + validaciones (§9.7–10).
3. Nodos custom en el builder; defaults LLM genéricos para roles custom.
4. UI: creación/edición de agentes custom + inserción en el editor de flujo.

**Criterio de aceptación**: un agente `fact_checker` creado 100% desde la web
(rol custom `contexto` con contrato `notas`) corre en un show real y su
artefacto queda en auditoría y en el flujo efectivo.

## 14. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Complejidad explode (grafo arbitrario) | Fases de orden fijo + tipos cerrados; lo dinámico es composición, no topología libre |
| Checkpointer roto por renombre de nodos | Nombres actuales congelados; flujo congelado por job |
| Recursion limit desajustado con flujos largos | Fórmula derivada del flujo efectivo + test de límite por configuración |
| Entregables heterogéneos confunden a consumidores | `alcance` en el deliverable + badges en viewer + CHANGELOG del bump 1.1 |
| Calidad sin control en custom agents | Contratos genéricos cerrados; revisor custom limitado a `dictamen`; sin escritor/transformador custom en MVP |
| Doble fuente de verdad (`activo` vs `[flujo]`) | Regla clara: con `[flujo]`, la lista manda; error accionable si conflitan |

## 15. Fuera de alcance

Topología libre con ciclos arbitrarios, múltiples compuertas por capítulo,
fan-out/fan-in de agentes en paralelo, votación de revisores, agentes custom
de tipo `escritor`/`transformador`, herramientas externas por agente (search,
código), render real de video (el pipeline sigue terminando en prompts/entregable
JSON), y ejecución de código definido en TOML.
