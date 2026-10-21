# /// script
# dependencies = ["ipywidgets"]
# ///

import marimo

__generated_with = "0.25.2"
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

    import tensorflow as tf
    import keras
    from keras import layers
    from numpy import array

    # Para el dataset
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from ipywidgets import interact, FloatSlider, VBox, HBox, Button, Output, IntSlider
    import time
    from IPython.display import display, clear_output

    from keras import regularizers

    return pd, plt


@app.cell
def _():
    from pathlib import Path
    import json

    import seaborn as sns

    return Path, json, sns


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

    Apertura de los datasets reducidos disponibles en `data_redux/`.
    """)
    return


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
def _(json, pd, sns):
    sns.set_theme(style='whitegrid')
    path = '/home/jerexio/Universidad/Lab de IA/temp-lab-ia/test_temp/data_redux/observacionesSegmentosViales_redux2.json'
    with open(path, 'r', encoding='utf-8') as f:
        contenido = f.read().strip().rstrip(',')
    # 1. Leer el archivo e imponer formato de lista JSON []
        if not contenido.startswith('['):
            contenido = f'[{contenido}]'
    df_1 = pd.DataFrame(json.loads(contenido))
    df_1['fecha_dt'] = pd.to_datetime(df_1['fecha'].apply(lambda x: x['$date'] if isinstance(x, dict) else x))
    df_1['dia'] = df_1['fecha_dt'].dt.date
    # Cargar el JSON procesado en el DataFrame
    df_1['hora'] = df_1['fecha_dt'].dt.hour
    # 2. Convertir la fecha anidada a datetime
    # 3. Crear columnas auxiliares
    df_1['nombre_dia'] = df_1['fecha_dt'].dt.day_name()
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


if __name__ == "__main__":
    app.run()
