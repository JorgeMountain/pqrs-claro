# Cuándo una respuesta tiene respaldo suficiente

Encontrar un archivo y decidir qué permite responder son pasos distintos. La evaluación
de fuentes registra ahora los componentes de la pregunta, las afirmaciones que pueden
responderlos, los pasajes literales seleccionados y el alcance de su uso. Esta cobertura
se conserva en borradores y revisión; no constituye aprobación de la respuesta.

## Contenido atribuido y controles pertinentes

Una consulta puede responderse explicando lo consignado en un antecedente sobre el
mismo hecho y periodo. Si la cobertura está completa y sus pasajes coinciden literalmente
con los seleccionados, el estado desconocido de expedición o revisión del catálogo
se conserva como advertencia. No obliga por sí solo a volver a comprobar todo el oficio.
Tampoco una fuente contextual que no sustenta ninguna afirmación impone requisitos a
las afirmaciones cubiertas por otras fuentes.

Esto no cambia los metadatos originales a `issued` o `reviewed`, no crea una revisión
humana y no convierte contenido atribuido en autenticidad, expedición, entrega o un
hecho actual. Para esos usos siguen aplicándose sus condiciones concretas.

Cada brecha propuesta debe identificar la afirmación afectada y explicar por qué los
pasajes disponibles no bastan. Se distinguen los avisos basados solo en metadatos de
las diferencias de contenido, contradicciones, documentos ausentes y lecturas fallidas.
Solo los avisos explícitos de catálogo que no afectan al uso respaldado pasan a
observaciones sin bloqueo. La propuesta original y la razón de esa decisión se conservan
en `gap_decisions`; las contradicciones y demás brechas concretas permanecen abiertas.

Si el evaluador no puede explicar qué está cubierto o qué falta, la aplicación registra
un error de análisis. No lo convierte en una obligación genérica para el usuario.

## Recuperación de pasajes concretos

Una petición que identifica un oficio y una página o literal prioriza ese pasaje y su
continuación. La portada que permite identificar el archivo se incorpora como fragmento
independiente. Los límites de colección, expediente y número de candidatos se mantienen.
No se ensamblan citas nuevas ni se mezcla un encabezado con el cuerpo de otro archivo.

## Compatibilidad y validación

La evaluación puede corregir una vez una inconsistencia de citas: un candidato citado
pero omitido de supports, un alias inexistente o texto que no coincide con el pasaje.
El reintento recibe los mismos candidatos y el diagnóstico, sin ampliar permisos ni
rebajar los filtros. Si vuelve a fallar, queda como error de análisis. La corrección
exitosa conserva su diagnóstico en citation_validation y no garantiza ausencia de
brechas sustantivas. La interfaz no describe un error de evaluación como búsqueda sin
resultados.

La versión de análisis de fuentes es 14, la de borradores 11 y la de revisión 7. Los
resultados anteriores necesitan reevaluación; no se eliminan pendientes o aprobaciones
antiguos mediante una migración silenciosa. Los registros sin cobertura conservan su
tratamiento anterior hasta una nueva evaluación.

La versión de análisis también forma parte de la identidad del checkpoint de fuentes.
Cambiar la política obliga a ejecutar la evaluación nueva; no se recupera un resultado
terminado con instrucciones antiguas bajo una huella de versión nueva.

Para contrastar aparentes contradicciones, la evaluación distingue el período, grupo
y versión curricular: un comparativo entre un curso anterior y otro actualizado sin
semestre explícito no establece, por sí solo, diferencias en una oferta concreta. Esta
orientación no garantiza ausencia de pendientes innecesarios; una decisión de revisión
debe conservar su actor, justificación y pasajes, sin certificar autenticidad ni inventar
una comprobación institucional.

La revisión 7 distingue source_checks, una fotografía de la búsqueda, de las
resoluciones actuales de pending. El contexto enviado al evaluador enlaza ambas por
identificador sin modificar el historial. Un estado open anterior no invalida una
resolución posterior justificada; una resolución histórica tampoco cierra un pendiente
actual. El evaluador conserva la obligación de rechazar decisiones injustificadas.

Las regresiones incluyen peticiones ordinarias y ficticias con el mismo resultado,
metadatos intactos, cobertura parcial, literal ausente, identidad ambigua, contradicción,
lectura fallida, acta mencionada pero no localizada y consultas sobre hechos actuales
o versión oficial. No existe una excepción de suficiencia para las demos.

El cotejo de contenido con IA y los resultados de una copia aislada permanecen en
`output/qa/source-sufficiency-20260910/`, fuera del repositorio público. El flujo no
aprueba institucionalmente, firma, radica ni envía documentos por resolver estos avisos.
