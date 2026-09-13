# Recorrido e2e — recursos ancla (spec-recursos-ancla §13-Fase 5, manual/E2E)

Verificación de punta a punta del escenario objetivo (§1): un personaje
lockeado en el capítulo 1 reaparece visualmente consistente en los capítulos
siguientes **y en una corrida posterior**; su keyframe aprobado, promocionado
a batería, mejora el QA de la segunda corrida. Los pasos automáticos (suites
pytest y vitest) corren en el CI; este recorrido cubre el circuito completo
con `sinnema-server` reales (biblioteca → corrida con media → QA → promoción
→ casting asistido → segunda corrida).

## 0. Preparación

```bash
uv sync --extra server --extra media --extra qa
export GEMINI_API_KEY="..."            # o OPENAI_API_KEY con proveedor_imagen="openai"
sinnema-server                         # http://127.0.0.1:8000
cd web && npm install && npm run build # UI 3D con el nodo media (opcional)
```

El extra `media` trae los SDK de imagen (`google-genai`, `openai`); el extra
`qa` trae los extractores del QA visual (`insightface`, `onnxruntime`). Sin
`qa` la corrida funciona y los keyframes viajan con `qa: []` ("QA no corrió").

El proyecto de este recorrido se crea por API (TOML equivalente: clave
`anclas` en `[visual]`, default `true`, y sección `[media]`):

```bash
curl -s -X POST http://127.0.0.1:8000/api/projects -H 'Content-Type: application/json' -d '{
  "proyecto": {
    "id": "aventura", "marca": "Aventura",
    "concepto": "micro-videos de aventura verticales",
    "tema_por_defecto": "Una expediente perdida en una isla misteriosa",
    "idioma": "Español"
  },
  "voz": {
    "audiencia": "Audiencia general", "contexto_cultural": "Latinoamérica",
    "tono": "aventurero y cercano", "guia_de_estilo": "frases cortas",
    "restricciones": "sin violencia gráfica"
  },
  "visual": {"estilo_maestro": "3D render style with clean environment and lighting"},
  "media": {
    "keyframes": true,
    "proveedor_imagen": "gemini",
    "encadenar_frames": true,
    "intentos_qa": 2
  }
}'
```

Respuesta esperada: `{"project_id": "aventura", "creado": true}` (201).

Verificar que la red 3D ya deriva el nodo de media del grafo (§9.2):

```bash
curl -s http://127.0.0.1:8000/api/projects/aventura/red | python3 -c "
import json,sys; red=json.load(sys.stdin)
n = next(n for n in red['nodes'] if n['id']=='render_keyframes')
print(n['fase'], n['tipo'], n['estructural'], n['rol'], n['llm'])"
# → media media True None None
```

El nodo cablea el último enriquecedor con el commit
(`technical_director->render_keyframes`, `render_keyframes->commit_episode`).
Un proyecto SIN sección `[media]` devuelve exactamente la red de siempre (sin
ese nodo; paridad). También es visible en la escena 3D: placa vertical en la
columna `media`, entre enriquecimiento y cierre.

## 1. Sembrar la biblioteca (alta + batería + lock)

Alta de la protagonista (siempre nace `borrador`; la descripción canónica va
EN INGLÉS, ≥40 caracteres, §11.1):

```bash
curl -s -X POST http://127.0.0.1:8000/api/projects/aventura/anclas \
  -H 'Content-Type: application/json' -d '{
    "ancla_id": "nita",
    "tipo": "personaje",
    "nombre": "Nita",
    "descripcion_canonica": "A fearless young explorer with short dark hair, an orange windbreaker and a leather satchel"
  }'
```

201 con `"estado": "borrador"`, `"version": 1`, `"bateria": []`.

Cargar la batería mínima de un `personaje` (roles `hero_portrait`,
`turnaround_front`, `turnaround_side`, `turnaround_back`; el nombre del
archivo lo genera SIEMPRE el servidor con el correlativo del rol):

