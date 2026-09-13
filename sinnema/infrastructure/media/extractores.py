"""Extractores reales del QA visual (spec-recursos-ancla §3.5, §7).

Son las implementaciones de REFERENCIA sobre las libs pesadas del extra
``sinnema[qa]`` (insightface/onnxruntime, timm, open_clip, ImageHash): cada
constructor importa SUS dependencias en el momento de construirse, de modo que
``construir_qa_visual`` pueda degradar por extractor (una instalación parcial
deja correr las métricas cuyas libs sí están). La suite NO los ejercita: los
tests del servicio usan extractores de juguete inyectados.
"""
from __future__ import annotations

import io
from typing import List, Optional


class HasherPHash:
    """pHash de 64 bits sobre ImageHash/PIL (§3.5: Hamming ≤10 = gemelas)."""

    def __init__(self) -> None:
        import imagehash  # noqa: F401 - verificación de disponibilidad
        from PIL import Image

        self._phash = imagehash.phash
        self._imagen = Image

    def phash(self, datos: bytes) -> Optional[int]:
        try:
            with self._imagen.open(io.BytesIO(datos)) as imagen:
                return int(str(self._phash(imagen.convert("RGB"))), 16)
        except Exception:  # noqa: BLE001 - un archivo ilegible no tumba la corrida
            return None


class ExtractorCarasInsightFace:
    """Embedding de la cara principal (mayor bbox) con ArcFace/InsightFace."""

    def __init__(self) -> None:
        import numpy
        from insightface.app import FaceAnalysis

        self._np = numpy
        self._app = FaceAnalysis(providers=["CPUExecutionProvider"])
        self._app.prepare(ctx_id=0, det_size=(640, 640))

    def embedding_de_cara(self, datos: bytes) -> Optional[List[float]]:
        try:
            from PIL import Image

            imagen = self._imagen_rgb(datos, Image)
            caras = self._app.get(imagen)
        except Exception:  # noqa: BLE001 - imagen ilegible o detector sin salida
            return None
        if not caras:
            return None
        principal = max(
            caras,
            key=lambda cara: (cara.bbox[2] - cara.bbox[0]) * (cara.bbox[3] - cara.bbox[1]),
        )
        return [float(x) for x in principal.normed_embedding]

    def _imagen_rgb(self, datos: bytes, Image):  # noqa: N803 - convención PIL
        return self._np.array(Image.open(io.BytesIO(datos)).convert("RGB"))


class ExtractorDinoClip:
    """DINOv2 (timm) para similitud de escena + CLIP (open_clip) para prompt."""

    def __init__(self) -> None:
        import open_clip
        import timm
        import torch
        from PIL import Image

        self._torch = torch
        self._imagen = Image
        self._dino = timm.create_model("vit_base_patch14_dinov2.lvd142m", pretrained=True)
        datos_dino = timm.data.resolve_model_data_config(self._dino)
        self._preprocesador_dino = timm.data.create_transform(**datos_dino, is_training=False)
        self._dino.eval()
        self._clip, _, self._preprocesador_clip = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="openai"
        )
        self._tokenizador = open_clip.get_tokenizer("ViT-B-32")
        self._clip.eval()

    def _tensor(self, datos: bytes, preprocesador):
        imagen = self._imagen.open(io.BytesIO(datos)).convert("RGB")
        return preprocesador(imagen).unsqueeze(0)

    def _primer_embedding(self, tensor) -> List[float]:
        with self._torch.no_grad():
            return [float(x) for x in tensor[0]]

    def embedding_imagen(self, datos: bytes) -> Optional[List[float]]:
        try:
            with self._torch.no_grad():
                salida = self._dino(self._tensor(datos, self._preprocesador_dino))
            return self._primer_embedding(salida)
        except Exception:  # noqa: BLE001 - imagen ilegible no tumba la corrida
            return None

    def embedding_imagen_clip(self, datos: bytes) -> Optional[List[float]]:
        try:
            with self._torch.no_grad():
                salida = self._clip.encode_image(
                    self._tensor(datos, self._preprocesador_clip)
                )
            return self._primer_embedding(salida)
        except Exception:  # noqa: BLE001
            return None

    def embedding_texto(self, prompt: str) -> Optional[List[float]]:
        try:
            tokens = self._tokenizador([prompt])
            with self._torch.no_grad():
                salida = self._clip.encode_text(tokens)
            return self._primer_embedding(salida)
        except Exception:  # noqa: BLE001
            return None
