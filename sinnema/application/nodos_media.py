"""Nodo estructural ``render_keyframes`` (spec-recursos-ancla §6).

Es el ÚNICO punto donde el pipeline genera media: un nodo de grafo ESCRITO A
MANO (como ``plan_series`` o ``commit_episode``, no un agente) que corre entre
el enriquecimiento y el commit SOLO cuando ``[media].keyframes = true`` y hay
puerto inyectado. Por cada escena del paquete técnico:

1. compone el ``PedidoKeyframe`` (servicio puro ``componer_pedido_escena``:
   image_prompt + descriptores canónicos, identidad-primero),
2. llama al ``MediaGenerationPort`` (el adaptador reintenta solo transporte),
3. persiste el archivo vía ``MediaStorePort``,
4. emite ``media_start``/``media_end`` por el canal de eventos del job
   (mismo ``on_event`` que llega a SSE) y registra en auditoría,
5. con ``encadenar_frames``, el último frame de la escena N condiciona la N+1;
   si el adaptador no expone frame, degrada a sin encadenado con registro.

SEMÁNTICA DE FALLO (§6): un fallo del proveedor tras los reintentos de
transporte deja la escena SIN keyframe — registro en auditoría
(``log_failure``) + adjunto de error — y la corrida SIGUE: el media nunca
tumba episodios aprobados. El resultado acumulado viaja como adjunto del
episodio (``ArtefactoAdjunto(rol="media")`` con ``MediaDelEpisodio``), sin
tocar slots canónicos.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sinnema.application.ports import AuditTrailPort, DependenciasMedia
from sinnema.application.projects import ProjectSpec
from sinnema.application.state import PipelineState
from sinnema.domain.models import ErrorDeMedia, MediaDelEpisodio, MediaGenerado
from sinnema.domain.services import componer_pedido_escena

logger = logging.getLogger("sinnema.media.nodo")

#: Rol del adjunto de episodio que transporta el media del capítulo.
ROL_ADJUNTO_MEDIA = "media"


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

        def emitir(evento: Dict[str, Any]) -> None:
            if eventos is not None:
                eventos(evento)

        keyframes: list = []
        errores: list = []
        ultimo_frame: Optional[bytes] = None
        for spec in paquete.visual_specs:
            pedido = componer_pedido_escena(
                paquete,
                spec,
                catalogo,
                frame_inicial=ultimo_frame if encadenar else None,
            )
            emitir({
                "tipo": "media_start",
                "escena": spec.scene_number,
                "proveedor": proveedor,
            })
            audit.log_event(
                f"media_start: escena {spec.scene_number} de "
                f"{paquete.chapter_id} ({proveedor})."
            )
            try:
                crudo = dependencias.puerto.generar_keyframe(pedido, catalogo)
                archivo = dependencias.almacen.guardar_keyframe(
                    project_id,
                    paquete.chapter_id,
                    spec.scene_number,
                    crudo.formato,
                    crudo.datos,
                )
            except Exception as exc:  # noqa: BLE001 - §6: el media no tumba el episodio
                mensaje = str(exc)
                logger.warning(
                    "Escena %s de %s queda SIN keyframe (%s): %s",
                    spec.scene_number, paquete.chapter_id, proveedor, mensaje,
                )
                errores.append(
                    ErrorDeMedia(
                        escena=spec.scene_number, proveedor=proveedor, error=mensaje
                    )
                )
                audit.log_failure(
                    f"Keyframe de la escena {spec.scene_number} "
                    f"({paquete.chapter_id}) falló tras los reintentos de "
                    f"transporte ({proveedor}): {mensaje} La escena queda sin "
                    "media y la corrida continúa."
                )
                emitir({
                    "tipo": "media_end",
                    "escena": spec.scene_number,
                    "proveedor": proveedor,
                    "error": mensaje,
                })
                # Sin frame de esta escena, el encadenado se rompe: la próxima
                # escena se genera sin frame inicial.
                ultimo_frame = None
                continue

            keyframes.append(
                MediaGenerado(archivo=archivo, manifest=crudo.manifest)
            )
            audit.log_step(
                "render_keyframes",
                f"Keyframe de la escena {spec.scene_number} ({paquete.chapter_id}) "
                f"generado con {proveedor}: {archivo} "
                f"(referencias: {len(crudo.manifest.anclas_usadas)}).",
            )
            emitir({
                "tipo": "media_end",
                "escena": spec.scene_number,
                "proveedor": proveedor,
                "archivo": archivo,
            })
            if encadenar and crudo.ultimo_frame is None:
                audit.log_event(
                    f"El proveedor no expuso último frame de la escena "
                    f"{spec.scene_number}: la escena siguiente se genera sin "
                    "encadenado (degradación §6)."
                )
            ultimo_frame = crudo.ultimo_frame

        resumen = (
            f"Media de {paquete.chapter_id}: {len(keyframes)} keyframe(s), "
            f"{len(errores)} escena(s) sin media."
        )
        logger.info("render_keyframes: %s", resumen)
        audit.log_step("render_keyframes", resumen)
        return {
            "artefactos": {
                ROL_ADJUNTO_MEDIA: MediaDelEpisodio(
                    chapter_id=paquete.chapter_id,
                    keyframes=keyframes,
                    errores=errores,
                )
            }
        }

    return _render_keyframes
