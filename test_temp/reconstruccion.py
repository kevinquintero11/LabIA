"""Reconstrucción exploratoria de pasadas GPS; no valida etiquetas de viaje."""
from contextlib import closing
import json
import math

import numpy as np
import psycopg2
from psycopg2.extras import RealDictCursor

from driverdb import DB_URI


def proyectar_gps(puntos, mediciones):
    """Aproxima progreso por vértice más cercano; puntos del JSON en [lat, lon]."""
    ruta = np.asarray(puntos, dtype=float)
    if ruta.ndim != 2 or ruta.shape[1] != 2 or len(ruta) < 2:
        raise ValueError("La geometría debe contener al menos dos puntos [lat, lon].")
    if not np.isfinite(ruta).all() or (np.abs(ruta[:, 0]) > 90).any() or (
        np.abs(ruta[:, 1]) > 180
    ).any():
        raise ValueError("Coordenadas inválidas en la geometría.")

    # Aproximación métrica local para inspección; no reemplaza map matching.
    escala = np.array([111_195.0, 111_195.0 * math.cos(math.radians(ruta[:, 0].mean()))])
    xy = (ruta - ruta[0]) * escala
    acumulada = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
    if acumulada[-1] <= 0:
        raise ValueError("La geometría no tiene longitud positiva.")

    salida = []
    for fila in mediciones:
        posicion = (np.array([fila["latitud"], fila["longitud"]]) - ruta[0]) * escala
        distancias = np.linalg.norm(xy - posicion, axis=1)
        indice = int(np.argmin(distancias))
        salida.append({
            **fila,
            "progreso": float(acumulada[indice] / acumulada[-1]),
            "distancia_ruta_m": float(distancias[indice]),
            "distancia_inicio_m": float(np.linalg.norm(posicion - xy[0])),
            "distancia_final_m": float(np.linalg.norm(posicion - xy[-1])),
        })
    return salida


def detectar_pasadas(traza, radio_extremos_m=500, tolerancia_ruta_m=500,
                     max_hueco_seg=900, min_puntos=5):
    """Devuelve candidatos completos y diagnósticos sin unir huecos grandes."""
    inicio = None
    ultimo = None
    candidatos = []
    diagnostico = {"inicios_detectados": 0, "cortes_por_hueco": 0,
                   "cortes_por_retroceso": 0, "llegadas_descartadas": 0,
                   "pasadas_descartadas": []}
    for indice, punto in enumerate(traza):
        if inicio is not None and ultimo is not None:
            hueco = (punto["fecha_utc"] - traza[ultimo]["fecha_utc"]).total_seconds()
            if hueco > max_hueco_seg:
                diagnostico["cortes_por_hueco"] += 1
            # No unimos días ni esperas de varias horas. Los huecos menores
            # se conservan para explicar por qué se descarta una llegada.
            if hueco > 4 * 3600 or (
                punto["fecha_utc"] - traza[inicio]["fecha_utc"]
            ).total_seconds() > 4 * 3600:
                inicio = None
            elif punto["progreso"] < traza[ultimo]["progreso"] - 0.15:
                diagnostico["cortes_por_retroceso"] += 1
                inicio = None

        if punto["distancia_inicio_m"] <= radio_extremos_m and punto["progreso"] <= 0.1:
            if inicio is None:
                diagnostico["inicios_detectados"] += 1
            # Última muestra cerca de la salida, para no sumar estacionamiento previo.
            inicio = indice

        if inicio is not None and punto["distancia_final_m"] <= radio_extremos_m and punto["progreso"] >= 0.9:
            tramo = traza[inicio:indice + 1]
            duracion = (punto["fecha_utc"] - tramo[0]["fecha_utc"]).total_seconds()
            cerca = sum(p["distancia_ruta_m"] <= tolerancia_ruta_m for p in tramo) / len(tramo)
            max_hueco = max((b["fecha_utc"] - a["fecha_utc"]).total_seconds()
                            for a, b in zip(tramo, tramo[1:])) if len(tramo) > 1 else 0
            resumen = {
                    "salida_utc": tramo[0]["fecha_utc"],
                    "llegada_utc": punto["fecha_utc"],
                    "duracion_gps_min": duracion / 60,
                    "puntos_gps": len(tramo),
                    "porcentaje_cerca_ruta": 100 * cerca,
                    "max_hueco_seg": max_hueco,
                    "indice_inicio": inicio,
                    "indice_final": indice,
                }
            if len(tramo) >= min_puntos and duracion > 0 and cerca >= 0.8 and max_hueco <= max_hueco_seg:
                candidatos.append(resumen)
            else:
                diagnostico["llegadas_descartadas"] += 1
                motivos = []
                if len(tramo) < min_puntos:
                    motivos.append(f"menos de {min_puntos} GPS")
                if max_hueco > max_hueco_seg:
                    motivos.append(f"hueco mayor de {max_hueco_seg} segundos")
                if cerca < 0.8:
                    motivos.append("menos del 80 % cerca de la ruta")
                if duracion <= 0:
                    motivos.append("duración no positiva")
                resumen["motivo_descarte"] = "; ".join(motivos)
                diagnostico["pasadas_descartadas"].append(resumen)
            inicio = None
        ultimo = indice
    diagnostico["inicio_sin_llegada"] = inicio is not None
    return candidatos, diagnostico


