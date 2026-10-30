# /// script
# dependencies = ["ipywidgets"]
# ///

import marimo

__generated_with = "0.25.0"
app = marimo.App()


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _():
    # packages added via marimo's package management: ipywidgets==8.1.9 !pip install ipywidgets==8.1.9
    return


@app.cell
def _():
    import numpy as np
    import pandas as pd

    from numpy import array

    # Para el dataset
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from ipywidgets import interact, FloatSlider, VBox, HBox, Button, Output, IntSlider
    import time
    from IPython.display import display, clear_output

    return pd, plt


@app.cell
def _():
    from pathlib import Path
    import json

    import seaborn as sns

    return Path, sns


@app.cell
def _():
    import psycopg2
    from dataset_up import importar_dataset_postgres

    return importar_dataset_postgres, psycopg2


@app.cell
def _(Path, importar_dataset_postgres, mo, psycopg2):
    # 1. Rutas de archivos de origen
    PROYECTO = Path.cwd()
    ORIGINALES = PROYECTO / "data" / "originales"

    ARCHIVOS_ETA = {
        "hojas": ORIGINALES / "hojaDeRuta.json",
        "gps": ORIGINALES / "rastreoSatelital.json",
        "observaciones": ORIGINALES / "observacionesSegmentosViales.json",
    }

    # 2. Credenciales de la base de datos PostgreSQL
    POSTGRES_URI = "postgresql://admin:pase@localhost:5432/db_dataset"

    # 3. Carga directa al evaluar la celda
    resumen_importacion_pg = importar_dataset_postgres(
        archivos=ARCHIVOS_ETA,
        db_uri=POSTGRES_URI,
        lote=5_000,
    )

    # 4. Función de consulta de apoyo para celdas posteriores
    def consultar_base_pg(sql: str, parametros=(), max_filas: int = 1000) -> list[dict]:
        with psycopg2.connect(POSTGRES_URI) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, parametros)
                columnas = [desc[0] for desc in cursor.description]
                filas = cursor.fetchmany(max_filas)
                return [dict(zip(columnas, fila)) for fila in filas]

    # Muestra el resultado de la carga automáticamente en la interfaz
    mo.ui.table(
        resumen_importacion_pg["tablas"],
        selection=None,
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Análisis de DataSet

    Exploración de una muestra de observaciones consultadas en PostgreSQL.
    """)
    return


@app.cell
def _(mo):
    from consultas import consultar

    filas_dataset = consultar(
        "observaciones",
        filtros={"campos_minimos_ok": 1},
        columnas=(
            "flota_id",
            "fecha_utc",
            "nodo_origen",
            "nodo_destino",
            "franja_horaria",
            "tiempo_real_seg",
        ),
        ordenar_por="observacion_n",
        limite=10_000,
    )
    mo.stop(
        not filas_dataset,
        mo.md("No hay observaciones válidas. Esperá a que termine la importación."),
    )

    # Conserva los nombres del JSON que utilizan los gráficos originales.
    datasets = {
        "observaciones_viales": [
            {
                "flotaID": fila["flota_id"],
                "fecha": {"$date": fila["fecha_utc"].isoformat()},
                "nodo_origen": fila["nodo_origen"],
                "nodo_destino": fila["nodo_destino"],
                "franja_horaria": fila["franja_horaria"],
                "tiempo_real": fila["tiempo_real_seg"],
            }
            for fila in filas_dataset
        ]
    }

    mo.md(f"Muestra cargada: **{len(filas_dataset):,} observaciones**.")
    return (datasets,)


@app.cell
def _(datasets, pd):
    data = pd.DataFrame(datasets)

    data.head()
    data.describe()
    data.info()
    return (data,)


@app.cell
def _(data):
    print(data.columns)
    return


@app.cell
def _(data, pd, sns):
    sns.set_theme(style="whitegrid")

    # 1. Desempaquetar los diccionarios anidados
    df = pd.json_normalize(data['observaciones_viales'])

    # 2. Convertir la fecha a datetime
    df['fecha_dt'] = pd.to_datetime(df['fecha.$date'])

    # 3. Crear columnas auxiliares
    df['dia_fecha'] = df['fecha_dt'].dt.date         # Ejemplo: 2026-06-05
    df['hora'] = df['fecha_dt'].dt.hour              # Ejemplo: 22
    df['nombre_dia'] = df['fecha_dt'].dt.day_name()  # Ejemplo: Friday
    return (df,)


@app.cell
def _(df, plt):
    # Opción: Cantidad de observaciones por día
    obs_por_dia = df.groupby('dia_fecha').size()

    plt.figure(figsize=(12, 5))
    obs_por_dia.plot(kind='line', marker='o', linewidth=2, color='#2b5c8f')
    plt.title('Cantidad de Observaciones Viales por Día', fontsize=14, fontweight='bold')
    plt.xlabel('Fecha', fontsize=12)
    plt.ylabel('Cantidad de Registros', fontsize=12)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()
    return


@app.cell
def _(df, plt, sns):
    # Ordenar días de la semana
    dias_orden = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

    # Pivote para el Mapa de Calor (conteo de registros por día y hora)
    pivot_tabla = df.pivot_table(
        index='nombre_dia', 
        columns='hora', 
        values='tiempo_real', 
        aggfunc='count'
    ).reindex(dias_orden)

    plt.figure(figsize=(14, 6))
    sns.heatmap(pivot_tabla, cmap='YlGnBu', annot=True, fmt='.0f', cbar_kws={'label': 'Cantidad de Registros'})
    plt.title('Distribución de Observaciones por Día y Hora', fontsize=14, fontweight='bold')
    plt.xlabel('Hora del Día (0-23)', fontsize=12)
    plt.ylabel('Día de la Semana', fontsize=12)
    plt.tight_layout()
    plt.show()
    return


@app.cell
def _(df, sns):
    sns.set_theme(style='whitegrid')
    df_1 = df.rename(columns={"dia_fecha": "dia"}).copy()
    return (df_1,)


@app.cell
def _(df_1, plt):
    plt.figure(figsize=(10, 4))
    df_1.groupby('dia').size().plot(kind='bar', color='#2b5c8f', edgecolor='black')
    plt.title('Cantidad de Observaciones por Día', fontsize=13, fontweight='bold')
    plt.xlabel('Fecha', fontsize=11)
    plt.ylabel('Cantidad de Registros', fontsize=11)
    plt.xticks(rotation=0)
    plt.tight_layout()
    plt.show()
    return


@app.cell
def _(df_1, plt, sns):
    pivot_dia_hora = df_1.pivot_table(index='dia', columns='hora', values='tiempo_real', aggfunc='count', fill_value=0)
    plt.figure(figsize=(14, 4))
    sns.heatmap(pivot_dia_hora, cmap='YlGnBu', annot=True, fmt='d', cbar_kws={'label': 'Cantidad de Registros'})
    plt.title('Distribución de Observaciones por Día y Hora', fontsize=13, fontweight='bold')
    plt.xlabel('Hora del Día (0-23)', fontsize=11)
    plt.ylabel('Día', fontsize=11)
    plt.tight_layout()
    plt.show()
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Asociar un recorrido con sus tiempos observados

    Primero analizamos **una hoja y uno de sus recorridos**, no toda la flota.
    La consulta une `hojas → recorridos → segmentos → observaciones`:

    1. La hoja identifica el vehículo, su tipo y la ventana de fechas.
    2. Los segmentos indican el camino en orden. El destino del último segmento
       es el nodo final del recorrido.
    3. Buscamos observaciones del **mismo vehículo**, dentro de las fechas de la
       hoja y con el **mismo origen y destino** que cada segmento.

    Por ejemplo, si A→B tarda 20 segundos, B→C tarda 30 y C→D tarda 15,
    la suma de los tiempos de los segmentos es 65 segundos hasta D.

    En la celda se puede indicar `RECORRIDO_A_REVISAR`. Si lo dejás en
    `None`, se elige el primer recorrido que tenga alguna observación compatible.
    `TIPO_A_REVISAR` permite filtrar, por ejemplo, por `"Pesada"`.

    La tabla muestra también segmentos **sin observaciones** y segmentos con
    **varias observaciones**. No elegimos una medición arbitrariamente: la suma
    completa solo se calcula si cada segmento tiene exactamente una coincidencia.
    """)
    return


