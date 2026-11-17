# Alcance temporal y contenido solicitado

Una decisión anunciada para el futuro no se presenta como un resultado ya obtenido.
La respuesta conserva las fechas, lugares, condiciones y alternativas que la
persona pidió, sin exigir otros datos que solo aparecen como contexto en el archivo.

## Cambios generales

La guía compartida distingue fecha del documento, estado de la actuación y momento
previsto del resultado. Se aplica también a negaciones y preguntas indirectas: no
conocer «cuál fue el resultado» puede presuponer que el resultado ya se produjo.
Si la fuente no lo acredita, se expresa ese límite sin borrar el anuncio. Se
conservan el pasado documentado, el presente en curso y los supuestos condicionales.

El plan separa los datos pedidos de la actuación futura. La comprobación contrasta
la pregunta original contra el borrador, aunque el inventario haya omitido alguno
de sus componentes. Una entrega o seguimiento de `fulfillment` no cubre contenido
respondible que haya quedado fuera. Los metadatos y datos adicionales continúan
siendo contexto opcional cuando no responden ni condicionan lo solicitado.
Cuando se pide explicar una discrepancia o comparación, se comprueba la relación
entre los dos términos y los datos necesarios para comprenderla. El resumen del
lector o una unidad del inventario no sustituyen el contraste con los pasajes.
Si la relación ya es inequívoca, los códigos incidentales no se convierten en
requisitos adicionales. Una omisión narrativa no crea un documento faltante.

Se ensayó un tipo adicional de detalle, `identifier`, para exigir identidades
literales. No mejoró la prueba y podía exigir frases genéricas innecesarias;
se retiró del código. Se conservan sus resultados como experimento descartado,
sin cambiar la rúbrica ni añadir etapas de IA.

La reparación atiende las ambigüedades temporales dentro de la ronda acotada ya
existente, conservando citas, fechas, condiciones y controles. No se añade otro
ciclo automático para forzar una aprobación. Si una incidencia aparece recién al
recomprobar, queda visible para revisión.

La traza distingue las comprobaciones de evidencia de las actuaciones futuras y
conserva sus identidades en listas separadas. Una actuación no acredita contenido:
para reconocer la respuesta revisada se exige inventario material, todas sus
unidades respondidas y detalles válidos, con las citas actuales. La traza no cambia
pendientes, resoluciones ni el resultado del comprobador.

Para evitar falsas alertas por nuevas clases documentales, el control de atribución
admite el nombre breve exacto de una fuente histórica citada y vigente, hasta su
primer identificador numérico, seguido de un verbo de reporte. Una mención suelta,
otro número, otro actor o un predicado en otra oración no cumplen esa regla. No
se codifican nombres ni identificadores de los expedientes de prueba.
El vocabulario de tipos se comparte con las clases documentales ya reconocidas;
una referencia natural como «El aviso prevé...» no exige repetir todo el título.
La mención de una fuente y el reporte de otro actor en otra oración no bastan.

La prueba descubrió además que la conciliación de archivos localizados reemplazaba
una entrega futura correctamente propuesta por un cotejo genérico bloqueante.
`source_assessment.py` ahora conserva las tareas de entrega propias reconocidas por
el mismo criterio de `evidence_contract.py`, antes de conciliar supuestas ausencias.
El cotejo material de autenticidad y los faltantes reales mantienen sus controles.

Al reutilizar una entrega se compara también el documento y la modalidad pedida.
Una tarea de copia simple no sustituye una copia certificada, ni la entrega de un
cronograma sustituye la de un informe aunque el lector enlace el mismo requisito.
Si no hay identidad demostrable se conserva la obligación original. Este control
no borra tareas existentes ni convierte la entrega futura en prueba de autenticidad.

## Versiones y alcance

Fuentes 29, política del lector 9, suficiencia 9, borrador 30/31 y revisión 25/26.
La variante de procedimientos sigue desactivada. Se conserva el recuperador y el
lector Fast, y no se modifican expedientes reales durante la evaluación.

## Pruebas nuevas

`temporal_coverage_generalization_content.json` y su rúbrica separada contienen seis
preguntas de tres dominios ficticios: conservación textil, residencias de intercambio
y filmoteca. La rúbrica se selló con 24 criterios para evaluar contenido y controles.
La revisión de alcance detectó después que uno exigía también un identificador
adicional, innecesario para explicar el contraste solicitado. Su puntuación
histórica se conserva y se distingue de una omisión material en el informe.
Incluyen un evento futuro, una recepción pasada, listas y alternativas, copia
simple, calendario sin seguimiento y una discrepancia material de autenticidad.

La evaluación usa una tanda candidata con llamadas reales. La base anterior
queda congelada para reproducciones locales; no se ejecuta otra tanda completa
para presentar una comparación de rendimiento que esta prueba no pretende medir.
Tras los hallazgos se reproducen las mismas lecturas sin API y se repite solo la
redacción del expediente que falló, conservando los resultados iniciales.
Se mantienen todos los resultados, incluidos errores, y no se cambia la rúbrica
después de observar las respuestas. La identificación inicial está fijada y
cotejada contra el escrito; esta prueba no evalúa extracción inicial ni OCR.
