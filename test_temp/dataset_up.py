import json
import math
from pathlib import Path
from typing import Mapping, Callable
from collections import Counter
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import ijson
import psycopg2
from psycopg2.extras import execute_values

# Esquema DDL adaptado a PostgreSQL (usando JSONB y TIMESTAMPTZ)
ESQUEMA_PG = """
CREATE TABLE IF NOT EXISTS control (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hojas (
    hoja_n BIGSERIAL PRIMARY KEY,
    hoja_id TEXT,
    flota_id TEXT,
    tipo_vehiculo TEXT,
    fecha_desde_utc TIMESTAMPTZ,
    fecha_hasta_utc TIMESTAMPTZ,
    ventana_positiva INT NOT NULL,
    estado TEXT,
    documento_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS recorridos (
    recorrido_id BIGSERIAL PRIMARY KEY,
    hoja_n BIGINT NOT NULL REFERENCES hojas(hoja_n) ON DELETE CASCADE,
    variante TEXT NOT NULL,
    ruta_json JSONB NOT NULL,
    n_segmentos INT NOT NULL,
    duracion_osrm_original DOUBLE PRECISION,
    distancia_osrm DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS segmentos (
    recorrido_id BIGINT NOT NULL REFERENCES recorridos(recorrido_id) ON DELETE CASCADE,
    orden INT NOT NULL,
    origen TEXT,
    destino TEXT,
    PRIMARY KEY (recorrido_id, orden)
);

CREATE TABLE IF NOT EXISTS gps (
    gps_n BIGSERIAL PRIMARY KEY,
    flota_id TEXT,
    fecha_utc TIMESTAMPTZ,
    longitud DOUBLE PRECISION,
    latitud DOUBLE PRECISION,
    velocidad DOUBLE PRECISION,
    evento TEXT,
    campos_minimos_ok INT NOT NULL
);

CREATE TABLE IF NOT EXISTS observaciones (
    observacion_n BIGSERIAL PRIMARY KEY,
    flota_id TEXT,
    fecha_utc TIMESTAMPTZ,
    nodo_origen TEXT,
    nodo_destino TEXT,
    franja_horaria TEXT,
    tiempo_real_seg DOUBLE PRECISION,
    campos_minimos_ok INT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_hojas_vehiculo_fecha ON hojas(flota_id, fecha_desde_utc);
CREATE INDEX IF NOT EXISTS ix_recorridos_hoja ON recorridos(hoja_n);
CREATE INDEX IF NOT EXISTS ix_segmentos_nodos ON segmentos(recorrido_id, origen, destino);
CREATE INDEX IF NOT EXISTS ix_gps_vehiculo_fecha ON gps(flota_id, fecha_utc);
CREATE INDEX IF NOT EXISTS ix_obs_vehiculo_fecha ON observaciones(flota_id, fecha_utc);
"""


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
        return dt.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def _iter_documentos(ruta: Path):
    with ruta.open("rb") as archivo:
        inicio = 3 if archivo.read(3) == b"\xef\xbb\xbf" else 0
        archivo.seek(inicio)
        for numero, documento in enumerate(ijson.items(archivo, "item", use_float=False), 1):
            if isinstance(documento, dict):
                yield documento


def _geometrias(valor, camino=()):
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

def _decimal_json(valor):
    if isinstance(valor, Decimal) and valor.is_finite():
        if valor == valor.to_integral_value():
            return int(valor)
        resultado = float(valor)
        if math.isfinite(resultado):
            return resultado
    raise TypeError(f"No se pudo serializar un valor de tipo {type(valor).__name__}")

def _json(valor) -> str:
    return json.dumps(valor, ensure_ascii=False, default=_decimal_json)


