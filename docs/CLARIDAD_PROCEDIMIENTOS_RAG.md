# Separar los efectos de procedimientos distintos

**Estado: piloto desactivado por defecto.** La variante V6 corrige los casos de
atribución probados, pero la validación completa todavía produjo omisiones y
pendientes incorrectos. No se acepta como sustituto de la referencia previa.
El informe está en
[RESULTADOS_PROCEDIMIENTOS_RAG_20261116.md](RESULTADOS_PROCEDIMIENTOS_RAG_20261116.md).

La continuación del inventario y de pendientes también se evaluó antes de activar
el auditor. Sus intentos, mejoras y límites están en
[RESULTADOS_INVENTARIO_PENDIENTES_20261117.md](RESULTADOS_INVENTARIO_PENDIENTES_20261117.md).

`PQRS_PROCEDURE_SCOPE_PILOT=false` evita la lectura independiente de referentes.
Las correcciones compartidas del inventario y de pendientes están descritas en
[INVENTARIO_AUTORIDADES_Y_PENDIENTES.md](INVENTARIO_AUTORIDADES_Y_PENDIENTES.md).
El modo `true` queda
disponible para ensayos explícitos, sin modificar la configuración de esta
instalación. Lo descrito a continuación corresponde al piloto activado.

El comprobador documental podía reconstruir la intención de una frase mirando la
cita correcta, aunque el texto dejara dos referentes posibles. Por ejemplo,
describir dos órganos y decir después «su decisión» no indica necesariamente a
cuál se atribuye el efecto. Una cita correcta no corrige esa ambigüedad narrativa.

## Prevención y comprobación

La redacción agrupa supuesto, autoridad y consecuencia de cada actuación antes
de pasar a otra. Si retoma una actuación anterior, debe identificarla de forma
natural junto al efecto. La reparación conserva la separación entre supuestos:
no transforma una comparación en pasos acumulativos ni retira un procedimiento
pedido o su respaldo para ocultar la ambigüedad.

Antes del contraste documental se hace una lectura independiente que recibe
únicamente:

- la petición y su contexto literal delimitador;
- los párrafos actuales, con palabras numeradas.

Esta lectura no recibe fuentes, identificadores de citas, plan, unidades,
suficiencia ni evaluaciones anteriores. Cada solicitud a la API es independiente;
no se le pasa el historial de la llamada documental para que reconstruya una
intención que el texto no expresa.

El esquema de cada llamada contiene un campo obligatorio por párrafo existente
(`paragraph_0`, `paragraph_1`, etc.) y prohíbe campos adicionales. La IA no genera
una lista libre de índices: no puede añadir una fila para un párrafo inexistente
ni omitir otro. Python vuelve a validar el contrato y rechaza claves duplicadas
en la salida original cuando está disponible.

El auditor comprueba cada párrafo. Para los efectos pertinentes selecciona rangos
numéricos de palabras que señalan la consecuencia, sus antecedentes posibles y
el ancla que la vincula a una actuación. Python copia el texto original, incluidos
espacios, saltos de línea y Unicode. No acepta citas parafraseadas ni realiza
coincidencias aproximadas.

Cada interpretación recibe un identificador `L1`, `L2`, etc. El comprobador
habitual recibe esas lecturas junto con las fuentes, los incisos, las unidades
de respuesta y los pendientes. Debe contrastar expresamente cada relación entre
actuación y consecuencia; no basta encontrar la frase de la consecuencia en una
fuente e inferir que el redactor quiso referirse al trámite correcto.

Si el lector entiende que «su decisión» corresponde al segundo procedimiento y
la fuente reserva ese efecto al primero, el contraste señala `misattributed`.
Si el texto permite actuaciones alternativas sin fijar el referente, señala
`ambiguous`. Ambos bloquean la comprobación aunque el resultado general diga
`passed`. Los otros estados son `supported` y `not_procedural`, que también
requieren una justificación concreta.

Python exige una comprobación por cada lectura, sin duplicados ni identificadores
inventados. `supported` y `misattributed` necesitan citas autorizadas. Para aprobar
una relación con `supported`, sus citas deben figurar en el párrafo evaluado:
conservar la unión de citas de todo el documento no sustituye su respaldo local.
Las referencias a candidatos o a documentos sin permiso no son evidencia admisible.

