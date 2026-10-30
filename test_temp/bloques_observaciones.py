"""Comparación exploratoria de bloques de observaciones y rutas planificadas."""
from contextlib import closing
from difflib import SequenceMatcher

import psycopg2
from psycopg2.extras import RealDictCursor

from driverdb import DB_URI


def separar_bloques(filas):
    """Separa rangos consecutivos del archivo; preserva visitas repetidas a un tramo."""
    bloques = []
    for fila in filas:
        if not bloques or fila["observacion_n"] != bloques[-1][-1]["observacion_n"] + 1:
            bloques.append([])
        bloques[-1].append(fila)

    unicos = []
    firmas = {}
    resumen = []
    for numero, bloque in enumerate(bloques, 1):
        firma = tuple(
            (f["nodo_origen"], f["nodo_destino"], f["tiempo_real_seg"],
             f["franja_horaria"])
            for f in bloque
        )
        repetido = firmas.get(firma)
        if repetido is None:
            firmas[firma] = numero
            unicos.append((numero, bloque))
        resumen.append({
            "bloque": numero,
            "primer_registro": bloque[0]["observacion_n"],
            "ultimo_registro": bloque[-1]["observacion_n"],
            "filas": len(bloque),
            "repeticion_exacta_de": repetido,
        })
    return unicos, resumen


def comparar_secuencias(observaciones, segmentos):
    """Alinea subcadenas ordenadas; heurística, no map matching ni prueba de viaje."""
    observados = [(f["nodo_origen"], f["nodo_destino"]) for f in observaciones]
    planeados = [(s["origen"], s["destino"]) for s in segmentos]
    comparador = SequenceMatcher(None, planeados, observados, autojunk=False)
    asociaciones = {}
    for bloque in comparador.get_matching_blocks():
        for desplazamiento in range(bloque.size):
            asociaciones[bloque.a + desplazamiento] = bloque.b + desplazamiento

    detalle = []
    for posicion, segmento in enumerate(segmentos):
        indice = asociaciones.get(posicion)
        observacion = observaciones[indice] if indice is not None else None
        detalle.append({
            **segmento,
            "posicion_bloque": indice,
            "observacion_n": observacion["observacion_n"] if observacion else None,
            "tiempo_observado_seg": observacion["tiempo_real_seg"] if observacion else None,
            "estado": "coincidencia_ordenada" if observacion else "sin_coincidencia",
        })

    coincidencias = len(asociaciones)
    cobertura_ruta = coincidencias / len(segmentos) if segmentos else 0
    cobertura_bloque = coincidencias / len(observaciones) if observaciones else 0
    completa = bool(segmentos) and coincidencias == len(segmentos)
    indices_asignados = set(asociaciones.values())
    return {
        "segmentos_ruta": len(segmentos),
        "observaciones_bloque": len(observaciones),
        "coincidencias_ordenadas": coincidencias,
        "cobertura_ruta_pct": 100 * cobertura_ruta,
        "cobertura_bloque_pct": 100 * cobertura_bloque,
        "similitud": comparador.ratio(),
        "ruta_completa_en_bloque": completa,
        "suma_parcial_coincidente_min": sum(
            observaciones[i]["tiempo_real_seg"] for i in asociaciones.values()
            if observaciones[i]["tiempo_real_seg"] is not None
        ) / 60,
        "detalle": detalle,
        "observaciones_sin_asignar": [
            fila for i, fila in enumerate(observaciones)
            if i not in indices_asignados
        ],
    }


