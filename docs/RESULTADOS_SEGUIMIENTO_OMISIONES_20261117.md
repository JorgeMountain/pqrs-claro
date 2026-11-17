# Resultado del seguimiento de omisiones y reutilización

Informe histórico del primer candidato. El defecto de firma/entrega descrito
aquí se corrigió en las etapas posteriores; véanse los
[resultados finales de alcance temporal y controles](RESULTADOS_ALCANCE_TEMPORAL_20261117.md).
Se conservan las mediciones y conclusiones originales de esta primera evaluación.

## Conclusión

El candidato corrige fallos reproducibles de recuperación de omisiones completas
y reutilización de controles. La prueba con la IA en documentos nuevos **no demuestra
todavía una reducción general de errores espontáneos**: ambas variantes cumplen
23 de los 24 criterios de la rúbrica. Se conservan los respaldos esperados.
**No se cumple todavía el requisito de conservación operativa de todos los controles
legítimos**: en una salida, el cotejo de firma queda mezclado con una actuación de
entrega no bloqueante. El resultado no justifica fusionar o activar este candidato.

Al cerrar esta evaluación los cambios quedaron preparados localmente con pruebas
y documentación, sin commit, push, despliegue ni recálculo de expedientes reales. La comparación
es contra `master` f633ba4, no contra una versión anterior escogida por sus fallos.

## Fallos reproducidos con entradas idénticas, sin API

| Comprobación | Master | Candidato |
| --- | ---: | ---: |
| Omisiones completas reparadas en tres ámbitos nuevos | 0/3 | 3/3 |
| Paráfrasis referenciada de un control abierto, normalizador | 2 pendientes | 1 |
| Control abierto presente solo en `checks` | 0, perdido | 1, conservado |
| Reaparición de un control resuelto referenciado, normalizador | 1 | 0 |
| Controles distintos de firma y competencia | 2 | 2 |
| Control tras cambio de versión | Abierto | Abierto |
| Control sin su fuente en el contenido autorizado | Abierto | Abierto |

Las tres omisiones se introdujeron deliberadamente y el proveedor fue simulado:
esto comprueba la recuperación del fallo detectado, no una tasa espontánea del
modelo. Se conservaron exactamente el párrafo previo, sus citas y los controles.
El candidato utiliza la única reparación y recomprobación existentes; cuando el
comprobador no detecta una omisión, la traza no puede descubrirla por sí sola.

`DraftEngine._pending` ya reutilizaba referencias explícitas en master: los casos
de paráfrasis abierta/cerrada allí son 1→1 y 0→0. La mejora 2→1 y 1→0 corresponde
al normalizador compartido; no debe presentarse como una capacidad nueva del redactor.
La conservación del control presente solo en `checks` sí cambia de 0 a 1 en ambas rutas.

Con tres controles idénticos, el contexto base serializado baja de 9596 a 5072 bytes
UTF-8 (47,14 %), y las apariciones de sus registros pasan de ocho a tres. Se mantiene
el registro del borrador que el comprobador necesita comparar. Son bytes de este
fixture, no un porcentaje de ahorro garantizado de tokens o latencia.

## Documentos nuevos con el modelo habitual

Tres PQRS PDF, seis solicitudes y cinco fuentes ficticias. La rúbrica separada de
24 criterios se selló antes de llamar a la API; nunca entra al contexto del modelo.
Ambas variantes usan la misma base inicial, E5 preparado, Fast y `gpt-6-luna`.
La identificación de solicitudes está fijada y cotejada; no se mide su extracción
automática ni OCR de imágenes. La evaluación revisa textos, fuentes y pendientes,
sin tomar el `passed` del modelo como aprobación.

| Ámbito | Master | Candidato |
| --- | ---: | ---: |
| Archivo sonoro: modalidades, plazo, deterioro y avisos | 4/4 | 4/4 |
| Archivo sonoro: disponibilidad, custodia, firma y copia | 4/4 | 4/4 |
| Instrumentos: alternativas, datos y reserva | 4/4 | 4/4 |
| Instrumentos: devolución particular sin acuse | 4/4 | 4/4 |
| Huerta: visita, acompañamiento y opciones de cancelación | 4/4 | 4/4 |
| Huerta: aviso preventivo y seguimiento de decisión final | 3/4 | 3/4 |
| **Total** | **23/24** | **23/24** |

