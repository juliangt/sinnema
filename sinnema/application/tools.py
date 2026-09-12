"""Catálogo de tools integradas del sistema (vocabulario de ``[agentes.<rol>].tools``).

Una tool es una función determinista y local que el agente puede invocar
dentro de su nodo antes de la generación estructurada (spec-red-3d §7.3).
Este módulo declara el VOCABULARIO: qué tools existen y qué hacen. Las
implementaciones concretas (``@tool`` de LangChain sobre ``JsonLoreStore`` y
``FormatProfile``) viven en la capa de infraestructura y se registran contra
este catálogo: la validación de ``[agentes.<rol>].tools`` (spec §3.13) y el
endpoint ``/api/meta/catalogos`` consumen esta única fuente.

Regla del sistema: añadir una tool = una entrada aquí + su implementación en
infraestructura (que verifica el wiring contra este catálogo al importarse).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ToolIntegrada:
    """Declaración de una tool: nombre estable y descripción para el modelo."""

    nombre: str
    descripcion: str


#: Tools integradas del MVP: deterministas y locales (sin red ni APIs externas).
TOOLS_INTEGRADAS: Dict[str, ToolIntegrada] = {
    "buscar_lore": ToolIntegrada(
        nombre="buscar_lore",
        descripcion=(
            "Busca en el lore persistido del proyecto (memoria de continuidad) "
            "por consulta: términos, definiciones y su capítulo de origen."
        ),
    ),
    "leer_formato": ToolIntegrada(
        nombre="leer_formato",
        descripcion=(
            "Devuelve las cotas editoriales de [formato] del proyecto: palabras, "
            "escenas y duraciones objetivo y duras."
        ),
    ),
}
