# Preparación persistente de la biblioteca

La fase 2 conserva las palabras y frecuencias de cada pasaje para evitar volver a
calcularlas para toda la biblioteca durante una consulta. Es un índice léxico local:
no llama a la IA, no consume tokens y no ejecuta OCR ni genera embeddings.

## Funcionamiento

Al arrancar el servidor, una cola en `biblioteca.sqlite` prepara las fuentes en
segundo plano. Las nuevas cargas tienen prioridad sobre la biblioteca histórica.
Cada documento terminado queda guardado; tras cerrar o reiniciar el sistema se
retoman los documentos pendientes y el documento interrumpido.

Las inserciones, actualizaciones y eliminaciones de fuentes invalidan el índice
en la misma transacción, también cuando provienen del importador o del OCR.
Una revisión y un identificador de trabajo impiden que un resultado antiguo se
publique después de cambiar o eliminar su documento. Un bloqueo del sistema
operativo permite un solo preparador por base de datos.

El índice se identifica por la versión del algoritmo y una huella del título y
texto exacto. Las citas siguen copiándose de los pasajes actuales. Las estadísticas
de búsqueda se calculan dentro del alcance autorizado de cada petición; no se
mezclan colecciones privadas. Preparar una fuente no equivale a aprobarla ni a
resolver sus comprobaciones pendientes.

## Uso y diagnóstico

En **Fuentes de consulta** se muestra cuántas fuentes están listas, en preparación,
sin texto utilizable o con error. El estado se actualiza mientras el diálogo está
abierto. Se puede continuar consultando: los documentos sin índice preparado usan
el cálculo habitual. Las cifras cuentan registros de fuente, incluidas versiones;
no representan necesariamente documentos únicos ni fuentes autorizadas para una PQRS.

- `GET /api/library/preparation`: progreso y total de pasajes preparados.
- `POST /api/library/preparation/retry`: vuelve a poner en cola los errores de
  preparación; conserva la protección de origen de las demás operaciones locales.
- Tabla derivada `source_index_jobs`: estado por fuente, revisión, algoritmo y
  tipo de error. No modifica originales, expedientes ni decisiones humanas.

Los documentos sin texto requieren extracción o revisión por los mecanismos
existentes. Los errores de preparación no se reintentan indefinidamente. Si la
caché falta o está corrupta, la búsqueda vuelve al cálculo habitual. Un cambio
de versión del algoritmo vuelve a preparar las entradas correspondientes.

## Validación y límites

Las pruebas comparan resultados, orden, puntuaciones y citas; cubren aislamiento
entre expedientes, actualizaciones de OCR, borrado concurrente, reinicio,
rollback, caché corrupta y exclusión entre trabajadores. La medición real se
guarda localmente en `output/performance-20261009/phase2-benchmark.json` y usa
una copia de SQLite, sin llamadas a modelos ni cambios en expedientes.

La primera preparación ocupa CPU y espacio adicional en disco. El beneficio se
aplica a la búsqueda léxica; la lectura de originales, las comprobaciones de
integridad, la búsqueda semántica y la latencia de la IA siguen siendo etapas
independientes. Esta fase no conecta todavía las futuras API institucionales.

## Resultado local del 9 de octubre de 2026

Medición sobre una copia de la biblioteca real: 10.773 fuentes en el alcance de
prueba y 131.799 pasajes. Se ejecutaron las mismas tres consultas, sin modelos.

| Etapa | Cálculo habitual | Índice preparado |
| --- | ---: | ---: |
| Cargar frecuencias preparadas | 0 s | 5,46 s |
| Consulta 1 | 47,28 s | 7,51 s |
| Consulta 2 | 1,56 s | 1,48 s |
| Consulta 3 | 15,62 s | 16,39 s |
| Total, incluida carga | 64,45 s | 31,21 s |

El total disminuyó aproximadamente un 52 %. Los resultados completos, su orden,
puntuaciones y citas coincidieron. No todas las consultas mejoraron: otras tareas
de recuperación siguen dominando la tercera. La medida excluye la lectura inicial
de originales, el OCR, los embeddings y la redacción con IA.

La preparación inicial de la copia tardó 240 segundos en ejecución continua.
El trabajador normal intercala pausas breves para dejar recursos a las consultas.
Para activar el sistema se reutilizaron las entradas medidas únicamente cuando
el registro y sus páginas coincidían exactamente con la biblioteca vigente.

Estado activado en 8772: 10.714 registros preparados, 63 sin texto utilizable,
cero errores y cero trabajos pendientes. Se verificaron sin cambios las huellas
de las 31 tablas de datos de trabajo (excluyendo la nueva caché derivada).
La interfaz mostró el progreso correcto y la consola no registró errores ni
advertencias durante la comprobación. Las respuestas existentes se conservaron.
