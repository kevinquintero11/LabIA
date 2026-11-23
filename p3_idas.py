import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import math
    import sys
    from bisect import bisect_left, bisect_right
    from collections import defaultdict
    from datetime import UTC, datetime, timedelta
    from pathlib import Path

    import gc
    import shutil
    import zlib
    import numpy as np

    import ijson
    import marimo as mo
    import pandas as pd
    import polars as pl
    import tensorflow as tf

    from bson import a_dt, a_float, a_id

    # Marimo vuelve local cualquier nombre con _, por eso se comparten sin _.
    _directorio = str(Path(__file__).resolve().parent)
    if _directorio not in sys.path:
        sys.path.insert(0, _directorio)

    from bisect import bisect_left, bisect_right
    from collections import defaultdict
    from datetime import UTC, datetime, timedelta
    import json
    import math
    from pathlib import Path

    import ijson
    import numpy as np
    import pandas as pd
    import polars as pl
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    return (
        Path,
        UTC,
        a_dt,
        a_float,
        a_id,
        bisect_left,
        bisect_right,
        datetime,
        defaultdict,
        gc,
        ijson,
        json,
        math,
        mo,
        np,
        pl,
        shutil,
        sys,
        tf,
        timedelta,
        zlib,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # P3 — el reloj de una ida

    Mide cuánto tardó una ida con el reloj del GPS, no con OSRM ni con las observaciones.
    Los insumos ya están recortados: `entregables/p3/hojaDeRuta.json` y `entregables/p3/rastreoSatelital.json`.
    No es el dump de origen. Nada corre al abrir. Primero se mira una hoja. Después se cuentan todas.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Las reglas

    Una ida es la lista que OSRM guardó en la hoja, `geometriaOSRM.ida.puntos`. Cada punto de esa lista es un vértice. El primero es el arranque. El último es el final. Se numeran en el orden de la lista: 0, 1, 2, y así.

    La cantidad no la elige este notebook. La trae la hoja. OSRM pone más puntos en una curva y menos en una recta. Hay idas de pocos puntos y otras de miles. En las primeras 400 hojas de este archivo, la mediana es 671: del 0 al 670.

    - La salida es el primer 15 % de esa lista, no solo el punto 0. La llegada es el último 15 %, no solo el punto final. Ese 15 % es una fracción de la lista, no de los kilómetros.
        - En la ida de 671 puntos, la salida llega hasta el 100. La llegada arranca en el 570. Si otra hoja tiene 200 puntos, la salida llega hasta el 29. Cada hoja usa su propia lista.
    - Un ping entra si está a 250 m o menos de la ida. Hereda el número del vértice más cercano.
    - El móvil va hacia la llegada cuando ese número se queda o sube. Si el siguiente cae en un número anterior, miramos cuánto bajó.
        - El 3 es esa tolerancia, en posiciones de la lista. No son metros. Bajar 1, 2 o 3 no corta. Hace falta bajar 4 o más. En una curva, 3 números pueden ser pocos metros. En una recta, pueden ser un salto largo.
        - Iba en el 420 y el siguiente cae en el 418. Bajó 2. Es temblor del GPS: sigue la misma pasada.
        - Iba en el 420 y el siguiente cae en el 416. Bajó 4. Va para atrás. La pasada se cierra y el 416 no entra.
        - El que bajó 4 o más se descarta, salvo que ya esté en la salida. Ahí puede abrir otra pasada. Así una vuelta por la misma calle no se mezcla con la ida.
    - Un silencio de más de una hora corta la pasada solo en las puntas.
        - Corta si el ping de antes ya está en la llegada, o si el ping de después está en la salida.
        - En el medio, el GPS puede callarse y sigue la misma pasada.
    - Una pasada de un solo ping, o que no recorre al menos un 5 % de los números, se tira.
    - El reloj arranca cuando el móvil deja de estar quieto en la salida, y se detiene en el primer ping de la llegada.
        - La espera en el camino entra. La espera quieta en la salida, antes de moverse, no. Tampoco el rato sentado en la llegada después de haber llegado.
    """)
    return


@app.cell
def _(timedelta):

    RADIO_M = 250
    PASO_M = 200  # búsqueda sobre la recta, no un vértice
    HUECO = timedelta(hours=1)
    INICIO = 0.15
    FIN = 0.85
    RUIDO_VERTICE = 3  # posiciones en la lista de OSRM, no metros

    def fraccion_lista(punto, n_poly):
        return punto["vertice"] / max(n_poly - 1, 1)

    def cerca(punto):
        dist = punto.get("dist_m")
        return dist is not None and dist <= RADIO_M and punto.get("vertice") is not None

    def pasadas_ida(puntos, n_poly):
        """Parte el GPS ya ubicado sobre la ida.

        Entra un punto si está a RADIO_M de la ida. Si el vértice baja más que el
        ruido, va en sentido contrario: cierra la pasada y ese punto no se queda,
        salvo que ya esté en la salida. Un silencio de más de una hora cierra la
        pasada solo en la salida o en la llegada. En el medio, sigue el mismo viaje.
        """
        sobre = [p for p in sorted(puntos, key=lambda p: p["fecha"]) if cerca(p)]
        grupos = []
        actual = []
        for p in sobre:
            if not actual:
                actual = [p]
                continue
            ant = actual[-1]
            retrocede = p["vertice"] < ant["vertice"] - RUIDO_VERTICE
            silencio = p["fecha"] - ant["fecha"] > HUECO
            en_punta = fraccion_lista(ant, n_poly) >= FIN or fraccion_lista(p, n_poly) <= INICIO
            if retrocede or (silencio and en_punta):
                grupos.append(actual)
                if retrocede and fraccion_lista(p, n_poly) > INICIO:
                    actual = []
                else:
                    actual = [p]
                continue
            actual.append(p)
        if actual:
            grupos.append(actual)
        return [g for g in grupos if recorre(g, n_poly)]

    def recorre(grupo, n_poly):
        if len(grupo) < 2:
            return False
        verts = [p["vertice"] for p in grupo]
        return (max(verts) - min(verts)) / max(n_poly - 1, 1) >= 0.05

    def reloj_de(pasada, n_poly):
        """Minutos desde que abandona la salida hasta que toca la llegada.

        La espera en el camino entra. La espera quieta en la salida, antes de
        moverse, no. Tampoco el rato sentado en la llegada después de llegar.
        """
        if len(pasada) < 2:
            return None
        i = 0
        while (
            i < len(pasada) - 1
            and fraccion_lista(pasada[i], n_poly) <= INICIO
            and pasada[i + 1]["vertice"] <= pasada[i]["vertice"]
        ):
            i += 1
        for k in range(i, len(pasada)):
            if fraccion_lista(pasada[k], n_poly) >= FIN:
                return (pasada[k]["fecha"] - pasada[i]["fecha"]).total_seconds() / 60
        return None

    def es_ida_completa(pasada, n_poly):
        if len(pasada) < 2:
            return False
        return fraccion_lista(pasada[0], n_poly) <= INICIO and reloj_de(pasada, n_poly) is not None

    def resumen_de(pasada, n_poly, duracion_s):
        reloj = reloj_de(pasada, n_poly)
        osrm_min = duracion_s / 60 if duracion_s else None
        ratio = (reloj / osrm_min) if reloj is not None and osrm_min else None
        return {
            "n": len(pasada),
            "desde": pasada[0]["fecha"],
            "hasta": pasada[-1]["fecha"],
            "salida": round(fraccion_lista(pasada[0], n_poly), 2),
            "llegada": round(fraccion_lista(pasada[-1], n_poly), 2),
            "es_ida": es_ida_completa(pasada, n_poly),
            "reloj_min": None if reloj is None else round(reloj, 1),
            "osrm_min": None if osrm_min is None else round(osrm_min, 1),
            "ratio": None if ratio is None else round(ratio, 2),
            "reloj_ok": bool(
                es_ida_completa(pasada, n_poly) and ratio is not None and 0.5 <= ratio <= 3.0
            ),
        }

    return FIN, INICIO, PASO_M, RADIO_M, pasadas_ida, resumen_de


@app.cell
def _(mo):
    mo.md("""
    ## De dónde salen los puntos

    Esta celda no mide el reloj. Junta la hoja de ruta y el rastreo ya recortados, y le pasa los pings a la regla de arriba. El ejemplo y el conteo llaman a la misma función, `resumenes_de`.

    Los dos archivos los escribió `uv run python -m src p3`. La hoja sale de `opsapp2.hojaderutas.json`. El rastreo sale de `opsapp2.rastreosatelital_listas.json`. Acá no se vuelve a cortar el dump, y no se lee `observacionesSegmentosViales.json`.

    - La hoja. De cada documento se queda la ida: `geometriaOSRM.ida.puntos`, en `[lat, lon]`. La vuelta y la alternativa no se leen.
        - `analitica_segmentos` se vacía al leer: pesa, y esta medición no lo usa.
        - Un punto con latitud fuera de −50 a −20, o longitud fuera de −80 a −50, no entra.
    - Qué hoja entra. Tiene vehículo, `fechaDesde`, `fechaHasta`, y una ida con `duracion_osrm_original` y al menos dos puntos. No está eliminada. No empieza antes del 1 de junio de 2026, no termina después del 29 de octubre, y dura al menos una hora. Si no, para este notebook la hoja no existe.
        - Esas dos fechas son la vigencia. No son la pasada. Dicen en qué fechas buscar pings de ese vehículo. Una hoja de 7 días puede tener varias pasadas.
        - El conteo etiqueta el largo de esa vigencia, no el de la pasada. «24 h» son de 20 a 28 horas. «7 días» son de 160 a 176. El resto es «otra».
    - Los puntos de búsqueda. `PASO_M` es 200 m. Esos metros no numeran.
        - Entre dos vértices de OSRM el tramo es una recta. Si mide el doble, 400 m o más, `con_busqueda` lo parte en partes iguales y pone un punto de búsqueda en cada corte. Queda sobre esa recta. Hereda el número del vértice del que sale el tramo. Un tramo más corto no recibe ninguno.
        - El 15 % y el corte de 3 se cuentan en la lista de OSRM, no en estos puntos.
    - El GPS. Del rastreo satelital ya recortado. `location.coordinates` viene en `[lon, lat]`, al revés que la ida. Solo se guardan los vehículos de las hojas que se están mirando.
        - Vale el mismo recorte: latitud de −50 a −20, longitud de −80 a −50.
        - La ventana son los pings de ese vehículo entre `fechaDesde` y `fechaHasta`.
    - Ubicar. `mas_cercano` busca el punto más próximo de la ida ya con esos puntos de búsqueda. El ping queda con una distancia en metros y con el número de la lista de OSRM. Si no encuentra punto, no se ubica. Pasar los 250 m no lo borra acá: eso lo corta la regla de arriba.
    - Medir. `resumenes_de` corta la ventana, ubica los pings y le pasa esa lista a `pasadas_ida`. Devuelve la ventana y un resumen por pasada. La secuencia no se guarda. No hay una segunda forma de armar la pasada.
        - El ejemplo pide las primeras 15 hojas que pasan el filtro. El archivo va de lo nuevo a lo viejo, así que son las más nuevas. El conteo pide todas.

    `duracion_osrm_original` se guarda para comparar. No es el reloj. El reloj es `reloj_min`.
    """)
    return


@app.cell
def _(
    PASO_M,
    Path,
    UTC,
    a_dt,
    a_float,
    a_id,
    bisect_left,
    bisect_right,
    datetime,
    defaultdict,
    ijson,
    json,
    math,
    pasadas_ida,
    resumen_de,
    sys,
):

    # Sin _: la hoja y el conteo llaman a esto desde otra celda.
    # Marimo vuelve local cualquier nombre con _.
    _RAIZ = Path(__file__).resolve().parents[2]
    if str(_RAIZ) not in sys.path:
        sys.path.insert(0, str(_RAIZ))


    HDR = _RAIZ / "entregables" / "p3" / "hojaDeRuta.json"
    GPS = _RAIZ / "entregables" / "p3" / "rastreoSatelital.json"
    CACHE = _RAIZ / "parquet" / "p3_cuentas"

    print(HDR)
    print(GPS)
    print(CACHE)

    GPS_DESDE = datetime(2026, 6, 1, tzinfo=UTC)
    GPS_HASTA = datetime(2026, 10, 29, tzinfo=UTC)

    def equirect_m(lat1, lon1, lat2, lon2):
        coslat = math.cos(math.radians((lat1 + lat2) / 2))
        x = (lon2 - lon1) * 111_320 * coslat
        y = (lat2 - lat1) * 110_540
        return math.hypot(x, y)

    def polilinea(puntos):
        out = []
        if not isinstance(puntos, list):
            return out
        for p in puntos:
            if not isinstance(p, (list, tuple)) or len(p) < 2:
                continue
            lat, lon = a_float(p[0]), a_float(p[1])
            if lat is None or lon is None:
                continue
            if -50 <= lat <= -20 and -80 <= lon <= -50:
                out.append((lat, lon))
        return out

    def con_busqueda(poly, cada_m=PASO_M):
        if len(poly) < 2:
            return []
        tramos = [equirect_m(*a, *b) for a, b in zip(poly, poly[1:])]
        total = sum(tramos)
        if total <= 0:
            return [(poly[0][0], poly[0][1], 0)]
        out = [(poly[0][0], poly[0][1], 0)]
        acc = 0.0
        n_orig = len(poly)
        for i, dist in enumerate(tramos):
            a, b = poly[i], poly[i + 1]
            n = max(1, int(dist // cada_m))
            for k in range(1, n + 1):
                t = k / n
                vert = i if t < 1 else min(i + 1, n_orig - 1)
                out.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), vert))
            acc += dist
        return out

    def celdas_de(pts, paso=0.01):
        celdas = defaultdict(list)
        for j, (lat, lon, _vert) in enumerate(pts):
            celdas[(int(lat / paso), int(lon / paso))].append(j)
        return celdas

    def mas_cercano(lat, lon, pts, celdas, paso=0.01):
        cx, cy = int(lat / paso), int(lon / paso)
        mejor = None
        vert = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in celdas.get((cx + dx, cy + dy), ()):
                    plat, plon, v = pts[j]
                    dist = equirect_m(lat, lon, plat, plon)
                    if mejor is None or dist < mejor:
                        mejor = dist
                        vert = v
        return mejor, vert

    def vigencia_de(horas):
        if 20 <= horas <= 28:
            return "24 h"
        if 160 <= horas <= 176:
            return "7 días"
        return "otra"

    def sin_segmentos(linea):
        clave = '"analitica_segmentos":'
        partes = []
        i = 0
        while True:
            j = linea.find(clave, i)
            if j < 0:
                partes.append(linea[i:])
                break
            partes.append(linea[i:j])
            k = j + len(clave)
            if k < len(linea) and linea[k] == "[":
                depth = 0
                while k < len(linea):
                    if linea[k] == "[":
                        depth += 1
                    elif linea[k] == "]":
                        depth -= 1
                        if depth == 0:
                            k += 1
                            break
                    k += 1
                partes.append('"analitica_segmentos":[]')
                i = k
            else:
                i = j + len(clave)
        return "".join(partes)

    def hoja_de(doc):
        if doc.get("eliminada") is True:
            return None
        desde = a_dt(doc.get("fechaDesde"))
        hasta = a_dt(doc.get("fechaHasta"))
        veh = a_id((doc.get("vehiculo") or {}).get("id"))
        if desde is None or hasta is None or not veh:
            return None
        if desde < GPS_DESDE or hasta > GPS_HASTA or hasta <= desde:
            return None
        horas = (hasta - desde).total_seconds() / 3600
        if horas < 1:
            return None
        ida = (doc.get("geometriaOSRM") or {}).get("ida") or {}
        dur = a_float(ida.get("duracion_osrm_original"))
        poly = con_busqueda(polilinea(ida.get("puntos")))
        if not dur or dur <= 0 or len(poly) < 2:
            return None
        return {
            "id": a_id(doc.get("_id")),
            "vehiculo": veh,
            "vigencia": vigencia_de(horas),
            "desde": desde,
            "hasta": hasta,
            "duracion_s": dur,
            "n_poly": max(p[2] for p in poly) + 1,
            "poly": poly,
            "celdas": celdas_de(poly),
        }

    def docs_hdr(path):
        vistos = 0
        with path.open(encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip().rstrip(",")
                if not linea.startswith("{"):
                    continue
                vistos += 1
                yield vistos, json.loads(sin_segmentos(linea))

    def leer_hojas(path=HDR, tope=None):
        hojas = []
        vistos = 0
        print("hdr …", flush=True)
        for vistos, doc in docs_hdr(path):
            if vistos % 500 == 0:
                print(f"hdr {vistos} idas={len(hojas)}", flush=True)
            hoja = hoja_de(doc)
            if hoja is None:
                continue
            hojas.append(hoja)
            if tope is not None and len(hojas) >= tope:
                break
        print(f"hdr ok vistos={vistos} idas={len(hojas)}", flush=True)
        return hojas, vistos

    def leer_gps(vehiculos, path=GPS):

        por_flota = defaultdict(list)
        n = 0
        print("gps …", flush=True)
        with path.open("rb") as f:
            for rec in ijson.items(f, "item"):
                n += 1
                if n % 500_000 == 0:
                    print(f"gps {n}", flush=True)
                flota = a_id(rec.get("flotaID"))
                if flota not in vehiculos:
                    continue
                loc = (rec.get("location") or {}).get("coordinates")
                if not isinstance(loc, (list, tuple)) or len(loc) != 2:
                    continue
                lon, lat = a_float(loc[0]), a_float(loc[1])
                fecha = a_dt(rec.get("fecha"))
                if lon is None or lat is None or fecha is None:
                    continue
                if not (-80 <= lon <= -50 and -50 <= lat <= -20):
                    continue
                por_flota[flota].append((fecha, lat, lon))
        for pts in por_flota.values():
            pts.sort()
        print(f"gps ok recs={n} flotas={len(por_flota)}", flush=True)
        return por_flota

    def ubicar(ventana, poly, celdas):
        out = []
        for fecha, lat, lon in ventana:
            dist, vert = mas_cercano(lat, lon, poly, celdas)
            if dist is None or vert is None:
                continue
            out.append({"fecha": fecha, "dist_m": dist, "vertice": vert})
        return out

    def ventana_de(hoja, gps):
        pts = gps.get(hoja["vehiculo"]) or []
        tiempos = [p[0] for p in pts]
        lo = bisect_left(tiempos, hoja["desde"])
        hi = bisect_right(tiempos, hoja["hasta"])
        return pts[lo:hi]

    def resumenes_de(hoja, gps):
        ventana = ventana_de(hoja, gps)
        anotados = ubicar(ventana, hoja["poly"], hoja["celdas"])
        grupos = pasadas_ida(anotados, hoja["n_poly"])
        return ventana, [resumen_de(g, hoja["n_poly"], hoja["duracion_s"]) for g in grupos]

    return CACHE, GPS, HDR, docs_hdr, hoja_de, mas_cercano, leer_gps, leer_hojas, resumenes_de


@app.cell
def _(mo):
    mo.md("""
    ## Una hoja

    La primera hoja que pasaría el conteo y que tiene al menos un ping en la vigencia. El archivo va de lo nuevo a lo viejo. Si no hay caminos, la tabla lo dice. Si las primeras 15 no tienen pings, se corta.

    **Ver la primera hoja** recorre el GPS una vez. No corre al abrir. Hay tres mapas. Cada uno explica sus marcas en la esquina. Si ya había un dibujo guardado, hay que apretarlo de nuevo.
    """)
    return


@app.cell
def _(
    CACHE,
    GPS,
    HDR,
    RADIO_M,
    UTC,
    datetime,
    json,
    leer_gps,
    leer_hojas,
    mas_cercano,
    math,
    pasadas_ida,
    pl,
    resumenes_de,
):
    def puntos_mapa(ventana, hoja):
        out = []
        for fecha, lat, lon in ventana:
            dist, vert = mas_cercano(lat, lon, hoja["poly"], hoja["celdas"])
            out.append(
                {
                    "fecha": fecha,
                    "lat": lat,
                    "lon": lon,
                    "dist_m": dist,
                    "vertice": vert,
                }
            )
        return out

    def svg_mapas(poly, gps, radio, paso_m=200, n_poly=None, inicio=0.15, fin=0.85, pasadas=None):

        if not poly:
            return "<p>sin polilínea</p>"

        puntos = []
        for p in poly:
            vert = p[2] if len(p) >= 3 else None
            origen = bool(p[3]) if len(p) >= 4 else None
            puntos.append({"lat": p[0], "lon": p[1], "vertice": vert, "origen": origen})
        con_vertices = any(p["vertice"] is not None for p in puntos)
        if n_poly is None and con_vertices:
            n_poly = max(p["vertice"] for p in puntos if p["vertice"] is not None) + 1

        lats = [p["lat"] for p in puntos]
        lons = [p["lon"] for p in puntos]
        lat_a, lat_b = min(lats), max(lats)
        lon_a, lon_b = min(lons), max(lons)
        if lat_b == lat_a:
            lat_b += 0.01
        if lon_b == lon_a:
            lon_b += 0.01
        pad_lat = max((lat_b - lat_a) * 0.08, 0.01)
        pad_lon = max((lon_b - lon_a) * 0.08, 0.01)
        lat0, lat1 = lat_a - pad_lat, lat_b + pad_lat
        lon0, lon1 = lon_a - pad_lon, lon_b + pad_lon
        w, map_h = 760, 440

        def xy(lat, lon):
            x = (lon - lon0) / (lon1 - lon0) * (w - 24) + 12
            y = (lat1 - lat) / (lat1 - lat0) * (map_h - 24) + 12
            return x, y

        def esc(texto):
            return (
                str(texto)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
            )

        def instante(valor):
            if valor is None:
                return None
            if hasattr(valor, "timestamp"):
                if getattr(valor, "tzinfo", None) is None:
                    return valor.replace(tzinfo=UTC)
                return valor
            texto = str(valor)
            if texto.endswith("Z"):
                texto = texto[:-1] + "+00:00"
            try:
                dt = datetime.fromisoformat(texto)
            except ValueError:
                return None
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)

        def hora(valor):
            dt = instante(valor)
            return "" if dt is None else dt.strftime("%H:%M")

        def zona(vert):
            if vert is None or not n_poly or n_poly <= 1:
                return "medio"
            prog = vert / (n_poly - 1)
            if prog <= inicio:
                return "salida"
            if prog >= fin:
                return "llegada"
            return "medio"

        def path(pts):
            if len(pts) < 2:
                return ""
            d = []
            for i, p in enumerate(pts):
                x, y = xy(p["lat"], p["lon"])
                d.append(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}")
            return " ".join(d)

        def circulos(pts, color, r, titulo):
            partes = []
            for p in pts:
                x, y = xy(p["lat"], p["lon"])
                t = titulo(p) if callable(titulo) else titulo
                extra = f"<title>{esc(t)}</title>" if t else ""
                partes.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{color}">{extra}</circle>'
                )
            return "".join(partes)

        def halo(x, y, texto, color="#222"):
            return (
                f'<text x="{x:.1f}" y="{y:.1f}" font-family="sans-serif" font-size="11" '
                f'fill="{color}" stroke="#f7f6f3" stroke-width="3" paint-order="stroke">'
                f"{esc(texto)}</text>"
            )

        def caja(lineas):
            alto = 12 + len(lineas) * 15
            ancho = 360
            x0, y0 = 8, map_h - alto - 8
            out = [
                f'<rect x="{x0}" y="{y0}" width="{ancho}" height="{alto}" rx="4" '
                f'fill="#fffefb" fill-opacity="0.94" stroke="#e4e0d8"/>'
            ]
            for i, linea in enumerate(lineas):
                out.append(
                    f'<text x="{x0 + 10}" y="{y0 + 16 + i * 15}" font-family="sans-serif" '
                    f'font-size="11" fill="#333">{esc(linea)}</text>'
                )
            return "".join(out)

        def svg(capas, leyenda):
            return (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{map_h}" '
                f'viewBox="0 0 {w} {map_h}">'
                '<rect width="100%" height="100%" fill="#f7f6f3"/>'
                + "".join(capas)
                + caja(leyenda)
                + "</svg>"
            )

        colores = {"salida": "#2a7a4b", "medio": "#8a8a8a", "llegada": "#c46b1a"}
        originales = [p for p in puntos if p["origen"]]
        busqueda = [p for p in puntos if p["origen"] is False]
        if con_vertices and not originales:
            vistos = {}
            for p in puntos:
                if p["vertice"] is not None and p["vertice"] not in vistos:
                    vistos[p["vertice"]] = p
            originales = list(vistos.values())
        linea = originales or puntos

        def tramos(pts, pintar):
            capas = []
            if not pintar:
                d = path(pts)
                if d:
                    capas.append(f'<path d="{d}" fill="none" stroke="#b0b0b0" stroke-width="2.2"/>')
                return capas
            actual = []
            zact = None
            grupos = []
            for p in pts:
                z = zona(p["vertice"])
                if zact is None:
                    zact = z
                    actual = [p]
                    continue
                if z != zact:
                    grupos.append((zact, actual))
                    actual = [actual[-1], p]
                    zact = z
                else:
                    actual.append(p)
            if actual:
                grupos.append((zact, actual))
            for z, grupo in grupos:
                d = path(grupo)
                if d:
                    capas.append(
                        f'<path d="{d}" fill="none" stroke="{colores[z]}" stroke-width="2.4"/>'
                    )
            return capas

        def flecha(pts):
            if len(pts) < 2:
                return ""
            x0, y0 = xy(pts[0]["lat"], pts[0]["lon"])
            nxt = pts[1]
            for p in pts[1:]:
                if (p["lat"], p["lon"]) != (pts[0]["lat"], pts[0]["lon"]):
                    nxt = p
                    break
            x1, y1 = xy(nxt["lat"], nxt["lon"])
            dx, dy = x1 - x0, y1 - y0
            largo = math.hypot(dx, dy) or 1
            ux, uy = dx / largo, dy / largo
            ax, ay = x0 + ux * 8, y0 + uy * 8
            bx, by = x0 + ux * 26, y0 + uy * 26
            px, py = -uy, ux
            return (
                f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" '
                f'stroke="#1a1a1a" stroke-width="1.5"/>'
                f'<polygon points="{bx:.1f},{by:.1f} '
                f"{bx - ux * 7 + px * 3.2:.1f},{by - uy * 7 + py * 3.2:.1f} "
                f'{bx - ux * 7 - px * 3.2:.1f},{by - uy * 7 - py * 3.2:.1f}" fill="#1a1a1a"/>'
            )

        def numeros(pts):
            if not pts or not n_poly:
                return ""
            tope = max(n_poly - 1, 0)
            vistos = set()
            marcas = []
            for frac in (0, inicio, fin, 1):
                idx = 0 if frac <= 0 else tope if frac >= 1 else round(frac * tope)
                if idx in vistos:
                    continue
                vistos.add(idx)
                for p in pts:
                    if p.get("vertice") == idx:
                        marcas.append(p)
                        break
            out = []
            for i, p in enumerate(marcas):
                x, y = xy(p["lat"], p["lon"])
                out.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#1a1a1a" '
                    f'stroke="#f7f6f3" stroke-width="1.2">'
                    f"<title>vértice {p['vertice']} · de la hoja</title></circle>"
                )
                dx = 8 if x < w - 40 else -28
                dy = 14 if y < 18 else -8
                if i % 2:
                    dy = -dy
                out.append(halo(x + dx, y + dy, str(p["vertice"])))
            return "".join(out)

        mid = (lat_a + lat_b) / 2
        px_por_m = ((w - 24) / (lon1 - lon0)) / (111_320 * math.cos(math.radians(mid)) or 1)
        nota_escala = ""
        if radio * px_por_m < 8:
            nota_escala = "A esta escala el radio casi no se ve."

        if not con_vertices:
            aviso = ["Esta caché no separa los puntos.", "Apretá el botón de nuevo."]
            gris = tramos(linea, False)
            return (
                "<p><strong>La ida</strong></p>"
                + svg(gris, aviso)
                + "<p><strong>Los pings</strong></p>"
                + svg(gris, aviso)
                + "<p><strong>La búsqueda</strong></p>"
                + svg(gris, aviso)
            )

        ida = tramos(linea, True)
        ida.append(flecha(linea))
        ida.append(numeros(linea))
        leyenda_ida = [
            "Verde: salida. Gris: medio. Naranja: llegada.",
            "Negro: vértice. Escritos: 0, 15 %, 85 % y el último.",
            "La línea es la lista de la hoja.",
            "Los puntos de búsqueda están en el tercer mapa.",
            f"{paso_m:.0f} m búsqueda · {radio:.0f} m radio.",
        ]
        if nota_escala:
            leyenda_ida.append(nota_escala)

        dentro = []
        for p in gps:
            if lat0 <= p["lat"] <= lat1 and lon0 <= p["lon"] <= lon1:
                dentro.append(p)

        def es_cerca(p):
            dist = p.get("dist_m")
            return dist is not None and dist <= radio

        def titulo_ping(p):
            bits = []
            if p.get("vertice") is not None:
                bits.append(f"vértice {p['vertice']}")
            if p.get("dist_m") is not None:
                bits.append(f"{p['dist_m']:.0f} m")
            h = hora(p.get("fecha"))
            if h:
                bits.append(h + " UTC")
            if p.get("es_ida"):
                bits.append("ida completa")
            return " · ".join(bits)

        paso_gps = max(1, len(dentro) // 2500)
        muestra = dentro[::paso_gps]
        lejos = [p for p in muestra if not es_cerca(p)]
        cerca = [p for p in muestra if es_cerca(p) and not p.get("es_ida")]
        en_ida = [p for p in muestra if p.get("es_ida")]
        pings = tramos(linea, False)
        pings.append(circulos(lejos, "#d2a3a3", 2.2, titulo_ping))
        pings.append(circulos(cerca, "#1d4e89", 2.2, titulo_ping))
        pings.append(circulos(en_ida, "#6b3fa0", 2.6, titulo_ping))

        completas = [f for f in (pasadas or []) if f.get("es_ida")]
        for i, fila in enumerate(completas[:3]):
            t0, t1 = instante(fila.get("desde")), instante(fila.get("hasta"))
            if t0 is None or t1 is None:
                continue
            lo, hi = t0.timestamp() - 2, t1.timestamp() + 2
            ancla = None
            for p in gps:
                if not p.get("es_ida"):
                    continue
                t = instante(p.get("fecha"))
                if t is None or not (lo <= t.timestamp() <= hi):
                    continue
                if not (lat0 <= p["lat"] <= lat1 and lon0 <= p["lon"] <= lon1):
                    continue
                if ancla is None or t >= ancla[0]:
                    ancla = (t, p)
            if ancla is None:
                continue
            x, y = xy(ancla[1]["lat"], ancla[1]["lon"])
            reloj = fila.get("reloj_min")
            texto = f"{hora(fila.get('desde'))} a {hora(fila.get('hasta'))}"
            if reloj is not None:
                texto += f" · reloj {reloj:g} min"
            if x > w - 180:
                x -= 176
            else:
                x += 8
            y = min(max(y - 8 - i * 14, 14), map_h - 96)
            pings.append(halo(x, y, texto, "#4a2878"))

        leyenda_pings = [
            "Gris: la ida.",
            f"Azul: ≤ {radio:.0f} m. Violeta: sale y llega.",
            "Rosa: en el recuadro, más lejos.",
            "Hora UTC: primer y último ping.",
            "No es el arranque del reloj.",
        ]
        if paso_gps > 1:
            leyenda_pings.append("El dibujo ralea los pings si hay muchos.")
        if len(completas) > 3:
            leyenda_pings.append(f"Marca las 3 primeras de {len(completas)} idas.")

        paso_busq = max(1, len(busqueda) // 1500)
        busca = tramos(linea, False)
        busca.append(
            circulos(
                busqueda[::paso_busq],
                "#3d6b8a",
                2.4,
                lambda p: f"búsqueda · hereda el {p['vertice']}",
            )
        )
        leyenda_busca = [
            "Gris: lista de la hoja.",
            "Punto: búsqueda. Hereda el número.",
            f"Tramo < {2 * paso_m:.0f} m: no hay punto.",
            f"Paso: {paso_m:.0f} m. No es un corte fijo.",
        ]
        if paso_busq > 1:
            leyenda_busca.append("El dibujo ralea estos puntos si hay muchos.")

        return (
            "<p><strong>La ida</strong></p>"
            + svg(ida, leyenda_ida)
            + "<p><strong>Los pings</strong></p>"
            + svg(pings, leyenda_pings)
            + "<p><strong>La búsqueda</strong></p>"
            + svg(busca, leyenda_busca)
        )

    def escribir_ejemplo(cache, meta, poly=None, gps=None):


        cache.mkdir(parents=True, exist_ok=True)
        (cache / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        for nombre in ("poly.parquet", "gps.parquet"):
            (cache / nombre).unlink(missing_ok=True)
        if poly:
            pl.DataFrame(
                {
                    "lat": [p[0] for p in poly],
                    "lon": [p[1] for p in poly],
                    "vertice": [int(p[2]) for p in poly],
                    "origen": [bool(p[3]) for p in poly],
                }
            ).write_parquet(cache / "poly.parquet")
        if gps:
            pl.DataFrame(
                {
                    "fecha": [p["fecha"] for p in gps],
                    "lat": [p["lat"] for p in gps],
                    "lon": [p["lon"] for p in gps],
                    "dist_m": pl.Series("dist_m", [p["dist_m"] for p in gps], dtype=pl.Float64),
                    "vertice": pl.Series("vertice", [p["vertice"] for p in gps], dtype=pl.Int64),
                    "es_ida": [bool(p.get("es_ida")) for p in gps],
                }
            ).write_parquet(cache / "gps.parquet")

    def armar_ejemplo(cache=None, tope=15):
        cache = CACHE / "ejemplo" if cache is None else cache
        if not HDR.exists() or not GPS.exists():
            raise FileNotFoundError(f"faltan entregables: {HDR} {GPS}")
        hojas, vistos = leer_hojas(tope=tope)
        if not hojas:
            escribir_ejemplo(
                cache,
                {
                    "aviso": "ninguna hoja pasó el filtro del conteo",
                    "vistos_hdr": vistos,
                    "miradas": 0,
                    "radio_m": RADIO_M,
                    "hoja": None,
                    "pasadas": [],
                },
            )
            return
        crudo = leer_gps({h["vehiculo"] for h in hojas})
        elegida = None
        ventana = None
        resumenes = None
        puesto = None
        for i, h in enumerate(hojas, 1):
            vent, fils = resumenes_de(h, crudo)
            if vent:
                elegida = h
                ventana = vent
                resumenes = fils
                puesto = i
                break
        if elegida is None:
            escribir_ejemplo(
                cache,
                {
                    "aviso": f"ninguna de las primeras {len(hojas)} hojas tiene GPS en la vigencia",
                    "vistos_hdr": vistos,
                    "miradas": len(hojas),
                    "radio_m": RADIO_M,
                    "hoja": None,
                    "pasadas": [],
                },
            )
            return
        anotados = puntos_mapa(ventana, elegida)
        grupos = pasadas_ida(anotados, elegida["n_poly"])
        for grupo, fila in zip(grupos, resumenes, strict=True):
            if fila["es_ida"]:
                for p in grupo:
                    p["es_ida"] = True
        n_cerca = sum(
            1 for p in anotados if p.get("dist_m") is not None and p["dist_m"] <= RADIO_M
        )
        poly_out = []
        prev = None
        for i, p in enumerate(elegida["poly"]):
            origen = i == 0 or p[2] > prev
            poly_out.append((p[0], p[1], int(p[2]), origen))
            prev = p[2]
        escribir_ejemplo(
            cache,
            {
                "aviso": None,
                "vistos_hdr": vistos,
                "miradas": len(hojas),
                "puesto": puesto,
                "radio_m": RADIO_M,
                "hoja": {
                    "id": elegida["id"],
                    "vehiculo": elegida["vehiculo"],
                    "vigencia": elegida["vigencia"],
                    "desde": elegida["desde"].isoformat(),
                    "hasta": elegida["hasta"].isoformat(),
                    "duracion_s": elegida["duracion_s"],
                    "n_poly": elegida["n_poly"],
                    "n_gps": len(ventana),
                    "n_cerca": n_cerca,
                    "n_pasadas": len(resumenes),
                    "n_completas": sum(1 for f in resumenes if f["es_ida"]),
                },
                "pasadas": [
                    {**f, "desde": f["desde"].isoformat(), "hasta": f["hasta"].isoformat()}
                    for f in resumenes
                ],
            },
            poly=poly_out,
            gps=anotados,
        )
        print(
            f"ejemplo {elegida['vehiculo']} puesto={puesto} gps={len(ventana)} "
            f"cerca={n_cerca} pasadas={len(resumenes)}",
            flush=True,
        )

    return armar_ejemplo, svg_mapas


@app.cell
def _(mo):
    ver_hoja = mo.ui.run_button(label="Ver la primera hoja (recorre el GPS, ~5 GB)")
    ver_hoja
    return (ver_hoja,)


@app.cell
def _(armar_ejemplo, ver_hoja):
    corrida_ejemplo = "sin corrida en esta sesión"
    if ver_hoja.value:
        armar_ejemplo()
        corrida_ejemplo = "escrito"
    corrida_ejemplo
    return (corrida_ejemplo,)


@app.cell
def _(CACHE, corrida_ejemplo, json, mo):

    _ = corrida_ejemplo
    _ejemplo = CACHE / "ejemplo"
    mo.stop(
        not (_ejemplo / "meta.json").exists(),
        mo.md("Todavía no hay una hoja. Apretá **Ver la primera hoja**."),
    )
    meta_ej = json.loads((_ejemplo / "meta.json").read_text())
    _hoja = meta_ej.get("hoja") or {}
    _puesto = meta_ej.get("puesto")
    _salto = ""
    if _puesto and _puesto > 1:
        _salto = (
            f" Es la {_puesto} de las {meta_ej['miradas']} primeras que pasan el filtro:"
            " las anteriores no tenían pings en la vigencia."
        )
    mo.stop(
        bool(meta_ej.get("aviso")),
        mo.md(
            f"## Una hoja\n\n{meta_ej['aviso']}. "
            f"Hojas miradas: {meta_ej.get('miradas', 0)}."
        ),
    )
    _n_poly = _hoja.get("n_poly")
    _verts = f" Vértices de la lista: **{_n_poly}**." if _n_poly else ""
    mo.md(
        f"""
        ## Hoja

        `{_hoja["vehiculo"]}` · {_hoja["vigencia"]}
        ({_hoja["desde"]} → {_hoja["hasta"]}).{_salto}{_verts}

        Pings en la vigencia: **{_hoja["n_gps"]}**.
        A {meta_ej["radio_m"]:.0f} m o menos: **{_hoja["n_cerca"]}**.
        Pasadas: **{_hoja["n_pasadas"]}**.
        Salen y llegan: **{_hoja["n_completas"]}**.

        OSRM de la ida: **{_hoja["duracion_s"] / 60:.0f} min**.
        Abajo hay tres mapas. Los totales están acá, no en el dibujo.
        """
    )
    return (meta_ej,)


@app.cell
def _(CACHE, FIN, INICIO, PASO_M, meta_ej, mo, pl, svg_mapas):

    _poly = pl.read_parquet(CACHE / "ejemplo" / "poly.parquet")
    _gps = pl.read_parquet(CACHE / "ejemplo" / "gps.parquet")
    if {"vertice", "origen"} <= set(_poly.columns):
        _puntos = list(
            zip(
                _poly["lat"].to_list(),
                _poly["lon"].to_list(),
                _poly["vertice"].to_list(),
                _poly["origen"].to_list(),
                strict=True,
            )
        )
    else:
        _puntos = list(zip(_poly["lat"].to_list(), _poly["lon"].to_list(), strict=True))
    _hoja = meta_ej.get("hoja") or {}
    mo.Html(
        svg_mapas(
            _puntos,
            _gps.to_dicts(),
            meta_ej["radio_m"],
            paso_m=PASO_M,
            n_poly=_hoja.get("n_poly"),
            inicio=INICIO,
            fin=FIN,
            pasadas=meta_ej.get("pasadas") or [],
        )
    )
    return


@app.cell
def _(meta_ej, mo, pl):

    _pasadas = meta_ej["pasadas"]
    _tabla_pasadas = (
        pl.DataFrame(_pasadas)
        if _pasadas
        else pl.DataFrame({"aviso": ["ninguna pasada sobre la ida"]})
    )
    mo.vstack(
        [
            mo.md("""
            ## Pasadas de esta hoja

            Cada fila es un camino sobre la ida. `es_ida` empieza en el primer 15 % y llega al último 15 %. `reloj_min` es el reloj, sin la espera quieta en las puntas. `osrm_min` es el plan, no el reloj.
            """),
            _tabla_pasadas,
        ]
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Cuántas hay

    La misma regla, sobre todas las hojas. `hojas` y `con_gps` son hojas. Las otras tres son pasadas.

    - `sobre_ida`: avanzó al menos un 5 % del dibujo.
    - `salen_y_llegan`: salió del primer 15 % y llegó al último 15 %.
    - `reloj_ok`: eso, y el reloj está entre la mitad y el triple del plan.

    Para saber si hay filas, mirá `salen_y_llegan`. `reloj_ok` solo dice si el reloj está cerca del plan.

    **Contar todas** recorre hoja y GPS. No corre al abrir.
    """)
    return