def inspeccionar_recorrido(recorrido_id, limite_gps=10_000,
                           radio_extremos_m=500, max_hueco_seg=900):
    """Lee una hoja y su GPS; informa observaciones para la primera pasada candidata."""
    with closing(psycopg2.connect(DB_URI)) as con:
        con.set_session(readonly=True)
        with con.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout = '30s'")
            cur.execute("""
                SELECT h.hoja_n, h.hoja_id, h.flota_id, h.tipo_vehiculo,
                       h.fecha_desde_utc, h.fecha_hasta_utc, h.documento_json,
                       r.recorrido_id, r.variante, r.ruta_json,
                       r.duracion_osrm_original, r.distancia_osrm
                FROM hojas h JOIN recorridos r USING (hoja_n)
                WHERE r.recorrido_id = %s AND h.ventana_positiva = 1
            """, (recorrido_id,))
            registro = cur.fetchone()
            if registro is None:
                raise ValueError("No existe ese recorrido con una ventana válida.")
            datos = dict(registro)
            documento = datos.pop("documento_json")
            if isinstance(documento, str):
                documento = json.loads(documento)
            camino = datos.pop("ruta_json")
            if isinstance(camino, str):
                camino = json.loads(camino)
            geometria = documento["geometriaOSRM"]
            for clave in camino:
                geometria = geometria[clave]

            cur.execute("""
                SELECT DISTINCT fecha_utc, latitud, longitud
                FROM gps
                WHERE flota_id = %s AND fecha_utc BETWEEN %s AND %s
                  AND campos_minimos_ok = 1
                ORDER BY fecha_utc, latitud, longitud
                LIMIT %s
            """, (datos["flota_id"], datos["fecha_desde_utc"],
                  datos["fecha_hasta_utc"], limite_gps + 1))
            gps = [dict(fila) for fila in cur.fetchall()]
            if len(gps) > limite_gps:
                raise ValueError("Se superó el límite GPS. Aumentalo explícitamente para no analizar una traza truncada.")
            if len({p["fecha_utc"] for p in gps}) != len(gps):
                raise ValueError("Hay posiciones diferentes con la misma fecha GPS: hay que resolver esa ambigüedad.")
            traza = proyectar_gps(geometria.get("puntos"), gps)
            candidatos, diagnostico = detectar_pasadas(
                traza, radio_extremos_m=radio_extremos_m,
                max_hueco_seg=max_hueco_seg,
            )

            observaciones = []
            if candidatos:
                primera = candidatos[0]
                cur.execute("""
                    WITH unicas AS (
                        SELECT DISTINCT fecha_utc, nodo_origen, nodo_destino,
                                        tiempo_real_seg, franja_horaria
                        FROM observaciones
                        WHERE flota_id = %s AND fecha_utc BETWEEN %s AND %s
                          AND campos_minimos_ok = 1
                    )
                    SELECT s.orden, s.origen, s.destino,
                           COUNT(o.fecha_utc) AS coincidencias,
                           MIN(o.fecha_utc) AS primera_fecha,
                           MAX(o.fecha_utc) AS ultima_fecha
                    FROM segmentos s LEFT JOIN unicas o
                      ON o.nodo_origen = s.origen AND o.nodo_destino = s.destino
                    WHERE s.recorrido_id = %s
                    GROUP BY s.orden, s.origen, s.destino ORDER BY s.orden
                """, (datos["flota_id"], primera["salida_utc"],
                      primera["llegada_utc"], recorrido_id))
                observaciones = [dict(fila) for fila in cur.fetchall()]

    fila_candidata = None
    if candidatos:
        primera = candidatos[0]
        fila_candidata = {
            **datos,
            "salida_utc": primera["salida_utc"],
            "llegada_utc": primera["llegada_utc"],
            "hora_utc": primera["salida_utc"].hour,
            "dia_semana": primera["salida_utc"].weekday(),
            "duracion_gps_min": primera["duracion_gps_min"],
            "estado": "pendiente_revision_manual",
        }
    return {"recorrido": datos, "traza": traza, "candidatos": candidatos,
            "diagnostico": diagnostico, "observaciones": observaciones,
            "fila_candidata": fila_candidata}
