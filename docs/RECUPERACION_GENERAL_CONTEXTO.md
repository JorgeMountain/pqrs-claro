# Recuperación general: contexto, documentos y continuidad

Esta revisión corrige mecanismos de selección que pueden afectar cualquier expediente. No contiene identificadores de fuentes, nombres de expedientes ni preguntas de la evaluación en las reglas de producción. La recuperación entrega **candidatos**: localizar un pasaje no acredita su aplicabilidad, vigencia, procedencia ni suficiencia para responder.

## Qué hace cada entrada

- La pregunta atómica (`title` y `description`) dirige E5 y la búsqueda dentro del cuerpo documental. El texto completo del original no se concatena a E5: un encabezado, una firma o una introducción larga pueden desplazar el significado de la pregunta o consumir el límite del codificador.
- `context.document_context.excerpts` conserva texto literal del original para el lector. Sus nombres documentales también pueden localizar candidatos, incluso cuando una pregunta posterior no repite el nombre. Esto no transforma las peticiones hermanas en requisitos de la pregunta actual.
- Si la pregunta atómica identifica un documento, sus coincidencias prevalecen sobre los nombres encontrados en otras partes del original. Para nombres sin número se exige el tipo documental y términos descriptivos consecutivos: al menos uno específico para reglamentos, estatutos, manuales, guías e instructivos; dos para otras clases. «Reglamento General» o «Acuerdo Superior» solos no identifican un documento. El nombre de una política puede estar dentro del título del acto que la expide. La coincidencia literal más específica del mismo tipo prevalece sobre un prefijo compartido. Las referencias numeradas reutilizan el reconocedor de identidad documental. Si no aparece un nombre completo, el tipo de política y sus calificadores distintivos pueden localizarse por separado en el ámbito original compartido, excluyendo los rangos de preguntas verificados. Los calificadores explícitos de la pregunta actual prevalecen sobre los del ámbito; un término genérico solo no basta. Esta ampliación únicamente abre búsqueda corporal y no decide aplicabilidad.
- Con contexto original estructurado, las consultas contextuales globales proceden únicamente de relaciones verificadas entre preguntas: padres, hijos, remisiones y secciones previas. Las despedidas y firmas no generan búsquedas independientes. Las entradas antiguas sin ese contexto conservan su comportamiento de consulta contextual.
- En la selección por metadatos se omiten los números sueltos del contexto original, para no confundir una fecha o un identificador del solicitante con un acto normativo. Los números explícitos de documentos se procesan por el canal de identidad; los de la pregunta atómica se conservan.

## Límites de selección

El máximo continúa siendo **24 fragmentos originales**. La última candidata conserva el selector de `master` como base, incluida su búsqueda dentro del documento y sus canales de fecha, tema, semántica, identidad y respuesta histórica. No redistribuye todos sus resultados: propone como máximo cuatro incorporaciones y, si hay que abrir espacio, sustituye candidatos léxicos/contextuales de la parte final. Prefiere retirar antecedentes léxicos antes que normas. Protege los resultados de cuerpo, semántica, identidad, tema, calendario, respuesta contigua y fuentes expresamente nombradas.

Las incorporaciones tienen este orden y límites:

1. Si la semántica quedó completamente excluida, hasta tres candidatos semánticos nuevos; uno si también hay cuerpo de una norma nombrada por incorporar.
2. Hasta dos fragmentos nuevos del cuerpo de documentos literalmente nombrados. La pregunta atómica sigue puntuando el cuerpo. Un nombre mencionado en otra pregunta sin contenido coincidente no abre un cupo por sí solo.
3. Vecindad original previa/siguiente, comenzando por el mejor pasaje del documento nombrado y los pasajes ya elegidos por búsqueda dentro del cuerpo. Una lista que empieza a continuar literalmente después del corte precede a los vecinos genéricos; no desplaza la prioridad del documento nombrado. Completa los lugares restantes del máximo de cuatro incorporaciones, sin borrar las respuestas históricas contiguas de la selección base.

