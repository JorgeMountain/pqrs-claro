# Conservar el contenido al pasar de las fuentes al borrador

El RAG puede recuperar la cita correcta y aun así perder una condición al resumirla.
Una comprobación por inciso amplio tampoco demuestra que todos sus requisitos,
alternativas, excepciones o fundamentos aparezcan en el texto final.

## Flujo general

1. La solicitud conserva sus incisos y el contexto literal del documento original.
2. El lector selecciona soportes autorizados y mantiene las brechas y los controles
   de procedencia, vigencia, transcripción, conflicto y actuaciones pendientes.
3. Antes de resumir, el planificador identifica unidades de contenido pertinentes
   leyendo los pasajes completos, sin asumir que el resumen del lector ya es
   exhaustivo. Conserva su suficiencia, controles y decisiones humanas.
4. Cada unidad enlaza un inciso con una proposición y rangos de líneas locales.
   Python copia la cita literal, valida documento, versión y permiso y asigna un
   identificador. El modelo no escribe la cita definitiva ni crea una fuente.
5. El redactor recibe las unidades junto con los soportes y pendientes. El
   comprobador revisa cada unidad obligatoria frente al texto realmente escrito.
   También mantiene la comprobación por inciso y frente a los soportes. El
   inventario sigue dependiendo de una interpretación semántica y puede omitir algo.
6. Una omisión con un párrafo identificado puede entrar en la única corrección
   acotada ya existente. Después se vuelve a comprobar el borrador completo.
   La corrección no puede modificar pendientes, resoluciones ni fuentes.
7. La revisión del gestor conserva el inventario y comprueba sus ediciones. Los
   cambios de documento o permiso invalidan/ocultan sus citas derivadas, igual
   que los soportes. Un inventario invalidado se reconstruye antes de comprobar.

No se codifican nombres de expedientes, números de artículos, respuestas esperadas
ni identificadores del conjunto de evaluación en estas reglas. Tampoco se amplía
el número de fragmentos ni se cambia el recuperador en esta segunda corrección.

## Qué se considera obligatorio

Una unidad debe responder, condicionar o limitar lo expresamente preguntado. El
contexto complementario tiene `kind=context` y `required=false`: no genera por sí
solo una obligación narrativa ni un documento faltante. Se separan las reglas
generales de las excepciones y se conserva qué actuación produce cada efecto.
Esto no permite omitir una excepción material o eludir un conflicto. La evaluación
observó que el modelo todavía puede exigir una exclusión redundante o aceptar
un referente ambiguo: son límites documentados, no capacidades garantizadas.

Los controles de catálogo y las actuaciones futuras no son unidades documentales
citables. Una solicitud sólo de copia puede tener un inventario vacío y conservar
las tareas de preparación, comprobación y entrega. Si también pregunta por su
contenido, ese contenido sí requiere unidades con citas. Localizar el archivo
permite preparar la copia, pero no demuestra autenticidad ni una entrega realizada.

## Contrato comprobable

`answer_coverage.py` valida hasta 64 unidades, 8 citas por unidad, identificadores
únicos, inciso existente, cita literal y ámbito autorizado. Los vínculos de
`unit_checks` deben apuntar a párrafos o pendientes existentes. Una unidad
`answered` necesita texto y, entre los párrafos indicados, todas sus fuentes;
cada párrafo indicado debe citar al menos una de ellas. `pending` requiere una
brecha específica abierta: no basta un control cerrado o `metadata_only`.

`out_of_scope` requiere una explicación; Python verifica el contrato, no certifica
esa interpretación semántica. Las unidades omitidas detectadas producen
`answer_unit_omitted`; el checklist por inciso también puede identificar omisiones.
Una mezcla de procedimientos debe señalarse como `procedure_scope_mixing`,
pero se observó un caso residual que el modelo no detecta. Un `passed` automático
no es aprobación humana ni una
garantía de exhaustividad.

El plan permite un único reintento ante un contrato de unidades inválido. La
comprobación permite el único reintento estructural existente para un checklist
inválido/incompleto, usando el mismo texto y fuentes. No reintenta una omisión
semántica para convertirla en aprobación. La corrección del borrador es distinta:
modifica sólo párrafos señalados y siempre exige una nueva comprobación.

## Persistencia y coste

El inventario se introdujo con `DRAFT_VERSION=14` y `REVIEW_VERSION=9`.
La continuación del inventario de autoridades y alternativas usa borradores 16
y revisión 11 en modo habitual, y 17/12 en el piloto de referentes, desactivado
por defecto. Véase
[INVENTARIO_AUTORIDADES_Y_PENDIENTES.md](INVENTARIO_AUTORIDADES_Y_PENDIENTES.md) y
[CLARIDAD_PROCEDIMIENTOS_RAG.md](CLARIDAD_PROCEDIMIENTOS_RAG.md).
El inventario participa en hashes y fotografías de aprobación.
La edición humana conserva el inventario y retira la evaluación anterior; un
cambio de fuente invalida el inventario. Si cambia el texto, versión o permiso
durante su reconstrucción, no se guarda el resultado obsoleto.

Se reutilizan las etapas normales de planificación, escritura y comprobación.
El inventario aumenta entrada/salida y puede aumentar latencia. Reconstruir un
inventario invalidado durante una revisión añade una planificación sin reescribir
el texto humano. No se presenta esta modificación como una aceleración.

La validación mecánica usa dobles explícitos del proveedor. La calidad semántica
se evalúa por separado con fuentes y preguntas ficticias nuevas, rúbrica congelada
y revisión independiente de los textos y citas; no se deduce del `passed`.
Véanse `QA_UNIDADES_REVISION_20261116.md` y el informe de resultados de omisiones.
