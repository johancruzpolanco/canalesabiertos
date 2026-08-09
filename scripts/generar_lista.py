#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generador de listas M3U categorizadas a partir de la API de TVAbierta.

Fuentes (en orden de preferencia):
  1. https://tvabierta.net/api/tv/channels.json   (catálogo oficial en JSON)
  2. https://tvabierta.net/bb.m3u                 (respaldo en M3U plano)

Genera en el directorio de salida:
  tvabierta.m3u              lista completa, ordenada y categorizada
  channels.json              catálogo normalizado (con metadatos)
  categorias/<slug>.m3u      una lista independiente por categoría
  CANALES.md                 índice legible para GitHub

Sin dependencias externas: solo biblioteca estándar de Python 3.9+.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# --------------------------------------------------------------------------
# Rutas y constantes
# --------------------------------------------------------------------------

RAIZ = Path(__file__).resolve().parent.parent
DIR_CONFIG = RAIZ / "config"

FUENTES_JSON = [
    "https://tvabierta.net/api/tv/channels.json",
]
FUENTES_M3U = [
    "https://tvabierta.net/bb.m3u",
]

USER_AGENT = "tvabierta-lista/1.0 (+https://github.com)"
TIMEOUT = 25

# Siglas que deben quedar en mayúsculas al embellecer nombres.
SIGLAS = {
    "tv", "tvi", "hd", "fhd", "sd", "uhd", "4k", "cdn", "rnn", "rtvd", "ztv",
    "retv", "tvo", "rcn", "cnn", "hbo", "tnt", "dw", "npr", "usa", "eeuu",
    "rd", "mx", "us", "ar", "co", "pe", "ve", "cl", "es", "pr", "am", "fm",
    "tve", "ntn24", "rt", "abc", "nbc", "cbs", "bbc", "mtv", "vh1", "ppv",
    "iptv", "ip", "hls", "ts", "sur", "unt", "atv", "utv", "ctv", "ntv",
}


# --------------------------------------------------------------------------
# Utilidades de texto
# --------------------------------------------------------------------------

def quitar_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def slug(texto: str) -> str:
    """Convierte un texto en un identificador seguro para nombres de archivo."""
    base = quitar_acentos(str(texto or "")).lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base or "sin-categoria"


def normalizar_url(url: str) -> str:
    """
    Codifica en porcentaje los caracteres no ASCII de una URL.

    El catálogo trae rutas con acentos, p. ej.
    ".../ssh101/Cosmovisión/playlist.m3u8". Muchos reproductores y clientes
    HTTP estrictos rechazan esa URL; percent-encoded funciona en todos.
    """
    url = url.strip()
    if url.isascii():
        return url

    partes = urllib.parse.urlsplit(url)

    # El host, si lleva acentos o eñes, va en IDNA (punycode).
    host = partes.netloc
    if not host.isascii():
        nombre, sep, puerto = host.rpartition(":")
        dominio = nombre if sep else host
        try:
            dominio = dominio.encode("idna").decode("ascii")
            host = f"{dominio}:{puerto}" if sep else dominio
        except (UnicodeError, ValueError):
            pass  # Host no convertible: se deja tal cual.

    return urllib.parse.urlunsplit((
        partes.scheme,
        host,
        urllib.parse.quote(partes.path, safe="/%:@&=+$,~()!*'"),
        urllib.parse.quote(partes.query, safe="/%:@&=+$,~?()!*'"),
        urllib.parse.quote(partes.fragment, safe="/%:@&=+$,~?"),
    ))


def reparar_mojibake(texto: str) -> str:
    """
    Corrige texto UTF-8 que fue decodificado como Latin-1 ("JimanÃ­TV").
    Solo aplica la corrección si el resultado es válido; si no, devuelve el original.
    """
    if not texto or not any(c in texto for c in ("Ã", "Â", "â€")):
        return texto
    try:
        arreglado = texto.encode("latin-1").decode("utf-8")
        return arreglado if arreglado.strip() else texto
    except (UnicodeEncodeError, UnicodeDecodeError):
        return texto