@app.cell
def _(mo):
    import driverdb

    RECORRIDO_A_REVISAR = None
    TIPO_A_REVISAR = None

    CONSULTA_SEGMENTOS_RECORRIDO = """
    WITH elegido AS (
        SELECT h.hoja_n, h.hoja_id, h.flota_id, h.tipo_vehiculo,
               h.fecha_desde_utc, h.fecha_hasta_utc,
               r.recorrido_id, r.variante
        FROM hojas AS h
        JOIN recorridos AS r ON r.hoja_n = h.hoja_n
        WHERE h.ventana_positiva = 1
          AND (%s::bigint IS NULL OR r.recorrido_id = %s)
          AND (%s::text IS NULL OR h.tipo_vehiculo = %s)
          AND EXISTS (
              SELECT 1 FROM segmentos AS s
              WHERE s.recorrido_id = r.recorrido_id
          )
          AND (
              %s::bigint IS NOT NULL OR EXISTS (
                  SELECT 1
                  FROM segmentos AS s
                  JOIN observaciones AS o
                    ON o.nodo_origen = s.origen
                   AND o.nodo_destino = s.destino
                  WHERE s.recorrido_id = r.recorrido_id
                    AND o.flota_id = h.flota_id
                    AND o.fecha_utc BETWEEN h.fecha_desde_utc
                                        AND h.fecha_hasta_utc
                    AND o.campos_minimos_ok = 1
              )
          )
        ORDER BY h.hoja_n, r.recorrido_id
        LIMIT 1
    )
    SELECT e.hoja_n, e.hoja_id, e.flota_id, e.tipo_vehiculo,
           e.recorrido_id, e.variante,
           s.orden, s.origen, s.destino,
           COUNT(o.observacion_n) AS coincidencias,
           MIN(o.fecha_utc) AS primera_fecha_observada,
           MAX(o.fecha_utc) AS ultima_fecha_observada,
           CASE WHEN COUNT(o.observacion_n) = 1
                THEN MIN(o.tiempo_real_seg) END AS tiempo_unico_seg
    FROM elegido AS e
    JOIN segmentos AS s ON s.recorrido_id = e.recorrido_id
    LEFT JOIN observaciones AS o
      ON o.flota_id = e.flota_id
     AND o.nodo_origen = s.origen
     AND o.nodo_destino = s.destino
     AND o.fecha_utc BETWEEN e.fecha_desde_utc AND e.fecha_hasta_utc
     AND o.campos_minimos_ok = 1
    GROUP BY e.hoja_n, e.hoja_id, e.flota_id, e.tipo_vehiculo,
             e.recorrido_id, e.variante, s.orden, s.origen, s.destino
    ORDER BY s.orden
    """

    try:
        segmentos_revisados = driverdb.realizarSelect(
            CONSULTA_SEGMENTOS_RECORRIDO,
            (
                RECORRIDO_A_REVISAR,
                RECORRIDO_A_REVISAR,
                TIPO_A_REVISAR,
                TIPO_A_REVISAR,
                RECORRIDO_A_REVISAR,
            ),
        )
    finally:
        driverdb.desconectarse()

    mo.stop(
        not segmentos_revisados,
        mo.md("No se encontró un recorrido compatible con los filtros."),
    )

    _total = len(segmentos_revisados)
    _con_datos = sum(fila["coincidencias"] > 0 for fila in segmentos_revisados)
    _ambiguos = sum(fila["coincidencias"] > 1 for fila in segmentos_revisados)
    _completo = all(fila["coincidencias"] == 1 for fila in segmentos_revisados)
    resumen_recorrido_revisado = {
        "recorrido_id": segmentos_revisados[0]["recorrido_id"],
        "tipo_vehiculo": segmentos_revisados[0]["tipo_vehiculo"],
        "nodo_final": segmentos_revisados[-1]["destino"],
        "segmentos": _total,
        "segmentos_con_observaciones": _con_datos,
        "segmentos_ambiguos": _ambiguos,
        "cobertura_porcentaje": round(100 * _con_datos / _total, 2),
        "suma_candidata_seg": (
            sum(fila["tiempo_unico_seg"] for fila in segmentos_revisados)
            if _completo else None
        ),
    }

    mo.vstack([
        mo.ui.table([resumen_recorrido_revisado], selection=None),
        mo.ui.table(segmentos_revisados, selection=None),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Reconstruir una pasada con GPS

    Para una hoja concreta buscamos una secuencia GPS desde el inicio hasta el
    final de su geometría. Se quitan duplicados exactos de fecha y coordenadas.
    El progreso se aproxima usando el vértice más cercano de la ruta; **no es
    un map matching definitivo**.

    Una pasada candidata necesita al menos 5 GPS, extremos a menos de 500 m,
    al menos 80 % de las posiciones cerca del camino y ningún hueco mayor de
    15 minutos. Retrocesos importantes cortan la secuencia. No se unen ventanas
    de más de 4 horas. Estos umbrales son hipótesis configurables, no garantías.

    **Duración candidata = llegada GPS − salida GPS.** Se usa la última muestra
    cerca del inicio y la primera cerca del final, por lo que existe incertidumbre
    entre muestras y no se mide exactamente el cruce de los nodos extremos.

    El ejemplo usa el recorrido 487, de vuelta, del vehículo que aparece en las
    primeras observaciones. Se pueden cambiar los parámetros en la celda siguiente.
    El botón solo lee PostgreSQL: no vuelve a importar datos.

    Mostramos también intentos descartados para entender faltantes de GPS.
    Si aparece una pasada aceptable, buscamos sus observaciones por vehículo,
    intervalo y nodos, sin sumar duplicados ni tratarlas como una secuencia temporal.

    La fila resultante queda **pendiente de revisión manual**: todavía hay que
    resolver hojas superpuestas y comprobar el recorrido. No dividimos 80/20 con
    un único viaje; eso requiere reunir varias pasadas validadas y separarlas
    completas por fecha. El objetivo sería `duracion_gps_min`; las fechas de
    llegada y los tiempos observados no se deben utilizar como entradas.
    """)
    return


@app.cell
def _(mo):
    RECORRIDO_PASADA = 487
    RADIO_EXTREMOS_M = 500
    MAX_HUECO_GPS_SEG = 900
    boton_reconstruir = mo.ui.run_button(label="Inspeccionar una pasada GPS")
    boton_reconstruir
    return (
        MAX_HUECO_GPS_SEG,
        RADIO_EXTREMOS_M,
        RECORRIDO_PASADA,
        boton_reconstruir,
    )


@app.cell
def _(
    MAX_HUECO_GPS_SEG,
    RADIO_EXTREMOS_M,
    RECORRIDO_PASADA,
    boton_reconstruir,
    mo,
):
    from reconstruccion import inspeccionar_recorrido

    mo.stop(
        not boton_reconstruir.value,
        mo.md("Presioná el botón para analizar el GPS sin repetir la importación."),
    )
    resultado_pasada = inspeccionar_recorrido(
        RECORRIDO_PASADA,
        radio_extremos_m=RADIO_EXTREMOS_M,
        max_hueco_seg=MAX_HUECO_GPS_SEG,
    )
    _descartadas = resultado_pasada["diagnostico"]["pasadas_descartadas"]
    _diagnostico = {
        k: v for k, v in resultado_pasada["diagnostico"].items()
        if k != "pasadas_descartadas"
    }
    _salidas = [
        mo.ui.table([resultado_pasada["recorrido"]], selection=None),
        mo.md(f"GPS únicos consultados: **{len(resultado_pasada['traza'])}**."),
        mo.ui.table([_diagnostico], selection=None),
    ]
    if resultado_pasada["candidatos"]:
        _salidas.extend([
            mo.md("### Pasadas candidatas (requieren revisión)"),
            mo.ui.table(resultado_pasada["candidatos"], selection=None),
            mo.md("### Primera fila candidata para un futuro dataset"),
            mo.ui.table([resultado_pasada["fila_candidata"]], selection=None),
            mo.md("### Observaciones compatibles por segmento de esa pasada"),
            mo.ui.table(resultado_pasada["observaciones"], selection=None),
        ])
    else:
        _salidas.append(mo.md(
            "**No se obtuvo una pasada con cobertura GPS suficiente.** "
            "No se genera una etiqueta de entrenamiento con este resultado."
        ))
    if _descartadas:
        _salidas.extend([
            mo.md("### Intentos descartados: revisar puntos, huecos y cercanía"),
            mo.ui.table(_descartadas, selection=None),
        ])
    _intentos = resultado_pasada["candidatos"] or _descartadas
    if _intentos:
        _primero = _intentos[0]
        _traza = resultado_pasada["traza"][
            _primero["indice_inicio"]:_primero["indice_final"] + 1
        ]
        _salidas.extend([
            mo.md("### GPS del primer intento (progreso entre 0 y 1)"),
            mo.ui.table(_traza, selection=None),
        ])
    mo.vstack(_salidas)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Analizar un bloque de observaciones

    La unidad es **un vehículo y una fecha exacta de observaciones**, no
    una ventana de llegada elegida a partir del GPS. Conservamos el orden de
    `observacion_n`, que refleja el orden de importación, no una cronología
    demostrada de cruces: todos estos registros comparten la misma fecha.

    1. Separamos rangos consecutivos de registros y detectamos copias de bloques
       enteros. No quitamos repeticiones de tramos dentro de un bloque: el vehículo
       puede atravesar un mismo tramo más de una vez.
    2. Buscamos las hojas del vehículo cuya ventana incluye esa fecha y sus recorridos.
       Las copias idénticas de una misma hoja/variante se comparan una sola vez.
    3. Alineamos pares origen→destino en orden, con una heurística de subcadenas.
       Cada posición observada se asigna como máximo una vez. No es un algoritmo
       definitivo de reconstrucción ni una prueba de que sea el viaje planificado.
    4. Mostramos cobertura de la ruta y del bloque, segmentos faltantes y
       observaciones no asignadas. La similitud sirve para ordenar candidatos;
       **no es exactitud del modelo ni probabilidad de asociación**.

    `suma_bloque_min` suma todos los tiempos del bloque original.
    `suma_parcial_coincidente_min` suma solo las observaciones alineadas.
    **Ninguna es automáticamente la duración hasta el destino.** Si faltan tramos,
    no se rellenan con cero, promedios ni OSRM para inventar una etiqueta real.

    Incluso si aparece una ruta completa, hay que validar el significado de la
    fecha, las repeticiones y la pasada GPS antes de incorporarla a entrenamiento.
    No se modifica la base ni se ejecuta una nueva importación.
    """)
    return


@app.cell
def _(mo):
    VEHICULO_BLOQUE = "VEH_e3d5866f0c"
    FECHA_BLOQUE_UTC = "2026-06-10 22:51:13+00:00"
    boton_analizar_bloque = mo.ui.run_button(label="Comparar bloque con recorridos")
    boton_analizar_bloque
    return FECHA_BLOQUE_UTC, VEHICULO_BLOQUE, boton_analizar_bloque


@app.cell
def _(FECHA_BLOQUE_UTC, VEHICULO_BLOQUE, boton_analizar_bloque, mo):
    from bloques_observaciones import inspeccionar_bloque

    mo.stop(
        not boton_analizar_bloque.value,
        mo.md("Presioná el botón para comparar un bloque de observaciones."),
    )
    resultado_bloque = inspeccionar_bloque(VEHICULO_BLOQUE, FECHA_BLOQUE_UTC)
    _paneles = [
        mo.md("### Bloques detectados (copias omitidas solo en el análisis)"),
        mo.ui.table(resultado_bloque["bloques"], selection=None),
        mo.md("### Resumen de los bloques no repetidos"),
        mo.ui.table(resultado_bloque["resumen_observaciones"], selection=None),
        mo.md(
            f"Recorridos repetidos omitidos: **{resultado_bloque['rutas_repetidas_omitidas']}**."
        ),
        mo.md("### Comparación con los recorridos candidatos"),
        mo.ui.table(resultado_bloque["comparaciones"], selection=None),
    ]
    if resultado_bloque["mejor"]:
        _detalle = resultado_bloque["detalle_mejor"]
        _paneles.extend([
            mo.md("### Mejor coincidencia: segmentos en orden"),
            mo.ui.table(_detalle["detalle"], selection=None),
            mo.md("### Observaciones del bloque no asignadas a esa ruta"),
            mo.ui.table(_detalle["observaciones_sin_asignar"], selection=None),
        ])
        if not resultado_bloque["mejor"]["ruta_completa_en_bloque"]:
            _paneles.append(mo.md(
                "**La mejor ruta no está completa en el bloque.** "
                "Este resultado no genera una fila de entrenamiento de viaje completo."
            ))
        else:
            _paneles.append(mo.md(
                "**Se encontró una cobertura ordenada completa, pendiente de revisión.** "
                "Todavía no se asigna una etiqueta de viaje ni se realiza la división 80/20."
            ))
    else:
        _paneles.append(mo.md("No hay recorridos candidatos para esa fecha y vehículo."))
    mo.vstack(_paneles)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Búsqueda rápida y conjunto exploratorio 80/20

    Buscamos hasta 100 grupos vehículo/fecha
    en los primeros 200.000 registros del archivo importado, alternando vehículos
    y omitiendo fechas sin una hoja compatible. Cada grupo se consulta
    completo, evitando truncar sus observaciones. No es una muestra
    representativa de toda la flota.

    Elegimos el recorrido más parecido que cubra al menos el **70 % de la ruta
    y del bloque**. Omitimos copias exactas de bloques y registros inválidos.
    No exigimos reconstrucción GPS manual para este experimento.

    ### ¿Qué significa el 70 % de la ruta y del bloque?

    Comparamos dos listas: los segmentos de la **ruta planificada** y las
    observaciones del **bloque**. Una coincidencia requiere el mismo nodo de
    origen y destino, respetando el orden de las listas.

    - **Cobertura de la ruta:** coincidencias ordenadas / segmentos de la ruta × 100.
      Indica qué proporción del camino planificado está representada en el bloque.
    - **Cobertura del bloque:** coincidencias ordenadas / observaciones del bloque × 100.
      Indica qué proporción de las observaciones se pudo asociar a esa ruta.

    **Ambas coberturas deben ser al menos 70 %.** Por ejemplo, si una ruta tiene
    10 segmentos, el bloque tiene 8 observaciones y coinciden 7 en orden:

    | Cobertura | Cálculo | Resultado |
    |---|---|---|
    | De la ruta | 7 / 10 × 100 | 70 % |
    | Del bloque | 7 / 8 × 100 | 87,5 % |

    Esa asociación se acepta para el experimento. En el caso del recorrido 487,
    coinciden 284 de 386 segmentos de ruta y de 370 observaciones del bloque:
    las coberturas son **73,58 %** y **76,76 %**, respectivamente.

    Si varios recorridos cumplen ambos mínimos, elegimos el de mayor puntuación
    de similitud de secuencia del comparador. El **70 % es un umbral práctico
    configurable**, no una garantía de asociación correcta. Se calcula por
    **cantidad de segmentos y observaciones**, no por kilómetros ni duración.
    Tampoco representa precisión del modelo ni probabilidad de que sea ese viaje.

    **Objetivo provisional:** `duracion_bloque_min`, suma de los tiempos del bloque.
    No representa necesariamente la duración completa del recorrido planificado.
    Las diferencias de camino, las repeticiones internas y la fecha común del
    bloque son limitaciones documentadas del prototipo.

    Separamos aproximadamente 80/20 por días UTC: los días más antiguos entrenan,
    los más recientes se reservan para prueba. La hora es la del bloque, no una
    salida GPS confirmada. Coberturas, tiempos reales e identificadores de muestra
    quedan fuera de las entradas del modelo. El preprocesamiento se deberá ajustar
    solamente con entrenamiento.
    """)
    return


@app.cell
def _(mo):
    MAX_BLOQUES_RAPIDOS = 100
    COBERTURA_MINIMA_RAPIDA = 70
    boton_busqueda_rapida = mo.ui.run_button(label="Buscar muestras y preparar 80/20")
    boton_busqueda_rapida
    return COBERTURA_MINIMA_RAPIDA, MAX_BLOQUES_RAPIDOS, boton_busqueda_rapida


@app.cell
def _(
    COBERTURA_MINIMA_RAPIDA,
    MAX_BLOQUES_RAPIDOS,
    boton_busqueda_rapida,
    mo,
    pd,
):
    from bloques_observaciones import buscar_dataset_exploratorio

    mo.stop(not boton_busqueda_rapida.value, mo.md("Iniciá la búsqueda con el botón."))
    muestras_rapidas, diagnostico_busqueda_rapida = buscar_dataset_exploratorio(
        limite_bloques=MAX_BLOQUES_RAPIDOS,
        cobertura_minima=COBERTURA_MINIMA_RAPIDA,
        registros_busqueda=200_000
    )
    dataset_exploratorio = pd.DataFrame(muestras_rapidas)
    mo.stop(
        dataset_exploratorio.empty,
        mo.vstack([
            mo.md("No se obtuvieron muestras con estos límites."),
            mo.ui.table(diagnostico_busqueda_rapida, selection=None),
        ]),
    )
    dataset_exploratorio = dataset_exploratorio.sort_values(
        ["fecha_utc", "muestra_id"]
    ).reset_index(drop=True)
    _dias = dataset_exploratorio["fecha_utc"].dt.date
    _dias_unicos = sorted(_dias.unique())
    mo.stop(
        len(_dias_unicos) < 2,
        mo.vstack([
            mo.md("Hay muestras, pero se necesitan al menos dos días para separar entrenamiento y test."),
            mo.ui.table(dataset_exploratorio, selection=None),
        ]),
    )
    _corte = max(1, min(len(_dias_unicos) - 1, int(len(_dias_unicos) * 0.8)))
    _primer_dia_test = _dias_unicos[_corte]
    entrenamiento_exploratorio = dataset_exploratorio.loc[_dias < _primer_dia_test].copy()
    test_exploratorio = dataset_exploratorio.loc[_dias >= _primer_dia_test].copy()
    columnas_X_exploratorio = [
        "tipo_vehiculo", "variante", "hora_bloque_utc", "dia_semana",
        "duracion_osrm_original", "distancia_osrm",
    ]
    X_train_exploratorio = entrenamiento_exploratorio[columnas_X_exploratorio]
    X_test_exploratorio = test_exploratorio[columnas_X_exploratorio]
    y_train_exploratorio = entrenamiento_exploratorio["duracion_bloque_min"]
    y_test_exploratorio = test_exploratorio["duracion_bloque_min"]
    mo.vstack([
        mo.md("### Muestras exploratorias obtenidas"),
        mo.ui.table(dataset_exploratorio, selection=None),
        mo.md("### División temporal por días"),
        mo.ui.table([
            {"conjunto": "entrenamiento", "filas": len(entrenamiento_exploratorio),
             "porcentaje": round(100 * len(entrenamiento_exploratorio) / len(dataset_exploratorio), 1)},
            {"conjunto": "test", "filas": len(test_exploratorio),
             "porcentaje": round(100 * len(test_exploratorio) / len(dataset_exploratorio), 1)},
        ], selection=None),
        mo.md("### Diagnóstico de búsqueda"),
        mo.ui.table(diagnostico_busqueda_rapida, selection=None),
    ])
    return


if __name__ == "__main__":
    app.run()