En ambas variantes, seis de seis solicitudes conservan los respaldos esperados.
Las siete referencias seleccionadas por variante pasan cotejo literal, versión,
hash del original y ámbito autorizado. Ninguna respuesta afirma que se haya
certificado, entregado, devuelto un instrumento o cancelado una reserva sin respaldo.

El criterio operativo pendiente de la rúbrica está en la huerta: el texto explica que falta la
decisión final de cierre, pero no registra una tarea de seguimiento. Se conserva
el criterio de la rúbrica; esto no implica exigir que el documento futuro exista
hoy ni convertir cualquier mención del futuro en un bloqueo de la respuesta.

Persisten avisos genéricos de vigencia para preguntas que piden exponer el contenido
de una guía o manual. En el caso de la copia también quedan actuaciones de entrega
solapadas o relacionadas. En la copia, master termina con cuatro controles y el
candidato con tres, pero ambos mantienen dos actuaciones de entrega: **no es una
reducción demostrada de duplicados**. Master añade en Redacción un cotejo de firma
separado (`signature_comparison`, evidencia bloqueante); el candidato conserva el
cotejo unido a preparar la copia (`fulfillment`, no bloqueante). Es una diferencia
material que impide declarar superada la condición de conservación de controles.

Las dos llamadas al lector para esta petición tenían parámetros, instrucciones y
entrada idénticos. Sus salidas fueron distintas antes de entrar a Redacción. Un
replay cruzado sin API, con cada hallazgo y cada propuesta en ambos códigos,
produce controles idénticos por clave, etapa y bloqueo (4/4, 3/3, 4/4, 3/3).
El normalizador no eliminó el cotejo; tampoco está aislado el efecto del contexto
compacto sobre el redactor. La variación del modelo no permite dar por cumplida la
condición global ni justificar más rigor indiscriminado para toda solicitud de copia.

El candidato conserva además un
reparo local de `historical_attribution` sobre un párrafo que ya atribuye el dato
al acta. Estos límites se documentan; no se eliminan controles para mejorar la cifra.

## Ejecución y tiempos descriptivos

| Expediente | Citas lector P1/P2 master | Citas lector P1/P2 candidato | Fin intento master/candidato |
| --- | --- | --- | --- |
| Archivo sonoro | 9,61 / 24,87 s | 9,65 / 19,77 s | 119,57 / 86,63 s |
| Instrumentos | 8,55 / 16,87 s | 9,41 / 16,44 s | 61,06 / 59,06 s |
| Huerta | 8,70 / 21,67 s | 6,81 / 17,53 s | 63,89 / 46,78 s |

Los tiempos excluyen preparación del índice y revisión humana. Las ejecuciones
se solaparon parcialmente y no hubo repeticiones estadísticas: no se concluye una
aceleración causal. Un intento con reparos no equivale a una respuesta aprobada.

Hubo 28 llamadas en master y 26 en candidato (54 en total), sin llamadas adicionales
para los replays. Los tokens informados por la API fueron 384790/41379 de
entrada/salida en master y 340980/37386 en candidato. El número de reparaciones y
la variación de las salidas también influyen en esos totales. No se calculó costo
monetario ni se atribuye toda la diferencia a compactar controles.

Se preservó un intento inicial sin llamadas cuyo observador QA no podía serializar
un objeto `Path`. Corregido el observador, las dos ejecuciones terminaron con código
e importaciones aislados y sin cambios durante la medición. No se descartaron
respuestas de la IA para escoger otras mejores.

## Evidencia y comprobaciones de software

- `scripts/check_request_trace_generalization.py`: preparación y ejecución API.
- `scripts/check_pending_reuse_replay.py`: comparación del normalizador y contexto.
- `scripts/check_request_trace_replay.py`: comparación del grafo con las mismas
  omisiones provocadas, sin depender de respuestas nuevas del modelo.
- `tests/test_request_trace_generalization.py`: omisiones provocadas en tres ámbitos.
- `tests/test_request_trace.py` y `tests/test_draft_omission_trace.py`: referencias,
  destinos, corrección de fuente, permisos, conservación de controles y reparación.
- `output/qa/trace-generalization-20261117/`: fotografías de código, PDFs, rúbrica
  sellada, resultados, replays, auditorías independientes y capturas API privadas.

Pasaron 706 pruebas relacionadas con borradores, revisión, contratos y controles.
Después de los últimos ajustes de reparación y auditoría, pasaron 58 pruebas
específicas adicionales (hay solapamiento; no se suman como pruebas distintas).
Ruff del proyecto completo pasó. Las pruebas de software no son una medición
de exhaustividad semántica del modelo.
