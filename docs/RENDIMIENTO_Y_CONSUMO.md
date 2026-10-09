# Rendimiento y consumo por expediente

Implementación del 9 de octubre de 2026: primera fase de reutilización de búsqueda
y medición de consumo. No cambia la política de evidencia ni aprueba pendientes.

## Búsqueda semántica

- La carga de vectores usa la clave compuesta `(model_key, text_key)` en SQLite,
  en lotes de 400. No lee todos los vectores del modelo para después filtrarlos.
- Cada ejecución de búsqueda reutiliza hasta cuatro matrices. La caché tiene
  un presupuesto de 64 MiB para matrices y claves; no es un límite para toda la
  memoria del proceso, el modelo ni los vectores individuales ya existentes.
- La clave incluye las huellas ordenadas del título y texto de los fragmentos
  actualmente autorizados. Modificar texto, selección u orden cambia la clave.
  Los metadatos, identificadores y citas siempre provienen de la consulta actual.
- Un alcance mayor que el presupuesto se procesa sin guardar la matriz en caché.
- Se conservan hasta 128 vectores de consulta por instancia. No se persisten
  las consultas. La matriz no se comparte entre ejecuciones ni se guarda en disco.
- Se conserva el mismo modelo, normalización, puntuación y ordenación.
  La búsqueda léxica y los controles de procedencia conservan su comportamiento.

## Medición reproducible

Benchmark local sin red: 20.000 fragmentos ficticios de longitud comparable a
pasajes documentales, vectores deterministas de 384 dimensiones. Se compara con
`source_semantic.py` de HEAD anterior a esta modificación. No mide inferencia real
ni redacción, y no modifica expedientes.

| Operación | Antes | Después |
| --- | ---: | ---: |
| Mediana de seis búsquedas repetidas, tras la primera | 270 ms | 107 ms |
| Cargar tres vectores existentes entre 20.000 | 63 ms | 1 ms |
| Preparar los 20.000 vectores desde disco | 466 ms | 544 ms |

Los resultados, puntuaciones, orden y citas coincidieron exactamente. La primera
preparación completa no mejoró en esta medición; la ventaja es evitar trabajo
repetido y limitar lecturas cuando solo se necesita parte del índice.
Evidencia local: `output/performance-20261009/semantic_cache_benchmark.json` y
`benchmark_semantic_cache.py`. La prueba real del modelo multilingüe se ejecuta
offline, sin descargar archivos.

## Consultar consumo y tiempos

Con el servidor activo:

```text
GET /api/cases/{case_id}/performance
```

También puede consultarse con el Python del proyecto:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev-python.ps1 -m pqrs_claro.performance_metrics --data-dir data --case IDENTIFICADOR
```

La respuesta incluye agrupación por etapa/operación y eventos individuales:

- Duración de identificación, revisión inicial, búsqueda, redacción, revisión
  de respuestas y propuestas de ajuste.
- Llamadas a OpenAI, modelo reportado, tokens de entrada/salida, entrada en caché
  y tokens de razonamiento cuando el proveedor los informa.
- Intentos HTTP observados y reintentos dentro de una llamada al SDK.
- Errores por tipo, sin texto del error ni contenido documental.
- Identificador de solicitud, incluso en tareas de redacción en paralelo.

Cada llamada de reparación se registra aparte. Los intentos HTTP fallidos pueden
no reportar consumo: las métricas no sustituyen el saldo o factura del proveedor.
Los tokens de razonamiento ya forman parte de los tokens de salida y no se suman
dos veces. Los tiempos de etapas anidadas y trabajos paralelos tampoco se suman
como duración total. `returned` significa que terminó la función, no que el
contenido esté aprobado; el estado funcional sigue en el expediente.

Solo se instrumenta OpenAI en esta fase. El clasificador alternativo JEV y las
futuras APIs institucionales no se incluyen en estos totales de proveedor.

## Estimar dinero sin inventar tarifas

El consumo monetario queda en `null` si faltan tokens o tarifas. Para estimarlo,
crear el archivo local `data/metrics-pricing.json` con el nombre **exacto** del
modelo reportado y tarifas verificadas por millón de tokens en USD:

```json
{
  "NOMBRE_EXACTO_DEL_MODELO": {
    "input_per_million_usd": null,
    "cached_input_per_million_usd": null,
    "output_per_million_usd": null
  }
}
```

Reemplazar los `null` únicamente con las tarifas aplicables a la cuenta. Este
ejemplo no asigna un precio ni habilita llamadas. El endpoint calcula una
estimación con la configuración actual: no es un registro histórico de tarifas.
Si un modelo reportado no está configurado, el total queda desconocido. Los
contadores `calls_without_usage`, `calls_without_attempt_count` y `priced_calls`
permiten evaluar qué parte se pudo medir.

## Preservación y límites

Las métricas se guardan en `data/files/{case_id}/performance.sqlite`, junto al
expediente; su eliminación definitiva borra también esta base. No se guardan
claves, prompts, citas, respuestas ni mensajes de excepción. Si falla la escritura
de métricas, continúa el trabajo y se emite una advertencia técnica sin contenido.
Un expediente eliminado no se recrea para guardar métricas.

Solo se mide el trabajo ejecutado después de activar estos cambios. Los casos
anteriores no reciben consumos reconstruidos o inventados. Las pruebas usan
datos temporales y respuestas simuladas; no generan respuestas de casos reales.

## Siguientes fases

1. Preparar e indexar documentos en segundo plano al incorporarlos, con progreso.
2. Persistir estadísticas léxicas o evaluar FTS5 contra los casos de regresión;
   no sustituir el ranking sin comparar calidad, alcance y referencias.
3. Integrar fuentes institucionales cuando se disponga de documentación y acceso
   autorizado. No se presume ningún endpoint, permiso de copia o mecanismo de
   actualización de la API futura.

Activación: reiniciar el backend cuando no haya trabajos activos. No requiere
regenerar expedientes ni cambiar las fuentes seleccionadas.

## Validación y activación de esta entrega

- Suite completa: 1.331 aprobadas y dos fallos de utilidades que construían el
  servicio sin configuración. Se corrigió el decorador para que la instrumentación
  no impida ese uso; ambas regresiones pasaron en la repetición `--lf`.
- 27 pruebas de recuperación, modelo real offline, caché y métricas aprobaron
  tras los ajustes de cierre de conexiones y configuración opcional.
- 11 pruebas de métricas y revisión inicial aprobaron con el control de reintentos
  final, que distingue redirecciones HTTP de reintentos del SDK.
- La integración API/grafo comprobó nueve llamadas simuladas repartidas entre
  tres solicitudes concurrentes. Reabrir resultados no añadió llamadas.
- Ruff aprobó todo `src/pqrs_claro`; `git diff --check` sin errores de espacios.
- Servidor unificado reiniciado en 8772 después de comprobar que no había trabajos
  actuales en curso. `/recorrido-status`, la página y el endpoint de métricas
  respondieron correctamente. Las huellas de filas de **31 tablas** coincidieron
  antes y después: no se modificaron expedientes, revisiones ni respuestas.
- No hubo llamadas pagadas para validar estos cambios. El caso existente usado
  para comprobar el endpoint mostró cero eventos nuevos y costo desconocido,
  conforme a la ausencia de consumo nuevo y de tarifas configuradas.
