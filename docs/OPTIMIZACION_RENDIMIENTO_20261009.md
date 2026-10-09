# Optimización de consultas y búsqueda local

9 de octubre de 2026. Cambios posteriores al diagnóstico guardado en
`output/performance-20261009/DIAGNOSTICO.md`.

## Problema y cambios

La biblioteca creció a 10.773 fuentes globales. Para consultar tres fuentes de un
expediente, el sistema deserializaba todos los metadatos y leía las páginas de
toda la biblioteca. Esas consultas se repetían durante las comprobaciones entre
etapas de redacción y durante las actualizaciones de pantalla.

- `SourceLibrary.scoped()` filtra colección, expediente, última versión,
  vigencia, categoría y estado de extracción en SQLite antes de materializar el
  catálogo. Un índice por colección evita recorrer las fuentes no seleccionadas.
- `snapshot()` consulta las páginas por identificador en lotes de hasta 400.
  Sigue verificando el SHA-256 de cada original seleccionado y conserva las
  mismas coordenadas y citas.
- El catálogo administrativo completo conserva su comportamiento anterior.
  No se almacenan resultados de autorización en una caché que pueda quedar
  obsoleta después de cambiar una colección, versión, revisión u OCR.
- La pantalla solicita `compact=true` en revisión inicial y fuentes. Omite
  catálogos y copias de auditoría voluminosas que no utiliza; conserva informes,
  decisiones, pendientes, errores, estado y avance. El GET sin ese parámetro
  y los datos persistidos mantienen la respuesta completa.
- La normalización Unicode usa `str.translate` con los mismos caracteres
  combinantes que eliminaba el algoritmo anterior. El índice construye sus
  estadísticas fragmento por fragmento, sin mantener todos los `Counter`
  temporales a la vez. Sus posiciones y frecuencias usan arrays compactos,
  en lugar de una tupla Python por coincidencia. Se evita calcular dos veces el ranking general de una
  consulta. La clave de estadísticas también incluye el título para detectar
  cambios de metadatos.
- Los nuevos resultados de redacción registran `timings`: duración por solicitud,
  comprobaciones locales y llamadas del motor para planificar, redactar,
  comprobar y reparar, también cuando fallan. Son tiempos del motor, que pueden
  incluir red y reintentos internos; no equivalen al tiempo de inferencia puro.

La concurrencia sigue en tres respuestas. No se eliminan comprobaciones humanas,
no se aprueban pendientes ni se modifican expedientes para mejorar las mediciones.

## Mediciones

Caso de referencia: `147968a30d8f5a37991c45e0691000f3`. Las mediciones locales
emplean cProfile; sirven para comparar estas operaciones, no para prometer la
duración completa de una petición a la IA. El conjunto grande se consultó en un
script aislado, sin cambiar la selección del expediente.

| Operación | Antes | Después | Validación |
| --- | ---: | ---: | --- |
| Consultar tres fuentes elegibles | 0,659 s | 0,004 s | Copia consistente de la misma SQLite con el índice nuevo |
| Preparar tres fuentes / 136 fragmentos | 0,938 s | 0,008 s | Mismos originales y controles de integridad |
| Tres búsquedas sobre 131.799 fragmentos | 113,760 s | 67,519 s | Mismos identificadores, orden y canales de recuperación |

La última comparación incluye una construcción inicial del índice y corresponde
a la primera optimización, antes de compactar las posiciones del índice. El perfilador
añade sobrecoste, especialmente a los bucles Python; estos tiempos no son una
medición de latencia final ni de percentiles bajo carga. La reducción observada
es aproximadamente del 41 % para esas tres búsquedas instrumentadas. Sin embargo,
la comparación adicional **sin perfilador** dio aproximadamente **54,1 s antes y
53,2 s después**, con los mismos resultados. No demuestra una mejora sustancial
en la primera búsqueda sobre toda la biblioteca. Se conserva la reducción de
memoria; no se vende el efecto del perfilador como una reducción de latencia real.

Con el servidor reiniciado, el ciclo equivalente al navegador bajó de **9,908 s**
a **0,438–0,477 s** en tres mediciones. El GET compacto de revisión inicial bajó
de **2.682.640 a 57.845 bytes**. Los GET de borradores y revisión bajaron de
3,300/3,200 s a 0,147/0,247 s respectivamente. No son tiempos de generación de IA.

No se ha repetido una redacción real con IA. El tiempo anterior de 17 minutos
incluía diez solicitudes y llamadas al proveedor; no se atribuye toda esa demora
al trabajo local ni se promete un tiempo nuevo sin medirlo.

## Evidencia y regresiones

Los archivos de medición están en `output/performance-20261009/`:
`retrieval_before.json`, `retrieval_after.json`, sus perfiles `.txt`,
`scoped_copy_after.json` y `data_before.json`. Los scripts no envían solicitudes
a modelos ni cambian las decisiones del expediente.

Se añadieron pruebas de equivalencia de alcance, uso del índice, lectura de
páginas seleccionadas, cambios externos de extracción, desvinculación inmediata,
normalización Unicode, cambios de título y contrato de progreso compacto.
También se comprueba la persistencia de tiempos de redacción exitosa y fallida.

La batería general produjo 1.312 pruebas correctas y una falla por instalación
incompleta del runtime: faltaba `huggingface_hub`. Se restauraron las dependencias
de FastEmbed con las versiones ya fijadas en `uv.lock` (sin modificarlo):
`filelock`, `fsspec`, `hf-xet`, `huggingface-hub` y `numpy`. La repetición de las
pruebas semánticas y de recuperación dio 49 resultados correctos, incluida
inferencia local real con conexiones de red prohibidas. La regresión adicional
de memoria también pasó. Ruff, sintaxis JS y pruebas de conservación del formulario
y representación del análisis/piloto pasaron.

Los hashes de las filas de 22 tablas de expedientes, biblioteca y borradores
coincidieron antes y después del reinicio. El navegador mostró las diez respuestas
conservadas y una consola sin errores.

## Activación

El índice se crea automáticamente al iniciar la aplicación. Es necesario
reiniciar el proceso Python para activar el nuevo backend y recargar la página
para utilizar los módulos del navegador actualizados.

El servidor se reinició tras la confirmación del usuario, mediante operaciones
separadas sobre el proceso verificado. `/recorrido-status` confirmó un único
servidor unificado con biblioteca conectada en `http://127.0.0.1:8772/`.

Queda por medir una nueva redacción real y el coste de la primera indexación
semántica de las colecciones grandes. Recuperar toda la biblioteca continúa siendo
costoso; una futura mejora requiere un índice persistente con invalidación por
versión/OCR y pruebas de alcance, en lugar de reducir comprobaciones o resultados.

La siguiente fase implementa esa preparación léxica persistente, con cola y
progreso, descrita en [PREPARACION_BIBLIOTECA.md](PREPARACION_BIBLIOTECA.md).
La preparación semántica y las API institucionales continúan siendo etapas distintas.
