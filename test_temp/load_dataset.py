import io
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

# ==============================================================================
# CONFIGURACIÓN DINÁMICA DEL ESQUEMA BASADA EN LOS ESQUEMAS REALES
# ==============================================================================
TABLAS_CONFIG = {
    "hojas": {
        "columnas": {
            "hoja_n": "BIGSERIAL PRIMARY KEY",
            "hoja_id": "TEXT",
            "obra_id": "TEXT",
            "flota_id": "TEXT",
            "tipo_vehiculo": "TEXT",
            "cantidad_plazas": "INT",
            "total_pasajeros": "INT",
            "fecha_desde_utc": "TIMESTAMPTZ",
            "fecha_hasta_utc": "TIMESTAMPTZ",
            "ventana_positiva": "INT NOT NULL",
            "estado": "TEXT",
            "eliminada": "BOOLEAN",
            "tipo_hdr": "TEXT",
            "documento_json": "JSONB NOT NULL",
        },
        "indices": [
            "CREATE INDEX IF NOT EXISTS ix_hojas_vehiculo_fecha ON hojas(flota_id, fecha_desde_utc);",
            "CREATE INDEX IF NOT EXISTS ix_hojas_obra ON hojas(obra_id);",
        ]
    },
    "pasajeros": {
        "columnas": {
            "pasajero_id": "BIGSERIAL PRIMARY KEY",
            "hoja_n": "BIGINT NOT NULL REFERENCES hojas(hoja_n) ON DELETE CASCADE",
            "dni": "TEXT",
            "tarea": "TEXT",
            "ciudad": "TEXT",
            "lugar_sube": "TEXT",
            "destino": "TEXT",
            "agregado_despues": "BOOLEAN",
        },
        "indices": [
            "CREATE INDEX IF NOT EXISTS ix_pasajeros_hoja ON pasajeros(hoja_n);",
            "CREATE INDEX IF NOT EXISTS ix_pasajeros_dni ON pasajeros(dni);",
        ]
    },
    "waypoints": {
        "columnas": {
            "waypoint_id": "BIGSERIAL PRIMARY KEY",
            "hoja_n": "BIGINT NOT NULL REFERENCES hojas(hoja_n) ON DELETE CASCADE",
            "sentido": "TEXT NOT NULL",
            "orden": "INT NOT NULL",
            "nombre": "TEXT",
            "tipo": "TEXT",
            "longitud": "DOUBLE PRECISION",
            "latitud": "DOUBLE PRECISION",
        },
        "indices": ["CREATE INDEX IF NOT EXISTS ix_waypoints_hoja ON waypoints(hoja_n);"]
    },
    "paradas": {
        "columnas": {
            "parada_id": "BIGSERIAL PRIMARY KEY",
            "hoja_n": "BIGINT NOT NULL REFERENCES hojas(hoja_n) ON DELETE CASCADE",
            "sentido": "TEXT NOT NULL",
            "orden": "INT NOT NULL",
            "localidad": "TEXT",
            "hora_utc": "TIMESTAMPTZ",
            "longitud": "DOUBLE PRECISION",
            "latitud": "DOUBLE PRECISION",
        },
        "indices": ["CREATE INDEX IF NOT EXISTS ix_paradas_hoja ON paradas(hoja_n);"]
    },
    "recorridos": {
        "columnas": {
            "recorrido_id": "BIGSERIAL PRIMARY KEY",
            "hoja_n": "BIGINT NOT NULL REFERENCES hojas(hoja_n) ON DELETE CASCADE",
            "variante": "TEXT NOT NULL",
            "puntos_json": "JSONB",
            "n_segmentos": "INT NOT NULL",
            "duracion_osrm_original": "DOUBLE PRECISION",
            "distancia_osrm": "DOUBLE PRECISION",
        },
        "indices": ["CREATE INDEX IF NOT EXISTS ix_recorridos_hoja ON recorridos(hoja_n);"]
    },
    "segmentos": {
        "columnas": {
            "recorrido_id": "BIGINT NOT NULL REFERENCES recorridos(recorrido_id) ON DELETE CASCADE",
            "orden": "INT NOT NULL",
            "origen": "TEXT",
            "destino": "TEXT",
            "tiempo_estimado": "DOUBLE PRECISION",
            "fuente": "TEXT",
        },
        "pk": "PRIMARY KEY (recorrido_id, orden)",
        "indices": ["CREATE INDEX IF NOT EXISTS ix_segmentos_nodos ON segmentos(recorrido_id, origen, destino);"]
    },
    "gps": {
        "columnas": {
            "gps_n": "BIGSERIAL PRIMARY KEY",
            "flota_id": "TEXT",
            "fecha_utc": "TIMESTAMPTZ",
            "longitud": "DOUBLE PRECISION",
            "latitud": "DOUBLE PRECISION",
            "velocidad": "DOUBLE PRECISION",
            "evento": "TEXT",
            "campos_minimos_ok": "INT NOT NULL",
        },
        "indices": ["CREATE INDEX IF NOT EXISTS ix_gps_vehiculo_fecha ON gps(flota_id, fecha_utc);"]
    },
    "observaciones": {
        "columnas": {
            "observacion_n": "BIGSERIAL PRIMARY KEY",
            "flota_id": "TEXT",
            "fecha_utc": "TIMESTAMPTZ",
            "nodo_origen": "TEXT",
            "nodo_destino": "TEXT",
            "franja_horaria": "TEXT",
            "tiempo_real_seg": "DOUBLE PRECISION",
            "campos_minimos_ok": "INT NOT NULL",
        },
        "indices": ["CREATE INDEX IF NOT EXISTS ix_obs_vehiculo_fecha ON observaciones(flota_id, fecha_utc);"]
    }
}


