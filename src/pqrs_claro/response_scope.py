"""Shared relevance criterion for sources, drafting and final checking."""

RESPONSE_SCOPE_GUIDANCE = """ALCANCE DE LOS PENDIENTES:
Aplica este criterio a cualquier expediente, tema y documento. Decide según lo
efectivamente solicitado y las afirmaciones que se pretenden sostener, nunca por
el nombre del archivo, la identidad del caso o que se trate de una demostración.

Una consulta de reglas, requisitos, plazos, horarios, costos o instrucciones
generales puede contestarse con fuentes pertinentes que cubran ese alcance. No
exige comprobar que el solicitante ya realizó el trámite, aportar su expediente
personal ni buscar consultas anteriores de esa persona. Su interés personal no
convierte por sí solo una consulta general en una verificación individual.
Solo exige ese cotejo si lo preguntado, una afirmación de la respuesta o un
antecedente concreto lo requieren. Una observación de repetición marcada como
required_for_response=false es informativa, no una obligación adicional.

Antes de proponer un pendiente o ajuste nuevo, identifica qué parte solicitada o
afirmación concreta no puede responderse con los soportes disponibles, y qué dato
o documento mínimo permitiría resolverla. No agregues tareas por precaución genérica
ni repitas datos presentes en el original o verificaciones vigentes del mismo alcance.
La cobertura parcial de una búsqueda no demuestra una carencia de la respuesta,
ni obliga a probar ausencia de antecedentes cuando las fuentes cubren lo preguntado.

Conserva los faltantes reales: copia documental expresamente pedida, hechos de un
caso individual sin sustento, contradicciones, lectura defectuosa y condiciones
necesarias para aplicar una regla. Una regla general no acredita un hecho personal.
Este criterio no autoriza cerrar comprobaciones guardadas ni aprobar respuestas.

"""
