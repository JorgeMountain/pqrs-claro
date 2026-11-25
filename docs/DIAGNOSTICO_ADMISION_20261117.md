# Demora y pendientes en la simulación de admisión

Diagnóstico del PDF ficticio de diez preguntas preparado el 17 de noviembre.
Se consultaron registros y checkpoints mediante SQLite de solo lectura. No se
reinició el servicio ni se recalculó o modificó el expediente durante la revisión.

## Hallazgos confirmados

- P4: la guía contiene la enumeración en p44, pero ese pasaje quedó quinto en el
  ranking interno del documento. `_baseline_document_content` selecciona cuatro.
  La página no llegó entre los 24 candidatos y el lector recibió p45, insuficiente
  para responder la lista completa. La brecha nace en la recuperación.
- P2: las páginas nativas 44 y 3 quedaron sexta y octava en ese ranking y tampoco
  llegaron al lector. Se eligió una resolución OCR pendiente de transcripción.
  El control material de OCR corresponde al pasaje elegido; el aviso local
  adicional repetía el cotejo del mismo fragmento y versión.
- P11: el cierre «Agradezco responder cada punto e indicar los documentos que
  sustentan la información» se convirtió en una búsqueda independiente de todos
  los respaldos, aunque es una instrucción transversal sobre la respuesta.

El recuperador y sus dependencias relevantes son idénticos entre `f633ba4` y
`8a334ff` (PR12). Revertir solo PR12 no devuelve esos pasajes para las mismas
entradas. La última modificación del recuperador pertenece a `e939cda` (PR11).
No se hizo una comparación nueva de inferencia para atribuir otros efectos a los
prompts; tampoco se afirma que todas las versiones anteriores se comporten igual.
Las pruebas previas de controles y redacción no demostraban recuperación completa
para estas formulaciones dentro de toda la biblioteca.

## Tiempos de la ejecución observada

Biblioteca autorizada: 19.097 documentos y 237.593 textos de embeddings distintos. E5 tenía los vectores
preparados: cero fragmentos codificados durante la preparación, una matriz creada
y diez reutilizaciones de esa matriz. Esto no significa que la búsqueda sea gratis.

| Operación | Tiempo observado |
| --- | ---: |
| Preparación semántica local | 56,25 s |
| Once recuperaciones locales, ejecutadas por turnos | 171,55 s acumulados; 7,27-38,45 s cada una |
| Lecturas Fast | 6,00-13,60 s por llamada, sin reintentos HTTP |
| Etapa completa de fuentes | 271,23 s |
| Redacción de las ocho peticiones habilitadas | 70,80 s |

Las llamadas a IA se solapan: no se suman a los tiempos anteriores como si fueran
secuenciales. El servicio expone cinco preguntas de fuentes y cinco de redacción
en esta instalación; el default del código de redacción es otro valor. Estos
tiempos no equivalen a once respuestas aprobadas: tres conservan pendientes.

## Correcciones locales verificadas

1. Identificación distingue instrucciones genéricas de citación de solicitudes
   independientes. Solo filtra una frase literal completa cuando el constructor
   real de contexto conserva su alcance. Mantiene copias, inventarios, fundamentos
   particulares, casos ambiguos, OCR y jerarquías. El replay aislado del caso pasa
   de once a diez peticiones y conserva la frase en el contexto de todas ellas.
2. El contrato absorbe el aviso OCR local redundante únicamente cuando un control
   material conserva la obligación del mismo fragmento completo y versión. En el
   replay de P2 pasan de dos a un control, aún abierto y bloqueante, con idénticos
   respaldos, cobertura, citas y verificaciones. No se aprueba la transcripción.

Validación conjunta: 109 pruebas aprobadas, Ruff y `git diff --check` correctos.
Los replays no hicieron llamadas a IA ni escrituras en las bases del expediente;
sus filas permanecen idénticas por hash.

## Selección de fragmentos en la búsqueda normal

El selector conserva hasta 24 originales. Reutiliza los rankings de texto de
los documentos localizados y compara sus pasajes con el título, la pregunta y
los vectores E5 preparados. Como máximo propone un pasaje adicional por documento
que quedara fuera de sus cuatro primeras coincidencias de texto. Para preguntas
de calendario, busca también la fecha junto al evento dentro de los documentos
localizados. Un calendario de otro período puede ceder su puesto cuando el
período solicitado coincide explícitamente. Se mantienen los permisos, el hash,
la versión, la página, las líneas y las marcas de revisión de los originales.

La comparación usó la copia de `master` en `8a334ff` y las seis colecciones
autorizadas. Se verificaron los 19.097 archivos originales, con 245.251
fragmentos y 237.593 textos distintos preparados en E5. La respuesta esperada
se guardó en un archivo separado de las preguntas. Se cotejaron tanto los
respaldos nuevos como los desplazados por el límite de 24.

