# Reutilización del análisis — fase 3

Implementación local del 28 de septiembre de 2026. No implica despliegue institucional.

## Qué cambia para el gestor

Una corrección de una petición conserva los resultados de las peticiones independientes. Se actualizan también las dependencias identificadas (apartados padre/hijo y referencias resueltas por el contexto del expediente). El original completo sigue disponible para el modelo. Las comprobaciones generales del documento se revisan en la llamada que evalúa las peticiones modificadas.

La pantalla distingue **Resultado conservado** de **Clasificando petición** e indica cuántas peticiones necesita analizar. **Reintentar pendientes** usa la caché vigente; **Reanalizar todo con IA** solicita expresamente una evaluación completa. Ambos mantienen la confirmación humana posterior.

## Entradas que determinan la reutilización

| Cambio | Revisión inicial |
| --- | --- |
| Descartar/deshacer una selección compatible | Reutiliza sin consulta al motor; retira la confirmación anterior |
| Guardar borrador o corregir decisiones humanas | No consulta IA |
| Numeración sin cambiar referencias entre peticiones | Reutiliza sin consulta al motor |
| Título, contenido o citas de una petición | Actualiza esa petición y dependencias identificadas |
| Metadatos generales, original, fuentes/colecciones, modelo, proveedor o instrucciones | Invalida el contexto compartido |
| Reanalizar todo | Ignora la caché previa para esta ejecución |
| Reintentar tras fallo | Reutiliza resultados válidos; no acepta respuestas parciales inválidas |

El título es una entrada semántica: no se supone que un cambio de título sea siempre decorativo. Las dependencias se basan en el contexto estructurado existente; no se presenta ese mecanismo como comprensión infalible de todas las referencias en lenguaje natural.

## Persistencia y compatibilidad

- La caché se guarda en SQLite junto al análisis, con versión, huella del contexto, claves por petición y resultados materializados. No se envía al navegador en las consultas ordinarias ni en el historial.
- Un informe anterior válido puede incorporarse al esquema de caché antes de editar. Un informe obsoleto no se convierte en válido por copiarlo.
- Las comprobaciones de versión, cierre de expediente y cambios durante la ejecución se mantienen. Reutilizar resultados nunca aprueba una revisión humana.
- `POST /initial-review/analyze` admite `mode: incremental | full`. El modo omitido conserva `full` para clientes anteriores. La interfaz actual y el análisis automático de correcciones solicitan `incremental`.
- Una actualización incremental sin entradas pendientes ni cambios devuelve la revisión existente sin invalidar una decisión guardada.
- Fuentes usa checkpoints por contexto común y petición enriquecida. Redacción usa petición, hallazgo, modelo, versión de reglas y original; no la versión global del caso. La validación de vigencia se mantiene separada de la clave de reutilización.
- Las claves anteriores de fuentes/redacción no se migran: la primera actualización puede volver a calcular esos checkpoints.

## Evidencia y límites de medición

536 pruebas Python de los módulos de fuentes, borradores, revisión inicial y preparación: aprobadas en 95,99 s. Tras el último ajuste de serialización de la caché se ejecutaron otras 46 pruebas de revisión inicial y checkpoints, aprobadas en 30,95 s. Estos conjuntos se solapan. Suite JavaScript: 46 aprobadas. Ruff de los módulos nuevos y de revisión inicial/fuentes modificados: aprobado. Permanece la advertencia existente de Starlette/AnyIO.

Con dos peticiones ficticias, la evaluación inicial recibe ambas; corregir P1 envía solo P1 y conserva exactamente el resultado de P2. Una corrección de numeración independiente envía cero peticiones. Cambiar fuentes o modelo evalúa ambas. En fuentes, el contador tras corregir P1 es P1=2 y P2=1. En borradores, P2 no repite planificación, escritura ni comprobación.

`timings` registra duración, peticiones evaluadas/reutilizadas y llamadas a `assess`. No equivale a un conteo de solicitudes HTTP: un proveedor puede hacer llamadas internas o reintentos. No se midió latencia real del proveedor ni se estima un porcentaje de ahorro de tokens. Cuando se evalúa una petición, sigue enviándose el documento original completo para conservar el contexto.

Navegador real: controlador `createLive`, datos y API ficticios. Reintentar envió `incremental`; reanálisis completo envió `full`; la vista distinguió progreso y conservación. Sin errores de consola. Fixture en `tests/browser/phase3-intake.js`; captura local en `output/qa/audit-20260927/phase3-incremental.png`.

Las pruebas no consumieron API de IA ni cambiaron expedientes reales. Se reinició el servidor local después de verificar 51 expedientes sin procesamiento activo. Los cambios de esta fase quedan locales, pendientes de commit/push. La fase 4 de simplificación de la revisión sigue pendiente.