@app.cell
def _(CACHE, GPS, HDR, json, leer_gps, leer_hojas, pl, resumenes_de):
    def cruzar(hojas, gps):
        filas = []
        ejemplos = []
        print(f"cruce {len(hojas)} idas …", flush=True)
        for i, h in enumerate(hojas, 1):
            if i % 500 == 0:
                print(f"cruce {i}", flush=True)
            ventana, resumenes = resumenes_de(h, gps)
            completas = 0
            ok = 0
            for ev in resumenes:
                if ev["es_ida"]:
                    completas += 1
                    if ev["reloj_ok"]:
                        ok += 1
                    if len(ejemplos) < 15:
                        ejemplos.append(
                            {
                                "vehiculo": h["vehiculo"],
                                "vigencia": h["vigencia"],
                                "desde": ev["desde"].isoformat(),
                                "hasta": ev["hasta"].isoformat(),
                                "reloj_min": ev["reloj_min"],
                                "osrm_min": ev["osrm_min"],
                                "ratio": ev["ratio"],
                            }
                        )
            filas.append(
                {
                    "vigencia": h["vigencia"],
                    "hojas": 1,
                    "con_gps": len(ventana) > 0,
                    "sobre_ida": len(resumenes),
                    "salen_y_llegan": completas,
                    "reloj_ok": ok,
                }
            )
        return filas, ejemplos

    def armar(cache=CACHE):


        if not HDR.exists() or not GPS.exists():
            raise FileNotFoundError(f"faltan entregables: {HDR} {GPS}")
        hojas, vistos = leer_hojas()
        gps = leer_gps({h["vehiculo"] for h in hojas})
        filas, ejemplos = cruzar(hojas, gps)
        tabla = (
            pl.DataFrame(filas)
            .group_by("vigencia")
            .agg(
                pl.col("hojas").sum(),
                pl.col("con_gps").sum(),
                pl.col("sobre_ida").sum(),
                pl.col("salen_y_llegan").sum(),
                pl.col("reloj_ok").sum(),
            )
            .sort("vigencia")
        )
        cache.mkdir(parents=True, exist_ok=True)
        tabla.write_parquet(cache / "resumen.parquet")
        (cache / "meta.json").write_text(
            json.dumps(
                {"vistos_hdr": vistos, "idas": len(hojas), "ejemplos": ejemplos},
                ensure_ascii=False,
                indent=2,
            )
        )
        print(tabla, flush=True)
        return tabla

    return (armar,)


