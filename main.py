#!/usr/bin/env python3
"""Punto de entrada delgado: delega toda la lógica en el paquete ``sinnema``.

Uso:
    python main.py                                  # serie por defecto (3 capítulos)
    python main.py -t "Fotosíntesis en 60s" -n 5
    python main.py -t "Regex desde cero" -n 4 -m 3 -o salidas/regex.json -v
"""
from __future__ import annotations

import sys

from sinnema.infrastructure.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
