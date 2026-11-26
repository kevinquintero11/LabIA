# P3 — Predicción de tiempos de viaje y ETA

Versión final del trabajo, implementada como una notebook interactiva de **Marimo** en `p3_idas_ult.py`.

Reconstruye pasadas de ida a partir de hojas de ruta y registros GPS, genera un dataset por segmento y compara tres modelos para predecir los minutos restantes: **red neuronal (TensorFlow), HistGradientBoosting y Random Forest**. Las referencias son OSRM y OSRM calibrado con los viajes de entrenamiento. También calcula la hora estimada de llegada (ETA) y demuestra una regla de aviso de demora.

## Contenido del repositorio

```text
LabIA/
├── p3_idas_ult.py       # Notebook final: reconstrucción, dataset, modelos y evaluación
├── bson.py              # Conversión de IDs, números y fechas de MongoDB Extended JSON
├── requirements.txt     # Versiones de las dependencias directas
├── README.md
└── .gitignore
```

Los datos y archivos generados se mantienen localmente:

```text
LabIA/
├── data-v2/
│   ├── hojaDeRuta.json
│   └── rastreoSatelital.json
├── parquet/                         # Se crea al ejecutar los botones
│   ├── p3_cuentas/                  # Ejemplo, mapas y conteo de pasadas
│   └── dataset_p3_idas/
│       ├── partes/part_*.parquet    # Dataset por fragmentos
│       └── meta_dataset.json       # Corte temporal y transformación de variables
└── .venv/                           # Entorno Python local
```

`bson.py` es un módulo propio necesario para ejecutar la notebook; no requiere instalar el paquete `bson`.

## Requisitos

- **Python 3.12**, versión usada para verificar esta entrega.
- Un navegador y espacio libre para los JSON, los Parquet finales y los temporales de procesamiento.
- Las dos entradas recortadas de la entrega, obtenidas por el canal de datos del equipo. **Clonar el repositorio no descarga los JSON.** El rastreo puede ocupar varios GB.

El procesamiento y el entrenamiento pueden ejecutarse en CPU. No se requiere un servidor de base de datos ni un servidor OSRM: se utilizan las geometrías y duraciones que ya contienen las hojas.

## Instalación y apertura

Ejecutar los comandos desde la raíz del repositorio.

### Linux

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/marimo edit p3_idas_ult.py
```

### Windows — PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\marimo.exe edit p3_idas_ult.py
```

No hace falta activar el entorno: los comandos usan sus ejecutables directamente. Marimo abre el editor en el navegador; mantener la terminal abierta durante el trabajo y detenerlo con `Ctrl+C` al terminar.

Para presentar la notebook como aplicación, reemplazar `edit` por `run`:

```bash
.venv/bin/marimo run p3_idas_ult.py
```

## Preparar los datos

Crear `data-v2/` junto a la notebook y colocar allí los archivos con estos nombres exactos:

| Archivo | Campos utilizados |
|---|---|
| `hojaDeRuta.json` | `_id`, vehículo, fechas de vigencia y `geometriaOSRM.ida` (puntos, duración y analítica de segmentos). |
| `rastreoSatelital.json` | `flotaID`, `fecha` y `location.coordinates`. |

**Formato importante:** el lector de hojas espera un documento JSON completo por línea, opcionalmente con coma al final y con `[` y `]` en líneas separadas. Un JSON reformateado en varias líneas por documento no es compatible con este lector. El rastreo se lee incrementalmente como un array JSON mediante `ijson`.

Las coordenadas de la ida están en **`[latitud, longitud]`** y las del GPS en **`[longitud, latitud]`**. Se conservan puntos con latitud entre −50 y −20 y longitud entre −80 y −50. Las fechas se procesan en UTC.

Las rutas se resuelven respecto del archivo Python. Si se necesita otra ubicación, modificar `HDR`, `GPS` y `CACHE` en la celda de rutas. `observacionesSegmentosViales.json` no se utiliza en este flujo.

## Cómo ejecutar el trabajo

El procesamiento pesado se inicia mediante botones. En el editor, si hay celdas pendientes por la configuración de ejecución, ejecutarlas para actualizar sus resultados y dependencias.

1. **Exploración opcional — “Ver la primera hoja”.** Busca entre las primeras 15 hojas válidas una con GPS en su vigencia. Muestra tres mapas (ida, pings y búsqueda) y una tabla de pasadas. Recorre el archivo de GPS completo.
2. **Conteo opcional — “Contar todas”.** Aplica las reglas a todas las hojas válidas y muestra los totales por vigencia. Guarda el resultado en `parquet/p3_cuentas/`.
3. **“Armar dataset P3 en disco (baja RAM)”.** Genera los fragmentos y metadatos en `parquet/dataset_p3_idas/`. La configuración final es `variantes=("ida",)`, `nivel="segmento"` y `objetivo="y_en_viaje_minutos"`. Las celdas posteriores de evaluación requieren esta configuración.
4. **Red neuronal.** Al completarse el dataset, la celda dependiente entrena automáticamente durante **50 épocas**. Usa dos capas densas de 25 unidades con ReLU, dropout de 0,3, salida lineal y Adam. Después se calculan predicciones, métricas, ETA y avisos. La red usa el conjunto de test como `validation_data` durante el entrenamiento; no tiene una validación interna separada.
5. **Árboles.** Ejecutar “Buscar configuración: HistGradientBoosting” y “Buscar configuración: Random Forest”. Se prueban 72 y 24 combinaciones, respectivamente, sobre una partición temporal interna de train. Cuando ambas búsquedas terminan, se ajustan los modelos finales y aparece la comparación conjunta en test y la importancia de variables del bosque.
6. **Avisos.** Ajustar el deslizador “Tolerancia del aviso (min)” (5 minutos inicialmente) para recalcular los avisos de OSRM y de la red neuronal.