@app.cell
def _(mo):
    rearmar = mo.ui.run_button(label="Contar todas (recorre hoja + GPS, ~5 GB)")
    rearmar
    return (rearmar,)


@app.cell
def _(armar, rearmar):
    corrida = "sin corrida en esta sesión"
    if rearmar.value:
        armar()
        corrida = "escrito"
    corrida
    return (corrida,)


@app.cell
def _(CACHE, corrida, json, mo, pl):

    _ = corrida
    mo.stop(
        not (CACHE / "resumen.parquet").exists(),
        mo.md("Todavía no hay conteo. Apretá **Contar todas**."),
    )
    _tabla = pl.read_parquet(CACHE / "resumen.parquet")
    _meta = json.loads((CACHE / "meta.json").read_text())
    _tot = _tabla.select(
        pl.col("sobre_ida").sum(),
        pl.col("salen_y_llegan").sum(),
        pl.col("reloj_ok").sum(),
    ).row(0)
    _ejemplos = (
        pl.DataFrame(_meta["ejemplos"])
        if _meta["ejemplos"]
        else pl.DataFrame({"aviso": ["ninguna ida salió y llegó"]})
    )
    mo.vstack(
        [
            mo.md(
                f"""
                ## Resultado

                Pasadas sobre la ida: **{_tot[0]}**.
                Salen y llegan: **{_tot[1]}**.
                Con reloj del mismo orden que el plan: **{_tot[2]}**.

                Hojas leídas: {_meta["vistos_hdr"]}. Idas con geometría dentro del GPS: {_meta["idas"]}.
                """
            ),
            _tabla,
            _ejemplos,
        ]
    )
    return


