"""QA visual de keyframes contra la biblioteca de anclas (spec-recursos-ancla §7).

El servicio compara cada keyframe contra la batería de sus anclas lockeadas:

- **Cara** (ancla ``personaje``): similitud coseno entre el embedding de cara
  del keyframe (ArcFace/InsightFace) y el ``hero_portrait`` lockeado; umbral
  default 0.35 (§3.5: la banda típica "misma identidad" es 0.35-0.45).
- **Sin cara** (``lugar``/``objeto``/``estilo``): coseno DINOv2 contra la
  batería (máximo sobre las imágenes relevantes) y **CLIP** para la adherencia
  prompt-imagen (§3.5: coseno crudo ~0.20-0.26, umbral default 0.20).
- **Dedup**: pHash entre keyframes del mismo capítulo — distancia de Hamming
  ≤10 delata escenas gemelas.

Las dependencias pesadas (torch/insightface/CLIP/ImageHash) viven en el extra
opcional ``sinnema[qa]`` y entran SOLO por los extractores inyectables: el
servicio es puro cálculo de métricas sobre embeddings y hashes, de modo que la
suite lo testea con fixtures de juguete sin instalar nada. Sin extractores la
corrida NO se tumba: cada métrica sin extractor se omite con un aviso (política
de degradación elegante §13-F4) y ``construir_qa_visual`` devuelve ``None``.
"""
from __future__ import annotations

import logging
import os
from typing import Callable, List, Optional, Protocol, Sequence, Tuple

from sinnema.domain.models import InformeQaVisual, RecursoAncla, ReferenciaAncla

logger = logging.getLogger("sinnema.media.qa")

#: Umbral "misma identidad" por cara (§3.5 / §7): env ``MEDIA_QA_UMBRAL_CARA``.
UMBRAL_CARA_DEFAULT = 0.35

#: Adherencia prompt-imagen con CLIP (§3.5): env ``MEDIA_QA_UMBRAL_PROMPT``.
UMBRAL_PROMPT_DEFAULT = 0.20

#: Distancia de Hamming (64 bits) a partir de la cual dos keyframes son
#: "gemelas" (§3.5: pHash ≤10).
DISTANCIA_PHASH_GEMELA = 10

#: Cargador de bytes de una imagen de batería: (project_id, ancla_id, archivo).
CargarImagenDeBateria = Callable[[str, str, str], bytes]


class ExtractorDeCaras(Protocol):
    """Embedding de la cara principal de una imagen (ArcFace/InsightFace).

    Devuelve ``None`` si no hay cara detectable: el keyframe se informa con un
    aviso en vez de inventar un score.
    """

    def embedding_de_cara(self, datos: bytes) -> Optional[List[float]]: ...


class ExtractorDeEmbeddings(Protocol):
    """Embeddings para las métricas sin cara.

    ``embedding_imagen`` es DINOv2 (similitud de escena contra la batería);
    ``embedding_imagen_clip``/``embedding_texto`` son el par CLIP visual/texto
    con el que se mide la adherencia prompt-imagen (§3.5).
    """

    def embedding_imagen(self, datos: bytes) -> Optional[List[float]]: ...

    def embedding_imagen_clip(self, datos: bytes) -> Optional[List[float]]: ...

    def embedding_texto(self, prompt: str) -> Optional[List[float]]: ...


class HasherImagenes(Protocol):
    """pHash de 64 bits de una imagen (ImageHash sobre PIL)."""

    def phash(self, datos: bytes) -> Optional[int]: ...


def coseno(a: Sequence[float], b: Sequence[float]) -> float:
    """Coseno crudo entre dos embeddings; vectores vacíos/irregulares → 0.0."""
    if not a or not b or len(a) != len(b):
        return 0.0
    producto = sum(x * y for x, y in zip(a, b))
    norma_a = sum(x * x for x in a) ** 0.5
    norma_b = sum(y * y for y in b) ** 0.5
    if norma_a == 0.0 or norma_b == 0.0:
        return 0.0
    return producto / (norma_a * norma_b)


def distancia_hamming(a: int, b: int) -> int:
    """Bits distintos entre dos hashes de 64 bits."""
    return bin(a ^ b).count("1")


def _umbral_de_entorno(variable: str, default: float) -> float:
    bruto = os.getenv(variable, "").strip()
    if not bruto:
        return default
    try:
        return float(bruto)
    except ValueError:
        logger.warning(
            "%s='%s' no es un número: se usa el default %s.", variable, bruto, default
        )
        return default