def inspeccionar_bloque(flota_id, fecha_utc, limite_observaciones=10_000,
                        limite_recorridos=100, limite_segmentos=100_000):
    """Consulta acotada de un vehículo/fecha; no cambia datos ni genera etiquetas."""
    with closing(psycopg2.connect(DB_URI)) as con:
        con.set_session(readonly=True)
        with con.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout = '30s'")
            cur.execute("""
                SELECT observacion_n, flota_id, fecha_utc, nodo_origen,
                       nodo_destino, tiempo_real_seg, franja_horaria,
                       campos_minimos_ok
                FROM observaciones WHERE flota_id = %s AND fecha_utc = %s
                ORDER BY observacion_n LIMIT %s
            """, (flota_id, fecha_utc, limite_observaciones + 1))
            filas = [dict(f) for f in cur.fetchall()]
            if not filas:
                raise ValueError("No hay observaciones para ese vehículo y fecha exacta.")
            if len(filas) > limite_observaciones:
                raise ValueError("Se superó el límite de observaciones; no se analiza un bloque truncado.")

            cur.execute("""
                SELECT h.hoja_n, h.hoja_id, h.tipo_vehiculo,
                       r.recorrido_id, r.variante,
                       r.duracion_osrm_original, r.distancia_osrm
                FROM hojas h JOIN recorridos r USING (hoja_n)
                WHERE h.flota_id = %s AND h.ventana_positiva = 1
                  AND %s::timestamptz BETWEEN h.fecha_desde_utc AND h.fecha_hasta_utc
                ORDER BY r.recorrido_id LIMIT %s
            """, (flota_id, fecha_utc, limite_recorridos + 1))
            rutas = [dict(r) for r in cur.fetchall()]
            if len(rutas) > limite_recorridos:
                raise ValueError("Demasiados recorridos candidatos; acotá las hojas antes de continuar.")
            cur.execute("""
                SELECT recorrido_id, orden, origen, destino
                FROM segmentos WHERE recorrido_id = ANY(%s)
                ORDER BY recorrido_id, orden LIMIT %s
            """, ([r["recorrido_id"] for r in rutas], limite_segmentos + 1))
            segmentos = [dict(s) for s in cur.fetchall()]
            if len(segmentos) > limite_segmentos:
                raise ValueError("Se superó el límite de segmentos; no se comparan rutas truncadas.")

    bloques, resumen_bloques = separar_bloques(filas)
    por_ruta = {r["recorrido_id"]: [] for r in rutas}
    for segmento in segmentos:
        por_ruta[segmento["recorrido_id"]].append(segmento)

    firmas_rutas = {}
    rutas_unicas = []
    for ruta in rutas:
        tramos = por_ruta[ruta["recorrido_id"]]
        firma = (ruta["hoja_id"], ruta["tipo_vehiculo"], ruta["variante"],
                 ruta["duracion_osrm_original"], ruta["distancia_osrm"],
                 tuple((s["orden"], s["origen"], s["destino"]) for s in tramos))
        if firma not in firmas_rutas:
            firmas_rutas[firma] = ruta["recorrido_id"]
            rutas_unicas.append(ruta)

    resumen = []
    detalles = {}
    resumen_observaciones = []
    for numero, bloque in bloques:
        resumen_observaciones.append({
            "bloque": numero,
            "filas": len(bloque),
            "nodo_inicial_observado": bloque[0]["nodo_origen"],
            "nodo_final_observado": bloque[-1]["nodo_destino"],
            "enlaces_continuos": sum(
                a["nodo_destino"] == b["nodo_origen"]
                for a, b in zip(bloque, bloque[1:])
            ),
            "transiciones": max(0, len(bloque) - 1),
            "filas_invalidas": sum(not f["campos_minimos_ok"] for f in bloque),
            "suma_bloque_min": sum(f["tiempo_real_seg"] or 0 for f in bloque) / 60,
            "estado": "no_validado_como_viaje",
        })
        for ruta in rutas_unicas:
            comparacion = comparar_secuencias(bloque, por_ruta[ruta["recorrido_id"]])
            detalles[(numero, ruta["recorrido_id"])] = comparacion
            resumen.append({
                "bloque": numero,
                **ruta,
                **{k: v for k, v in comparacion.items()
                   if k not in ("detalle", "observaciones_sin_asignar")},
                "estado": "requiere_revision" if comparacion["ruta_completa_en_bloque"]
                          else "recorrido_incompleto_o_distinto",
            })
    resumen.sort(key=lambda r: r["similitud"], reverse=True)
    mejor = resumen[0] if resumen else None
    detalle_mejor = detalles[(mejor["bloque"], mejor["recorrido_id"])] if mejor else None
    return {
        "bloques": resumen_bloques,
        "resumen_observaciones": resumen_observaciones,
        "comparaciones": resumen,
        "mejor": mejor,
        "detalle_mejor": detalle_mejor,
        "rutas_repetidas_omitidas": len(rutas) - len(rutas_unicas),
        "fila_entrenamiento": None,
    }


