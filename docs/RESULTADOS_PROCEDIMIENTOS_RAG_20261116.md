# Prueba general de atribución entre procedimientos

## Decisión

**Piloto implementado, pero desactivado por defecto. No aceptado como sustituto
de la referencia anterior.** Detecta y corrige el vínculo incorrecto entre un
procedimiento y su consecuencia en las pruebas dirigidas. La prueba completa con
documentos nuevos todavía produjo omisiones, un pendiente legítimo no generado,
otro pendiente incorrecto y mayor latencia. No se presenta como una solución
general ya validada.

La instalación conserva `PQRS_PROCEDURE_SCOPE_PILOT=false`. No se editó `.env` ni
se recalcularon expedientes vivos. Los cambios anteriores de contexto, recuperación,
copia documental y unidades de respuesta se conservan. La referencia de esta
comparación es la copia aceptada de esas correcciones, `baseline`, no el `master`
limpio ni una nueva comparación con todos los cambios acumulados.

## Qué se implementó

El lector independiente interpreta el borrador sin ver fuentes ni plan. Sus
selecciones son rangos de palabras copiados literalmente por Python. El esquema
exige exactamente los párrafos existentes, sin filas adicionales ni omitidas.

Después, la comprobación documental debe evaluar cada interpretación `L1…`:
¿la fuente atribuye esa consecuencia al trámite que entendió el lector?
`ambiguous` y `misattributed` bloquean el texto aunque la salida general proponga
`passed`. Una relación aprobada necesita respaldo autorizado y citado en ese
mismo párrafo. Contar dos rangos del mismo procedimiento no constituye un veto.

La reparación acotada conserva los controles y vuelve a ejecutar ambas
comprobaciones. La revisión del texto humano informa incidencias sin reescribirlo.
No se incluyeron nombres de expedientes, números de artículos ni soluciones de
las preguntas evaluadas en la lógica del producto.

Contrato y límites: [CLARIDAD_PROCEDIMIENTOS_RAG.md](CLARIDAD_PROCEDIMIENTOS_RAG.md).

## Diseño de la evaluación

- Entradas, fuentes, planes y rúbricas congeladas antes de sus llamadas API.
  Las rúbricas no se enviaron al modelo.
- Seis preguntas sobre siete PDF ficticios, tres dominios distintos y 32 criterios.
  Servicios normales `SourceService` y `DraftService`, índice preparado.
- Un conjunto adicional de dos preguntas, dos documentos y 12 criterios se
  reservó después de los primeros ajustes. Se usó en V5 y V6; por tanto, no se
  describe como un conjunto nunca observado durante toda la investigación.
- Diez textos adversariales, dos repeticiones adicionales de seis de ellos:
  22 comprobaciones. Tres reparaciones separadas, sin reintentar hasta aprobar.
- Ocho regresiones con textos fijos, incluyendo la atribución equivocada y la
  pérdida de una cita local; cuatro redacciones nuevas con planes y respaldos
  capturados de la evaluación anterior.
- La revisión independiente evalúa significado, respaldo local y pendientes.
  `ok` significa ejecución terminada; `passed` es un control automático y ninguno
  equivale por sí solo a una respuesta correcta.

Modelo configurado: `gpt-6-luna`. Los ensayos mantienen los intentos fallidos.
Usan copias aisladas y no aprueban, envían ni modifican los expedientes reales.

## Resultado del defecto de atribución

La primera tanda V6 detectó **4/4 defectos objetivo**. Los tres textos ambiguos
repetidos se detectaron **3/3 veces cada uno**. Las 22 comprobaciones terminaron
sin errores de contrato. Las tres reparaciones quedaron claras y conservaron
fuentes, plan y pendientes; se verificaron también las citas de cada párrafo.

En el caso original, el lector podía entender que la nota definitiva correspondía
al jurado del segundo procedimiento. El nuevo contraste rechaza esa lectura con
las fuentes del primero. La reparación atribuye expresamente el efecto al trámite
que realmente lo establece. No basta citar el documento correcto al final.

Hubo **dos alertas sobre controles claros** por la nomenclatura del inicio del
plazo. Conservaban recepción, comunicación y cuatro días hábiles, pero el modelo
exigió nombrar por separado reclamación y solicitud. Esa precisión ya apareció
en comprobaciones anteriores; V6 también la clasificó como problema de atribución.
No se reclasificaron las rúbricas para afirmar cero falsos positivos.

En la regresión fija, la disposición correcta pasó de **7/8 a 8/8**. Se bloquearon
los dos textos con atribución incorrecta y el párrafo cuya cita necesaria sólo
aparecía en otro párrafo. Se conservaron la incertidumbre y los controles legítimos.

## Lo que todavía falló con documentos nuevos

| Evaluación | Referencia | V6 | Límite material |
| --- | --- | --- | --- |
| Seis preguntas, 32 criterios | 32/32 | 29/32 | Dos detalles omitidos y un control de conflicto no generado |
| Dos preguntas adicionales | 12/12 | 12/12 de contenido | Una añade un bloqueo indebido para una copia localizada |
| Cuatro redacciones sobre planes capturados | Textos anteriores conservados como referencia | 3/4 aceptables por revisión independiente | Una vuelve a omitir los nombres de dos comités |

En Feria faltaron la alternativa de pertenencia interna/externa de electricistas
y el actor que publica el resultado. Son detalles de la rúbrica de conservación;
la pregunta pedía principalmente número de integrantes y lugar de publicación.
Se informa esa diferencia sin convertirla en ausencia de documentos.

