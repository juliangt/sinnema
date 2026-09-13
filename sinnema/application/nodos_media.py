"""Nodo estructural ``render_keyframes`` (spec-recursos-ancla §6, §7).

Es el ÚNICO punto donde el pipeline genera media: un nodo de grafo ESCRITO A
MANO (como ``plan_series`` o ``commit_episode``, no un agente) que corre entre
el enriquecimiento y el commit SOLO cuando ``[media].keyframes = true`` y hay
puerto inyectado. Por cada escena del paquete técnico:

1. compone el ``PedidoKeyframe`` (servicio puro ``componer_pedido_escena``:
   image_prompt + descriptores canónicos, identidad-primero),
2. llama al ``MediaGenerationPort`` (el adaptador reintenta solo transporte),
3. con servicio de QA inyectado (``DependenciasMedia.qa``), ejecuta el BUCLE
   ACOTADO de regeneración §7: QA fallido → nuevo intento con escalado (peso
   de referencia ↑, seed nueva) hasta ``[media].intentos_qa``; agotado, se
   entrega el MEJOR candidato y los informes de TODOS los intentos viajan en
   ``MediaDelEpisodio.qa_agotado`` (política honesta: sin rechazo silencioso),
4. persiste el archivo vía ``MediaStorePort``,
5. emite ``media_start``/``media_end`` por el canal de eventos del job
   (mismo ``on_event`` que llega a SSE) y registra en auditoría,
6. con ``encadenar_frames``, el último frame de la escena N condiciona la N+1;
   si el adaptador no expone frame, degrada a sin encadenado con registro.

SEMÁNTICA DE FALLO (§6): un fallo del proveedor tras los reintentos de
transporte deja la escena SIN keyframe — registro en auditoría
(``log_failure``) + adjunto de error — y la corrida SIGUE: el media nunca
tumba episodios aprobados. El QA (§7) tampoco re-abre la compuerta de guion:
solo gobierna regeneraciones dentro de este nodo. El resultado acumulado viaja
como adjunto del episodio (``ArtefactoAdjunto(rol="media")`` con
``MediaDelEpisodio``), sin tocar slots canónicos.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sinnema.application.ports import AuditTrailPort, DependenciasMedia
from sinnema.application.projects import ProjectSpec
from sinnema.application.state import PipelineState
from sinnema.domain.models import (
    ErrorDeMedia,
    InformeQaVisual,
    MediaCrudo,
    MediaDelEpisodio,
    MediaGenerado,
    PedidoKeyframe,
    RecursoAncla,
    ReferenciaAncla,
)
from sinnema.domain.services import componer_pedido_escena, pares_identidad_primero

logger = logging.getLogger("sinnema.media.nodo")

#: Rol del adjunto de episodio que transporta el media del capítulo.
ROL_ADJUNTO_MEDIA = "media"

#: Escalado del peso de referencia por intento extra (§7: peso ↑). El primer
#: reintento pide 1.3, el segundo 1.6, ...; los proveedores que no soporten
#: peso lo registran en el manifest sin efecto.
PASO_DE_PESO = 0.3

#: Base de la seed determinista por intento (§7: seed nueva por regeneración;
#: derivada de escena+intento para que una misma corrida sea reproducible).
BASE_DE_SEED = 100_003


def _pedido_escalado(base: PedidoKeyframe, intento: int) -> PedidoKeyframe:
    """Pedido del intento N (1-based): desde el 2º lleva escalado §7."""
    if intento <= 1:
        return base
    return base.model_copy(
        update={
            "peso_referencia": round(1.0 + PASO_DE_PESO * (intento - 1), 2),
            "seed": base.scene_number * BASE_DE_SEED + intento,
        }
    )


def _calidad_de_candidato(informes: Sequence[InformeQaVisual]) -> float:
    """Calidad de un candidato: el PEOR margen (score - umbral) de sus informes.

    Elige el candidato cuya métrica más floja sea lo más alta posible; sin
    informes (QA ausente u omitido) el único candidato disponible gana.
    """
    if not informes:
        return 0.0
    return min(informe.score - informe.umbral for informe in informes)


def make_render_keyframes_node(
    project: ProjectSpec,
    dependencias: DependenciasMedia,
    audit: AuditTrailPort,
):
    """Construye el nodo del grafo (cierra sobre proyecto, dependencias y auditoría)."""

    def _render_keyframes(state: PipelineState) -> Dict[str, Any]:
        paquete = state.get("technical_package")
        if paquete is None:
            # Proyecto sin director técnico: no hay specs que renderizar.
            audit.log_step(
                "render_keyframes",
                "Sin paquete técnico en el estado: no hay keyframes que renderizar.",
            )
            return {}
        project_id = state["project_id"]
        catalogo = list(state.get("anclas") or [])
        eventos = dependencias.eventos
        proveedor = dependencias.proveedor or project.media.proveedor_imagen or "media"
        encadenar = project.media.encadenar_frames
        intentos_max = 1 + max(0, project.media.intentos_qa)

        def emitir(evento: Dict[str, Any]) -> None:
            if eventos is not None:
                eventos(evento)

        keyframes: List[MediaGenerado] = []
        errores: List[ErrorDeMedia] = []
        qa_agotado: List[InformeQaVisual] = []
        previos: List[Tuple[int, bytes]] = []
        ultimo_frame: Optional[bytes] = None
        for spec in paquete.visual_specs:
            pedido_base = componer_pedido_escena(
                paquete,
                spec,
                catalogo,
                frame_inicial=ultimo_frame if encadenar else None,
            )
            pares = pares_identidad_primero(spec.anclas, catalogo)
            emitir({
                "tipo": "media_start",
                "escena": spec.scene_number,
                "proveedor": proveedor,
            })
            audit.log_event(
                f"media_start: escena {spec.scene_number} de "
                f"{paquete.chapter_id} ({proveedor})."
            )

            # Bucle acotado §7: 1 intento + hasta intentos_qa regeneraciones.
            intentos: List[Tuple[int, MediaCrudo, str, List[InformeQaVisual]]] = []
            fallo_escena: Optional[str] = None
            for intento in range(1, intentos_max + 1):
                try:
                    crudo = dependencias.puerto.generar_keyframe(
                        _pedido_escalado(pedido_base, intento), catalogo
                    )
                    archivo = dependencias.almacen.guardar_keyframe(
                        project_id,
                        paquete.chapter_id,
                        spec.scene_number,
                        crudo.formato,
                        crudo.datos,
                    )
                except Exception as exc:  # noqa: BLE001 - §6: el media no tumba
                    fallo_escena = str(exc)
                    break
                informes: List[InformeQaVisual] = []
                avisos: List[str] = []
                if dependencias.qa is not None:
                    informes, avisos = dependencias.qa.evaluar_keyframe(
                        escena=spec.scene_number,
                        project_id=project_id,
                        prompt=pedido_base.prompt_final,
                        datos_keyframe=crudo.datos,
                        pares=pares,
                        previos=previos,
                    )
                    for aviso in avisos:
                        audit.log_event(f"QA visual: {aviso}")
                intentos.append((intento, crudo, archivo, informes))
                if all(informe.aprueba for informe in informes):
                    break
                if intento < intentos_max:
                    audit.log_event(
                        f"QA visual: intento {intento}/{intentos_max} de la escena "
                        f"{spec.scene_number} rechazado ({_resumen_de_informes(informes)}); "
                        "se regenera con escalado (peso ↑, seed nueva)."
                    )
            if fallo_escena is not None:
                _registrar_fallo(
                    audit, emitir, proveedor, paquete.chapter_id,
                    spec.scene_number, fallo_escena, errores,
                )
                # Sin frame de esta escena, el encadenado se rompe: la próxima
                # escena se genera sin frame inicial.
                ultimo_frame = None
                continue

            elegido = max(
                intentos,
                key=lambda intento: (
                    _calidad_de_candidato(intento[3]),
                    intento[0],
                ),
            )
            numero_elegido, crudo_elegido, archivo_elegido, informes_elegidos = elegido
            keyframes.append(
                MediaGenerado(
                    archivo=archivo_elegido,
                    manifest=crudo_elegido.manifest,
                    qa=list(informes_elegidos),
                )
            )
            aprueba = all(informe.aprueba for informe in informes_elegidos)
            if not aprueba:
                # Política honesta §7: el mejor candidato se entrega, pero los
                # informes de TODOS los intentos quedan visibles (adjunto).
                for _, _, _, informes in intentos:
                    qa_agotado.extend(informes)
            resumen_intentos = (
                f" tras {len(intentos)} intento(s)" if len(intentos) > 1 else ""
            )
            veredicto = (
                "aprobado por QA" if aprueba
                else f"ENTREGADO SIN APROBACIÓN QA ({_resumen_de_informes(informes_elegidos)})"
            )
            audit.log_step(
                "render_keyframes",
                f"Keyframe de la escena {spec.scene_number} ({paquete.chapter_id}) "
                f"generado con {proveedor}: {archivo_elegido} "
                f"(referencias: {len(crudo_elegido.manifest.anclas_usadas)}) "
                f"[intento {numero_elegido}, {veredicto}{resumen_intentos}].",
            )
            emitir({
                "tipo": "media_end",
                "escena": spec.scene_number,
                "proveedor": proveedor,
                "archivo": archivo_elegido,
                "qa": "aprobado" if aprueba else "agotado",
                "intentos": len(intentos),
            })
            if encadenar and crudo_elegido.ultimo_frame is None:
                audit.log_event(
                    f"El proveedor no expuso último frame de la escena "
                    f"{spec.scene_number}: la escena siguiente se genera sin "
                    "encadenado (degradación §6)."
                )
            ultimo_frame = crudo_elegido.ultimo_frame
            previos.append((spec.scene_number, crudo_elegido.datos))

        resumen = (
            f"Media de {paquete.chapter_id}: {len(keyframes)} keyframe(s), "
            f"{len(errores)} escena(s) sin media."
        )
        if qa_agotado:
            resumen += f" {len(qa_agotado)} informe(s) de QA sin aprobación (adjuntos)."
        logger.info("render_keyframes: %s", resumen)
        audit.log_step("render_keyframes", resumen)
        return {
            "artefactos": {
                ROL_ADJUNTO_MEDIA: MediaDelEpisodio(
                    chapter_id=paquete.chapter_id,
                    keyframes=keyframes,
                    errores=errores,
                    qa_agotado=qa_agotado,
                )
            }
        }

    return _render_keyframes


def _resumen_de_informes(informes: Sequence[InformeQaVisual]) -> str:
    if not informes:
        return "sin informes de QA"
    return "; ".join(
        f"{informe.metrica}={informe.score:.2f} (umbral {informe.umbral:.2f})"
        for informe in informes
    )


def _registrar_fallo(
    audit: AuditTrailPort,
    emitir,
    proveedor: str,
    chapter_id: str,
    escena: int,
    mensaje: str,
    errores: List[ErrorDeMedia],
) -> None:
    """Semántica de fallo §6: la escena queda sin keyframe y la corrida sigue."""
    logger.warning(
        "Escena %s de %s queda SIN keyframe (%s): %s",
        escena, chapter_id, proveedor, mensaje,
    )
    errores.append(ErrorDeMedia(escena=escena, proveedor=proveedor, error=mensaje))
    audit.log_failure(
        f"Keyframe de la escena {escena} ({chapter_id}) falló tras los "
        f"reintentos de transporte ({proveedor}): {mensaje} La escena queda "
        "sin media y la corrida continúa."
    )
    emitir({
        "tipo": "media_end",
        "escena": escena,
        "proveedor": proveedor,
        "error": mensaje,
    })