def generar_ddl_tablas(config: dict) -> str:
    sentencias = []
    for nombre_tabla, meta in config.items():
        defs = [f"    {col} {tipo}" for col, tipo in meta["columnas"].items()]
        if "pk" in meta:
            defs.append(f"    {meta['pk']}")
        body = ",\n".join(defs)
        sentencias.append(f"CREATE TABLE IF NOT EXISTS {nombre_tabla} (\n{body}\n);")
    return "\n\n".join(sentencias)


def generar_ddl_indices(config: dict) -> str:
    indices = []
    for meta in config.values():
        indices.extend(meta.get("indices", []))
    return "\n".join(indices)


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
        for documento in ijson.items(archivo, "item", use_float=False):
            if isinstance(documento, dict):
                yield documento


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


def _fmt_tsv(val) -> str:
    if val is None:
        return r"\N"
    s = str(val)
    return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def copy_bulk_dinamico(cursor, tabla: str, registros: list[dict]):
    if not registros:
        return
    columnas = tuple(registros[0].keys())
    buffer = io.StringIO()
    for reg in registros:
        buffer.write("\t".join(_fmt_tsv(reg[col]) for col in columnas) + "\n")
    buffer.seek(0)
    cols_sql = ", ".join(columnas)
    cursor.copy_expert(f"COPY {tabla} ({cols_sql}) FROM STDIN WITH (FORMAT text, NULL '\\N')", buffer)


def insert_bulk_returning_dinamico(cursor, tabla: str, registros: list[dict], campo_returning: str) -> list[tuple]:
    if not registros:
        return []
    columnas = tuple(registros[0].keys())
    cols_sql = ", ".join(columnas)
    filas = [tuple(r[col] for col in columnas) for r in registros]
    sql = f"INSERT INTO {tabla} ({cols_sql}) VALUES %s RETURNING {campo_returning}"
    return execute_values(cursor, sql, filas, fetch=True)


