# Alcance de los cuatro criterios textuales parciales

Revisión de solo lectura del corpus `followup_signature_content.json`, la rúbrica
sellada y los borradores de `output/qa/followup-signature-20261117/runs/candidate-draft`.
No se modifica la evaluación histórica de **20/24 criterios completos y cuatro
parciales**. Esta revisión distingue esa medida de una omisión de lo solicitado.

| Criterio parcial histórico | Alcance de la petición | Diagnóstico |
|---|---|---|
| MUS/P1: extensión de una página | Copia certificada, correspondencia de firma, cotejo y custodia del original | La extensión no se pidió ni condiciona esas respuestas; es contexto opcional. |
| MUS/P2: legibilidad de la ficha | Entrega de una copia simple de PM-17 | No se pidió evaluar la legibilidad; el respaldo permite localizar la copia. No hay un defecto de lectura que deba ocultarse. |
| MUS/P2: extensión de una página | Entrega de una copia simple de PM-17 | No se pidió un inventario de páginas ni una transcripción completa. La extensión es contexto opcional. |
| VIV/P1: entrega proyectada para el 24 de noviembre | Seguimiento sanitario y lugar/fecha del registro de la decisión | La fecha preguntada es la del registro: 21 de noviembre. El 24 corresponde a la entrega condicionada y es contexto opcional. |

Los cuatro datos permanecen en los respaldos. El inventario no los declaró
afirmaciones materiales obligatorias, coherentemente con el alcance de estas
preguntas. No corresponde añadirlos mediante reglas fijas, abrir pendientes por
su ausencia ni modificar retrospectivamente la rúbrica. Si un documento nuevo
pregunta por extensión, legibilidad o fecha de entrega, esos datos sí deben
inventariarse, contestarse y comprobarse.

## Defectos distintos de esos cuatro parciales

VIV/P1 conserva una ambigüedad real: «cuál fue el resultado» presupone un resultado
pasado que el antecedente no acredita. La fecha de registro sí aparece. Ese
problema requiere corregir la formulación temporal, sin añadir el resultado ni
afirmar que la comprobación futura ya ocurrió.

El revisor también mezcló dos dimensiones en algunos requisitos: contenido
respondido y una actuación futura pendiente. `request_requirements` admitía esa
actuación como pendiente abierto, mientras `request_trace` sólo admite brechas de
evidencia para explicar contenido sin respuesta. Por eso ciertos requisitos
figuraban como `not_evaluated` aunque sus unidades materiales estaban contestadas.

La traza ahora conserva `fulfillment_check_keys` aparte de `pending_check_keys`.
Sólo recupera el estado de contenido revisado cuando hay un inventario material
no vacío y todas sus unidades y detalles están contestados con vínculos actuales,
sin omisiones. La actuación debe conservar identidad, objeto, ámbito y versión
del registro abierto. Un seguimiento futuro no responde por sí solo el lugar,
fecha, condición o explicación preguntados; tampoco acredita su ejecución.
La traza no modifica pendientes, resoluciones, fuentes, borradores ni el veredicto
del revisor, y no declara realizada ninguna entrega o comprobación.
