"""Base común de los adaptadores de imagen (template method del puerto).

Cada adaptador concreto (``gemini.py``, ``openai.py``) declara su proveedor,
modelo default, límites de referencias y variables de clave; la base:
1. verifica la configuración (clave) ANTES de importar SDK o tocar red:
   error accionable, patrón de degradación elegante de los proveedores LLM,
2. resuelve la batería vía su ``ResolverDeBateria`` (máximos verificados
   antes de llamar — §11.3),
3. reintenta solo el transporte (``con_reintentos``),
4. arma el ``ManifestDeGeneracion`` completo (seed si el proveedor la
   devuelve, ``id_externo``, parámetros y anclas_usadas EN ORDEN).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence, Tuple

from sinnema.application.ports import MediaGenerationPort
from sinnema.domain.models import (
    ManifestDeGeneracion,
    MediaCrudo,
    PedidoKeyframe,
    RecursoAncla,
)
from sinnema.infrastructure.media.resolver import (
    CargarImagenDeBateria,
    ResolverDeBateria,
    formato_de_mime,
)
from sinnema.infrastructure.media.transporte import (
    PoliticaReintentos,
    con_reintentos,
)


class AdaptadorImagenBase(MediaGenerationPort):
    """Implementa ``MediaGenerationPort`` para un proveedor de imagen."""

    #: Identidades y límites que cada adaptador concreto fija (§3.1).
    PROVEEDOR: str = ""
    MODELO_DEFAULT: str = ""
    VAR_CLAVES: Tuple[str, ...] = ()
    MAX_CONSISTENCIA: int = 0
    MAX_ESTILO: int = 0
    MAX_TOTAL: int | None = None
    EXTRA_NOMBRE: str = "media"  # extra opcional de pyproject que trae el SDK

    def __init__(
        self,
        project_id: str,
        cargar_imagen: CargarImagenDeBateria,
        api_key: Optional[str] = None,
        modelo: Optional[str] = None,
        retry_policy: Optional[PoliticaReintentos] = None,
        resolver: Optional[ResolverDeBateria] = None,
    ) -> None:
        self._project_id = project_id
        self._cargar_imagen = cargar_imagen
        self._api_key = api_key
        self._modelo = modelo or self.MODELO_DEFAULT
        self._politica = retry_policy or PoliticaReintentos()
        self._resolver = resolver or ResolverDeBateria(
            project_id,
            cargar_imagen,
            maximo_consistencia=self.MAX_CONSISTENCIA,
            maximo_estilo=self.MAX_ESTILO,
            maximo_total=self.MAX_TOTAL,
        )

    # ------------------------------ clave / SDK ------------------------------

    def clave(self) -> Optional[str]:
        """Clave explícita o la del entorno (mismas vars que los LLM: §4.3)."""
        if self._api_key:
            return self._api_key
        for variable in self.VAR_CLAVES:
            valor = os.getenv(variable)
            if valor:
                return valor
        return None

    def exigir_configuracion(self) -> None:
        """Clave presente o error accionable (ANTES de importar SDK/red)."""
        if self.clave() is None:
            raise RuntimeError(
                f"El proveedor de media '{self.PROVEEDOR}' no tiene clave de "
                f"API: exporta {', '.join(self.VAR_CLAVES)} (o construye el "
                "adaptador con api_key=...) para generar keyframes."
            )

    def _importar_sdk(self) -> Any:
        """Import perezoso del SDK; la subclase lo implementa (módulo se
        importa sin el SDK instalado — extra opcional ``sinnema[media]``)."""
        raise NotImplementedError

    def _cliente(self) -> Any:
        raise NotImplementedError

    # ------------------------------ generación ------------------------------

    def generar_keyframe(
        self,
        pedido: PedidoKeyframe,
        catalogo: Sequence[RecursoAncla],
    ) -> MediaCrudo:
        self.exigir_configuracion()
        referencias = self._resolver.resolver(pedido, catalogo)
        cliente = self._cliente()
        descripcion = f"{self.PROVEEDOR}/{self._modelo} escena {pedido.scene_number}"
        respuesta = con_reintentos(
            lambda: self._llamar(cliente, pedido, referencias),
            self._politica,
            descripcion,
        )
        datos, mime = self._extraer_imagen(respuesta, pedido)
        return MediaCrudo(
            datos=datos,
            formato=formato_de_mime(mime),
            manifest=self._manifest(pedido, referencias, respuesta),
            # Keyframe fijo: la imagen generada ES el último frame de la
            # escena; los adaptadores de video (fase `video=true`) traerán el
            # lastFrame real del proveedor.
            ultimo_frame=datos,
        )

    def _llamar(self, cliente: Any, pedido: PedidoKeyframe, referencias) -> Any:
        raise NotImplementedError

    def _extraer_imagen(self, respuesta: Any, pedido: PedidoKeyframe) -> Tuple[bytes, str]:
        raise NotImplementedError

    def _seed(self, respuesta: Any) -> Optional[int]:
        """Seed que el proveedor devuelva; default None (no expuesta)."""
        return None

    def _id_externo(self, respuesta: Any) -> Optional[str]:
        """Id de la respuesta del proveedor, si la expone."""
        return getattr(respuesta, "id", None)

    def _parametros(
        self, pedido: PedidoKeyframe, referencias, respuesta: Any
    ) -> Dict[str, Any]:
        parametros = {
            "aspect_ratio": pedido.aspect_ratio,
            "referencias": len(referencias),
            "encadenado": pedido.frame_inicial is not None,
        }
        # Escalado del bucle de QA (§7): se registra en el manifest aunque el
        # proveedor no soporte el parámetro (los actuales no exponen peso/seed).
        if pedido.peso_referencia is not None:
            parametros["peso_referencia"] = pedido.peso_referencia
        if pedido.seed is not None:
            parametros["seed"] = pedido.seed
        return parametros

    # ------------------------------ manifest ------------------------------

    def _manifest(
        self, pedido: PedidoKeyframe, referencias, respuesta: Any
    ) -> ManifestDeGeneracion:
        return ManifestDeGeneracion(
            proveedor=self.PROVEEDOR,
            modelo=self._modelo,
            seed=self._seed(respuesta),
            prompt_final=pedido.prompt_final,
            anclas_usadas=[r.triple for r in referencias],
            parametros=self._parametros(pedido, referencias, respuesta),
            id_externo=self._id_externo(respuesta),
            creado_en=datetime.now(timezone.utc),
        )
