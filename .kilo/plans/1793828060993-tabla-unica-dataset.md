# Plan: Tabla única `dataset_entrenamiento` para entrenar la red neuronal

## Objetivo

Extender `test_temp/load_dataset.py` para producir una **tabla única denormalizada** en
PostgreSQL (más export CSV) donde **cada fila = una observación real de segmento**
(de `observacionesSegmentosViales.json`), enriquecida con:

- **Vehiculo**: `idvehiculo`, `tipoVehiculo`, `cantPlazas`
- **Nodo origen/destino**: `idnodoorigen`, `lat_origen`, `lon_origen`, `idnododestino`, `lat_destino`, `lon_destino`
- **Segmento observado**: `dia` (fecha calendario), `franja_horaria`, `tiemporeal` (segundos)
- **Hojaruta** (match estricto, NULL si no hay): `fechadesde`, `fechahasta`, `duracion_osrm_original`, `ref_recorrido`, `variante`

## Decisiones ya tomadas con el usuario

1. **Grano**: una fila por observación real (de la tabla `observaciones`).
2. **Match Hojaruta**: estricto — mismo `flota_id`, `fecha_utc` dentro de
   `[fecha_desde_utc, fecha_hasta_utc]` y el par `(nodo_origen, nodo_destino)` presente en
   algún `recorrido` de esa hoja. Si hay varias candidatas, gana la de **ventana más corta**.
   Si no hay ninguna, campos de hojaruta en NULL (LEFT JOIN, no se descartan filas).
3. **`dia`**: fecha calendario `YYYY-MM-DD` derivada de `fecha_utc` (`fecha_utc::date`).
4. **Ubicación del código**: dentro de `test_temp/load_dataset.py`. `dataset_up.py` NO se toca.
5. **Entregable**: tabla `dataset_entrenamiento` en PostgreSQL **+ CSV** en
   `data/procesados/dataset_entrenamiento.csv`.
6. **Tablas intermedias normalizadas**: se conservan `vehiculos` y `nodos` en la base.

## Hechos verificados sobre los datos (no re-decidir)

- `observaciones`: `nodo_origen`/`nodo_destino` son IDs de nodo OSM numéricos; `franja_horaria`
  tipo `"Viernes_19_20"`; `tiempo_real` en segundos; `fecha` en `$date`.
- En `geometriaOSRM.<variante>`: `len(puntos) == len(analitica_segmentos) + 1` y los segmentos
  están encadenados (`seg[i].destino == seg[i+1].origen`). Por tanto:
  **nodo origen de `seg[i]` ↔ `puntos[i]`, nodo destino ↔ `puntos[i+1]`** (formato `[lat, lon]`).
- Los IDs de nodo de `analitica_segmentos` son del mismo espacio (OSM) que los de `observaciones`,
  lo que permite el join por par `(origen, destino)`.

## Cambios en `test_temp/load_dataset.py`

### 1. `TABLAS_CONFIG`: agregar 3 tablas

```python
"vehiculos": {
    "columnas": {
        "idvehiculo": "TEXT PRIMARY KEY",
        "tipo_vehiculo": "TEXT",
        "cant_plazas": "INT",
    },
    "indices": [],
},
"nodos": {
    "columnas": {
        "idnodo": "TEXT PRIMARY KEY",
        "latitud": "DOUBLE PRECISION",
        "longitud": "DOUBLE PRECISION",
    },
    "indices": [],
},
```

`dataset_entrenamiento` NO va en `TABLAS_CONFIG`: se crea al final con `CREATE TABLE AS`
(CTAS) a partir de la query de join, y luego se le agregan índices.

### 2. Extracción durante `_flush_hojas()`

- **Vehiculos**: por cada doc de hoja, upsert con
  `INSERT ... ON CONFLICT (idvehiculo) DO NOTHING` (el primero gana; `cant_plazas` se asume
  estable por vehículo). Acumular por lote y usar `execute_values`.
- **Nodos**: en el loop existente de `variante in ("ida", "vuelta", "alternativa")`,
  donde ya se leen `segmentos = var_obj["analitica_segmentos"]`, leer también
  `puntos = var_obj.get("puntos")` y, si `len(puntos) == len(segmentos) + 1`, generar pares:
  - `seg[i].origen  → lat/lon de puntos[i]`
  - `seg[i].destino → lat/lon de puntos[i+1]`
  Insertar por lote con `execute_values(..., "INSERT INTO nodos ... ON CONFLICT (idnodo) DO NOTHING")`
  (el primer mapeo gana; las diferencias entre rutas son despreciables).
  IDs de nodo como TEXT, coherente con `segmentos.origen/destino` y `observaciones.nodo_*`.

### 3. Paso final: construir `dataset_entrenamiento`

Después de importar observaciones y **antes o después de crear índices** (crear primero
`ix_obs_vehiculo_fecha`, `ix_hojas_vehiculo_fecha` y un índice nuevo
`ix_segmentos_par ON segmentos(origen, destino)` para que el match sea viable):