```bash
for rol in hero_portrait turnaround_front turnaround_side turnaround_back; do
  curl -s -X POST http://127.0.0.1:8000/api/projects/aventura/anclas/nita/imagenes \
    -F "rol=$rol" -F "archivo=@./$rol.png"
done
```

201 por imagen; cada entrada de `bateria` viaja como
`{"rol": "...", "archivo": "hero_portrait_1.png", "origen": "subida"}`.
(El mismo flujo está en la web: drawer → pestaña **Anclas** → alta, upload y
checklist de batería.)

Lock prematuro rechazado con error accionable (§4.1):

```bash
# con una sola imagen subida:
curl -s -X POST http://127.0.0.1:8000/api/projects/aventura/anclas/nita/lock
# → 400 {"detail": "No se puede lockear 'nita': a la batería mínima de un
#    'personaje' le faltan imágenes de rol: turnaround_front, turnaround_side,
#    turnaround_back (spec-recursos-ancla §4.1)."}
```

Lock completo:

```bash
curl -s -X POST http://127.0.0.1:8000/api/projects/aventura/anclas/nita/lock
# → 200 con "estado": "lockeado"
```

Evidencia esperada: `GET /api/projects/aventura/anclas` lista a Nita con
`estado: lockeado`, `version: 1`, 4 imágenes y `qa_medio: null` (aún no hay
media entregado que puntuarla).

## 2. Corrida con anclas (continuidad + dirección + media)

Lanzar la serie de 2 capítulos:

```bash
curl -s -X POST http://127.0.0.1:8000/api/series \
  -H 'Content-Type: application/json' \
  -d '{"project_id": "aventura", "num_chapters": 2}'
# → 202 {"job_id": "<job1>", "status": "queued"}
```

Seguir el progreso (SSE; equivalente no-stream:
`GET /api/jobs/<job1>/events/history`):

```bash
curl -sN http://127.0.0.1:8000/api/jobs/<job1>/events
```

Con el guion aprobado, la dirección técnica declara anclas en las specs
(`VisualAssetSpec.anclas`) y la continuidad cita sus descriptores canónicos;
con `[media].keyframes = true` el flujo pasa por el nodo de media antes del
commit. Frames esperados en el stream (uno por escena):

```
event: media_start
data: {"kind": "media_start", "job_id": "<job1>", "escena": 1, "proveedor": "gemini", ...}

event: media_end
data: {"kind": "media_end", "job_id": "<job1>", "escena": 1, "proveedor": "gemini",
       "archivo": "aventura/ch-01/escena_1.png", "qa": "aprobado", "intentos": 1}
```

`"qa"` vale `"aprobado"` o `"agotado"` (bucle §7); un `media_end` con
`"error"` deja la escena SIN keyframe y la corrida SIGUE (§6: el media nunca
tumba episodios aprobados). En la escena 3D, `render_keyframes` entra en
*tool* (halo ámbar) con el primer `media_start` y pasa a *done* con cada
`media_end`; el timeline 2D lista los mismos eventos.

Al terminar (`GET /api/jobs/<job1>` → `"status": "completed"`), inspeccionar
el entregable 1.2:

```bash
curl -s http://127.0.0.1:8000/api/jobs/<job1>/deliverable | python3 -m json.tool
```

Campos nuevos (todos con default: un proyecto sin anclas ni `[media]`
serializa igual, solo cambia `schema_version`):