| Consulta del expediente | Resultado de master | Resultado con el cambio |
| --- | --- | --- |
| Fechas de examen | Recuperó la resolución OCR, faltó la página nativa | Entró la guía, p. 44. Salió un acta de otro período y se conservó la resolución |
| Datos de la credencial | Faltó la lista completa | Entró la lista de la guía, p. 44. Salieron dos pasajes de una respuesta sobre actualización de datos de matrícula |

En la primera comparación, en 14 preguntas adicionales de admisiones, Consejo Académico, pregrado y
prácticas, ambos selectores recuperaron los 33 elementos esperados. La rúbrica
estricta reconoció 31, y se documentaron dos equivalencias en los artículos
172 y 173 de dos compilaciones del mismo reglamento. En las 16 consultas
se sustituyeron 17 pasajes léxicos de respuestas históricas y un calendario.
Algunos pasajes nuevos tienen poca relación con la petición. La presencia de
un candidato tampoco acredita su aplicabilidad.

Se fijó un segundo lote de cuatro consultas y 15 obligaciones antes de buscar:
inscripción y pago, transferencia regular, Empresarismo y matrícula individual.
El primer ensayo recuperó 13 de 15 obligaciones en ambos modos. Los dos fallos
eran los plazos de inscripción y pago. El período constaba en la introducción,
mientras que el selector lo buscaba sólo en la pregunta. La corrección usa un
único período literal del texto compartido y excluye las demás preguntas. Un
año o período escrito en la pregunta tiene prioridad. El caso que reveló este
fallo sirvió después como regresión.

La ejecución final volvió a correr ambas variantes desde cero contra la misma
biblioteca. En las 18 preguntas nuevas, master recuperó 46 de 48 elementos
y el selector corregido recuperó 48 de 48. Con la rúbrica literal inicial
fueron 44 y 46, respectivamente. Las dos equivalencias de pregrado se aplicaron
a ambas variantes. En las dos preguntas de la captura, la página nativa esperada
pasó de 0/2 a 2/2. Sumando las 20 consultas, se sustituyeron 23 fragmentos
en 14 selecciones. Se ganaron cuatro elementos de evidencia, sin perder ninguno
de los que cubría master.

| Recuperación con los vectores E5 preparados, 18 preguntas | Master | Cambio local |
| --- | ---: | ---: |
| Mediana por pregunta | 9,76 s | 7,80 s |
| Menor y mayor tiempo | 5,42–50,65 s | 4,76–42,38 s |
| Plazos de inscripción y pago | 12,27 s | 10,04 s |

En las dos consultas de la captura, encontrar los fragmentos para la fecha
tardó 10,77 s con master y 7,73 s con el cambio. Para la credencial,
8,82 s y 6,04 s respectivamente.

Las variantes alternaron el orden por pregunta, compartieron corpus, modelo y
matriz semántica y mantuvieron índices léxicos separados. Cada una codificó la
pregunta. La primera consulta incluye la construcción diferida de estadísticas.
Los tiempos excluyen la carga inicial del corpus y de E5, la cola del gestor,
la lectura de la IA y la redacción. Es una medición por pregunta y versión.

En la prueba controlada del validador de producción, la guía nativa produjo
una cita de fechas y una de la lista de la credencial, con cero pendientes en
ambas. Al retirar los fragmentos de la guía y usar la resolución OCR, volvió
a aparecer un único cotejo de transcripción. Esta prueba prescribe los pasajes
al lector para verificar qué acepta el sistema. Un ensayo autónomo con el lector
local Granite 4.1 3B y 24 fragmentos agotó los 900 s sin producir una cita.
Se probaron diez preguntas en ambos modos y la variante sin la guía, 21
evaluaciones controladas en total. El validador aceptó 25 citas con la selección
corregida y 22 con la selección de master en las diez preguntas. La validación
de las respuestas prescritas tardó 8,2 ms de mediana en la versión corregida.
El postproceso del servicio recorrió 19.154 entradas de catálogo y el contenido
autorizado. En los 21 escenarios conservó citas, respaldos y comprobaciones.
La auditoría adicional tardó 3,09 s de mediana y la aplicación final de los
controles, 1,28 ms.

### Comprobación autónoma del lector habitual

Se realizaron cuatro llamadas a `gpt-6-luna` en modo Fast, una por pregunta
ficticia. Cada llamada recibió dos o tres pasajes públicos de guías o reglamentos
con identificadores de prueba. El modelo seleccionó libremente los pasajes y
sus líneas. Los cuatro resultados pasaron por el validador del proyecto.