@app.cell
def _(
    Path,
    UTC,
    datetime,
    defaultdict,
    gc,
    ijson,
    json,
    math,
    np,
    pl,
    shutil,
    timedelta,
    zlib,
):
    def armar_dataset_p3_streaming(
        hdr_path: Path | str,
        gps_path: Path | str,
        salida_dir: Path | str,
        variantes: tuple[str, ...] = ("ida",),
        nivel: str = "segmento",
        objetivo: str = "y_en_viaje_minutos",
        proporcion_train: float = 0.8,
        n_buckets: int = 32,
        max_puntos_buffer_gps: int = 400_000,
        filas_por_parquet: int = 50_000,
        radio_m: float = 250.0,
        paso_m: float = 200.0,
        hueco: timedelta = timedelta(hours=1),
        inicio: float = 0.15,
        fin: float = 0.85,
        ruido_vertice: int = 3,
        rango_ratio: tuple[float, float] = (0.5, 3.0),
    ) -> dict:
        """
        Construye el dataset de p3_idas por fragmentos Parquet sin cargar el GPS ni
        la tabla final completa en memoria RAM.
        """
        if nivel not in ("segmento", "viaje"):
            raise ValueError("nivel debe ser 'segmento' o 'viaje'")
        if objetivo not in ("y_en_viaje_minutos", "y_al_salir_minutos"):
            raise ValueError("objetivo debe ser 'y_en_viaje_minutos' o 'y_al_salir_minutos'")
        if nivel == "viaje" and objetivo == "y_en_viaje_minutos":
            objetivo = "y_al_salir_minutos"

        hdr_path = Path(hdr_path)
        gps_path = Path(gps_path)
        salida_dir = Path(salida_dir)
        partes_dir = salida_dir / "partes"
        tmp_gps_dir = salida_dir / "_tmp_gps"

        for carpeta in (partes_dir, tmp_gps_dir):
            if carpeta.exists():
                shutil.rmtree(carpeta)
            carpeta.mkdir(parents=True, exist_ok=True)

        # Esquema explícito para evitar conflictos de tipos entre fragmentos Parquet
        schema_salida = {
            "idrecorrido": pl.String,
            "idhojaruta": pl.String,
            "idvehiculo": pl.String,
            "total_segmentos": pl.Int32,
            "instant_t_fechahora": pl.Datetime("us", "UTC"),
            "t_franjahoraria": pl.String,
            "t_dia_semana": pl.Int8,
            "t_hora_dia": pl.Int8,
            "tipovehiculo": pl.String,
            "cantplazas": pl.Float32,
            "variante": pl.String,
            "osrm_total_est_min": pl.Float32,
            "y_al_salir_minutos": pl.Float32,
        }
        if nivel == "segmento":
            schema_salida.update(
                {
                    "idsegmento_actual": pl.String,
                    "segmento_orden_actual": pl.Int32,
                    "osrm_restante_est_min": pl.Float32,
                    "minutos_ya_transcurridos": pl.Float32,
                    "pct_progreso_recorrido": pl.Float32,
                    "y_en_viaje_minutos": pl.Float32,
                }
            )

        # --- Helpers ligeros ---
        def bucket_de(veh_id: str) -> int:
            return zlib.crc32(veh_id.encode("utf-8")) % n_buckets

        def parsear_oid(val):
            if isinstance(val, dict):
                return val.get("$oid")
            return str(val) if val is not None else None

        def parsear_float(val):
            if val is None:
                return None
            if isinstance(val, dict):
                for k in ("$numberDouble", "$numberInt", "$numberLong"):
                    if k in val:
                        val = val[k]
                        break
            try:
                f = float(val)
                return f if math.isfinite(f) else None
            except (TypeError, ValueError):
                return None

        def parsear_dt(val):
            if isinstance(val, dict):
                val = val.get("$date")
            if not val:
                return None
            if isinstance(val, (int, float)):
                return datetime.fromtimestamp(val / 1000.0, tz=UTC)
            txt = str(val)
            if txt.endswith("Z"):
                txt = txt[:-1] + "+00:00"
            try:
                dt = datetime.fromisoformat(txt)
                return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
            except ValueError:
                return None

        def equirect_m(lat1, lon1, lat2, lon2):
            coslat = math.cos(math.radians((lat1 + lat2) / 2))
            x = (lon2 - lon1) * 111_320 * coslat
            y = (lat2 - lat1) * 110_540
            return math.hypot(x, y)

        def filtrar_poly(puntos):
            out = []
            if not isinstance(puntos, list):
                return out
            for p in puntos:
                if not isinstance(p, (list, tuple)) or len(p) < 2:
                    continue
                lat, lon = parsear_float(p[0]), parsear_float(p[1])
                if lat is not None and lon is not None and -50 <= lat <= -20 and -80 <= lon <= -50:
                    out.append((lat, lon))
            return out

        def con_busqueda(poly):
            if len(poly) < 2:
                return []
            tramos = [equirect_m(*a, *b) for a, b in zip(poly, poly[1:])]
            if sum(tramos) <= 0:
                return [(poly[0][0], poly[0][1], 0)]
            out = [(poly[0][0], poly[0][1], 0)]
            n_orig = len(poly)
            for i, dist in enumerate(tramos):
                a, b = poly[i], poly[i + 1]
                n = max(1, int(dist // paso_m))
                for k in range(1, n + 1):
                    t = k / n
                    vert = i if t < 1 else min(i + 1, n_orig - 1)
                    out.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), vert))
            return out

        def celdas_de(pts, paso=0.01):
            celdas = defaultdict(list)
            for j, (lat, lon, _v) in enumerate(pts):
                celdas[(int(lat / paso), int(lon / paso))].append(j)
            return celdas

        def mas_cercano(lat, lon, pts, celdas, paso=0.01):
            cx, cy = int(lat / paso), int(lon / paso)
            mejor, vert = None, None
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in celdas.get((cx + dx, cy + dy), ()):
                        plat, plon, v = pts[j]
                        dist = equirect_m(lat, lon, plat, plon)
                        if mejor is None or dist < mejor:
                            mejor, vert = dist, v
            return mejor, vert

        def franja_horaria(hora: int) -> str:
            if hora < 6:
                return "madrugada"
            if hora < 12:
                return "manana"
            if hora < 18:
                return "tarde"
            return "noche"

        # --- 1. Leer hojas de ruta y agruparlas por cubeta de vehículo ---
        recorridos_por_bucket = defaultdict(list)
        vehiculos = set()
        with hdr_path.open(encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip().rstrip(",")
                if not linea.startswith("{"):
                    continue
                doc = json.loads(linea)
                if doc.get("eliminada") is True:
                    continue
                desde = parsear_dt(doc.get("fechaDesde"))
                hasta = parsear_dt(doc.get("fechaHasta"))
                veh_obj = doc.get("vehiculo") or {}
                veh_id = parsear_oid(veh_obj.get("id"))
                if not desde or not hasta or not veh_id or (hasta - desde).total_seconds() < 3600:
                    continue

                id_hdr = parsear_oid(doc.get("_id"))
                tipo_veh = veh_obj.get("tipoVehiculo")
                cant_plazas = parsear_float(veh_obj.get("cantidadPlazas"))
                geom = doc.get("geometriaOSRM") or {}
                b_id = bucket_de(veh_id)

                for var in variantes:
                    gvar = geom.get(var) or {}
                    dur_s = parsear_float(gvar.get("duracion_osrm_original"))
                    raw_poly = filtrar_poly(gvar.get("puntos"))
                    if not dur_s or dur_s <= 0 or len(raw_poly) < 2:
                        continue

                    n_orig = len(raw_poly)
                    analitica = gvar.get("analitica_segmentos") or []
                    segmentos = [
                        (f"{s['origen']}_{s['destino']}", max(0, min(int(s["origen"]), n_orig - 1)))
                        for s in analitica
                        if s.get("origen") is not None and s.get("destino") is not None
                    ] or [(f"{i}_{i + 1}", i) for i in range(max(n_orig - 1, 1))]

                    vehiculos.add(veh_id)
                    recorridos_por_bucket[b_id].append(
                        {
                            "idhojaruta": id_hdr,
                            "idvehiculo": veh_id,
                            "tipovehiculo": tipo_veh,
                            "cantplazas": cant_plazas,
                            "variante": var,
                            "desde_ts": desde.timestamp(),
                            "hasta_ts": hasta.timestamp(),
                            "duracion_s": dur_s,
                            "raw_poly": raw_poly,
                            "segmentos": segmentos,
                        }
                    )

        # --- 2. Volcar rastreoSatelital.json a cubetas Parquet en disco (RAM acotada) ---
        gps_buffers = defaultdict(list)
        partes_gps_counter = defaultdict(int)
        puntos_en_ram = 0

        def vaciar_bucket_gps(b_id: int):
            nonlocal puntos_en_ram
            datos = gps_buffers.get(b_id)
            if not datos:
                return
            idx = partes_gps_counter[b_id]
            partes_gps_counter[b_id] += 1
            pl.DataFrame(
                datos,
                schema={"flota": pl.String, "ts": pl.Float64, "lat": pl.Float32, "lon": pl.Float32},
                orient="row",
            ).write_parquet(tmp_gps_dir / f"gps_b{b_id:03d}_{idx:04d}.parquet")
            puntos_en_ram -= len(datos)
            gps_buffers[b_id] = []

        with gps_path.open("rb") as f:
            for rec in ijson.items(f, "item"):
                flota = parsear_oid(rec.get("flotaID"))
                if flota not in vehiculos:
                    continue
                loc = (rec.get("location") or {}).get("coordinates")
                if not isinstance(loc, (list, tuple)) or len(loc) != 2:
                    continue
                lon, lat = parsear_float(loc[0]), parsear_float(loc[1])
                fecha = parsear_dt(rec.get("fecha"))
                if lon is None or lat is None or fecha is None:
                    continue
                if -80 <= lon <= -50 and -50 <= lat <= -20:
                    b_id = bucket_de(flota)
                    gps_buffers[b_id].append((flota, fecha.timestamp(), lat, lon))
                    puntos_en_ram += 1
                    if puntos_en_ram >= max_puntos_buffer_gps:
                        mayor_b = max(gps_buffers, key=lambda k: len(gps_buffers[k]))
                        vaciar_bucket_gps(mayor_b)

        for b_id in list(gps_buffers.keys()):
            vaciar_bucket_gps(b_id)
        del gps_buffers, vehiculos
        gc.collect()

        # --- 3. Procesar cubeta por cubeta y escribir fragmentos Parquet del dataset ---
        hueco_seg = hueco.total_seconds()
        filas_buffer = []
        parte_salida_idx = 0
        total_filas_guardadas = 0

        def vaciar_salida():
            nonlocal filas_buffer, parte_salida_idx, total_filas_guardadas
            if not filas_buffer:
                return
            pl.DataFrame(filas_buffer, schema=schema_salida).write_parquet(
                partes_dir / f"part_{parte_salida_idx:05d}.parquet"
            )
            total_filas_guardadas += len(filas_buffer)
            parte_salida_idx += 1
            filas_buffer = []

        for b_id in range(n_buckets):
            recs_bucket = recorridos_por_bucket.pop(b_id, [])
            archivos_gps = sorted(tmp_gps_dir.glob(f"gps_b{b_id:03d}_*.parquet"))
            if not recs_bucket or not archivos_gps:
                for p in archivos_gps:
                    p.unlink(missing_ok=True)
                continue

            df_gps_b = pl.read_parquet(archivos_gps).sort(["flota", "ts"])
            for p in archivos_gps:
                p.unlink(missing_ok=True)

            gps_flotas_b = {}
            for sub_df in df_gps_b.partition_by("flota", maintain_order=True):
                flota_id = sub_df["flota"][0]
                gps_flotas_b[flota_id] = (
                    sub_df["ts"].to_numpy(),
                    sub_df["lat"].to_numpy(),
                    sub_df["lon"].to_numpy(),
                )
            del df_gps_b

            for rec in recs_bucket:
                tupla_gps = gps_flotas_b.get(rec["idvehiculo"])
                if tupla_gps is None:
                    continue
                ts_arr, lat_arr, lon_arr = tupla_gps
                lo = int(np.searchsorted(ts_arr, rec["desde_ts"], side="left"))
                hi = int(np.searchsorted(ts_arr, rec["hasta_ts"], side="right"))
                if hi - lo < 2:
                    continue

                poly = con_busqueda(rec["raw_poly"])
                if len(poly) < 2:
                    continue
                celdas = celdas_de(poly)
                n_poly = max(p[2] for p in poly) + 1
                denom = max(n_poly - 1, 1)

                sobre = []
                for ts_v, lat_v, lon_v in zip(ts_arr[lo:hi], lat_arr[lo:hi], lon_arr[lo:hi]):
                    dist, vert = mas_cercano(float(lat_v), float(lon_v), poly, celdas)
                    if dist is not None and dist <= radio_m and vert is not None:
                        sobre.append((float(ts_v), vert))

                grupos, actual = [], []
                for p in sobre:
                    if not actual:
                        actual = [p]
                        continue
                    ant = actual[-1]
                    retrocede = p[1] < ant[1] - ruido_vertice
                    silencio = (p[0] - ant[0]) > hueco_seg
                    en_punta = (ant[1] / denom) >= fin or (p[1] / denom) <= inicio
                    if retrocede or (silencio and en_punta):
                        grupos.append(actual)
                        actual = [] if (retrocede and (p[1] / denom) > inicio) else [p]
                    else:
                        actual.append(p)
                if actual:
                    grupos.append(actual)

                num_pasada = 0
                for g in grupos:
                    if len(g) < 2:
                        continue
                    verts = [p[1] for p in g]
                    if (max(verts) - min(verts)) / denom < 0.05 or (g[0][1] / denom) > inicio:
                        continue

                    i_sal = 0
                    while (
                        i_sal < len(g) - 1
                        and (g[i_sal][1] / denom) <= inicio
                        and g[i_sal + 1][1] <= g[i_sal][1]
                    ):
                        i_sal += 1

                    i_lleg = next((k for k in range(i_sal, len(g)) if (g[k][1] / denom) >= fin), None)
                    if i_lleg is None:
                        continue

                    tramo = g[i_sal : i_lleg + 1]
                    ts_sal, ts_lleg = tramo[0][0], tramo[-1][0]
                    dur_real_s = ts_lleg - ts_sal
                    ratio = dur_real_s / rec["duracion_s"]
                    if dur_real_s <= 0 or not (rango_ratio[0] <= ratio <= rango_ratio[1]):
                        continue

                    num_pasada += 1
                    idrecorrido = f"{rec['idhojaruta']}_{rec['variante']}_p{num_pasada}"
                    total_segs = len(rec["segmentos"])
                    osrm_min = round(rec["duracion_s"] / 60.0, 2)
                    real_min = round(dur_real_s / 60.0, 2)

                    if nivel == "viaje":
                        dt_sal = datetime.fromtimestamp(ts_sal, tz=UTC)
                        filas_buffer.append(
                            {
                                "idrecorrido": idrecorrido,
                                "idhojaruta": rec["idhojaruta"],
                                "idvehiculo": rec["idvehiculo"],
                                "total_segmentos": total_segs,
                                "instant_t_fechahora": dt_sal,
                                "t_franjahoraria": franja_horaria(dt_sal.hour),
                                "t_dia_semana": (dt_sal.weekday() + 1) % 7,
                                "t_hora_dia": dt_sal.hour,
                                "tipovehiculo": rec["tipovehiculo"],
                                "cantplazas": rec["cantplazas"],
                                "variante": rec["variante"],
                                "osrm_total_est_min": osrm_min,
                                "y_al_salir_minutos": real_min,
                            }
                        )
                    else:
                        env_v, env_t, max_v = [], [], -1
                        for ts_p, v_p in tramo:
                            if v_p > max_v:
                                max_v = v_p
                                env_v.append(max_v)
                                env_t.append(ts_p)

                        env_v_arr = np.asarray(env_v, dtype=np.int32)
                        env_t_arr = np.asarray(env_t, dtype=np.float64)

                        for orden, (idseg, v_obj) in enumerate(rec["segmentos"], start=1):
                            if orden == 1 or len(env_v_arr) == 0:
                                ts_act = ts_sal
                            else:
                                pos = int(np.searchsorted(env_v_arr, v_obj, side="left"))
                                if pos == 0:
                                    ts_act = float(env_t_arr[0])
                                elif pos >= len(env_v_arr):
                                    ts_act = float(env_t_arr[-1])
                                else:
                                    v0, v1 = int(env_v_arr[pos - 1]), int(env_v_arr[pos])
                                    t0, t1 = float(env_t_arr[pos - 1]), float(env_t_arr[pos])
                                    ts_act = t0 + ((v_obj - v0) / max(v1 - v0, 1)) * (t1 - t0)

                            ts_act = min(max(ts_act, ts_sal), ts_lleg)
                            dt_act = datetime.fromtimestamp(ts_act, tz=UTC)
                            osrm_rest_s = rec["duracion_s"] * (1.0 - (orden - 1) / total_segs)

                            filas_buffer.append(
                                {
                                    "idrecorrido": idrecorrido,
                                    "idhojaruta": rec["idhojaruta"],
                                    "idvehiculo": rec["idvehiculo"],
                                    "total_segmentos": total_segs,
                                    "instant_t_fechahora": dt_act,
                                    "t_franjahoraria": franja_horaria(dt_act.hour),
                                    "t_dia_semana": (dt_act.weekday() + 1) % 7,
                                    "t_hora_dia": dt_act.hour,
                                    "tipovehiculo": rec["tipovehiculo"],
                                    "cantplazas": rec["cantplazas"],
                                    "variante": rec["variante"],
                                    "osrm_total_est_min": osrm_min,
                                    "y_al_salir_minutos": real_min,
                                    "idsegmento_actual": idseg,
                                    "segmento_orden_actual": orden,
                                    "osrm_restante_est_min": round(osrm_rest_s / 60.0, 2),
                                    "minutos_ya_transcurridos": round((ts_act - ts_sal) / 60.0, 2),
                                    "pct_progreso_recorrido": round((orden / total_segs) * 100.0, 2),
                                    "y_en_viaje_minutos": round((ts_lleg - ts_act) / 60.0, 2),
                                }
                            )

                    if len(filas_buffer) >= filas_por_parquet:
                        vaciar_salida()

            del gps_flotas_b, recs_bucket
            gc.collect()

        vaciar_salida()
        shutil.rmtree(tmp_gps_dir, ignore_errors=True)

        if total_filas_guardadas == 0:
            raise RuntimeError("No se encontraron pasadas válidas con los parámetros indicados.")

        # --- 4. Split temporal 80/20 y estadísticas del preprocesador en modo LAZY ---
        lf = pl.scan_parquet(str(partes_dir / "part_*.parquet"))
        dias_unicos = (
            lf.select(pl.col("instant_t_fechahora").dt.date().alias("dia"))
            .unique()
            .sort("dia")
            .collect()["dia"]
            .to_list()
        )
        if len(dias_unicos) < 2:
            raise RuntimeError("Se necesitan al menos 2 días distintos para el split temporal 80/20.")

        corte = max(1, min(len(dias_unicos) - 1, int(len(dias_unicos) * proporcion_train)))
        primer_dia_test = dias_unicos[corte]

        lf_train = lf.filter(pl.col("instant_t_fechahora").dt.date() < primer_dia_test)
        lf_test = lf.filter(pl.col("instant_t_fechahora").dt.date() >= primer_dia_test)

        cols_num = [
            "total_segmentos",
            "cantplazas",
            "t_dia_semana",
            "t_hora_dia",
            "osrm_total_est_min",
        ]
        if nivel == "segmento":
            cols_num.extend(
                [
                    "segmento_orden_actual",
                    "osrm_restante_est_min",
                    "minutos_ya_transcurridos",
                    "pct_progreso_recorrido",
                ]
            )
        cols_cat = ["tipovehiculo", "t_franjahoraria", "variante"]

        # Estadísticas numéricas calculadas solo sobre train
        exprs_stats = []
        for c in cols_num:
            exprs_stats.extend(
                [
                    pl.col(c).median().alias(f"{c}__med"),
                    pl.col(c).mean().alias(f"{c}__mean"),
                    pl.col(c).std().alias(f"{c}__std"),
                ]
            )
        stats_row = lf_train.select(exprs_stats).collect().row(0, named=True)
        num_stats = {}
        for c in cols_num:
            med = stats_row[f"{c}__med"]
            mean = stats_row[f"{c}__mean"]
            std = stats_row[f"{c}__std"]
            num_stats[c] = {
                "median": float(med) if med is not None else 0.0,
                "mean": float(mean) if mean is not None else 0.0,
                "std": float(std) if (std is not None and std > 0) else 1.0,
            }

        # Categorías vistas en train para One-Hot Encoding
        cat_vocab = {}
        for c in cols_cat:
            vals = (
                lf_train.select(pl.col(c).fill_null("desconocido").unique().sort())
                .collect()[c]
                .to_list()
            )
            cat_vocab[c] = vals

        n_train = lf_train.select(pl.len()).collect().item()
        n_test = lf_test.select(pl.len()).collect().item()
        n_features = len(cols_num) + sum(len(v) for v in cat_vocab.values())

        meta = {
            "partes_dir": str(partes_dir),
            "primer_dia_test": primer_dia_test.isoformat(),
            "objetivo": objetivo,
            "cols_num": cols_num,
            "cols_cat": cols_cat,
            "num_stats": num_stats,
            "cat_vocab": cat_vocab,
            "n_train": n_train,
            "n_test": n_test,
            "n_features": n_features,
        }
        (salida_dir / "meta_dataset.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return meta


    def crear_tf_dataset(meta: dict, split: str = "train", batch_size: int = 1024):
        """
        Crea un tf.data.Dataset que lee y transforma lotes desde Parquet en disco
        con consumo mínimo de RAM.
        """
        import tensorflow as tf

        partes = sorted(Path(meta["partes_dir"]).glob("part_*.parquet"))
        corte_dt = datetime.fromisoformat(meta["primer_dia_test"]).date()
        cols_num = meta["cols_num"]
        cols_cat = meta["cols_cat"]
        num_stats = meta["num_stats"]
        cat_vocab = meta["cat_vocab"]
        objetivo = meta["objetivo"]
        n_features = meta["n_features"]
        es_train = split == "train"

        def transformar_df(df: pl.DataFrame) -> tuple[np.ndarray, np.ndarray]:
            bloques = []
            for c in cols_num:
                st = num_stats[c]
                arr = (
                    df[c]
                    .fill_null(st["median"])
                    .to_numpy()
                    .astype(np.float32)
                )
                arr = (arr - st["mean"]) / st["std"]
                bloques.append(arr[:, None])

            for c in cols_cat:
                serie = df[c].fill_null("desconocido")
                for val in cat_vocab[c]:
                    bloques.append((serie == val).to_numpy().astype(np.float32)[:, None])

            X = np.hstack(bloques).astype(np.float32)
            y = df[objetivo].to_numpy().astype(np.float32)
            return X, y

        def generador():
            rng = np.random.default_rng()
            archivos = list(partes)
            if es_train:
                rng.shuffle(archivos)

            for ruta in archivos:
                lf = pl.scan_parquet(ruta)
                if es_train:
                    lf = lf.filter(pl.col("instant_t_fechahora").dt.date() < corte_dt)
                else:
                    lf = lf.filter(pl.col("instant_t_fechahora").dt.date() >= corte_dt)

                df_chunk = lf.collect()
                if df_chunk.is_empty():
                    continue

                X_chunk, y_chunk = transformar_df(df_chunk)
                del df_chunk

                n = len(y_chunk)
                indices = np.arange(n)
                if es_train:
                    rng.shuffle(indices)

                for start in range(0, n, batch_size):
                    idx = indices[start : start + batch_size]
                    yield X_chunk[idx], y_chunk[idx]

        return tf.data.Dataset.from_generator(
            generador,
            output_signature=(
                tf.TensorSpec(shape=(None, n_features), dtype=tf.float32),
                tf.TensorSpec(shape=(None,), dtype=tf.float32),
            ),
        ).prefetch(2)

    return armar_dataset_p3_streaming, crear_tf_dataset


@app.cell
def _(mo):
    boton_armar_ds = mo.ui.run_button(label="Armar dataset P3 en disco (baja RAM)")
    boton_armar_ds
    return (boton_armar_ds,)


@app.cell
def _(GPS, HDR, Path, armar_dataset_p3_streaming, boton_armar_ds, mo, pl):
    mo.stop(
        not boton_armar_ds.value,
        mo.md("Presioná el botón para construir los fragmentos Parquet en disco."),
    )

    dir_ds_p3 = Path(__file__).resolve().parents[2] / "parquet" / "dataset_p3_idas"
    meta_ds_p3 = armar_dataset_p3_streaming(
        hdr_path=HDR,
        gps_path=GPS,
        salida_dir=dir_ds_p3,
        variantes=("ida",),
        nivel="segmento",              # o "viaje"
        objetivo="y_en_viaje_minutos", # o "y_al_salir_minutos"
        n_buckets=32,                  # subí a 64 si tenés menos de 4 GB de RAM libre
    )

    muestra = pl.scan_parquet(f"{meta_ds_p3['partes_dir']}/part_*.parquet").head(15).collect()

    mo.vstack([
        mo.md(
            f"Dataset listo en disco: **{meta_ds_p3['n_train']:,}** filas train / "
            f"**{meta_ds_p3['n_test']:,}** filas test · **{meta_ds_p3['n_features']}** features."
        ),
        mo.ui.table(muestra.to_dicts(), selection=None),
    ])
    return (meta_ds_p3,)


@app.cell
def _(crear_tf_dataset, meta_ds_p3, tf):
    train_ds = crear_tf_dataset(meta_ds_p3, split="train", batch_size=512)
    val_ds = crear_tf_dataset(meta_ds_p3, split="test", batch_size=512)

    modelo_p3 = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(meta_ds_p3["n_features"],)),
        tf.keras.layers.Dense(units=25, activation="relu"),
        tf.keras.layers.Dropout(0.3),
        tf.keras.layers.Dense(units=25, activation="relu"),
        tf.keras.layers.Dropout(0.3),
        tf.keras.layers.Dense(units=1, activation="linear"),
    ])

    modelo_p3.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=0.01),
        loss="mean_squared_error",
        metrics=["mae"],
    )

    historial_p3 = modelo_p3.fit(
        train_ds,
        validation_data=val_ds,
        epochs=50,
    )
    return


if __name__ == "__main__":
    app.run()
