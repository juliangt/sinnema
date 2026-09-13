"""Composición pura de pedidos de keyframe (spec-recursos-ancla §6).

El nodo ``render_keyframes`` convierte cada ``VisualAssetSpec`` del paquete
técnico en un ``PedidoKeyframe``: el ``prompt_final`` es el ``image_prompt``
de la spec más los descriptores canónicos EN de las anclas citadas, EN ORDEN
identidad-primero (§3.1, mismo orden que luego impone el resolver al payload
del proveedor). Funciones PURAS: sin I/O, sin reloj — testables sin mocks.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from sinnema.domain.models import (
    PedidoKeyframe,
    RecursoAncla,
    ReferenciaAncla,
    TechnicalPackage,
    VisualAssetSpec,
)

#: Orden de grupos §3.1: el ancla de IDENTIDAD (personaje) siempre primera.
_ORDEN_DE_GRUPO: Dict[str, int] = {"personaje": 0, "lugar": 1, "objeto": 2, "estilo": 3}


def pares_identidad_primero(
    referencias: Sequence[ReferenciaAncla],
    catalogo: Sequence[RecursoAncla],
) -> List[Tuple[ReferenciaAncla, RecursoAncla]]:
    """(referencia, ancla) ordenado identidad-primero, estable por grupo.

    El catálogo es el lockeado sembrado en el estado; una referencia ausente
    delataría un bug de wiring (``validate_anchor_refs`` ya lo rechazó aguas
    arriba) y falla en voz alta.
    """
    por_id = {ancla.ancla_id: ancla for ancla in catalogo}
    pares: List[Tuple[ReferenciaAncla, RecursoAncla]] = []
    for referencia in referencias:
        ancla = por_id.get(referencia.ancla_id)
        if ancla is None:
            raise ValueError(
                f"Wiring de media: la escena cita el ancla "
                f"'{referencia.ancla_id}' que no está en el catálogo lockeado "
                "(error local, no de proveedor)."
            )
        pares.append((referencia, ancla))
    pares.sort(key=lambda par: _ORDEN_DE_GRUPO[par[1].tipo])
    return pares


def componer_prompt_final(
    image_prompt: str,
    pares: Sequence[Tuple[ReferenciaAncla, RecursoAncla]],
) -> str:
    """``image_prompt`` + descriptores canónicos (un bloque por ancla única).

    Los personajes/lugares anclados NO se re-describen con palabras nuevas
    (§5.3): el prompt final solo anexa su ficha canónica, una vez por ancla,
    en el orden identidad-primero.
    """
    if not pares:
        return image_prompt
    bloques: List[str] = []
    vistos: set = set()
    for _, ancla in pares:
        if ancla.ancla_id in vistos:
            continue
        vistos.add(ancla.ancla_id)
        bloques.append(f"{ancla.nombre}: {ancla.descripcion_canonica}.")
    return image_prompt + "\n\n" + "\n".join(bloques)


def componer_pedido_escena(
    paquete: TechnicalPackage,
    spec: VisualAssetSpec,
    catalogo: Sequence[RecursoAncla],
    *,
    frame_inicial: Optional[bytes] = None,
) -> PedidoKeyframe:
    """Pedido del keyframe de UNA escena (puro; el nodo lo llama por escena)."""
    pares = pares_identidad_primero(spec.anclas, catalogo)
    return PedidoKeyframe(
        scene_number=spec.scene_number,
        chapter_id=paquete.chapter_id,
        prompt_final=componer_prompt_final(spec.image_prompt, pares),
        negative_prompt=spec.negative_prompt,
        aspect_ratio=paquete.aspect_ratio,
        anclas=[referencia for referencia, _ in pares],
        frame_inicial=frame_inicial,
    )