```json
{
  "schema_version": "1.2",
  "episodes": [{
    "scenes": [{
      "scene_number": 1,
      "anclas": [{"ancla_id": "nita", "roles": ["hero_portrait"]}],
      "keyframe": {
        "archivo": "aventura/ch-01/escena_1.png",
        "manifest": {
          "proveedor": "gemini", "modelo": "...", "seed": null,
          "prompt_final": "A fearless young explorer ... , orange windbreaker",
          "anclas_usadas": [["nita", 1, "hero_portrait"]],
          "parametros": {}, "id_externo": "...", "creado_en": "..."
        },
        "qa": [
          {"escena": 1, "ancla_id": "nita", "metrica": "cara_coseno",
           "score": 0.62, "umbral": 0.35, "aprueba": true, "detalle": ""}
        ]
      }
    }],
    "adjuntos": [{
      "rol": "media",
      "artefacto": {"chapter_id": "ch-01", "keyframes": ["..."],
                    "errores": [], "qa_agotado": []}
    }]
  }]
}
```

`anclas_usadas` viaja EN ORDEN (identidad primero, §6). La `seed` del pedido
inicial la asigna el proveedor (`null` si no reporta); cada regeneración del
bucle §7 lleva seed determinista `escena·100003 + intento` y peso de
referencia escalado ↑. Los intentos intermedios NO están en `keyframe.qa`
(solo el candidato entregado): los de las escenas que agotaron su bucle sin
aprobar viajan en `artefacto.qa_agotado` (política honesta, §7).

Verificar el keyframe servido por la API (raíz de media compartida
worker/API, `<data_dir>/media/aventura/ch-01/escena_1.png`):

```bash
curl -sI http://127.0.0.1:8000/api/media/aventura/ch-01/escena_1.png | grep -i "content-type\|cache-control"
# → content-type: image/png ; cache-control: public, max-age=3600
```

Y el visor HTML (`curl -s http://127.0.0.1:8000/api/jobs/<job1>/viewer`):
cada escena con keyframe muestra la imagen, chips `@nita · hero_portrait`,
y los desplegables *manifest (procedencia)* e *QA visual* con su veredicto.

Evidencia esperada (criterio §1, primera mitad): Nita aparece en escenas de
AMBOS capítulos (`anclas` citadas en ch-01 y ch-02) y sus keyframes pasan el
QA. `GET /api/projects/aventura/anclas` ahora reporta `qa_medio` y
`qa_muestras` para Nita (media entregado del job completado).

## 3. Promoción del keyframe aprobado a batería (§8.1)

Candidatos del entregable (solo keyframes con QA aprobado; la última entrada
es el estilo global §8.3 con `ancla_id: null`):

```bash
curl -s http://127.0.0.1:8000/api/jobs/<job1>/anclas-candidatas
# → [
#     {"ancla_id": "nita", "chapter_id": "ch-01", "escena": 1,
#      "archivo": "aventura/ch-01/escena_1.png",
#      "rol_sugerido": "expression_sheet", "score_qa": 0.62},
#     ...
#     {"ancla_id": null, "chapter_id": "ch-01", "escena": 1,
#      "archivo": "aventura/ch-01/escena_1.png",
#      "rol_sugerido": "style_reference", "estilo_global": true,
#      "score_qa": 0.62}
#   ]
```

(`rol_sugerido` por TIPO: personaje → `expression_sheet`, lugar →
`coverage_angle`, objeto → `prop_detail`, estilo → `style_reference`.)

Promover el keyframe a la batería de Nita (lock humano; el manifest de
procedencia viaja con la imagen):

```bash
curl -s -X POST http://127.0.0.1:8000/api/projects/aventura/anclas/nita/promover \
  -H 'Content-Type: application/json' \
  -d '{"archivo": "aventura/ch-01/escena_1.png", "rol": "expression_sheet"}'
```

201 con `version: 2` (estaba lockeada: subir batería sube versión, §4.1) y la
nueva entrada al final de `bateria`:

```json
{"rol": "expression_sheet", "archivo": "expression_sheet_1.png",
 "origen": "generada", "manifest": {"proveedor": "gemini", "...": "..."}}
```

Verificaciones: (a) la imagen promovida se sirve desde la batería
(`GET /api/projects/aventura/anclas/nita/imagenes/expression_sheet_1.png`);
(b) promover el MISMO keyframe de nuevo responde 409 (idempotencia por
manifest); (c) un keyframe rechazado por QA o sin informes NO figura en los
candidatos y `promover` responde 404.

