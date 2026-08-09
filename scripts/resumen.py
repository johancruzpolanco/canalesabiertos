#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Imprime un resumen en Markdown del catálogo generado.
Se usa para alimentar el "Job Summary" de GitHub Actions.

Uso: python scripts/resumen.py [ruta_channels_json]
"""

import json
import sys
from pathlib import Path


def main() -> int:
    ruta = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/channels.json")

    if not ruta.exists():
        print(f"⚠️ No se encontró `{ruta}`: la generación falló.")
        return 1

    datos = json.loads(ruta.read_text(encoding="utf-8"))
    categorias = datos.get("categorias", [])

    print("## 📺 Lista actualizada")
    print()
    print(f"- **Canales:** {datos.get('total', 0)}")
    print(f"- **Categorías:** {len(categorias)}")
    print(f"- **Generado:** {datos.get('generado', '?')}")
    print(f"- **Fuente:** `{datos.get('origen', '?')}`")
    print()
    print("| Categoría | Canales |")
    print("|---|---:|")
    for categoria in categorias:
        print(f"| {categoria['nombre']} | {categoria['canales']} |")

    activos = [c for c in datos.get("canales", []) if "activo" in c]
    if activos:
        caidos = sum(1 for c in activos if not c["activo"])
        print()
        print(f"**Verificación:** {len(activos) - caidos} activos · {caidos} sin respuesta")

    return 0


if __name__ == "__main__":
    sys.exit(main())