def embellecer_nombre(nombre: str, overrides: dict) -> str:
    """
    Normaliza nombres del catálogo, que llegan mayormente en minúsculas y
    pegados: "misioneltv" -> "Misionel TV", "antena7" -> "Antena 7".

    Los casos especiales se resuelven en config/nombres.json, que tiene
    prioridad absoluta sobre las reglas automáticas.
    """
    nombre = reparar_mojibake(str(nombre or "")).strip()
    nombre = re.sub(r"\s+", " ", nombre)
    if not nombre:
        return "Canal"

    # 1. Sustitución manual (config/nombres.json), sin distinguir mayúsculas.
    manual = overrides.get(nombre.lower())
    if manual:
        return manual

    # 2. Si el nombre ya viene con formato humano (mayúsculas intermedias o
    #    varias palabras), se respeta tal cual.
    if " " in nombre or (nombre != nombre.lower() and nombre != nombre.upper()):
        return _mayusculas_siglas(nombre)

    trabajo = nombre.lower()

    # 3. Separar el sufijo/prefijo "tv" pegado, solo si queda una raíz con
    #    cuerpo suficiente ("misioneltv" sí, "retv" no).
    if trabajo.endswith("tv") and len(trabajo) >= 6:
        trabajo = trabajo[:-2] + " tv"
    elif trabajo.startswith("tv") and len(trabajo) >= 6:
        trabajo = "tv " + trabajo[2:]

    # 4. Separar el límite entre letras y dígitos: "antena7" -> "antena 7".
    trabajo = re.sub(r"(?<=[a-záéíóúñ])(?=\d)", " ", trabajo)
    trabajo = re.sub(r"(?<=\d)(?=[a-záéíóúñ])", " ", trabajo)
    trabajo = re.sub(r"\s+", " ", trabajo).strip()

    return _mayusculas_siglas(trabajo)


def _mayusculas_siglas(texto: str) -> str:
    """Capitaliza cada palabra, dejando las siglas conocidas en mayúsculas."""
    palabras = []
    for palabra in texto.split(" "):
        if not palabra:
            continue
        limpio = quitar_acentos(palabra).lower()
        if limpio in SIGLAS:
            palabras.append(palabra.upper())
        elif palabra.isdigit():
            palabras.append(palabra)
        elif palabra == palabra.lower():
            palabras.append(palabra[0].upper() + palabra[1:])
        else:
            palabras.append(palabra)
    return " ".join(palabras)


# --------------------------------------------------------------------------
# Descarga
# --------------------------------------------------------------------------

def descargar(url: str) -> bytes:
    peticion = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(peticion, timeout=TIMEOUT) as respuesta:
        return respuesta.read()


def obtener_catalogo() -> tuple[list[dict], str]:
    """
    Devuelve (canales_crudos, origen). Intenta el JSON oficial y, si falla,
    recurre al M3U plano igual que hace la propia web de TVAbierta.
    """
    errores = []

    for url in FUENTES_JSON:
        try:
            datos = json.loads(descargar(url).decode("utf-8"))
            canales = _extraer_lista(datos)
            if canales:
                print(f"[ok] Catálogo JSON desde {url}: {len(canales)} entradas")
                return canales, url
            errores.append(f"{url}: JSON sin canales")
        except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError) as e:
            errores.append(f"{url}: {e}")
            print(f"[aviso] Falló {url}: {e}", file=sys.stderr)

    for url in FUENTES_M3U:
        try:
            texto = descargar(url).decode("utf-8", errors="replace")
            canales = parsear_m3u(texto)
            if canales:
                print(f"[ok] Respaldo M3U desde {url}: {len(canales)} entradas")
                return canales, url
            errores.append(f"{url}: M3U sin canales")
        except (urllib.error.URLError, OSError, ValueError) as e:
            errores.append(f"{url}: {e}")
            print(f"[aviso] Falló {url}: {e}", file=sys.stderr)

    raise SystemExit(
        "No se pudo obtener el catálogo desde ninguna fuente:\n  - "
        + "\n  - ".join(errores)
    )