Si no quedan candidatos léxicos/contextuales sustituibles, la ampliación no desplaza los respaldos protegidos para forzar una incorporación. Tampoco supera ocho fragmentos de un mismo documento. El límite de cuatro permite acotar y auditar los desplazamientos; no garantiza pertinencia ni cobertura completa.

La búsqueda adicional dentro de documentos comprueba hasta seis documentos nombrados contra el cuerpo y conserva hasta dos con coincidencia de la pregunta atómica. El selector auxiliar trabaja con hasta tres documentos y cuatro pasajes por documento; la ampliación final admite únicamente pasajes de fuentes nombradas y el máximo de dos descrito arriba. Las coincidencias de metadatos no se convierten en evidencia.

El tamaño del contexto continúa limitado por `source_context.py`. La búsqueda de nombres usa hasta 6.000 caracteres de `retrieval_context` y hasta 12.000 de extractos originales ya retenidos. Una mención fuera del texto retenido puede no localizarse; los indicadores de truncamiento deben seguir visibles para el lector.

## Continuidad y límites de seguridad

La vecindad usa los lugares restantes de las cuatro incorporaciones. Examina un ancla por fuente y puede agregar su fragmento previo, el siguiente o ambos. Deben pertenecer a una norma o un soporte del caso, a la misma fuente, documento, versión y hash que el ancla seleccionada. Se admite continuidad de líneas en la misma página o entre páginas inmediatamente consecutivas, comprobando el inicio de la página siguiente; se rechazan saltos de rangos, encabezados de capítulo/título/sección y fragmentos mayores de 6.500 caracteres.

Cada continuación conserva su cita independiente y su relación `adjacent_to`. No se concatenan textos de páginas o documentos para fabricar una cita mayor. La pertenencia al expediente, las colecciones autorizadas, las versiones actuales y las categorías permitidas se filtran antes de seleccionar. Un índice preparado nunca sustituye el contenido o los permisos actuales.

## Versionado y comprobación

La huella de recuperación utiliza `SOURCE_ANALYSIS_VERSION`; la del contexto incorpora `CONTEXT_VERSION` y el original/páginas del expediente. Al cambiar estas reglas deben invalidarse los resultados anteriores mediante el versionado del servicio, sin mezclar checkpoints de lectores o contextos distintos.

`tests/test_retrieval_general_coverage.py` añade 28 pruebas con casos ficticios nuevos de ayudas rurales, personal técnico y manuales de ámbitos distintos. Comprueba los 24 lugares, la entrada semántica con canales saturados, el reglamento general, la continuidad de líneas/páginas, la preferencia por el documento expresamente pedido, el rechazo de títulos hermanos sin contenido relevante, la exclusión de firmas como consultas, la actualización tras corregir texto o retirar permisos, el rango previo de una condición cortada, la conservación de los candidatos protegidos del selector base, el ámbito no contiguo frente a una pregunta hermana de otro ámbito y la prioridad de una lista que continúa entre páginas. La comprobación focal de recuperación terminó con **198 pruebas aprobadas**, además de Ruff y `git diff --check` en los archivos de esta mejora.

La evaluación de los ocho PDF anteriores conserva por separado las iteraciones en `output/qa/rag-general-correcciones-20261116/recuperacion`, `recuperacion-v2`, `recuperacion-v3`, `recuperacion-v3-1` y `recuperacion-v3-2`, con scripts, huellas, candidatos y desplazamientos. Usa una copia QA, abre la biblioteca en modo lectura y reutiliza una preparación por iteración para las cuarenta preguntas. Los tiempos de recuperación excluyen esa preparación y la lectura/redacción de IA; no representan tiempo hasta una cita validada. Las coincidencias de fuente/página de la rúbrica son indicadores de recuperación, no una calificación semántica de las respuestas.

## Resultado de recuperación v3.2 — 16 de noviembre de 2026