En Herramientas se explicaron dos plazos incompatibles y qué comprobar, pero no
se generó el pendiente estructurado para resolver su aplicabilidad. El lector
dejó `missing`, `checks` y `actions` vacíos. Además, una afirmación de cobertura
sobre falta de constancias se vinculó a una página que no la demostraba; la
redacción final evitó repetirla. Conservar los **4/4 controles heredados** restantes
no demuestra detectar el que nunca llegó a generarse.

En Huerto la atribución quedó clara, pero una salvedad sobre el ciclo consultado
volvió a disparar `period_grounded` después de repararla. No se eliminó el control
para conseguir una aprobación.

En el segundo documento reservado se localizaron la copia íntegra y sus canales.
Sin embargo, un registro `search_incomplete`, en etapa `evidence` y bloqueante,
pidió adjuntar el archivo concreto disponible. Procedencia y entrega pendiente
siguen siendo controles legítimos; ese bloqueo adicional no lo es. La comprobación
automática aceptó el texto y no detectó el problema del pendiente.

En C07 los dos nombres de comités están en el soporte y la cita del plan previo,
pero su unidad obligatoria ya decía «comité correspondiente». El escritor y el
checker mantuvieron esa simplificación. El plan no se regeneró en esta prueba.
Es una omisión residual observable, no prueba causal de que el nuevo auditor
eliminara los nombres.

La recuperación y el lector de fuentes no se modificaron en este piloto. La
generación del pendiente faltante y del bloqueo de copia ocurrió antes de la
comprobación nueva. La prueba revela que el sistema completo todavía no satisface
la condición solicitada; no permite atribuir todos los fallos a este cambio.

## Respaldos, latencia y consumo

El orden recuperado fue idéntico en las seis preguntas. Los respaldos seleccionados
fueron idénticos en cinco; en Herramientas/P2 se seleccionaron dos fragmentos en vez
de tres, manteniendo ambos documentos. No se describe como conservación exacta de
todos los fragmentos ni se oculta la página que quedó fuera.

La mediana de la regresión fija pasó de **8,43 a 26,24 s** por comprobación. No
incluye recuperación ni redacción. En el caso adicional que sí quedó válido, el
tiempo hasta el resultado comprobado pasó de **48,42 a 68,90 s**. El otro intento
terminó en **130,62 s** con un pendiente incorrecto: no es tiempo hasta una
respuesta validada correctamente.

Las seis preguntas pasaron de 24 a 33 llamadas; de 328.063 a 377.595 tokens de
entrada y de 32.338 a 62.443 de salida. Las dos adicionales pasaron de 8 a 10
llamadas. No hay tarifa configurada para calcular dinero. Son tiempos observados
en una ejecución por versión, con otros ensayos concurrentes; no constituyen un
benchmark controlado de rendimiento ni una mejora de velocidad. Sólo hay dos
preguntas por expediente en el primer conjunto y una en el segundo.

## Variantes descartadas y estado del código

V1 omitió una ambigüedad en una repetición. V2 falló al exigir texto literal al
modelo; V3 y V4 revelaron errores de rangos, falsos bloqueos o filas inexistentes.
V5 corrigió el contrato, pero una atribución equivocada volvió a pasar ambos
verificadores separados. V6 conecta las interpretaciones con el contraste
documental; conserva sus positivos y sus limitaciones, sin promoverla por ellos.

El piloto queda disponible con `PQRS_PROCEDURE_SCOPE_PILOT=true` sólo para pruebas
explícitas. El valor efectivo de esta instalación se comprobó como `false`.
Se verificó que apagado conserva los prompts, esquemas y firma de Draft de la
referencia y el contrato completo de Review. Activado conserva los de V6.
Las versiones son Draft14/Review9 apagado y Draft15/Review10 activado; cambiar
de perfil invalida evaluaciones anteriores y conserva el texto humano.

La suite completa de V6, antes de introducir el interruptor, pasó **2.121 pruebas**.
La validación posterior del interruptor pasó **565 pruebas** de configuración,
motores, servicios, huellas, edición, permisos y ambos modos; no se suman como
si fueran pruebas distintas de las de la suite anterior. El listado y resultado consolidado se
guardan en `pilot-final-test-files.json` y `pytest-pilot-containment-final.log`.
Ruff y la comprobación de espacios del diff pasaron sobre el estado final.

La comparación de las cuatro bases de datos vivas y sus 25 tablas seleccionadas
no encontró cambios respecto del cierre anterior. No se realizaron pruebas nuevas
de revocación en la instalación ni se reinició el servidor para activar el piloto.

Antes de habilitarlo debe mejorarse el inventario de autoridades y alternativas,
la creación del control estructurado cuando se detecta un conflicto y la distinción
entre preparar una copia localizada y buscar evidencia ausente. Luego debe repetirse
la evaluación completa con nuevos documentos, sin retirar las rúbricas ni los
pendientes legítimos para obtener aprobación.

## Evidencia local

Carpeta principal: `output/qa/rag-procedimientos-general-20261116/`.

- `candidate-v6-code.json`, `replication-plan-v6.json` y los archivos de congelación.
- `audit-checker-repair-v6.json/.md`: 22 comprobaciones y tres reparaciones.
- `audit-regression-candidate-v6.json/.md` y `audit-write-candidate-v6.json/.md`.
- `service-comparison-v6.json/.md`, `service-v6-diagnostics.json`, `verification-v6.json`.
- `diagnostic-c07-v6-scope.md`: alcance de la omisión de nombres.
- `draft-off-on-contract.json`, `draft-off-on-runtime.json`,
  `review-off-on-contract.json`, `review-off-on-runtime.json`.
- `live-comparison.json`, logs de pruebas y variantes anteriores conservadas.

Conjunto adicional: `output/qa/rag-procedimientos-holdout-final-20261116/`, con
su propia comparación, diagnóstico y verificación V6. Estas carpetas QA son locales
y no sustituyen los tests ni este informe versionable.
