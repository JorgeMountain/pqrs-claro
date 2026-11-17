# Autoridades, alternativas y pendientes específicos

**Estado al finalizar la evaluación del 17 de noviembre de 2026: candidato local,
sin aceptación global del piloto.** El resultado de las pruebas se conserva en
[RESULTADOS_INVENTARIO_PENDIENTES_20261117.md](RESULTADOS_INVENTARIO_PENDIENTES_20261117.md).
El estado de integración posterior se documenta en
[INTEGRACION_CORRECCIONES_RAG_20261117.md](INTEGRACION_CORRECCIONES_RAG_20261117.md).

Esta continuación corrige el paso de una fuente recuperada a la respuesta y a sus
pendientes. No cambia los 24 candidatos ni añade reglas para un expediente,
artículo o nombre concreto. El auditor independiente de procedimientos continúa
controlado por `PQRS_PROCEDURE_SCOPE_PILOT`, desactivado por defecto y en la
instalación durante la validación. Las comprobaciones compartidas de contenido
descritas aquí están habilitadas en el código común de ambos modos. Integrarlas
no activa el auditor independiente ni declara aceptación global del piloto.

## Inventario antes de resumir

El planificador recibe los pasajes con palabras numeradas. Cada unidad de respuesta
puede contener detalles de tipo `authority` o `alternatives`: identifica los
nombres propios que deben conservarse y las opciones cuya relación importa para
contestar. Si no hay detalles pertinentes debe justificarlo; no se inventan
autoridades para las unidades que sólo contienen cifras o contexto.

Python materializa las selecciones desde el texto original. Un detalle debe estar
dentro de una cita de su unidad padre, con el mismo identificador autorizado.
Cada unidad admite hasta 12 detalles y cada alternativa hasta 8 miembros; los
límites producen un error de contrato si se exceden, no un recorte silencioso.

El redactor y el comprobador reciben este inventario. Marcar la unidad amplia como
`answered` ya no sustituye la comprobación de sus detalles. Cada detalle necesita
un resultado propio y evidencia en párrafos actuales que citen su fuente. Un nombre
identificado no se satisface con «órgano correspondiente», aunque el modelo diga
que está contestado. Las alternativas se comprueban por separado: deben conservar
todos los miembros, condiciones y la relación entre opciones, sin convertir una
disyunción en requisitos acumulativos.

La literalidad de los nombres tiene una comprobación adicional en Python, con
normalización tipográfica conservadora. La relación semántica entre alternativas
sigue dependiendo del comprobador. No se infieren automáticamente abreviaturas ni
alias de autoridades; una abreviatura equivalente puede requerir revisión.

Una omisión localizada puede entrar en la reparación acotada existente y después
exige otra comprobación. Los errores de estructura admiten el único reintento de
contrato existente. Una omisión semántica no provoca repeticiones hasta obtener
una aprobación.

## Incertidumbres que no pueden desaparecer del pendiente

Cada afirmación del lector declara si su aplicabilidad no se pregunta, está
respaldada o sigue sin resolver. Una decisión `unresolved` debe enlazar una
incertidumbre específica: afirmación afectada, motivo, cotejo necesario, incisos y
pasajes autorizados. Se validan los enlaces en ambos sentidos. Una contradicción
necesita al menos dos pasajes contrastados.

Los incisos pueden enlazar `uncertainty_indexes` sin duplicar ese mismo cotejo en
`missing`. El vínculo debe corresponder a su inciso y cobertura. Los índices
originales de `missing` y `evaluated_gaps` mantienen su significado; los de
incertidumbres pertenecen a una lista independiente. No se fusionan controles
por parecido textual ni se eliminan dos controles legítimos de alcance distinto.

La redacción contrasta también las comprobaciones materiales que anuncia como
pendientes con el registro estructurado. Debe reutilizar el control existente o
proponer el cotejo nuevo con una diferencia concreta. Una incertidumbre material
no queda gestionada por mencionarla sólo en la prosa. Este control no convierte
una reserva atribuida a una fuente en un impedimento para una consulta meramente
descriptiva.

