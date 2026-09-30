import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium")


@app.cell
def _():
    from pathlib import Path
    from itertools import islice
    import ijson

    PROYECTO = Path.cwd()
    ORIGINALES = PROYECTO / "data" / "originales"
    PROCESADOS = PROYECTO / "data" / "procesados"

    PROCESADOS.mkdir(parents=True, exist_ok=True)
    return ORIGINALES, PROCESADOS, Path, ijson, islice


@app.cell
def _(ORIGINALES, ijson, islice):
    archivo_gps = ORIGINALES / "rastreoSatelital.json"

    if not archivo_gps.is_file():
        raise FileNotFoundError(
            f"No se encontró {archivo_gps}. Revisá dónde guardaste el archivo."
        )

    with archivo_gps.open("rb") as _archivo:
        vista_previa_gps = list(
            islice(ijson.items(_archivo, "item"), 5)
        )

    vista_previa_gps
    return


@app.cell
def _():
    import marimo as mo
    import json
    import shutil

    from eta_importacion import (
        importar_dataset,
        consultar_base,
        ejemplo_geometria,
    )

    return (
        consultar_base,
        ejemplo_geometria,
        importar_dataset,
        json,
        mo,
        shutil,
    )


@app.cell
def _(ORIGINALES, PROCESADOS, shutil):
    ARCHIVOS_ETA = {
        "hojas": ORIGINALES / "hojaDeRuta.json",
        "gps": ORIGINALES / "rastreoSatelital.json",
        "observaciones": (
            ORIGINALES / "observacionesSegmentosViales.json"
        ),
    }

    BASE_ETA = PROCESADOS / "eta_datos_v1.sqlite"

    print("Carpeta de originales:", ORIGINALES.resolve())
    print("Base que se generará:", BASE_ETA.resolve())

    for _nombre, _ruta in ARCHIVOS_ETA.items():
        if not _ruta.is_file():
            raise FileNotFoundError(
                f"No se encontró {_ruta}. Revisá la carpeta y el nombre."
            )

        print(
            f"{_nombre}: "
            f"{_ruta.stat().st_size / 1024**3:.2f} GiB"
        )

    print(
        "\nEspacio libre en el disco de salida:",
        f"{shutil.disk_usage(PROCESADOS).free / 1024**3:.2f} GiB",
    )
    return ARCHIVOS_ETA, BASE_ETA


@app.cell
def _(mo):
    boton_importacion = mo.ui.run_button(
        label="Importar los tres JSON a SQLite"
    )

    boton_importacion
    return (boton_importacion,)


@app.cell
def _(ARCHIVOS_ETA, BASE_ETA, Path, boton_importacion, importar_dataset, mo):
    mo.stop(
        not BASE_ETA.exists() and not boton_importacion.value,
        mo.md(
            "Presioná **Importar los tres JSON a SQLite** "
            "para comenzar."
        ),
    )

    resumen_importacion_eta = importar_dataset(
        archivos=ARCHIVOS_ETA,
        destino=BASE_ETA,
        lote=5_000,
    )

    BASE_ETA_LISTA = Path(resumen_importacion_eta["base"])

    mo.ui.table(
        resumen_importacion_eta["tablas"],
        selection=None,
    )
    return (BASE_ETA_LISTA,)


@app.cell
def _(BASE_ETA_LISTA, consultar_base, mo):
    muestra_hojas_eta = consultar_base(
        BASE_ETA_LISTA,
        """
        SELECT
            hoja_n,
            hoja_id,
            flota_id,
            tipo_vehiculo,
            fecha_desde_utc,
            fecha_hasta_utc,
            ventana_positiva
        FROM hojas
        ORDER BY hoja_n
        LIMIT 10
        """,
    )

    mo.ui.table(
        muestra_hojas_eta,
        selection=None,
    )
    return


@app.cell
def _(BASE_ETA_LISTA, ejemplo_geometria, json):
    geometria_ejemplo_eta = ejemplo_geometria(
        BASE_ETA_LISTA
    )

    print(
        json.dumps(
            geometria_ejemplo_eta,
            indent=2,
            ensure_ascii=False,
        )
    )
    return


@app.cell
def _(BASE_ETA_LISTA, consultar_base, mo):
    candidatos_eta = consultar_base(
        BASE_ETA_LISTA,
        """
        SELECT
            h.hoja_n,
            h.hoja_id,
            h.flota_id,
            h.tipo_vehiculo,
            h.fecha_desde_utc,
            h.fecha_hasta_utc,
            r.recorrido_id,
            r.variante,
            r.n_segmentos

        FROM hojas AS h

        JOIN recorridos AS r
            ON r.hoja_n = h.hoja_n

        WHERE h.ventana_positiva = 1
          AND r.n_segmentos > 0

          AND EXISTS (
              SELECT 1
              FROM gps AS g
              WHERE g.flota_id = h.flota_id
                AND g.campos_minimos_ok = 1
                AND g.fecha_utc BETWEEN
                    h.fecha_desde_utc AND h.fecha_hasta_utc
          )

          AND EXISTS (
              SELECT 1
              FROM observaciones AS o
              WHERE o.flota_id = h.flota_id
                AND o.campos_minimos_ok = 1
                AND o.fecha_utc BETWEEN
                    h.fecha_desde_utc AND h.fecha_hasta_utc

                AND EXISTS (
                    SELECT 1
                    FROM segmentos AS s
                    WHERE s.recorrido_id = r.recorrido_id
                      AND s.origen = o.nodo_origen
                      AND s.destino = o.nodo_destino
                )
          )

        ORDER BY h.hoja_n, r.recorrido_id
        LIMIT 10
        """,
    )

    mo.ui.table(
        candidatos_eta,
        selection=None,
    )
    return


if __name__ == "__main__":
    app.run()
