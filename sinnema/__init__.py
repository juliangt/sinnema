"""Sinnema: motor multi-proyecto de series de micro-videos.

Arquitectura hexagonal (puertos y adaptadores):

- ``sinnema.domain``: entidades, contratos Pydantic y reglas de negocio puras.
  No conocen ningún framework de I/O ni de LLM.
- ``sinnema.application``: casos de uso, estado del grafo, prompts por rol,
  la definición de proyecto (``ProjectSpec``) y puertos (interfaces) que el
  núcleo necesita del mundo exterior.
- ``sinnema.infrastructure``: adaptadores concretos: clientes LLM (LangChain),
  cargador de proyectos TOML, lore persistente y la CLI que hace de
  composition root.
"""

__version__ = "3.0.0"