def _extraer_lista(datos) -> list[dict]:
    """El JSON puede venir como lista suelta o envuelto en channels/data/items."""
    if isinstance(datos, list):
        return datos
    for clave in ("channels", "data", "items"):
        valor = datos.get(clave) if isinstance(datos, dict) else None
        if isinstance(valor, list):
            return valor
    return []


def parsear_m3u(texto: str) -> list[dict]:
    """Parser mínimo de M3U, usado solo como respaldo."""
    canales = []
    actual = {}
    for linea in texto.splitlines():
        linea = linea.strip()
        if linea.startswith("#EXTINF"):
            atributos = dict(re.findall(r'([\w-]+)="([^"]*)"', linea))
            actual = {
                "name": linea.split(",", 1)[-1].strip() if "," in linea else "Canal",
                "category": atributos.get("group-title", ""),
                "logo": atributos.get("tvg-logo", ""),
                "tvg_id": atributos.get("tvg-id", ""),
                "tvg_name": atributos.get("tvg-name", ""),
            }
        elif linea and not linea.startswith("#"):
            if actual:
                actual["stream"] = linea
                canales.append(actual)
                actual = {}
    return canales


# --------------------------------------------------------------------------
# Normalización
# --------------------------------------------------------------------------

def cargar_config(nombre: str, por_defecto):
    ruta = DIR_CONFIG / nombre
    if not ruta.exists():
        print(f"[aviso] No existe {ruta}, se usan valores por defecto", file=sys.stderr)
        return por_defecto
    with ruta.open(encoding="utf-8") as f:
        return json.load(f)


def resolver_categoria(cruda: str, config: dict) -> dict:
    """
    Traduce el código de categoría de la API ("RD", "Cl", "NEWS") a una
    categoría presentable, aplicando primero los alias de config.
    """
    clave = str(cruda or "").strip()
    alias = config.get("alias", {})
    # Los alias se comparan en mayúsculas para unificar "Cl" y "CL" (Chile).
    canonica = alias.get(clave) or alias.get(clave.upper()) or clave.upper()

    definicion = config.get("categorias", {}).get(canonica)
    if not definicion:
        definicion = dict(config.get("por_defecto", {"nombre": "Otros", "emoji": "📺", "orden": 900}))
        definicion["nombre"] = definicion.get("nombre", "Otros")

    return {
        "codigo": canonica,
        "nombre": definicion.get("nombre", canonica),
        "emoji": definicion.get("emoji", ""),
        "orden": int(definicion.get("orden", 900)),
    }


