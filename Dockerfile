# Imagen de DESARROLLO del backend (issue #14): API FastAPI (sinnema-server).
# El código no se hornea: docker-compose.yml monta ./sinnema sobre /app/sinnema
# y con SINNEMA_RELOAD=1 el servidor se recarga al editar. Cambiar dependencias
# (pyproject.toml) sí requiere rebuild: docker compose build api.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # PYTHONPATH=/app hace que el código montado pise al instalado en
    # site-packages: el hot reload sirve los edits del host sin reinstalar.
    PYTHONPATH=/app

WORKDIR /app

# README.md y proyectos/ son necesarios para construir la wheel (hatchling:
# `readme` + force-include de los shows de muestra).
COPY pyproject.toml README.md ./
COPY sinnema ./sinnema
COPY proyectos ./proyectos

RUN pip install --no-cache-dir ".[server]"

EXPOSE 8000

CMD ["sinnema-server"]