def importar_dataset_postgres(
    archivos: Mapping[str, Path | str],
    db_uri: str,
    lote: int = 5000,
    log: Callable[[str], None] = print,
) -> dict:
    """Lee streaming desde los archivos JSON e inserta en PostgreSQL por lotes usando execute_values."""
    conn = psycopg2.connect(db_uri)
    conn.autocommit = False
    cursor = conn.cursor()

    log("Creando tablas e índices en PostgreSQL si no existen...")
    cursor.execute(ESQUEMA_PG)
    conn.commit()

    tablas = ("hojas", "recorridos", "segmentos", "gps", "observaciones")
    contadores = Counter({tabla: 0 for tabla in tablas})

    rutas = {k: Path(v) for k, v in archivos.items()}

    # 1. Hojas, Recorridos y Segmentos
    log("Importando Hojas, Recorridos y Segmentos...")
    for vistos, doc in enumerate(_iter_documentos(rutas["hojas"]), 1):
        vehiculo = doc.get("vehiculo") if isinstance(doc.get("vehiculo"), dict) else {}
        flota = _identificador(vehiculo.get("id"))
        desde, hasta = _fecha_utc(doc.get("fechaDesde")), _fecha_utc(doc.get("fechaHasta"))
        positiva = bool(desde and hasta and hasta > desde)

        cursor.execute(
            """
            INSERT INTO hojas (hoja_id, flota_id, tipo_vehiculo, fecha_desde_utc, fecha_hasta_utc, ventana_positiva, estado, documento_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING hoja_n
            """,
            (
                _identificador(doc.get("_id")),
                flota,
                _texto(vehiculo.get("tipoVehiculo")),
                desde,
                hasta,
                int(positiva),
                _texto(doc.get("estado")),
                _json(doc),
            ),
        )
        hoja_n = cursor.fetchone()[0]
        contadores["hojas"] += 1

        for camino, geo in _geometrias(doc.get("geometriaOSRM")):
            segmentos = geo.get("analitica_segmentos") if isinstance(geo.get("analitica_segmentos"), list) else []
            cursor.execute(
                """
                INSERT INTO recorridos (hoja_n, variante, ruta_json, n_segmentos, duracion_osrm_original, distancia_osrm)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING recorrido_id
                """,
                (
                    hoja_n,
                    ".".join(map(str, camino)) or "unico",
                    _json(camino),
                    len(segmentos),
                    _numero(geo.get("duracion_osrm_original")),
                    _numero(geo.get("distancia_osrm")),
                ),
            )
            recorrido_id = cursor.fetchone()[0]
            contadores["recorridos"] += 1

            filas_segmentos = []
            for orden, seg in enumerate(segmentos):
                if isinstance(seg, dict):
                    filas_segmentos.append((recorrido_id, orden, _identificador(seg.get("origen")), _identificador(seg.get("destino"))))
                    contadores["segmentos"] += 1

            if filas_segmentos:
                execute_values(cursor, "INSERT INTO segmentos (recorrido_id, orden, origen, destino) VALUES %s", filas_segmentos)

        if vistos % 500 == 0:
            conn.commit()
            log(f"Hojas leídas: {vistos:,}")

    conn.commit()

    # 2. GPS
    log("Importando GPS por lotes...")
    pendientes_gps = []
    for vistos, doc in enumerate(_iter_documentos(rutas["gps"]), 1):
        flota, fecha = _identificador(doc.get("flotaID")), _fecha_utc(doc.get("fecha"))
        ubicacion = doc.get("location") if isinstance(doc.get("location"), dict) else {}
        coords = ubicacion.get("coordinates") if isinstance(ubicacion.get("coordinates"), list) else []
        lon = _numero(coords[0]) if len(coords) >= 2 else None
        lat = _numero(coords[1]) if len(coords) >= 2 else None
        velocidad = _numero(doc.get("velocidad"))
        ok = bool(flota and fecha and lon is not None and lat is not None and -180 <= lon <= 180 and -90 <= lat <= 90)

        pendientes_gps.append((flota, fecha, lon, lat, velocidad, _texto(doc.get("evento")), int(ok)))
        contadores["gps"] += 1

        if len(pendientes_gps) >= lote:
            execute_values(cursor, "INSERT INTO gps (flota_id, fecha_utc, longitud, latitud, velocidad, evento, campos_minimos_ok) VALUES %s", pendientes_gps)
            conn.commit()
            pendientes_gps.clear()
            log(f"GPS leídos: {vistos:,}")

    if pendientes_gps:
        execute_values(cursor, "INSERT INTO gps (flota_id, fecha_utc, longitud, latitud, velocidad, evento, campos_minimos_ok) VALUES %s", pendientes_gps)
        conn.commit()

    # 3. Observaciones
    log("Importando Observaciones por lotes...")
    pendientes_obs = []
    for vistos, doc in enumerate(_iter_documentos(rutas["observaciones"]), 1):
        flota, fecha = _identificador(doc.get("flotaID")), _fecha_utc(doc.get("fecha"))
        origen, destino = _identificador(doc.get("nodo_origen")), _identificador(doc.get("nodo_destino"))
        segundos = _numero(doc.get("tiempo_real"))
        ok = bool(flota and fecha and origen and destino and segundos is not None and segundos > 0)

        pendientes_obs.append((flota, fecha, origen, destino, _texto(doc.get("franja_horaria")), segundos, int(ok)))
        contadores["observaciones"] += 1

        if len(pendientes_obs) >= lote:
            execute_values(cursor, "INSERT INTO observaciones (flota_id, fecha_utc, nodo_origen, nodo_destino, franja_horaria, tiempo_real_seg, campos_minimos_ok) VALUES %s", pendientes_obs)
            conn.commit()
            pendientes_obs.clear()
            log(f"Observaciones leídas: {vistos:,}")

    if pendientes_obs:
        execute_values(cursor, "INSERT INTO observaciones (flota_id, fecha_utc, nodo_origen, nodo_destino, franja_horaria, tiempo_real_seg, campos_minimos_ok) VALUES %s", pendientes_obs)
        conn.commit()

    cursor.close()
    conn.close()

    return {
        "tablas": [{"tabla": t, "filas": contadores[t]} for t in tablas],
        "mensaje": "Importación completada con éxito en PostgreSQL",
    }