class QaVisualService:
    """Evalúa keyframes contra la batería lockeada (spec §7).

    ``evaluar_keyframe`` devuelve ``(informes, avisos)``: los informes son la
    salida validada que viaja al adjunto ``media``; los avisos registran
    métricas omitidas (extractor ausente, sin cara detectable) para que la
    auditoría y la UI puedan mostrar la degradación sin inventar éxito.
    """

    def __init__(
        self,
        *,
        cargar_imagen: CargarImagenDeBateria,
        extractor_caras: Optional[ExtractorDeCaras] = None,
        extractor_embeddings: Optional[ExtractorDeEmbeddings] = None,
        hasher: Optional[HasherImagenes] = None,
        umbral_cara: Optional[float] = None,
        umbral_prompt: Optional[float] = None,
        distancia_phash_maxima: int = DISTANCIA_PHASH_GEMELA,
    ) -> None:
        self._cargar_imagen = cargar_imagen
        self._caras = extractor_caras
        self._embeddings = extractor_embeddings
        self._hasher = hasher
        self._umbral_cara = (
            umbral_cara
            if umbral_cara is not None
            else _umbral_de_entorno("MEDIA_QA_UMBRAL_CARA", UMBRAL_CARA_DEFAULT)
        )
        self._umbral_prompt = (
            umbral_prompt
            if umbral_prompt is not None
            else _umbral_de_entorno("MEDIA_QA_UMBRAL_PROMPT", UMBRAL_PROMPT_DEFAULT)
        )
        self._distancia_phash_maxima = distancia_phash_maxima

    # ------------------------------ API ------------------------------

    def evaluar_keyframe(
        self,
        *,
        escena: int,
        project_id: str,
        prompt: str,
        datos_keyframe: bytes,
        pares: Sequence[Tuple[ReferenciaAncla, RecursoAncla]],
        previos: Sequence[Tuple[int, bytes]] = (),
    ) -> Tuple[List[InformeQaVisual], List[str]]:
        """Compara el keyframe con cada ancla citada y con los keyframes previos.

        ``pares`` son (referencia, ancla) en el orden identidad-primero que ya
        compone el nodo; ``previos`` son los ``(escena, bytes)`` ya generados
        del capítulo para el dedup.
        """
        informes: List[InformeQaVisual] = []
        avisos: List[str] = []

        embedding_keyframe: Optional[List[float]] = None
        embedding_clip: Optional[List[float]] = None
        embedding_keyframe_consultado = False
        hash_keyframe: Optional[int] = None

        for referencia, ancla in pares:
            if ancla.tipo == "personaje":
                self._evaluar_cara(
                    escena, project_id, ancla, datos_keyframe,
                    informes, avisos,
                )
                continue
            if self._embeddings is None:
                avisos.append(
                    f"escena {escena}: sin extractor de embeddings (extra 'qa' no "
                    f"instalado): la ancla '{ancla.ancla_id}' quedó sin QA DINOv2/CLIP."
                )
                continue
            if not embedding_keyframe_consultado:
                embedding_keyframe = self._embeddings.embedding_imagen(datos_keyframe)
                embedding_clip = self._embeddings.embedding_imagen_clip(datos_keyframe)
                embedding_keyframe_consultado = True
                if embedding_keyframe is None:
                    avisos.append(
                        f"escena {escena}: el extractor no produjo embedding del "
                        "keyframe: QA DINOv2/CLIP omitido."
                    )
            if embedding_keyframe is None:
                continue
            self._evaluar_escena(
                escena, project_id, ancla, referencia,
                embedding_keyframe, informes, avisos,
            )
            self._evaluar_prompt(
                escena, ancla, prompt, embedding_clip, informes, avisos,
            )

        if previos and self._hasher is not None:
            hash_keyframe = self._hasher.phash(datos_keyframe)
            if hash_keyframe is not None:
                informes.extend(self._evaluar_dedup(escena, hash_keyframe, previos, avisos))
        elif previos and self._hasher is None:
            avisos.append(
                f"escena {escena}: sin hasher de imágenes (extra 'qa' no instalado): "
                "dedup pHash omitido."
            )

        return informes, avisos

    # ------------------------------ métricas ------------------------------

    def _evaluar_cara(
        self,
        escena: int,
        project_id: str,
        ancla: RecursoAncla,
        datos_keyframe: bytes,
        informes: List[InformeQaVisual],
        avisos: List[str],
    ) -> None:
        if self._caras is None:
            avisos.append(
                f"escena {escena}: sin extractor de caras (extra 'qa' no instalado): "
                f"la ancla '{ancla.ancla_id}' quedó sin QA de identidad."
            )
            return
        hero = next(
            (img for img in ancla.bateria if img.rol == "hero_portrait"), None
        )
        if hero is None:
            avisos.append(
                f"escena {escena}: la ancla '{ancla.ancla_id}' no tiene "
                "hero_portrait en su batería: QA de cara omitido."
            )
            return
        cara_keyframe = self._caras.embedding_de_cara(datos_keyframe)
        if cara_keyframe is None:
            avisos.append(
                f"escena {escena}: sin cara detectable en el keyframe: QA de la "
                f"ancla '{ancla.ancla_id}' omitido."
            )
            return
        cara_referencia = self._caras.embedding_de_cara(
            self._cargar_imagen(project_id, ancla.ancla_id, hero.archivo)
        )
        if cara_referencia is None:
            avisos.append(
                f"escena {escena}: sin cara detectable en el hero_portrait de "
                f"'{ancla.ancla_id}': QA de cara omitido."
            )
            return
        score = coseno(cara_keyframe, cara_referencia)
        informes.append(
            InformeQaVisual(
                escena=escena,
                ancla_id=ancla.ancla_id,
                metrica="cara_coseno",
                score=round(score, 4),
                umbral=self._umbral_cara,
                aprueba=score >= self._umbral_cara,
                detalle=(
                    f"Coseno de cara contra {hero.archivo} "
                    f"(umbral identidad {self._umbral_cara}, §3.5)."
                ),
            )
        )

    def _evaluar_escena(
        self,
        escena: int,
        project_id: str,
        ancla: RecursoAncla,
        referencia: ReferenciaAncla,
        embedding_keyframe: List[float],
        informes: List[InformeQaVisual],
        avisos: List[str],
    ) -> None:
        imagenes = [
            img
            for img in ancla.bateria
            if not referencia.roles or img.rol in referencia.roles
        ]
        if not imagenes:
            avisos.append(
                f"escena {escena}: la ancla '{ancla.ancla_id}' no tiene imágenes "
                "de los roles pedidos: QA DINOv2 omitido."
            )
            return
        mejor = None
        for imagen in imagenes:
            embedding = self._embeddings.embedding_imagen(
                self._cargar_imagen(project_id, ancla.ancla_id, imagen.archivo)
            )
            if embedding is None:
                continue
            score = coseno(embedding_keyframe, embedding)
            if mejor is None or score > mejor:
                mejor = score
        if mejor is None:
            avisos.append(
                f"escena {escena}: el extractor no produjo embeddings de la "
                f"batería de '{ancla.ancla_id}': QA DINOv2 omitido."
            )
            return
        informes.append(
            InformeQaVisual(
                escena=escena,
                ancla_id=ancla.ancla_id,
                metrica="escena_dino",
                score=round(mejor, 4),
                umbral=self._umbral_prompt,
                aprueba=mejor >= self._umbral_prompt,
                detalle=(
                    f"Máximo coseno DINOv2 contra {len(imagenes)} imagen(es) de "
                    "la batería."
                ),
            )
        )

    def _evaluar_prompt(
        self,
        escena: int,
        ancla: RecursoAncla,
        prompt: str,
        embedding_clip: Optional[List[float]],
        informes: List[InformeQaVisual],
        avisos: List[str],
    ) -> None:
        if embedding_clip is None:
            avisos.append(
                f"escena {escena}: el extractor no produjo embedding CLIP del "
                f"keyframe: QA CLIP de '{ancla.ancla_id}' omitido."
            )
            return
        embedding_prompt = self._embeddings.embedding_texto(prompt)
        if embedding_prompt is None:
            avisos.append(
                f"escena {escena}: el extractor no produjo embedding del prompt: "
                "QA CLIP omitido."
            )
            return
        score = coseno(embedding_clip, embedding_prompt)
        informes.append(
            InformeQaVisual(
                escena=escena,
                ancla_id=ancla.ancla_id,
                metrica="clip_prompt",
                score=round(score, 4),
                umbral=self._umbral_prompt,
                aprueba=score >= self._umbral_prompt,
                detalle="Coseno CLIP prompt-imagen (adherencia, §3.5).",
            )
        )

    def _evaluar_dedup(
        self,
        escena: int,
        hash_keyframe: int,
        previos: Sequence[Tuple[int, bytes]],
        avisos: List[str],
    ) -> List[InformeQaVisual]:
        gemelas: List[str] = []
        for escena_previa, datos_previos in previos:
            hash_previo = self._hasher.phash(datos_previos)
            if hash_previo is None:
                continue
            distancia = distancia_hamming(hash_keyframe, hash_previo)
            if distancia <= self._distancia_phash_maxima:
                gemelas.append(f"escena {escena_previa} (Hamming {distancia})")
        if not gemelas:
            return []
        return [
            InformeQaVisual(
                escena=escena,
                ancla_id="",
                metrica="phash_dedup",
                score=float(self._distancia_phash_maxima),
                umbral=float(self._distancia_phash_maxima),
                aprueba=False,
                detalle="Keyframe gemela de: " + ", ".join(gemelas) + ".",
            )
        ]