def buscar_dataset_exploratorio(limite_bloques=100, cobertura_minima=70,
                               registros_busqueda=200_000):
    """Muestra inicial por orden de archivo; etiquetas proxy, no viajes validados."""
    if not 0 < cobertura_minima <= 100 or limite_bloques < 1 or registros_busqueda < 1:
        raise ValueError("Revisá cobertura_minima y los límites de búsqueda.")
    with closing(psycopg2.connect(DB_URI)) as con:
        con.set_session(readonly=True)
        with con.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout = '30s'")
            cur.execute("""
                WITH muestra AS (
                    SELECT observacion_n, flota_id, fecha_utc
                    FROM observaciones ORDER BY observacion_n LIMIT %s
                ), grupos AS (
                    SELECT flota_id, fecha_utc, MIN(observacion_n) AS primero
                    FROM muestra WHERE flota_id IS NOT NULL AND fecha_utc IS NOT NULL
                    GROUP BY flota_id, fecha_utc HAVING COUNT(*) >= 50
                ), compatibles AS (
                    SELECT g.*, ROW_NUMBER() OVER (
                        PARTITION BY g.flota_id ORDER BY g.primero
                    ) AS ronda
                    FROM grupos g WHERE EXISTS (
                        SELECT 1 FROM hojas h WHERE h.flota_id = g.flota_id
                          AND h.ventana_positiva = 1
                          AND g.fecha_utc BETWEEN h.fecha_desde_utc AND h.fecha_hasta_utc
                    )
                )
                SELECT flota_id, fecha_utc FROM compatibles
                ORDER BY ronda, primero LIMIT %s
            """, (registros_busqueda, limite_bloques))
            semillas = [dict(f) for f in cur.fetchall()]

    muestras = []
    diagnosticos = []
    for semilla in semillas:
        try:
            resultado = inspeccionar_bloque(semilla["flota_id"], semilla["fecha_utc"])
        except (ValueError, psycopg2.errors.QueryCanceled) as exc:
            diagnosticos.append({**semilla, "estado": "omitido", "motivo": str(exc)})
            continue
        aceptadas = 0
        for bloque in resultado["resumen_observaciones"]:
            opciones = [
                c for c in resultado["comparaciones"]
                if c["bloque"] == bloque["bloque"]
                and c["cobertura_ruta_pct"] >= cobertura_minima
                and c["cobertura_bloque_pct"] >= cobertura_minima
            ]
            if not opciones or bloque["filas_invalidas"] or bloque["suma_bloque_min"] <= 0:
                continue
            mejor = opciones[0]
            fecha = semilla["fecha_utc"]
            muestras.append({
                "muestra_id": f"{semilla['flota_id']}|{fecha.isoformat()}|{bloque['bloque']}",
                **semilla,
                "bloque": bloque["bloque"],
                "hoja_id": mejor["hoja_id"],
                "recorrido_id": mejor["recorrido_id"],
                "tipo_vehiculo": mejor["tipo_vehiculo"] or "desconocido",
                "variante": mejor["variante"],
                "hora_bloque_utc": fecha.hour,
                "dia_semana": fecha.weekday(),
                "duracion_osrm_original": mejor["duracion_osrm_original"],
                "distancia_osrm": mejor["distancia_osrm"],
                "cobertura_ruta_pct": mejor["cobertura_ruta_pct"],
                "cobertura_bloque_pct": mejor["cobertura_bloque_pct"],
                "duracion_bloque_min": bloque["suma_bloque_min"],
                "etiqueta": "proxy_suma_observaciones_no_viaje_validado",
            })
            aceptadas += 1
        diagnosticos.append({
            **semilla,
            "estado": "aceptado" if aceptadas else "sin_cobertura_suficiente",
            "muestras": aceptadas,
        })
    return muestras, diagnosticos