La exploración y el conteo cargan en memoria los pings de los vehículos seleccionados. El constructor del dataset distribuye el GPS en cubetas temporales en disco, aunque cada cubeta y las geometrías requieren RAM. Para reducir el tamaño de cada cubeta, aumentar `n_buckets` de 32 a 64. Las búsquedas de árboles y la evaluación también utilizan matrices en memoria.

**Volver a ejecutar el botón del dataset reemplaza sus fragmentos anteriores.** Los modelos y métricas se mantienen en la sesión: el código no guarda automáticamente modelos entrenados ni reportes finales. Los mapas y el conteo sí pueden mostrar su caché al reabrir; para el flujo de entrenamiento actual hay que volver a construir el dataset con su botón.

## Criterios del dataset y evaluación

- Un ping se asocia a la ida si está a **250 m o menos**. Se usa el vértice más cercano y se agregan puntos de búsqueda en tramos largos con un paso de referencia de 200 m.
- Salida y llegada corresponden al **primer y último 15 % de la lista de vértices**, no al porcentaje de kilómetros recorridos. La llegada de la etiqueta se alcanza a partir del 85 % de esa lista.
- Un retroceso superior a 3 posiciones corta la pasada. Un silencio de más de una hora la corta solo en las puntas. Se descartan pasadas de menos de dos pings o con avance inferior al 5 %.
- El reloj excluye la espera quieta inicial y termina en el primer ping de llegada. Para generar el dataset se conservan idas completas con duración entre **0,5 y 3 veces** la duración OSRM.
- El conteo exploratorio restringe las vigencias al período **1 de junio–29 de octubre de 2026 (UTC)**. El constructor streaming usa las vigencias de los archivos de entrada sin aplicar ese mismo filtro de fechas; sus totales pueden diferir.
- En modo segmento, la analítica debe tener un elemento por par de vértices consecutivos. Si no existe, se generan identificadores por posición; si existe pero no coincide en longitud, se detiene la construcción con un error.
- La duración OSRM restante se aproxima proporcionalmente al orden de los segmentos. El instante por segmento se interpola entre los pings: no es una observación GPS directa de cada tramo.
- La partición se realiza por días de salida: aproximadamente **80 % de días para train y 20 % para test**. Los viajes que cruzan el corte se excluyen. Se necesitan al menos dos días distintos con pasadas válidas y viajes en ambos conjuntos.
- Medianas, normalización y vocabulario de categorías se calculan sobre train. Los árboles usan una muestra de un instante cada 30 segmentos, incluyendo la salida (`PASO_ARB = 30`).

Las tablas comparan **MAE, RMSE y sesgo en minutos**, al salir y en ruta, además del error por avance. OSRM calibrado multiplica su duración por la mediana de `real / OSRM` de los viajes de train.

La regla de aviso se activa cuando `ETA en ruta > ETA al salir + tolerancia`. La evaluación del aviso muestra precisión, recall y anticipación mediana por viaje. Cada fuente se evalúa contra su propia ETA inicial. La inspección final de campos de paradas es exploratoria; no implementa un aviso contra un horario programado.

## Verificación y problemas frecuentes

Para validar la estructura de la notebook:

```bash
.venv/bin/marimo check p3_idas_ult.py
```

| Problema | Qué revisar |
|---|---|
| `FileNotFoundError` | La ubicación y nombres de los dos JSON en `data-v2/`. |
| Error de JSON en hojas | Que cada documento esté completo en una sola línea. |
| No se encuentran pasadas válidas | Vehículos, fechas, coordenadas y cobertura entre ambas entradas. |
| Incompatibilidad entre segmentos y vértices | La alineación de `analitica_segmentos` con la geometría de ida. |
| Falta de memoria o búsqueda muy lenta | Aumentar `n_buckets`, aumentar `PASO_ARB` o reducir las listas de `GRID_HGB` y `GRID_RF`. |
| Celdas de entrenamiento bloqueadas | Ejecutar el botón del dataset y esperar su finalización; para la comparación final se necesitan ambas búsquedas de árboles. |

`.gitignore` excluye los datos, ZIP de la entrega, Parquet generados, el entorno virtual y el estado local de Marimo. Para reproducir el trabajo en otra computadora, instalar las dependencias y copiar las mismas dos entradas.
