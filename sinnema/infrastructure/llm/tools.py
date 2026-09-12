"""Implementación de las tools integradas (spec-red-3d §7.3).

El vocabulario vive en ``sinnema/application/tools.py`` (``TOOLS_INTEGRADAS``);
este adaptador las materializa como ``@tool`` de LangChain sobre puertos ya
existentes del sistema: ``JsonLoreStore`` para ``buscar_lore`` y el
``FormatProfile`` del proyecto para ``leer_formato``. Son deterministas y
locales: sin red, sin APIs externas.

``construir_tools_por_rol`` devuelve, para cada rol cuyo ``[agentes.<rol>]``
declara ``tools`` no vacío, la lista de tools habilitadas; el gateway la usa
para armar el loop ``bind_tools`` previo a la generación estructurada.
"""
from __future__ import annotations

import json
import logging
from typing import Dict, List, Mapping

from langchain_core.tools import BaseTool, tool

from sinnema.application.tools import TOOLS_INTEGRADAS
from sinnema.application.projects import ProjectSpec
from sinnema.infrastructure.lore import JsonLoreStore

logger = logging.getLogger("sinnema.infrastructure.tools")


def _verificar_wiring(nombres: Mapping[str, str]) -> None:
    """Verifica que toda tool implementada esté declarada en el catálogo."""
    desconocidas = set(nombres) - set(TOOLS_INTEGRADAS)
    if desconocidas:
        raise ValueError(
            f"Tools implementadas fuera del catálogo: {sorted(desconocidas)}. "
            f"Válidas: {sorted(TOOLS_INTEGRADAS)}."
        )


def construir_tools(
    proyecto: ProjectSpec, lore_store: JsonLoreStore
) -> Dict[str, BaseTool]:
    """Tools instanciadas para un proyecto (cierran sobre su lore/formato)."""
    implementadas = {}

    @tool
    def buscar_lore(consulta: str) -> str:
        """Busca en el lore persistido del proyecto (memoria de continuidad)
        por consulta: términos, definiciones y su capítulo de origen."""
        consulta_normalizada = consulta.strip().lower()
        entradas = lore_store.load(proyecto.project_id)
        hallazgos = [
            entrada
            for entrada in entradas
            if consulta_normalizada in entrada.term.lower()
            or consulta_normalizada in entrada.definition.lower()
        ]
        if not hallazgos:
            return (
                f"Sin resultados de lore para '{consulta}' "
                f"({len(entradas)} entrada(s) en la memoria)."
            )
        lineas = [
            f"- {e.term}: {e.definition} (origen: {e.chapter_id})"
            for e in hallazgos
        ]
        return "Lore encontrado:\n" + "\n".join(lineas)

    @tool
    def leer_formato() -> str:
        """Devuelve las cotas editoriales de [formato] del proyecto: palabras,
        escenas y duraciones objetivo y duras."""
        perfil = proyecto.format
        if perfil is None:
            return "El proyecto no declara [formato]: rige el perfil por defecto."
        return (
            "Cotas editoriales (JSON):\n"
            + json.dumps(perfil.model_dump(mode="json"), ensure_ascii=False, indent=2)
        )

    implementadas = {"buscar_lore": buscar_lore, "leer_formato": leer_formato}
    _verificar_wiring(implementadas)
    return implementadas


def construir_tools_por_rol(
    proyecto: ProjectSpec, lore_store: JsonLoreStore
) -> Dict[str, List[BaseTool]]:
    """Rol → tools habilitadas según ``[agentes.<rol>].tools`` (§7.3).

    Solo roles con ``tools`` no vacío aparecen en el resultado: los demás
    corren el camino de siempre, sin loop ni overhead. Un nombre fuera del
    catálogo no debería llegar acá (la validación §3.13 lo rechaza al cargar
    el TOML), pero se defiende con un error explícito.
    """
    disponibles = construir_tools(proyecto, lore_store)
    por_rol: Dict[str, List[BaseTool]] = {}
    for rol, config in proyecto.agentes.items():
        if not config.tools:
            continue
        desconocidas = [n for n in config.tools if n not in disponibles]
        if desconocidas:
            raise ValueError(
                f"El rol '{rol}' declara tools fuera del registro: "
                f"{desconocidas}. Disponibles: {sorted(disponibles)}."
            )
        por_rol[rol] = [disponibles[n] for n in config.tools]
    if por_rol:
        logger.debug(
            "Tools habilitadas para %s: %s",
            proyecto.project_id, {r: [t.name for t in ts] for r, ts in por_rol.items()},
        )
    return por_rol
