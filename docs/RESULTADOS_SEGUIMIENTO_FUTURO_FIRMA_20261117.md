# Evaluación de seguimiento futuro y firma — 17 de noviembre de 2026

## Método y comparación inicial

Tres expedientes ficticios nuevos (observatorio, museo y vivero), seis solicitudes,
seis respaldos PDF y 24 criterios de contenido/actuación. Las preguntas y la rúbrica
se sellaron antes de evaluar. La base es el candidato de seguimiento de omisiones
del experimento anterior, no una nueva ejecución de master. Los resultados
históricos del experimento anterior se conservan sin cambiar su calificación.

| Lector | Respaldos y citas válidas | Seguimientos solicitados | Firma material separada | Negativos sin firma/seguimiento extra |
| --- | --- | --- | --- | --- |
| Candidato anterior | 6/6 | 2/2 | 1/2 | 2/2 |
| Primer ajuste | 6/6 | 2/2 | 2/2 | 2/2 |

Cada lector necesitó siete llamadas, incluida una repetición estructural. No se
ejecutó Redacción de la base: esta tabla no califica respuestas finales. La media
descriptiva hasta cita validada fue 17,95 y 16,57 segundos respectivamente. Una sola
corrida por variante no demuestra aceleración ni una tasa general de calidad.

El primer ajuste todavía falló la aceptación: una acción de preparar, certificar
y remitir la copia se clasificaba como procedencia bloqueante al mencionar una
condición; las tres copias conservaban una entrega específica y otra genérica.
También apareció un control de procedencia motivado por la metadata ficticia del
corpus. Ese control se conserva como tal; no se elimina para mejorar el resultado.

## Correcciones sobre los mismos resultados

Las correcciones de normalización se prueban reproduciendo las respuestas del
lector en otra base aislada. Se mantienen las respuestas originales, los hashes,
las citas y la cobertura. Esa reproducción no cuenta como otra muestra de IA ni
como tiempo hasta cita de una nueva búsqueda. Redacción utiliza después la copia
reconciliada, sin repetir las llamadas al lector.

Además, una prueba de identidad detectó que dos anuncios distintos del mismo
fragmento podían compartir clave de seguimiento. La identidad ahora incluye el
inciso, los pasajes y las afirmaciones: cerrar uno no cierra el otro.

## Reproducción de los dos fallos anteriores

Con exactamente los mismos inputs y sin llamadas a la API:

- SON/P2 conserva tres controles: el cotejo de firma queda bloqueante, la entrega
  no bloqueante y la procedencia mantiene su identidad. Se conserva la instrucción
  de preparar la copia en los datos de auditoría.
- HUE/P2 pasa de cero a un seguimiento específico no bloqueante, vinculado al
  inciso R2, la cobertura 1 y su cita/versiones. No exige hoy la decisión futura.
- Repetir conserva IDs, apoyos y cobertura. La resolución simulada se reutiliza
  sin reabrir el control ni perder los demás. Cambiar la versión de la firma
  produce una comprobación abierta distinta. No se registran actuaciones reales.

Evidencia local en `output/qa/followup-signature-20261117/`: auditorías
`audit-baseline` y `audit-candidate`, respuestas originales en `runs/`, y
`replay-historical-controls`. Estos datos de QA están fuera de Git; los fixtures,
pruebas y scripts reproducibles forman parte de los cambios del proyecto.

## Contrato final y Redacción

La reproducción final (`runs/candidate-contract-final`, código congelado
`candidate-release`) procesó las siete respuestas capturadas de las seis preguntas
con **cero llamadas a la API y cero intentos de red**. Se conservaron instrucciones,
input y modelo, además de fuentes, cobertura y citas. Los seis resultados mantuvieron
los controles correctos; las tres copias quedaron con una sola entrega no bloqueante.

Redacción (`runs/candidate-draft`) reutilizó esas fuentes y produjo seis borradores:

- Seguimientos futuros específicos, no bloqueantes: **2/2**.
- Cotejos materiales separados y bloqueantes: **2/2**.
- Entregas únicas y no bloqueantes: **3/3**.
- Negativos sin seguimiento ni cotejo de firma añadido: **2/2**.
- Respaldos conservados: **6/6**; referencias a respaldos autorizados: **9/9**.
- IDs, etapas y controles conservados del contrato al borrador: **6/6**.

La rúbrica textual se conserva sin ajustar: **20/24 criterios completos y cuatro
parciales**. No todos esos datos estaban pedidos por la pregunta: extensión de una
página en las copias del museo, legibilidad de la ficha y fecha del 24 de noviembre
para la entrega condicionada del vivero. Siguen en los respaldos, pero no todos
aparecen en la prosa. No se presenta este resultado como recuperación perfecta de
todos los detalles ni como un 24/24.

La ejecución original dejó **3/6 comprobaciones automáticas aprobadas**. En OBS/P1
y OBS/P2 aparecieron falsas alertas locales de atribución; el matcher no reconocía
los tipos documentales y algunos verbos utilizados. OBS/P1 también tuvo un rango
de revisión que excluía el artículo inicial de un nombre presente en el párrafo.
VIV/P1 conservó una alerta sobre «cuál fue el resultado», que puede presentar como
pasada una decisión futura. Esa alerta no se elimina ni se marca como resuelta.

Se hicieron **26 llamadas de Redacción**, todas con respuesta completa; ninguna
lectura adicional. Tiempo por expediente con fuentes ya preparadas: observatorio
46,90 s, museo 71,00 s y vivero 62,86 s. Incluyen planificación, redacción, revisión
y reparaciones acotadas. No son una comparación de rendimiento contra master.

Las auditorías detalladas son `audit-contract-final.md`, `audit-draft-final.md/json`
y `replay-historical-controls-final.json`. Los resultados intermedios se conservan,
incluidos los que fallaron. No hay commit, push ni fusión de estos cambios.

## Validación local posterior, sin otra ronda de IA

Las falsas alertas de OBS se corrigen en el validador local: se reconocen
atribuciones explícitas de circulares, calendarios y comunicados, y se admite un
artículo definido inmediatamente anterior al rango solo cuando reconstruye la
identidad completa exacta. Se mantienen las exigencias de cita y contigüidad; no
se busca otro nombre en el párrafo ni se altera la respuesta de la IA. Las formas
ambiguas que también son sustantivos/adjetivos no bastan como verbo de reporte.

La ejecución con IA permanece tal como salió: no se reescribe su 3/6 ni se suma
este replay como otra muestra. El aviso temporal de VIV/P1 y los cuatro criterios
textuales parciales siguen pendientes de revisión. Por eso se considera validada
la corrección operativa de seguimientos, firma y entrega en esta tanda, pero no
una aprobación integral de todos los borradores.

El bloque amplio de regresión del contrato pasó **1.206 pruebas**. Después pasaron
**229 pruebas** de atribución, identidad y redacción, junto con Ruff y la revisión
de espacios del diff. Sus cuentas se solapan con el bloque amplio y no se suman.
`local-validation-final.json` registra los hashes del código y de los borradores:
las falsas alertas de OBS desaparecen, la alerta temporal de VIV permanece y los
resultados originales no se modifican ni se aprueban automáticamente. Esta última
validación tampoco hizo llamadas a la API.