`source_uncertainties.py` convierte esas incertidumbres en pendientes de evidencia
de tipo `applicability`, aunque el modelo haya devuelto `missing=[]`. Contestar
qué dicen dos textos no acredita cuál se aplica al caso. Una comparación histórica
que no pide aplicar ninguno no genera un conflicto sólo por tener fechas o plazos
diferentes.

No se elimina un control para que el resultado quede en verde. Procedencia,
transcripción, identidad, vigencia, aplicabilidad y preparación o entrega se
mantienen diferenciadas. Un fallo del proveedor, un permiso retirado o una búsqueda
parcial tampoco se convierte en un documento inexistente.

## Copias y referencias dentro de la solicitud

Para «el ejemplar disponible» o una referencia semejante se puede resolver una
identidad documental explícita y única del mismo escrito, usando tipo, número y
año cuando se proporcionan. No se elige un documento porque sea el único candidato
recuperado. Un contexto incompleto, varios referentes o una referencia insuficiente
mantienen un pendiente de identidad.

Una norma localizada e íntegra puede servir para preparar su copia aunque también
respalde una regla. Esto no prueba autenticidad, hechos individuales ni que se
haya enviado. Los controles de integridad, versión y permisos siguen vigentes.
La resolución anafórica de títulos sin identidad numérica sigue siendo conservadora.

La denominación documental numerada no depende sólo de un catálogo cerrado de
tipos. Si se pide explícitamente una copia de una denominación nueva, se contrasta
esa identidad con el encabezado, número, año y metadatos del original. Las otras
preguntas del escrito no se usan para inventar el objeto de una copia ambigua.
El identificador conserva su sufijo completo y el año debe pertenecer a su propio
encabezado o fecha inmediata; el año de otra norma citada no satisface ese cotejo.
Dos objetos bajo un único mandato de copia no se reducen silenciosamente al primero.
Una solicitud sólo de copia puede conservar sus controles con inventario de
contenido vacío; si además pide explicar el contenido, el inventario sigue siendo
necesario. Describir un candidato rechazado no obliga a redactar una respuesta
sobre su contenido cuando únicamente se pidió otro ejemplar.

## Persistencia y protección de ediciones

La política de detalles entra en la firma del borrador y de la revisión. Un
inventario antiguo se puede leer, pero se reconstruye antes de aprobar bajo esta
política; se conserva el texto humano y los pendientes. El grafo de revisión
comprueba los detalles independientemente del `passed` del proveedor.

La invalidación también marca para reconstrucción los inventarios vacíos antiguos.
Una lista vacía con política actual sigue siendo válida cuando corresponde, sin
añadir una llamada por cada revisión. Para unidades de contenido y detalles, un
estado `pending` exige una brecha de evidencia abierta y bloqueante: una tarea
futura de entrega no puede sustituir el contenido omitido. La tarea se conserva.

Corregir el documento invalida su inventario derivado. Retirar un permiso oculta
resultados y citas afectados también en las respuestas API y el historial. Si la
entrada cambia durante el cálculo, el resultado obsoleto no puede guardarse.

Versiones actuales: análisis de fuentes 23, política del lector 3, suficiencia 4,
borradores 16/revisión 11 en modo habitual y borradores 17/revisión 12 con el
auditor de procedimientos activado. El inventario de detalles usa versión 1.

## Validación y límites

Las pruebas con dobles comprueban contratos, veto de aprobaciones incorrectas,
conservación de pendientes, actualización de fuentes y permisos. Las llamadas
reales se prueban aparte con documentos ficticios nuevos, referencias congeladas
y rúbrica que no recibe la IA. Los replays de defectos anteriores comprueban
regresiones concretas; no equivalen a una búsqueda completa sobre otra biblioteca.

El inventario semántico todavía puede omitir un detalle o clasificar mal su
pertinencia. Numerar palabras asegura la procedencia de la selección, no su
exhaustividad. La mejora necesita revisión humana y pruebas periódicas con
documentos nuevos. Tampoco es una optimización de velocidad: añade información
a las llamadas existentes y puede aumentar su duración.