## Anclas y límites de la comprobación

Un rango válido situado antes del efecto puede ser contexto útil. Se conserva
como `context_anchor` para auditoría, separado del `explicit_anchor` situado en
el propio efecto. El contraste documental evalúa su significado y continuidad.
Los rangos inexistentes, invertidos o fuera del texto siguen siendo inválidos.

El alcance son actuaciones o etapas distintas con efectos diferentes. Dos
documentos que describen el mismo trámite no son, por ese solo hecho, dos
procedimientos. Un conflicto normativo claramente atribuido y su cotejo pendiente
no se convierten en una ambigüedad que obligue a elegir una norma o cerrar el
pendiente. Contar dos rangos no produce por sí solo un veto: ambos pueden describir
el mismo trámite. La validez y aplicabilidad siguen en el comprobador documental.

La literalidad de una selección no demuestra que la interpretación sea correcta.
El modelo todavía debe identificar los antecedentes pertinentes. El lector ciego
no aprueba ni rechaza por sí solo: su interpretación se contrasta explícitamente
con la evidencia. Ambas etapas siguen dependiendo de evaluación semántica y no
sustituyen la revisión humana.

## Integración y conservación

`procedure_scope.py` obtiene las lecturas y valida su contraste mediante
`reconcile_procedure_scope_checks`. `OpenAIDraftEngine.check` y
`OpenAIReviewEngine.assess` ejecutan primero la lectura ciega y después la
comprobación de fuentes, incorporando las incidencias antes de decidir el estado
final. Los rangos y la matriz detallada quedan disponibles en QA; en el expediente
se conservan las incidencias y comprobaciones locales, sin exponer una matriz nueva.

La explicación del modelo puede usar aliases de evidencia; se convierten en
referencias legibles. La selección literal del efecto no se transforma, aunque
contenga texto parecido a `S1` o `F1`.

Una incidencia `procedure_scope_ambiguous` o `procedure_scope_misattributed`
señala el párrafo cuya atribución debe aclararse o corregirse.
El borrador usa la única reparación acotada existente y después vuelve a ejecutar
ambas comprobaciones. La revisión del texto guardado sólo informa incidencias;
no reescribe automáticamente la edición humana.

El auditor no puede devolver párrafos, pendientes ni resoluciones. Una reparación
no modifica los documentos ni los controles; las citas del párrafo se vuelven a
comprobar. Un error de comprobación conserva el texto
y no equivale a una aprobación. No se repiten evaluaciones semánticas hasta
obtener un `passed`.

Tras la corrección del inventario, el modo habitual utiliza borradores **16** y
revisión **11**. El piloto utiliza borradores **17** y revisión **12**. La
firma del motor de borradores y la huella de entrada de revisión incorporan la
política del auditor cuando está activado. Cambiar de modo invalida la evaluación
anterior sin aprobar ni borrar el texto humano. La edición, la corrección de fuentes o la retirada de
permisos mantienen las invalidaciones existentes; las evaluaciones se ocultan
junto con los resultados afectados, también en el historial.

## Coste y pruebas

Se añade una llamada por comprobación de texto no vacío, y otra si hay una
reparación seguida de comprobación. Reintentar un nodo de comprobación fallido
puede repetir ambas lecturas; el plan y el texto previos siguen conservados.
No se presenta el cambio como una aceleración. Las métricas diferencian el tiempo
del auditor, el tiempo hasta la primera cita y el del borrador comprobado.

Las pruebas mecánicas cubren selección literal, índices, múltiples antecedentes,
anclas contextuales, límites de 30 párrafos y 6.000 caracteres en revisión,
fallos del proveedor, texto cambiado durante la llamada, aprobación e invalidación.
Las pruebas con API usan documentos ficticios nuevos, entradas congeladas,
rúbricas separadas y auditoría semántica independiente. Los intentos descartados
se conservan. El informe de resultados documenta qué se corrigió, qué siguió
abierto y el coste observado. La suite V6 pasó 2.121 pruebas y la contención
posterior, 565 pruebas pertinentes. Esos resultados mecánicos no anulan los
fallos semánticos que justifican mantener el piloto apagado.
