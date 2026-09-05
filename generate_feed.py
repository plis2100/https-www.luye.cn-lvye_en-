import re
import xml.etree.ElementTree as ET

from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator


SOURCE_URL = "https://www.luye.cn/lvye_en/news.php"
BASE_URL = "https://www.luye.cn/lvye_en/"
OUTPUT_FILE = Path("docs/feed.xml")
MAX_ITEMS = 80


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def limpiar(texto):
    return " ".join((texto or "").split())


def obtener_fecha(bloque):
    fecha = None

    # Noticias principales: August 31,2026
    elemento_fecha = bloque.select_one(".date")

    if elemento_fecha:
        texto_fecha = limpiar(elemento_fecha.get_text(" ", strip=True))

        for formato in ("%B %d,%Y", "%B %d, %Y"):
            try:
                fecha = datetime.strptime(texto_fecha, formato)
                break
            except ValueError:
                pass

    # Noticias de la lista: día 16 y mes 2026-06
    if fecha is None:
        dia = bloque.select_one(".inner-top")
        año_mes = bloque.select_one(".inner-bottom")

        if dia and año_mes:
            texto = (
                f"{limpiar(año_mes.get_text())}-"
                f"{limpiar(dia.get_text()).zfill(2)}"
            )

            try:
                fecha = datetime.strptime(texto, "%Y-%m-%d")
            except ValueError:
                pass

    if fecha is None:
        fecha = datetime.now(timezone.utc)
    else:
        fecha = fecha.replace(
            hour=8,
            minute=0,
            second=0,
            tzinfo=timezone.utc
        )

    return fecha


def leer_noticias_anteriores():
    anteriores = {}

    if not OUTPUT_FILE.exists():
        return anteriores

    try:
        root = ET.parse(OUTPUT_FILE).getroot()

        for item in root.findall("./channel/item"):
            enlace = limpiar(item.findtext("link"))

            if not enlace:
                continue

            anteriores[enlace] = {
                "title": limpiar(item.findtext("title")),
                "link": enlace,
                "description": limpiar(
                    item.findtext("description")
                ),
                "pubDate": limpiar(item.findtext("pubDate")),
            }

    except Exception as error:
        print(f"No se pudo leer la RSS anterior: {error}")

    return anteriores


def obtener_noticias():
    respuesta = requests.get(
        SOURCE_URL,
        headers=HEADERS,
        timeout=45
    )
    respuesta.raise_for_status()

    respuesta.encoding = respuesta.apparent_encoding
    soup = BeautifulSoup(respuesta.text, "html.parser")

    noticias = {}

    bloques = soup.select(
        ".neirong_content .first, "
        ".neirong_content .two, "
        ".lists .item"
    )

    for bloque in bloques:
        onclick = bloque.get("onclick", "")

        coincidencia = re.search(
            r"view\.php\?id=(\d+)",
            onclick
        )

        if not coincidencia:
            continue

        identificador = coincidencia.group(1)
        enlace = urljoin(BASE_URL, f"view.php?id={identificador}")

        titulo_elemento = bloque.select_one(
            ".jies p[title], .inner-right"
        )

        if not titulo_elemento:
            continue

        titulo = limpiar(
            titulo_elemento.get("title")
            or titulo_elemento.get_text(" ", strip=True)
        )

        if not titulo:
            continue

        descripcion_elemento = bloque.select_one(".piczhujie")

        if descripcion_elemento:
            descripcion = limpiar(
                descripcion_elemento.get_text(" ", strip=True)
            )
        else:
            descripcion = (
                "Nota de prensa publicada por Luye Pharma Group."
            )

        noticias[enlace] = {
            "title": titulo,
            "link": enlace,
            "description": descripcion,
            "date": obtener_fecha(bloque),
        }

    if not noticias:
        raise RuntimeError(
            "No se encontraron noticias. "
            "La RSS anterior no será eliminada."
        )

    return list(noticias.values())


def generar_rss(noticias):
    anteriores = leer_noticias_anteriores()
    combinadas = {}

    for noticia in noticias:
        combinadas[noticia["link"]] = {
            "title": noticia["title"],
            "link": noticia["link"],
            "description": noticia["description"],
            "pubDate": format_datetime(noticia["date"]),
        }

    # Conservar noticias antiguas aunque desaparezcan de la portada.
    for enlace, noticia in anteriores.items():
        if enlace not in combinadas:
            combinadas[enlace] = noticia

    def ordenar_por_fecha(noticia):
        try:
            return datetime.strptime(
                noticia["pubDate"],
                "%a, %d %b %Y %H:%M:%S %z"
            )
        except ValueError:
            return datetime(1970, 1, 1, tzinfo=timezone.utc)

    ordenadas = sorted(
        combinadas.values(),
        key=ordenar_por_fecha,
        reverse=True
    )[:MAX_ITEMS]

    feed = FeedGenerator()

    feed.title("Luye Pharma Group - News")
    feed.link(href=SOURCE_URL, rel="alternate")
    feed.description(
        "Últimas noticias y comunicados de Luye Pharma Group"
    )
    feed.language("en")
    feed.id(SOURCE_URL)
    feed.lastBuildDate(datetime.now(timezone.utc))

    for noticia in reversed(ordenadas):
        entrada = feed.add_entry()
        entrada.id(noticia["link"])
        entrada.title(noticia["title"])
        entrada.link(href=noticia["link"])
        entrada.description(noticia["description"])

        try:
            fecha = datetime.strptime(
                noticia["pubDate"],
                "%a, %d %b %Y %H:%M:%S %z"
            )
            entrada.pubDate(fecha)
        except ValueError:
            pass

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    feed.rss_file(str(OUTPUT_FILE), pretty=True)

    print(
        f"RSS creada correctamente con "
        f"{len(ordenadas)} noticias."
    )


if __name__ == "__main__":
    noticias_luye = obtener_noticias()
    generar_rss(noticias_luye)
