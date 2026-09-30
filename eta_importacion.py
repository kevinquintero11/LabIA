"""Importación local de los tres JSON del proyecto ETA a SQLite.

Requiere Python >= 3.10 e ijson en el mismo entorno que marimo.
No modifica los JSON ni construye viajes, etiquetas o modelos.
Las fechas sin zona horaria NO se interpretan automáticamente como UTC.
Los tiempos/distancias OSRM conservan sus unidades de origen.

El archivo SQLite final sólo aparece cuando la importación termina. Un archivo
.lock impide dos importaciones simultáneas al mismo destino. La reutilización
se comprueba por versión, ruta, tamaño y mtime; no es una verificación SHA-256.
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterator, Mapping
import json
import math
import os
import sqlite3
import tempfile
import time

VERSION = 1
TABLAS = ("hojas", "recorridos", "segmentos", "gps", "observaciones")

ESQUEMA = """
CREATE TABLE control (clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
CREATE TABLE hojas (
    hoja_n INTEGER PRIMARY KEY,
    hoja_id TEXT, flota_id TEXT, tipo_vehiculo TEXT,
    fecha_desde_utc TEXT, fecha_hasta_utc TEXT,
    ventana_positiva INTEGER NOT NULL, estado TEXT,
    documento_json TEXT NOT NULL
);
CREATE TABLE recorridos (
    recorrido_id INTEGER PRIMARY KEY,
    hoja_n INTEGER NOT NULL REFERENCES hojas(hoja_n),
    variante TEXT NOT NULL, ruta_json TEXT NOT NULL,
    n_segmentos INTEGER NOT NULL,
    duracion_osrm_original REAL, distancia_osrm REAL
);
CREATE TABLE segmentos (
    recorrido_id INTEGER NOT NULL REFERENCES recorridos(recorrido_id),
    orden INTEGER NOT NULL, origen TEXT, destino TEXT,
    PRIMARY KEY (recorrido_id, orden)
) WITHOUT ROWID;
CREATE TABLE gps (
    gps_n INTEGER PRIMARY KEY,
    flota_id TEXT, fecha_utc TEXT,
    longitud REAL, latitud REAL, velocidad REAL, evento TEXT,
    campos_minimos_ok INTEGER NOT NULL
);
CREATE TABLE observaciones (
    observacion_n INTEGER PRIMARY KEY,
    flota_id TEXT, fecha_utc TEXT,
    nodo_origen TEXT, nodo_destino TEXT, franja_horaria TEXT,
    tiempo_real_seg REAL, campos_minimos_ok INTEGER NOT NULL
);
"""

INDICES = (
    "CREATE INDEX ix_hojas_vehiculo_fecha ON hojas(flota_id, fecha_desde_utc)",
    "CREATE INDEX ix_recorridos_hoja ON recorridos(hoja_n)",
    "CREATE INDEX ix_segmentos_nodos ON segmentos(recorrido_id, origen, destino)",
    "CREATE INDEX ix_gps_vehiculo_fecha ON gps(flota_id, fecha_utc)",
    "CREATE INDEX ix_obs_vehiculo_fecha ON observaciones(flota_id, fecha_utc)",
)


def _identificador(valor) -> str | None:
    if isinstance(valor, dict):
        for clave in ("$oid", "$numberLong", "$numberInt"):
            if clave in valor:
                return _identificador(valor[clave])
        return None
    if isinstance(valor, str):
        return valor if valor else None
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return str(valor)
    if isinstance(valor, Decimal) and valor.is_finite():
        if valor == valor.to_integral_value():
            return str(int(valor))
    return None


def _numero(valor) -> float | None:
    if isinstance(valor, dict):
        for clave in ("$numberLong", "$numberInt", "$numberDouble", "$numberDecimal"):
            if clave in valor:
                return _numero(valor[clave])
        return None
    if valor is None or isinstance(valor, bool):
        return None
    try:
        resultado = float(valor)
    except (TypeError, ValueError, OverflowError):
        return None
    return resultado if math.isfinite(resultado) else None


def _texto(valor) -> str | None:
    return valor if isinstance(valor, str) else None


def _fecha_utc(valor) -> str | None:
    if isinstance(valor, dict):
        valor = valor.get("$date")
    try:
        if isinstance(valor, dict) and "$numberLong" in valor:
            milisegundos = int(valor["$numberLong"])
            dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=milisegundos)
        elif isinstance(valor, str):
            dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                return None
        else:
            return None
        # Formato fijo: las comparaciones SQL por intervalo conservan el orden.
        return dt.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (ValueError, TypeError, OverflowError):
        return None


def _decimal_json(valor):
    if isinstance(valor, Decimal) and valor.is_finite():
        if valor == valor.to_integral_value():
            return int(valor)
        resultado = float(valor)
        if math.isfinite(resultado):
            return resultado
    raise TypeError(f"No se pudo serializar un valor de tipo {type(valor).__name__}")


def _json(valor) -> str:
    return json.dumps(valor, ensure_ascii=False, separators=(",", ":"),
                      default=_decimal_json, allow_nan=False)


def _iter_documentos(ruta: Path) -> Iterator[dict]:
    # Importación diferida: consultar una base ya creada no requiere ijson.
    try:
        import ijson
    except ImportError as exc:
        raise ImportError("Instalá ijson en el mismo entorno de marimo: python -m pip install ijson") from exc
    with ruta.open("rb") as archivo:
        inicio = 3 if archivo.read(3) == b"\xef\xbb\xbf" else 0
        archivo.seek(inicio)
        caracter = archivo.read(1)
        while caracter in (b" ", b"\t", b"\r", b"\n"):
            caracter = archivo.read(1)
        if caracter != b"[":
            raise ValueError(f"{ruta.name}: se esperaba un array JSON [{{...}}, ...].")
        archivo.seek(inicio)
        # False conserva enteros grandes y usa Decimal para números no enteros.
        for numero, documento in enumerate(ijson.items(archivo, "item", use_float=False), 1):
            if not isinstance(documento, dict):
                raise ValueError(f"{ruta.name}: el elemento {numero} no es un documento.")
            yield documento


def _geometrias(valor, camino=()):
    """Encuentra objetos de recorrido por los campos documentados; no infiere tiempos."""
    if isinstance(valor, dict):
        if "analitica_segmentos" in valor or "duracion_osrm_original" in valor:
            yield camino, valor
        else:
            for clave, contenido in valor.items():
                if isinstance(contenido, (dict, list)):
                    yield from _geometrias(contenido, camino + (clave,))
    elif isinstance(valor, list):
        for indice, contenido in enumerate(valor):
            if isinstance(contenido, (dict, list)):
                yield from _geometrias(contenido, camino + (indice,))


def _huella(ruta: Path) -> dict:
    estado = ruta.stat()
    return {"ruta": str(ruta.resolve()), "bytes": estado.st_size, "mtime_ns": estado.st_mtime_ns}


def _importar_hojas(con, ruta, contadores, incidencias, informar):
    vistos = 0
    for vistos, doc in enumerate(_iter_documentos(ruta), 1):
        vehiculo = doc.get("vehiculo")
        vehiculo = vehiculo if isinstance(vehiculo, dict) else {}
        flota = _identificador(vehiculo.get("id"))
        desde, hasta = _fecha_utc(doc.get("fechaDesde")), _fecha_utc(doc.get("fechaHasta"))
        positiva = bool(desde and hasta and hasta > desde)
        if not positiva:
            incidencias["hojas_sin_ventana_positiva"] += 1
        if flota is None:
            incidencias["hojas_sin_vehiculo"] += 1
        con.execute("INSERT INTO hojas VALUES (?,?,?,?,?,?,?,?,?)", (
            vistos, _identificador(doc.get("_id")), flota, _texto(vehiculo.get("tipoVehiculo")),
            desde, hasta, int(positiva), _texto(doc.get("estado")), _json(doc)))
        contadores["hojas"] += 1
        encontrados = 0
        for camino, geo in _geometrias(doc.get("geometriaOSRM")):
            encontrados += 1
            segmentos = geo.get("analitica_segmentos")
            if not isinstance(segmentos, list):
                segmentos = []
                incidencias["recorridos_sin_lista_segmentos"] += 1
            cur = con.execute("""INSERT INTO recorridos
                (hoja_n,variante,ruta_json,n_segmentos,duracion_osrm_original,distancia_osrm)
                VALUES (?,?,?,?,?,?)""", (
                vistos, ".".join(map(str, camino)) or "unico", _json(camino), len(segmentos),
                _numero(geo.get("duracion_osrm_original")), _numero(geo.get("distancia_osrm"))))
            recorrido_id = cur.lastrowid
            def filas_segmentos():
                for orden, segmento in enumerate(segmentos):
                    if not isinstance(segmento, dict):
                        incidencias["segmentos_no_documento"] += 1
                        continue
                    origen = _identificador(segmento.get("origen"))
                    destino = _identificador(segmento.get("destino"))
                    if origen is None or destino is None:
                        incidencias["segmentos_sin_nodos"] += 1
                    contadores["segmentos"] += 1
                    yield recorrido_id, orden, origen, destino
            con.executemany("INSERT INTO segmentos VALUES (?,?,?,?)", filas_segmentos())
            contadores["recorridos"] += 1
        if not encontrados:
            incidencias["hojas_sin_recorrido_detectado"] += 1
        # No se acumulan documentos de hojas en una lista de Python.
        if vistos % 100 == 0:
            con.commit()
            informar("hojas", vistos)
    con.commit()
    informar("hojas", vistos, True)


def _importar_mediciones(con, ruta, tipo, lote, contadores, incidencias, informar):
    pendientes = []
    vistos = 0
    sql = ("INSERT INTO gps VALUES (?,?,?,?,?,?,?,?)" if tipo == "gps" else
           "INSERT INTO observaciones VALUES (?,?,?,?,?,?,?,?)")
    for vistos, doc in enumerate(_iter_documentos(ruta), 1):
        flota, fecha = _identificador(doc.get("flotaID")), _fecha_utc(doc.get("fecha"))
        if tipo == "gps":
            ubicacion = doc.get("location")
            coords = ubicacion.get("coordinates") if isinstance(ubicacion, dict) else None
            lon = _numero(coords[0]) if isinstance(coords, list) and len(coords) >= 2 else None
            lat = _numero(coords[1]) if isinstance(coords, list) and len(coords) >= 2 else None
            velocidad = _numero(doc.get("velocidad"))
            ok = bool(flota and fecha and lon is not None and lat is not None
                      and -180 <= lon <= 180 and -90 <= lat <= 90)
            fila = (vistos, flota, fecha, lon, lat, velocidad, _texto(doc.get("evento")), int(ok))
            if velocidad == 0:
                incidencias["gps_velocidad_cero_conservados"] += 1
            elif velocidad is None or velocidad < 0:
                incidencias["gps_velocidad_a_revisar"] += 1
        else:
            origen, destino = _identificador(doc.get("nodo_origen")), _identificador(doc.get("nodo_destino"))
            segundos = _numero(doc.get("tiempo_real"))
            ok = bool(flota and fecha and origen and destino and segundos is not None and segundos > 0)
            fila = (vistos, flota, fecha, origen, destino, _texto(doc.get("franja_horaria")), segundos, int(ok))
        if not ok:
            incidencias[f"{tipo}_campos_minimos_a_revisar"] += 1
        pendientes.append(fila)
        contadores[tipo] += 1
        if len(pendientes) >= lote:
            con.executemany(sql, pendientes)
            con.commit()
            pendientes.clear()
            informar(tipo, vistos)
    if pendientes:
        con.executemany(sql, pendientes)
    con.commit()
    informar(tipo, vistos, True)


def importar_dataset(archivos: Mapping[str, Path | str], destino: Path | str,
                     lote: int = 5000, log: Callable[[str], None] = print) -> dict:
    """Crea la base una vez o reutiliza una importación completa de los mismos archivos.

    claves de archivos: hojas, gps, observaciones.
    No reanuda un archivo interrumpido: ante un error se descarta sólo la base
    temporal de esta ejecución. Los JSON originales nunca se modifican.
    """
    if isinstance(lote, bool) or not isinstance(lote, int) or lote <= 0:
        raise ValueError("lote debe ser un entero positivo.")
    claves = ("hojas", "gps", "observaciones")
    rutas = {clave: Path(archivos[clave]).expanduser().resolve() for clave in claves}
    for ruta in rutas.values():
        if not ruta.is_file():
            raise FileNotFoundError(ruta)
    destino = Path(destino).expanduser().resolve()
    if destino in rutas.values():
        raise ValueError("La base de destino no puede ser un JSON de origen.")
    destino.parent.mkdir(parents=True, exist_ok=True)
    huellas = {clave: _huella(ruta) for clave, ruta in rutas.items()}
    firma = {"version": VERSION, "archivos": huellas}
    if destino.exists():
        try:
            with closing(sqlite3.connect(destino.as_uri() + "?mode=ro", uri=True)) as con:
                registro = con.execute("SELECT valor FROM control WHERE clave='resultado'").fetchone()
            anterior = json.loads(registro[0]) if registro else None
        except (sqlite3.Error, ValueError, TypeError) as exc:
            raise ValueError("La base existente no corresponde a este importador. Usá otro nombre de base.") from exc
        if not anterior or anterior.get("firma") != firma:
            raise ValueError("La base existe, pero cambió el origen o la versión. Usá otro nombre de base; no se sobrescribió nada.")
        log("Base completa encontrada: no se vuelven a leer los JSON.")
        return {**anterior, "base": str(destino), "reutilizada": True}

    bloqueo = destino.with_suffix(destino.suffix + ".lock")
    try:
        fd = os.open(bloqueo, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(f"Existe {bloqueo.name}. No inicies otra importación. Si hubo un cierre forzado, verificá que no siga activa antes de quitar ese bloqueo.") from exc
    os.close(fd)
    temporal = None
    con = None
    inicio = time.monotonic()
    ultimo_aviso = inicio
    try:
        if destino.exists():
            raise FileExistsError("Otra ejecución creó la base. Volvé a ejecutar la celda.")
        fd, nombre = tempfile.mkstemp(prefix=destino.stem + "_", suffix=".parcial.sqlite", dir=destino.parent)
        os.close(fd)
        temporal = Path(nombre)
        con = sqlite3.connect(temporal)
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA cache_size=-32768")
        con.execute("PRAGMA temp_store=FILE")
        con.executescript(ESQUEMA)
        contadores = Counter({tabla: 0 for tabla in TABLAS})
        incidencias = Counter()
        def informar(tipo, n, forzar=False):
            nonlocal ultimo_aviso
            ahora = time.monotonic()
            if forzar or ahora - ultimo_aviso >= 5:
                log(f"{tipo}: {n:,} documentos leídos. Transcurrido: {(ahora-inicio)/60:.1f} min")
                ultimo_aviso = ahora
        log("Importando hojas y sus recorridos...")
        _importar_hojas(con, rutas["hojas"], contadores, incidencias, informar)
        for tipo in ("gps", "observaciones"):
            log(f"Importando {tipo} por lotes de {lote:,}...")
            _importar_mediciones(con, rutas[tipo], tipo, lote, contadores, incidencias, informar)
        for n, sentencia in enumerate(INDICES, 1):
            log(f"Creando índice {n}/{len(INDICES)}; esta etapa también puede demorar...")
            con.execute(sentencia)
            con.commit()
        if huellas != {clave: _huella(ruta) for clave, ruta in rutas.items()}:
            raise RuntimeError("Un JSON cambió durante la lectura. Repetí con archivos estables.")
        resultado = {
            "base": str(destino), "firma": firma,
            "tablas": [{"tabla": tabla, "filas": contadores[tabla]} for tabla in TABLAS],
            "incidencias": dict(incidencias),
            "segundos_importacion": round(time.monotonic() - inicio, 2),
            "reutilizada": False,
            "notas": ["No se identificaron viajes ni etiquetas.",
                      "OSRM mantiene sus unidades de origen.",
                      "Los nodos se guardan como texto, sin pasar por float.",
                      "campos_minimos_ok sólo comprueba presencia y rangos básicos."]
        }
        con.execute("INSERT INTO control VALUES ('resultado',?)", (_json(resultado),))
        con.commit()
        con.close()
        con = None
        # El bloqueo evita dos escritores cooperativos sobre este destino.
        if destino.exists():
            raise FileExistsError("El destino apareció durante la importación; no se sobrescribió.")
        os.replace(temporal, destino)
        log(f"Importación terminada: {destino}")
        return resultado
    finally:
        if con is not None:
            con.close()
        if temporal is not None:
            for sufijo in ("", "-journal", "-wal", "-shm"):
                Path(str(temporal) + sufijo).unlink(missing_ok=True)
        bloqueo.unlink(missing_ok=True)


def consultar_base(base: Path | str, sql: str, parametros=(), max_filas: int = 1000) -> list[dict]:
    """Consulta de sólo lectura y salida acotada. Agregá LIMIT a consultas de detalle."""
    if not isinstance(max_filas, int) or isinstance(max_filas, bool) or max_filas <= 0:
        raise ValueError("max_filas debe ser un entero positivo.")
    base = Path(base).resolve()
    with closing(sqlite3.connect(base.as_uri() + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        filas = con.execute(sql, parametros).fetchmany(max_filas + 1)
        if len(filas) > max_filas:
            raise ValueError(f"La consulta devuelve más de {max_filas} filas. Agregá LIMIT o agregaciones.")
        return [dict(fila) for fila in filas]


def ejemplo_geometria(base: Path | str, recorrido_id: int | None = None) -> dict:
    filtro = "AND r.recorrido_id=?" if recorrido_id is not None else ""
    parametros = (recorrido_id,) if recorrido_id is not None else ()
    filas = consultar_base(base, f"""
        SELECT h.hoja_id, h.flota_id, r.recorrido_id, r.variante,
               r.ruta_json, h.documento_json
        FROM recorridos r JOIN hojas h ON h.hoja_n=r.hoja_n
        WHERE r.n_segmentos>0 {filtro}
        ORDER BY r.recorrido_id LIMIT 1
    """, parametros)
    if not filas:
        return {"mensaje": "No se encontró un recorrido con segmentos para esta selección."}
    fila = filas[0]
    doc = json.loads(fila.pop("documento_json"))
    geo = doc["geometriaOSRM"]
    for clave in json.loads(fila.pop("ruta_json")):
        geo = geo[clave]
    def compacto(valor, nivel=0):
        if nivel >= 6 and isinstance(valor, (list, dict)):
            return f"<{type(valor).__name__}: {len(valor)} elementos>"
        if isinstance(valor, dict):
            return {k: compacto(v, nivel+1) for k, v in valor.items()}
        if isinstance(valor, list):
            primeros = [compacto(v, nivel+1) for v in valor[:4]]
            return primeros if len(valor) <= 4 else primeros + [f"... {len(valor)-4} elementos más"]
        if isinstance(valor, str) and len(valor) > 300:
            return valor[:300] + "..."
        return valor
    return {
        **fila,
        "claves_geometria": list(geo),
        "duracion_osrm_original": geo.get("duracion_osrm_original"),
        "distancia_osrm": geo.get("distancia_osrm"),
        "n_segmentos": len(geo["analitica_segmentos"]),
        "primeros_dos_segmentos": compacto(geo["analitica_segmentos"][:2]),
        "nota": "Vista acotada; listas internas largas se abreviaron. No se asumieron unidades OSRM."
    }