```sql
DROP TABLE IF EXISTS dataset_entrenamiento;
CREATE TABLE dataset_entrenamiento AS
SELECT
    o.flota_id            AS idvehiculo,
    v.tipo_vehiculo       AS tipovehiculo,
    v.cant_plazas         AS cantplazas,
    o.fecha_utc::date     AS dia,
    o.fecha_utc           AS fecha_utc,       -- útil para split cronológico 80/20
    o.franja_horaria      AS franjahoraria,
    o.nodo_origen         AS idnodoorigen,
    no.latitud            AS lat_origen,
    no.longitud           AS lon_origen,
    o.nodo_destino        AS idnododestino,
    nd.latitud            AS lat_destino,
    nd.longitud           AS lon_destino,
    o.tiempo_real_seg     AS tiemporeal,
    hr.fecha_desde_utc    AS fechadesde,
    hr.fecha_hasta_utc    AS fechahasta,
    hr.duracion_osrm_original,
    hr.recorrido_id       AS ref_recorrido,
    hr.variante
FROM observaciones o
LEFT JOIN vehiculos v  ON v.idvehiculo = o.flota_id
LEFT JOIN nodos no     ON no.idnodo = o.nodo_origen
LEFT JOIN nodos nd     ON nd.idnodo = o.nodo_destino
LEFT JOIN LATERAL (
    SELECT h.fecha_desde_utc, h.fecha_hasta_utc,
           r.duracion_osrm_original, r.recorrido_id, r.variante
    FROM hojas h
    JOIN recorridos r ON r.hoja_n = h.hoja_n
    WHERE h.flota_id = o.flota_id
      AND o.fecha_utc BETWEEN h.fecha_desde_utc AND h.fecha_hasta_utc
      AND EXISTS (
          SELECT 1 FROM segmentos s
          WHERE s.recorrido_id = r.recorrido_id
            AND s.origen  = o.nodo_origen
            AND s.destino = o.nodo_destino
      )
    ORDER BY h.fecha_hasta_utc - h.fecha_desde_utc ASC
    LIMIT 1
) hr ON TRUE
WHERE o.campos_minimos_ok = 1 AND o.tiempo_real_seg > 0;
```

Luego:

```sql
CREATE INDEX ix_dataset_vehiculo_dia ON dataset_entrenamiento(idvehiculo, dia);
CREATE INDEX ix_dataset_segmento ON dataset_entrenamiento(idnodoorigen, idnododestino);
```

Nota de robustez: envolver el LATERAL en subquery porque PostgreSQL no permite
`ORDER BY` con referencias externas directas dentro de LATERAL en todas las versiones;
si falla, alternativa equivalente: `LEFT JOIN LATERAL (SELECT ... ORDER BY ... LIMIT 1) hr ON TRUE`
ya es la forma correcta — mantenerla tal cual.

### 4. Export CSV

Tras el CTAS, exportar con `copy_expert`:

```sql
COPY (SELECT * FROM dataset_entrenamiento ORDER BY idvehiculo, fecha_utc)
TO STDOUT WITH (FORMAT csv, HEADER true, NULL '')
```

Destino: `data/procesados/dataset_entrenamiento.csv` (parametrizable; crear el dir si no existe).

### 5. Resumen final

Extender el dict de retorno para incluir filas de `vehiculos`, `nodos` y
`dataset_entrenamiento` (contar con `SELECT count(*)` tras el CTAS).

## Archivos afectados

- **Modificado**: `test_temp/load_dataset.py` (único archivo de código).
- **Generado**: `data/procesados/dataset_entrenamiento.csv` (artefacto de salida).
- `test_temp/dataset_up.py`: sin cambios (versión obsoleta).

## Riesgos y notas

- **Rendimiento del match LATERAL**: puede ser la parte más lenta con millones de
  observaciones. Mitigación: crear los índices mencionados ANTES del CTAS
  (mover `generar_ddl_indices` antes del paso 3 y agregar `ix_segmentos_par`).
- **`cant_plazas` variable por hoja**: se conserva el primer valor visto
  (`ON CONFLICT DO NOTHING`); documentado como supuesto aceptado.
- **Observaciones sin coordenadas de nodo**: si el nodo nunca apareció en ninguna
  geometría OSRM, `lat/lon` quedan NULL (aceptado; el filtro de entrenamiento es
  responsabilidad del notebook).
- Re-ejecutar la importación es idempotente salvo acumulación: el script actual usa
  `CREATE TABLE IF NOT EXISTS`; el plan asume importación sobre base limpia
  (el CTAS hace `DROP TABLE IF EXISTS` solo de `dataset_entrenamiento`).

## Validación

1. Ejecutar la importación sobre `test_temp/data_redux/` (los 3 JSON reducidos) contra
   una base PostgreSQL local de prueba.
2. Verificar conteos: `vehiculos > 0`, `nodos > 0`,
   `count(dataset_entrenamiento) == count(observaciones válidas)`.
3. Verificar que existen filas con `ref_recorrido NOT NULL` (el match funciona) y que
   `lat_origen/lon_origen` no son mayoritariamente NULL.
4. Verificar que el CSV existe, tiene header y el mismo número de filas que la tabla.
5. Spot-check: una fila del CSV con `franjahoraria` coherente con `dia`
   (día de semana de `dia` == nombre en `franjahoraria`).