def importar_dataset_postgres(
    archivos: Mapping[str, Path | str],
    db_uri: str,
    lote: int = 25000,
    log: Callable[[str], None] = print,
) -> dict:
    conn = psycopg2.connect(db_uri)
    conn.autocommit = False
    cursor = conn.cursor()

    cursor.execute("SET LOCAL synchronous_commit = off;")

    log("Creando esquemas de tablas dinámicamente según esquemas reales...")
    cursor.execute(generar_ddl_tablas(TABLAS_CONFIG))
    conn.commit()

    tablas = tuple(TABLAS_CONFIG.keys())
    contadores = Counter({tabla: 0 for tabla in tablas})
    rutas = {k: Path(v) for k, v in archivos.items()}

    # 1. Hojas de Ruta y Sub-estructuras (Pasajeros, Waypoints, Paradas, Recorridos, Segmentos)
    log("Iniciando procesamiento de Hojas de Ruta...")
    lote_hojas = []
    docs_hojas_buffer = []

    def _flush_hojas():
        if not lote_hojas:
            return

        n_hojas = len(lote_hojas)
        log(f" ─► [BATCH HOJAS] Insertando {n_hojas:,} hojas de ruta...")
        hojas_ids = insert_bulk_returning_dinamico(cursor, "hojas", lote_hojas, "hoja_n")

        filas_pasajeros = []
        filas_waypoints = []
        filas_paradas = []
        lote_recorridos = []
        docs_recorridos_buffer = []

        for (hoja_n,), doc in zip(hojas_ids, docs_hojas_buffer):
            # A. Pasajeros
            pasajeros_list = doc.get("pasajeros") if isinstance(doc.get("pasajeros"), list) else []
            for p in pasajeros_list:
                if isinstance(p, dict):
                    filas_pasajeros.append({
                        "hoja_n": hoja_n,
                        "dni": _identificador(p.get("dni")),
                        "tarea": _texto(p.get("tarea")),
                        "ciudad": _texto(p.get("ciudad")),
                        "lugar_sube": _texto(p.get("lugarSube")),
                        "destino": _texto(p.get("destino")),
                        "agregado_despues": bool(p.get("agregadoDespuesDeCreacion")),
                    })

            # B. Waypoints (Ida, Vuelta, Alternativa)
            for sentido in ("ida", "vuelta", "alternativa"):
                clave_wp = f"waypoints{sentido.capitalize()}"
                wps = doc.get(clave_wp) if isinstance(doc.get(clave_wp), list) else []
                for item in wps:
                    if isinstance(item, dict):
                        coords = item.get("coordenadas") if isinstance(item.get("coordenadas"), dict) else {}
                        filas_waypoints.append({
                            "hoja_n": hoja_n,
                            "sentido": sentido,
                            "orden": item.get("orden", 0),
                            "nombre": _texto(item.get("nombre")),
                            "tipo": _texto(item.get("tipo")),
                            "latitud": _numero(coords.get("latitud")),
                            "longitud": _numero(coords.get("longitud")),
                        })

            # C. Paradas (Ida, Vuelta, Alternativa)
            for sentido in ("ida", "vuelta", "alternativa"):
                clave_parada = f"paradas{sentido.capitalize()}"
                paradas = doc.get(clave_parada) if isinstance(doc.get(clave_parada), list) else []
                for item in paradas:
                    if isinstance(item, dict):
                        coords = item.get("coordenadas") if isinstance(item.get("coordenadas"), dict) else {}
                        filas_paradas.append({
                            "hoja_n": hoja_n,
                            "sentido": sentido,
                            "orden": item.get("orden", 0),
                            "localidad": _texto(item.get("localidad")),
                            "hora_utc": _fecha_utc(item.get("hora")),
                            "latitud": _numero(coords.get("latitud")),
                            "longitud": _numero(coords.get("longitud")),
                        })

            # D. Geometria OSRM (Recorridos y Segmentos)
            geo_osrm = doc.get("geometriaOSRM") if isinstance(doc.get("geometriaOSRM"), dict) else {}
            for variante in ("ida", "vuelta", "alternativa"):
                var_obj = geo_osrm.get(variante) if isinstance(geo_osrm.get(variante), dict) else None
                if var_obj:
                    segmentos = var_obj.get("analitica_segmentos") if isinstance(var_obj.get("analitica_segmentos"), list) else []
                    lote_recorridos.append({
                        "hoja_n": hoja_n,
                        "variante": variante,
                        "puntos_json": _json(var_obj.get("puntos")),
                        "n_segmentos": len(segmentos),
                        "duracion_osrm_original": _numero(var_obj.get("duracion_osrm_original")),
                        "distancia_osrm": _numero(var_obj.get("distancia_osrm")),
                    })
                    docs_recorridos_buffer.append(segmentos)

        # Inserciones asociadas en batch
        if filas_pasajeros:
            log(f"    ├─► [COPY PASAJEROS] Insertando {len(filas_pasajeros):,} pasajeros...")
            copy_bulk_dinamico(cursor, "pasajeros", filas_pasajeros)
            contadores["pasajeros"] += len(filas_pasajeros)

        if filas_waypoints:
            log(f"    ├─► [COPY WAYPOINTS] Insertando {len(filas_waypoints):,} waypoints...")
            copy_bulk_dinamico(cursor, "waypoints", filas_waypoints)
            contadores["waypoints"] += len(filas_waypoints)

        if filas_paradas:
            log(f"    ├─► [COPY PARADAS] Insertando {len(filas_paradas):,} paradas...")
            copy_bulk_dinamico(cursor, "paradas", filas_paradas)
            contadores["paradas"] += len(filas_paradas)

        if lote_recorridos:
            log(f"    ├─► [BATCH RECORRIDOS] Insertando {len(lote_recorridos):,} recorridos...")
            recorridos_ids = insert_bulk_returning_dinamico(cursor, "recorridos", lote_recorridos, "recorrido_id")
            filas_segmentos = []

            for (recorrido_id,), segmentos in zip(recorridos_ids, docs_recorridos_buffer):
                for orden, seg in enumerate(segmentos):
                    if isinstance(seg, dict):
                        filas_segmentos.append({
                            "recorrido_id": recorrido_id,
                            "orden": orden,
                            "origen": _identificador(seg.get("origen")),
                            "destino": _identificador(seg.get("destino")),
                            "tiempo_estimado": _numero(seg.get("tiempo_estimado")),
                            "fuente": _texto(seg.get("fuente")),
                        })

            if filas_segmentos:
                log(f"    └─► [COPY SEGMENTOS] Insertando {len(filas_segmentos):,} segmentos...")
                copy_bulk_dinamico(cursor, "segmentos", filas_segmentos)
                contadores["segmentos"] += len(filas_segmentos)

            contadores["recorridos"] += len(lote_recorridos)

        contadores["hojas"] += len(lote_hojas)
        lote_hojas.clear()
        docs_hojas_buffer.clear()

    vistos_hojas = 0
    for doc in _iter_documentos(rutas["hojas"]):
        vistos_hojas += 1
        vehiculo = doc.get("vehiculo") if isinstance(doc.get("vehiculo"), dict) else {}
        desde, hasta = _fecha_utc(doc.get("fechaDesde")), _fecha_utc(doc.get("fechaHasta"))
        total_p = _numero(doc.get("totalPasajeros"))

        lote_hojas.append({
            "hoja_id": _identificador(doc.get("_id")),
            "obra_id": _identificador(doc.get("obra_id")),
            "flota_id": _identificador(vehiculo.get("id")),
            "tipo_vehiculo": _texto(vehiculo.get("tipoVehiculo")),
            "cantidad_plazas": int(_numero(vehiculo.get("cantidadPlazas"))) if _numero(vehiculo.get("cantidadPlazas")) is not None else None,
            "total_pasajeros": int(total_p) if total_p is not None else None,
            "fecha_desde_utc": desde,
            "fecha_hasta_utc": hasta,
            "ventana_positiva": int(bool(desde and hasta and hasta > desde)),
            "estado": _texto(doc.get("estado")),
            "eliminada": bool(doc.get("eliminada")),
            "tipo_hdr": _texto(doc.get("tipoHDR")),
            "documento_json": _json(doc),
        })
        docs_hojas_buffer.append(doc)

        if len(lote_hojas) >= 2000:
            _flush_hojas()
            conn.commit()
            log(f"  [PROGRESO HOJAS] Leídas {vistos_hojas:,} hojas de ruta...")

    _flush_hojas()
    conn.commit()
    log(f"✔ Hojas de Ruta finalizadas. Total Hojas: {contadores['hojas']:,}")

    # 2. Rastreo Satelital (GPS)
    log("\nIniciando importación de Rastreo Satelital (GPS)...")
    pendientes_gps = []
    for vistos, doc in enumerate(_iter_documentos(rutas["gps"]), 1):
        flota, fecha = _identificador(doc.get("flotaID")), _fecha_utc(doc.get("fecha"))
        ubicacion = doc.get("location") if isinstance(doc.get("location"), dict) else {}
        coords = ubicacion.get("coordinates") if isinstance(ubicacion.get("coordinates"), list) else []
        lon = _numero(coords[0]) if len(coords) >= 2 else None
        lat = _numero(coords[1]) if len(coords) >= 2 else None
        velocidad = _numero(doc.get("velocidad"))
        ok = bool(flota and fecha and lon is not None and lat is not None and -180 <= lon <= 180 and -90 <= lat <= 90)

        pendientes_gps.append({
            "flota_id": flota,
            "fecha_utc": fecha,
            "longitud": lon,
            "latitud": lat,
            "velocidad": velocidad,
            "evento": _texto(doc.get("evento")),
            "campos_minimos_ok": int(ok),
        })
        contadores["gps"] += 1

        if len(pendientes_gps) >= lote:
            log(f" ─► [COPY GPS] Insertando lote de {len(pendientes_gps):,} registros (Total leídos: {vistos:,})...")
            copy_bulk_dinamico(cursor, "gps", pendientes_gps)
            conn.commit()
            pendientes_gps.clear()

    if pendientes_gps:
        log(f" ─► [COPY GPS] Insertando último lote de {len(pendientes_gps):,} registros...")
        copy_bulk_dinamico(cursor, "gps", pendientes_gps)
        conn.commit()
    log(f"✔ GPS finalizado. Total registros: {contadores['gps']:,}")

    # 3. Observaciones de Segmentos Viales
    log("\nIniciando importación de Observaciones de Segmentos Viales...")
    pendientes_obs = []
    for vistos, doc in enumerate(_iter_documentos(rutas["observaciones"]), 1):
        flota, fecha = _identificador(doc.get("flotaID")), _fecha_utc(doc.get("fecha"))
        origen, destino = _identificador(doc.get("nodo_origen")), _identificador(doc.get("nodo_destino"))
        segundos = _numero(doc.get("tiempo_real"))
        ok = bool(flota and fecha and origen and destino and segundos is not None and segundos > 0)

        pendientes_obs.append({
            "flota_id": flota,
            "fecha_utc": fecha,
            "nodo_origen": origen,
            "nodo_destino": destino,
            "franja_horaria": _texto(doc.get("franja_horaria")),
            "tiempo_real_seg": segundos,
            "campos_minimos_ok": int(ok),
        })
        contadores["observaciones"] += 1

        if len(pendientes_obs) >= lote:
            log(f" ─► [COPY OBS] Insertando lote de {len(pendientes_obs):,} observaciones (Total leídas: {vistos:,})...")
            copy_bulk_dinamico(cursor, "observaciones", pendientes_obs)
            conn.commit()
            pendientes_obs.clear()

    if pendientes_obs:
        log(f" ─► [COPY OBS] Insertando último lote de {len(pendientes_obs):,} observaciones...")
        copy_bulk_dinamico(cursor, "observaciones", pendientes_obs)
        conn.commit()
    log(f"✔ Observaciones finalizadas. Total observaciones: {contadores['observaciones']:,}")

    # 4. Creación final de Índices
    log("\nConstruyendo índices relacionales finales...")
    cursor.execute(generar_ddl_indices(TABLAS_CONFIG))
    conn.commit()
    log("✔ Índices creados exitosamente.")

    cursor.close()
    conn.close()

    return {
        "tablas": [{"tabla": t, "filas": contadores[t]} for t in tablas],
        "mensaje": "Importación completada con éxito en PostgreSQL",
    }