## 4. Casting asistido (§8.2)

En la MISMA corrida, introducir un personaje nuevo (sin ancla) que reaparezca
en el plan: si el lore lo registra con `category: "personaje"` y es
recurrente (presente en ≥2 episodios del plan), el cierre de la corrida lo
propone como ancla `propuesto` — sin pisar la biblioteca — y, con media
activa, intenta un hero portrait (`origen: "generada"`); si la generación
falla, la propuesta queda sin batería y la corrida sigue.

```bash
curl -s http://127.0.0.1:8000/api/projects/aventura/anclas | python3 -c "
import json,sys
for a in json.load(sys.stdin):
    print(a['ancla_id'], a['estado'], a['version'], len(a['bateria']))"
# → nita lockeado 2 5
# → <nuevo> propuesto 1 1   (hero portrait best-effort; 0 si falló)
```

En la auditoría de la corrida (log de ejecución en
`<data_dir>/auditoria/aventura/serie_<job1>/log.txt`), el evento queda
registrado: *"Casting asistido: propuesta de ancla '...' (personaje
recurrente del lore, estado 'propuesto' con hero portrait generado)."*.

El lock sigue siendo humano: la propuesta NO participa del pipeline hasta
que se complete su batería y se lockee (paso 1 con sus imágenes).

## 5. Segunda corrida: consistencia (criterio de aceptación §1)

Relanzar el mismo proyecto:

```bash
curl -s -X POST http://127.0.0.1:8000/api/series \
  -H 'Content-Type: application/json' \
  -d '{"project_id": "aventura", "num_chapters": 2}'
# → 202 {"job_id": "<job2>", "status": "queued"}
```

Verificar al terminar:

1. **El personaje reaparece consistente**: `GET /api/jobs/<job2>/deliverable`
   cita `nita` en las escenas de ambos capítulos, y los `manifest` de sus
   keyframes vuelven a viajar con `anclas_usadas: [["nita", 2, ...]]` — ojo
   al `version: 2`: la promoción del paso 3 subió la versión que los
   manifiestos estampan.
2. **El QA mejora**: el keyframe promovido ahora es PARTE de la batería con la
   que el QA compara caras; comparar los scores `cara_coseno` de Nita entre
   corridas (el score es coseno contra la batería, umbral default 0.35 via
   `MEDIA_QA_UMBRAL_CARA`):

   ```bash
   for job in <job1> <job2>; do
     curl -s http://127.0.0.1:8000/api/jobs/$job/deliverable | python3 -c "
   import json,sys; d=json.load(sys.stdin)
   scores=[i['score'] for e in d['episodes'] for s in e['scenes']
           if s.get('keyframe') for i in s['keyframe']['qa']
           if i['ancla_id']=='nita']
   print('$job', 'n=' + str(len(scores)), 'media=' + str(sum(scores)/len(scores)))"
   done
   ```

   Evidencia esperada: la media de `<job2>` ≥ la de `<job1>` (más referencias
   en batería → comparaciones más estables); todos los informes de Nita con
   `aprueba: true`.
3. **La biblioteca queda mejor**: `GET /api/projects/aventura/anclas` muestra
   para Nita `version: 2`, 5 imágenes (4 subidas + 1 promovida) y un
   `qa_medio` actualizado con `qa_muestras > 0` de la segunda corrida.

## 6. Paridad (sin anclas ni [media] no cambia nada)

1. Crear un proyecto gemelo SIN sección `media` y sin anclas; lanzar una
   corrida: sin eventos `media_*` en el stream, `GET .../red` sin
   `render_keyframes`, entregable sin `anclas`/`keyframe` por escena y el
   visor HTML sin el bloque de keyframes.
2. `uv run pytest -q` (backend, incluye el test de paridad byte a byte) y
   `cd web && npm test && npm run build` en verde.