def normalizar(crudos: list[dict], cfg_categorias: dict, overrides: dict,
               usar_emojis: bool) -> list[dict]:
    """Limpia, deduplica y ordena el catálogo."""
    vistos_url = set()
    canales = []
    descartados = {"sin_url": 0, "deshabilitados": 0, "duplicados": 0}

    for indice, item in enumerate(crudos):
        if not isinstance(item, dict):
            continue

        if item.get("enabled") is False:
            descartados["deshabilitados"] += 1
            continue

        url = str(
            item.get("stream")
            or item.get("url")
            or item.get("stream_url")
            or item.get("src")
            or item.get("link")
            or ""
        ).strip()

        if not re.match(r"^https?://", url, re.I):
            descartados["sin_url"] += 1
            continue

        url = normalizar_url(url)

        if url in vistos_url:
            descartados["duplicados"] += 1
            continue
        vistos_url.add(url)

        nombre = embellecer_nombre(
            item.get("name") or item.get("title") or item.get("channel_name") or f"Canal {indice + 1}",
            overrides,
        )

        cat = resolver_categoria(
            item.get("category") or item.get("group") or item.get("group-title") or "",
            cfg_categorias,
        )
        grupo = f"{cat['emoji']} {cat['nombre']}".strip() if usar_emojis else cat["nombre"]

        logo = reparar_mojibake(str(item.get("logo") or item.get("tvg-logo") or "").strip())
        if not re.match(r"^https?://", logo, re.I):
            logo = ""

        numero = item.get("number") or item.get("channel_number") or indice + 1
        try:
            numero = int(numero)
        except (TypeError, ValueError):
            numero = indice + 1

        canales.append({
            "id": str(item.get("id") or "").strip() or slug(nombre),
            "numero": numero,
            "nombre": nombre,
            "categoria": grupo,
            "categoria_codigo": cat["codigo"],
            "categoria_orden": cat["orden"],
            "logo": logo,
            "url": url,
            "tvg_id": str(item.get("tvg_id") or item.get("tvg-id") or "").strip(),
            "slug": slug(nombre),
        })

    canales.sort(key=lambda c: (c["categoria_orden"], c["categoria"], c["numero"], c["nombre"]))

    print(
        f"[ok] Normalizados {len(canales)} canales "
        f"(duplicados: {descartados['duplicados']}, "
        f"sin URL: {descartados['sin_url']}, "
        f"deshabilitados: {descartados['deshabilitados']})"
    )
    return canales


# --------------------------------------------------------------------------
# Verificación opcional de enlaces
# --------------------------------------------------------------------------