| Pregunta | Lectura y validación | Respuesta observada |
| --- | ---: | --- |
| Fechas del examen | 6,07 s | Citó el 26 y el 27 de octubre de 2026 en la página 44, sin pendientes |
| Credencial | 5,79 s | Enumeró los datos de identificación, inscripción y lugar del examen, sin pendientes |
| Transferencia regular | 8,31 s | Citó los cuatro criterios, ambas clases de sanción y los dos consejos, sin pendientes |
| Matrícula individual de práctica | 19,46 s | Citó la condición reglamentaria y pidió el registro individual. La lectura produjo dos formulaciones para comprobar ese registro, además de los controles de la norma |

Por alcance del envío autorizado, el lector recibió una selección pública
reducida. Los tiempos de esta tabla miden lectura y validación. La prueba de
recuperación usó los 24 candidatos de la biblioteca completa para cada pregunta.
En conjunto se usaron cuatro llamadas y 35.546 tokens según el proveedor.

Queda una duplicación visible en la respuesta autónoma sobre matrícula. Un
pendiente pide obtener la constancia y el otro pide consultarla para decidir
si la condición se cumple. Se refieren a la misma actuación del gestor, pero
tienen claves y formas de cierre distintas. La comprobación de aplicabilidad
admite una confirmación que no basta para acreditar el documento. La salida
guardada no identifica de forma inequívoca una obligación común. Ambas siguen
abiertas. Fusionarlas sólo porque dos frases o una fuente se parecen permitiría
cerrar con evidencia insuficiente otras peticiones. La prueba con citas
prescritas no había revelado esta duplicación generada por el lector.

El contrato reconoce el alcance documental de una introducción compartida
cuando la pregunta pide describir lo que dice un texto. La consulta sobre los
criterios de transferencia conservó cinco citas y la de Empresarismo, siete.
En ambas desapareció el cotejo de vigencia innecesario. Cuando se pregunta
si una persona concreta puede comenzar la práctica, permanecen la comprobación
de matrícula y los controles de procedencia y vigencia de la norma utilizada.

Las versiones del análisis y del lector cambiaron para que una nueva búsqueda
pueda recalcular resultados antiguos. Ningún expediente se reescribió durante
la comparación. Tras iniciar la comparación se aisló también el error opcional
de E5 al ordenar pasajes dentro de un documento. Una prueba simula un fallo de
memoria y comprueba que la siguiente pregunta sigue usando la matriz global.
Este manejo de excepciones no interviene en los tiempos de búsqueda anteriores.

Evidencia local:
- `output/qa/admission-selector-20261117/DIAGNOSTICO.md`.
- `output/qa/admission-library-diagnosis-20261117/identification-replay.json`.
- `output/qa/admission-library-diagnosis-20261117/ocr-replay.json`.
- `output/qa/full-library-retrieval-20261117/round-4/retrieval-summary.json`.
- `output/qa/full-library-retrieval-20261117/round-4/audited-contract-replay.json`.
- `output/qa/full-library-retrieval-20261117/final-ab/retrieval-summary.json`.
- `output/qa/full-library-retrieval-20261117/final-ab/audit-summary.json`.
- `output/qa/full-library-retrieval-20261117/final-ab/audited-contract-replay.json`.
- `output/qa/full-library-retrieval-20261117/final-ab/audited-catalog-replay.json`.
- `output/qa/full-library-retrieval-20261117/preview-reader-public/http-attempts/`.

### Repetir la comparación local

Desde la raíz del proyecto en PowerShell, con la instalación que conserva este
catálogo y sus permisos, se puede preparar la copia de referencia mediante
los siguientes comandos. El modelo E5 y sus cachés deben existir en disco.

```powershell
$qa = 'output/qa/full-library-retrieval-20261117'
New-Item -ItemType Directory -Force $qa | Out-Null
git archive --format=zip --output="$qa/baseline-master.zip" 8a334ff src/pqrs_claro
Expand-Archive -Path "$qa/baseline-master.zip" -DestinationPath "$qa/baseline-master" -Force
.\scripts\dev-python.ps1 scripts/check_full_library_retrieval.py --all-cases --output "$qa/repeticion"
.\scripts\dev-python.ps1 scripts/check_full_library_contract.py "$qa/repeticion" --require-candidate
.\scripts\dev-python.ps1 scripts/check_full_library_contract.py "$qa/repeticion" --require-candidate --with-catalog
```

El ensayo se detiene si cambian los permisos, el catálogo o los originales
respecto de la instantánea. Guarda por pregunta los fragmentos, su orden, las
identidades desplazadas, los aciertos literales y los tiempos en `output/qa/`.
El segundo comando toma la selección guardada, vuelve a verificar sus permisos,
versiones y originales y prescribe citas para probar los controles del sistema.
Guarda los resultados aunque un escenario falle; con `--require-candidate`
devuelve un código de error si se incumple una expectativa de la prueba.
El último comando pasa esas mismas evaluaciones por la auditoría de catálogo y
los controles finales del servicio, con todos los fragmentos autorizados.
