"""Resolver de baterías: de ``ReferenciaAncla`` a la lista ordenada de imágenes
que cada proveedor acepta (spec-recursos-ancla §3.1, §6, §11.3).

Cada adaptador de proveedor construye su resolver con los LÍMITES de su API;
el resolver:
1. resuelve cada ``ancla_id`` contra el catálogo lockeado del estado y
   RE-VERIFICA lock y existencia (``validate_anchor_refs`` ya lo hizo aguas
   arriba; aquí el fallo sería un bug de wiring, así que también es error
   local accionable),
2. expande ``roles: []`` a la batería completa del tipo (``ROLES_POR_TIPO``),
3. reordena IDENTITY-FIRST (personaje → lugar → objeto → estilo, §3.1: en
   ``gpt-image-1`` la ``input_fidelity`` alta solo aplica a la primera imagen;
   en Gemini las referencias de consistencia van antes que las de estilo),
4. verifica los máximos del proveedor ANTES de cargar bytes o llamar: exceder
   un máximo es un error de wiring local (``ValueError`` claro), nunca un
   fallo remoto detectado tarde,
5. carga los bytes de cada imagen elegida vía el cargador inyectado
   (``JsonAnchorStore`` en producción; doble en tests) y deduplica.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple

from sinnema.domain.models import (
    PedidoKeyframe,
    RecursoAncla,
    ReferenciaAncla,
    RolDeImagen,
)
from sinnema.domain.models.anclas import ROLES_POR_TIPO

#: Cargador de bytes de una imagen de batería: (project_id, ancla_id, archivo).
CargarImagenDeBateria = Callable[[str, str, str], bytes]

#: Orden de grupos §3.1: el ancla de IDENTIDAD (personaje) siempre primera.
_ORDEN_DE_GRUPO: Dict[str, int] = {"personaje": 0, "lugar": 1, "objeto": 2, "estilo": 3}

#: Mimes de batería aceptados (misma lista blanca que el serving de la Fase 1).
MIMES_DE_IMAGEN = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def mime_de_archivo(archivo: str) -> str:
    """Mime de una imagen de batería por extensión (default png)."""
    return MIMES_DE_IMAGEN.get(Path(archivo).suffix.lower(), "image/png")


def formato_de_archivo(archivo: str) -> str:
    """Extensión sin punto (``MediaCrudo.formato`` / nombre del keyframe)."""
    extension = Path(archivo).suffix.lower().lstrip(".")
    return "jpeg" if extension == "jpg" else (extension or "png")


def formato_de_mime(mime: str) -> str:
    """Mime del proveedor → extensión sin punto (``MediaCrudo.formato``)."""
    return {
        "image/png": "png",
        "image/jpeg": "jpeg",
        "image/jpg": "jpeg",
        "image/webp": "webp",
    }.get((mime or "").lower(), "png")


@dataclass(frozen=True)
class ReferenciaResuelta:
    """Una imagen de referencia ya resuelta, en el orden final del payload.

    ``triple`` es exactamente la entrada ``(ancla_id, version, rol)`` que el
    manifest estampa en ``anclas_usadas`` (EN ORDEN, §3.6).
    """

    ancla_id: str
    version: int
    rol: RolDeImagen
    archivo: str
    datos: bytes

    @property
    def triple(self) -> Tuple[str, int, str]:
        return (self.ancla_id, self.version, self.rol)

    @property
    def mime(self) -> str:
        return mime_de_archivo(self.archivo)


class ResolverDeBateria:
    """Resuelve el pedido contra el catálogo con los límites de UN proveedor."""

    def __init__(
        self,
        project_id: str,
        cargar_imagen: CargarImagenDeBateria,
        maximo_consistencia: int,
        maximo_estilo: int,
        maximo_total: int | None = None,
    ) -> None:
        self._project_id = project_id
        self._cargar_imagen = cargar_imagen
        self._maximo_consistencia = maximo_consistencia
        self._maximo_estilo = maximo_estilo
        self._maximo_total = maximo_total

    # ------------------------------ resolución ------------------------------

    def resolver(
        self,
        pedido: PedidoKeyframe,
        catalogo: Sequence[RecursoAncla],
    ) -> List[ReferenciaResuelta]:
        """Referencias del pedido en el orden final, con bytes cargados.

        Todas las verificaciones (existencia, lock, máximos) corren ANTES de
        cargar bytes o llamar al proveedor: un pedido mal compuesto es un
        error local, no un gasto remoto (§11.3).
        """
        por_id = {ancla.ancla_id: ancla for ancla in catalogo}
        pares = self._pares_ordenados(pedido.anclas, por_id)
        seleccion = self._seleccion_expandida(pares)
        self._verificar_maximos(seleccion)
        return [
            ReferenciaResuelta(
                ancla_id=ancla_id,
                version=por_id[ancla_id].version,
                rol=rol,
                archivo=archivo,
                datos=self._cargar_imagen(self._project_id, ancla_id, archivo),
            )
            for ancla_id, _, rol, archivo in seleccion
        ]

    # ------------------------------ verificaciones ------------------------------

    @staticmethod
    def _pares_ordenados(
        referencias: Sequence[ReferenciaAncla],
        catalogo: Dict[str, RecursoAncla],
    ) -> List[Tuple[ReferenciaAncla, RecursoAncla]]:
        """(referencia, ancla) con existencia y lock re-verificados, ordenados
        por grupo §3.1 (identidad primero) y estable dentro de cada grupo."""
        pares: List[Tuple[ReferenciaAncla, RecursoAncla]] = []
        for referencia in referencias:
            ancla = catalogo.get(referencia.ancla_id)
            if ancla is None:
                raise ValueError(
                    f"Wiring de media: el pedido cita el ancla "
                    f"'{referencia.ancla_id}' que no está en el catálogo "
                    "lockeado del estado (validate_anchor_refs debió rechazarlo "
                    "antes: error local de wiring, no de proveedor)."
                )
            if ancla.estado != "lockeado":
                raise ValueError(
                    f"Wiring de media: el ancla '{referencia.ancla_id}' está en "
                    f"estado '{ancla.estado}': solo las lockeadas participan "
                    "(error local de wiring, no de proveedor)."
                )
            pares.append((referencia, ancla))
        pares.sort(key=lambda par: _ORDEN_DE_GRUPO[par[1].tipo])
        return pares

    @staticmethod
    def _seleccion_expandida(
        pares: List[Tuple[ReferenciaAncla, RecursoAncla]],
    ) -> List[Tuple[str, str, RolDeImagen, str]]:
        """Selección final de imágenes: roles expandidos, orden identidad-
        primero, sin duplicados. Devuelve (ancla_id, tipo, rol, archivo)."""
        seleccion: List[Tuple[str, str, RolDeImagen, str]] = []
        vistas: set = set()
        for referencia, ancla in pares:
            roles = (
                set(referencia.roles)
                if referencia.roles
                else set(ROLES_POR_TIPO[ancla.tipo])  # vacío = batería completa
            )
            for imagen in ancla.bateria:
                clave = (ancla.ancla_id, imagen.rol)
                if imagen.rol not in roles or clave in vistas:
                    continue
                vistas.add(clave)
                seleccion.append((ancla.ancla_id, ancla.tipo, imagen.rol, imagen.archivo))
        return seleccion

    def _verificar_maximos(
        self, seleccion: List[Tuple[str, str, RolDeImagen, str]]
    ) -> None:
        """Selección CONTRA los límites del proveedor, antes de cualquier I/O.

        La selección se agrupa en consistencia (personaje/lugar/objeto) y
        estilo; ``maximo_total`` cubre proveedores que solo fijan un techo
        global (gpt-image-1 ~16).
        """
        total = len(seleccion)
        if self._maximo_total is not None and total > self._maximo_total:
            raise ValueError(
                f"Wiring de media: el pedido lleva {total} imágenes de "
                f"referencia y el proveedor acepta como máximo "
                f"{self._maximo_total} (error local de wiring, §11.3: el "
                "pedido no debe llegar a llamarse)."
            )
        consistencia = sum(1 for _, tipo, _, _ in seleccion if tipo != "estilo")
        estilo = total - consistencia
        if consistencia > self._maximo_consistencia:
            raise ValueError(
                f"Wiring de media: {consistencia} referencias de consistencia "
                f"(personaje/lugar/objeto) superan el máximo del proveedor "
                f"({self._maximo_consistencia}) (error local de wiring, §11.3)."
            )
        if estilo > self._maximo_estilo:
            raise ValueError(
                f"Wiring de media: {estilo} referencias de estilo superan el "
                f"máximo del proveedor ({self._maximo_estilo}) (error local de "
                "wiring, §11.3)."
            )