La versión v3.2 conserva el enfoque de base más cuatro incorporaciones de v3. Añade únicamente la prioridad del ancla corporal de v3.1, el reconocimiento del tipo de política y calificadores de ámbito no contiguos y la prioridad estructural de listas que continúan entre páginas. Los candidatos finales, la selección anterior y los cambios están en `recuperacion-v3-2/FICT-PQRS-*/retrievals.json` y `audit.json`; `summary.json` contiene el resumen de las cuarenta consultas.

- Las cuarenta consultas entregaron exactamente 24 candidatos. En cada una entraron y salieron como máximo cuatro fragmentos frente a los resultados guardados de `master`.
- Se comprobaron en cada candidato los permisos/ámbito actuales y la igualdad de fuente, documento, versión, hash, texto, página y líneas con el fragmento original del snapshot. Los ocho expedientes usan las mismas colecciones autorizadas y fuentes elegibles.
- Las preguntas con al menos una página de la fuente canónica prevista por la rúbrica pasaron de 25 a 36. No se perdió ninguna página canónica antes presente. Este indicador no equivale a 36 respuestas completas: también existen fuentes alternativas válidas, páginas incompletas y restricciones de aplicabilidad.
- Se recuperaron el rango de spam en C02/P5 (página 4, líneas 22–47), los artículos del reglamento de pregrado en C04/P2 (páginas 31–32) y la continuación de los criterios de reconocimiento de cursos en C06/P5 (páginas 9–10). Los respaldos de composición del comité y evaluación docente de C07/P2–P3 permanecen en la selección.
- Un soporte usado por el lector anterior dejó de estar contenido: el acta histórica de C04/P4 que transcribe el artículo 117 y comenta la actuación del jurado en pleno. La selección incorpora el reglamento directo, pero la coincidencia de artículo no acredita por sí sola que cubra toda la interpretación de esa acta; queda señalado para la auditoría del lector en `FICT-PQRS-04/audit.json`.

La recuperación consultó 245.251 fragmentos mediante un índice preparado con 237.593 textos semánticos distintos ya almacenados, sin generar embeddings nuevos. Crear y verificar el snapshot tomó 51,21 s; preparar los índices, 73,43 s. Se hicieron una sola vez y se excluyen de la tabla. La primera consulta, C04/P1, incluye la primera carga de la matriz/modelo; por tanto, tampoco representa una consulta completamente caliente.

| Expediente ficticio | Recuperación de sus cinco preguntas, secuencial |
| --- | ---: |
| C01 | 35,61 s |
| C02 | 47,84 s |
| C03 | 43,18 s |
| C04 | 61,33 s |
| C05 | 39,98 s |
| C06 | 39,17 s |
| C07 | 31,79 s |
| C08 | 53,35 s |

Las cuarenta consultas sumaron 352,25 s, con mediana de 7,58 s y rango de 4,37–23,54 s. Son tiempos locales de recuperación con preparación compartida, medidos una sola vez; el baseline guardado se ejecutó en otra corrida. No demuestran una aceleración ni una regresión de velocidad del flujo normal o del tiempo hasta una cita validada. Esa conclusión necesita una comparación integral con la misma preparación, carga y política de ejecución.

`payload-reuse-manifest.json` compara el texto exacto enviado inicialmente al lector, incluidos orden, alias, roles y cobertura. De las cuarenta entradas de v3.2, 19 coinciden con v3 y tres de C02 con v3.1: 22 lecturas pueden reutilizarse si modelo, instrucciones, esquema y política permanecen iguales; las 18 restantes necesitan lectura nueva. La coincidencia de entrada no garantiza igualdad entre reintentos. Esta comprobación no llamó a la API y no califica las respuestas de IA.

## Riesgos que siguen requiriendo revisión

Un título parcialmente coincidente puede nombrar una versión, recopilación o norma de otro ámbito. Un pasaje con palabras de la pregunta también puede ser insuficiente. La continuidad física puede incorporar un artículo distinto. El lector debe contrastar el contexto literal, respetar la pregunta atómica y dejar un pendiente específico cuando corresponda. Estas pruebas reducen regresiones conocidas; no garantizan recuperar todas las fuentes de futuros documentos.