def verificar_canal(canal: dict, timeout: int = 10) -> bool:
    """Comprueba que el stream responda. No descarga el vídeo completo."""
    peticion = urllib.request.Request(
        canal["url"],
        headers={"User-Agent": USER_AGENT, "Range": "bytes=0-2047"},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            return respuesta.status < 400 and bool(respuesta.read(1))
    except Exception:
        return False


def verificar_todos(canales: list[dict], hilos: int = 16) -> None:
    print(f"[..] Verificando {len(canales)} enlaces con {hilos} hilos...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=hilos) as pool:
        resultados = list(pool.map(verificar_canal, canales))
    for canal, activo in zip(canales, resultados):
        canal["activo"] = activo
    caidos = resultados.count(False)
    print(f"[ok] Verificación: {len(canales) - caidos} activos, {caidos} sin respuesta")


# --------------------------------------------------------------------------
# Salidas
# --------------------------------------------------------------------------

def escribir(ruta: Path, contenido: str) -> None:
    """Escribe siempre en UTF-8 con saltos LF para no ensuciar el diff en Git."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="\n") as f:
        f.write(contenido)
    print(f"[ok] {ruta.relative_to(RAIZ) if RAIZ in ruta.parents else ruta}")


def construir_m3u(canales: list[dict], epg_url: str = "") -> str:
    cabecera = '#EXTM3U' + (f' x-tvg-url="{epg_url}"' if epg_url else "")
    lineas = [cabecera]
    for canal in canales:
        atributos = (
            f'#EXTINF:-1 tvg-id="{canal["tvg_id"]}" '
            f'tvg-name="{canal["nombre"]}" '
            f'tvg-chno="{canal["numero"]}" '
            f'tvg-logo="{canal["logo"]}" '
            f'group-title="{canal["categoria"]}",{canal["nombre"]}'
        )
        lineas.append(atributos)
        # #EXTGRP mejora la compatibilidad con reproductores antiguos.
        lineas.append(f'#EXTGRP:{canal["categoria"]}')
        lineas.append(canal["url"])
    return "\n".join(lineas) + "\n"


def agrupar(canales: list[dict]) -> dict[str, list[dict]]:
    grupos: dict[str, list[dict]] = {}
    for canal in canales:
        grupos.setdefault(canal["categoria"], []).append(canal)
    return grupos


def construir_markdown(canales: list[dict], grupos: dict, generado: str,
                       origen: str, repo_raw: str) -> str:
    lineas = [
        "# 📺 Canales disponibles",
        "",
        f"**Total:** {len(canales)} canales en {len(grupos)} categorías  ",
        f"**Actualizado:** {generado}  ",
        f"**Fuente:** `{origen}`",
        "",
        "## Listas por categoría",
        "",
        "| Categoría | Canales | Lista M3U |",
        "|---|---:|---|",
    ]

    for categoria, items in grupos.items():
        archivo = f"categorias/{slug(categoria)}.m3u"
        enlace = f"{repo_raw}/{archivo}" if repo_raw else archivo
        lineas.append(f"| {categoria} | {len(items)} | [`{slug(categoria)}.m3u`]({enlace}) |")

    lineas += ["", "## Detalle", ""]

    for categoria, items in grupos.items():
        lineas.append(f"<details><summary><b>{categoria}</b> ({len(items)} canales)</summary>")
        lineas.append("")
        for canal in items:
            estado = ""
            if "activo" in canal:
                estado = " ✅" if canal["activo"] else " ⚠️"
            lineas.append(f"- {canal['nombre']}{estado}")
        lineas += ["", "</details>", ""]

    return "\n".join(lineas) + "\n"


# --------------------------------------------------------------------------
# Programa principal
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Genera listas M3U categorizadas desde la API de TVAbierta."
    )
    parser.add_argument("--salida", default="dist", help="Directorio de salida (por defecto: dist)")
    parser.add_argument("--verificar", action="store_true",
                        help="Comprueba que cada stream responda (lento)")
    parser.add_argument("--excluir-caidos", action="store_true",
                        help="Con --verificar, omite los canales que no responden")
    parser.add_argument("--sin-emojis", action="store_true",
                        help="Categorías sin emoji, para reproductores que no los muestran")
    parser.add_argument("--epg", default="", help="URL de EPG/XMLTV para la cabecera M3U")
    parser.add_argument("--repo-raw", default="",
                        help="URL base raw de GitHub para los enlaces del índice")
    args = parser.parse_args()

    salida = (RAIZ / args.salida).resolve()

    cfg_categorias = cargar_config("categorias.json", {"alias": {}, "categorias": {}})
    overrides_crudos = cargar_config("nombres.json", {})
    overrides = {str(k).lower(): v for k, v in overrides_crudos.items()}

    crudos, origen = obtener_catalogo()
    canales = normalizar(crudos, cfg_categorias, overrides, usar_emojis=not args.sin_emojis)

    if not canales:
        print("[error] El catálogo quedó vacío tras normalizar", file=sys.stderr)
        return 1

    if args.verificar:
        verificar_todos(canales)
        if args.excluir_caidos:
            antes = len(canales)
            canales = [c for c in canales if c.get("activo")]
            print(f"[ok] Excluidos {antes - len(canales)} canales caídos")

    generado = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    grupos = agrupar(canales)

    # 1. Lista completa
    m3u_completo = construir_m3u(canales, args.epg)
    escribir(salida / "tvabierta.m3u", m3u_completo)

    # 2. Una lista por categoría
    for categoria, items in grupos.items():
        escribir(salida / "categorias" / f"{slug(categoria)}.m3u",
                 construir_m3u(items, args.epg))

    # 3. Catálogo JSON normalizado
    catalogo = {
        "generado": generado,
        "origen": origen,
        "total": len(canales),
        "hash": hashlib.sha256(m3u_completo.encode("utf-8")).hexdigest(),
        "categorias": [
            {"nombre": nombre, "canales": len(items), "archivo": f"categorias/{slug(nombre)}.m3u"}
            for nombre, items in grupos.items()
        ],
        "canales": canales,
    }
    escribir(salida / "channels.json",
             json.dumps(catalogo, ensure_ascii=False, indent=2) + "\n")

    # 4. Índice legible
    escribir(salida / "CANALES.md",
             construir_markdown(canales, grupos, generado, origen, args.repo_raw.rstrip("/")))

    print(f"\n✅ Listo: {len(canales)} canales en {len(grupos)} categorías -> {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
