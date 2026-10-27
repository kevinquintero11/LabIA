import driverdb
from psycopg2 import sql
from typing import Mapping, Any, Sequence


def consultar(
    nombre_tabla: str,
    filtros: Mapping[str, Any] | None = None,
    columnas: Sequence[str] | None = None,
    limite: int | None = None,
    ordenar_por: str | None = None,
    orden_desc: bool = False
) -> list[dict[str, Any]]:
    """
    Construye la consulta SQL dinámica con los filtros parametrizados,
    se conecta a la base de datos vía driverdb, ejecuta el SELECT, desconecta y retorna los datos.

    :param nombre_tabla: Nombre de la tabla a consultar (ej: 'hojas', 'gps', 'paradas').
    :param filtros: Diccionario de columna: valor para el filtrado WHERE.
                    - Lista/tupla/set: operador IN.
                    - None: operador IS NULL.
                    - Valor escalar: operador =.
    :param columnas: Lista/tupla con los nombres de columnas a seleccionar (por defecto '*').
    :param limite: Cantidad máxima de registros a retornar (LIMIT).
    :param ordenar_por: Columna por la cual ordenar (ORDER BY).
    :param orden_desc: True para orden descendente (DESC), False para ascendente (ASC).
    :return: Lista de diccionarios con los resultados.
    """
    # 1. Construcción de la consulta SQL
    if columnas:
        cols_query = sql.SQL(", ").join(sql.Identifier(col) for col in columnas)
    else:
        cols_query = sql.SQL("*")

    query = sql.SQL("SELECT {cols} FROM {tabla}").format(
        cols=cols_query,
        tabla=sql.Identifier(nombre_tabla)
    )

    condiciones = []
    valores = []

    if filtros:
        for col, val in filtros.items():
            ident = sql.Identifier(col)
            if val is None:
                condiciones.append(sql.SQL("{} IS NULL").format(ident))
            elif isinstance(val, (list, tuple, set)):
                if len(val) == 0:
                    condiciones.append(sql.SQL("FALSE"))
                else:
                    condiciones.append(sql.SQL("{} IN %s").format(ident))
                    valores.append(tuple(val))
            else:
                condiciones.append(sql.SQL("{} = %s").format(ident))
                valores.append(val)

    if condiciones:
        query += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(condiciones)

    if ordenar_por:
        direccion = sql.SQL("DESC") if orden_desc else sql.SQL("ASC")
        query += sql.SQL(" ORDER BY {} {}").format(sql.Identifier(ordenar_por), direccion)

    if limite is not None and limite > 0:
        query += sql.SQL(" LIMIT %s")
        valores.append(limite)

    driverdb.conectarse()
    try:
       resultados = driverdb.realizarSelect(query, valores if valores else None)
    finally:
       driverdb.desconectarse()

    return resultados
