# Validación real con expedientes nuevos y contexto compartido

El 16 de noviembre de 2026 se probaron los servicios reales `SourceService` y
`DraftService` con tres expedientes completamente ficticios de ámbitos distintos:
subsidios rurales, empleados técnicos temporales y visitantes de un laboratorio
de imagen no clínica. La revisión final encontró correctas las nueve respuestas
para el contenido disponible: 19 incisos auditados, nueve citas con texto literal,
versión y huella correctos, y ninguna cita del ámbito equivocado.

La prueba descubrió y permitió corregir dos defectos adicionales: una petición
plural de copia normativa podía quedar restringida a uso de regla; y una solicitud
mixta de copia más explicación de reglas no tenía representación válida en un
único soporte. Se conservaron los intentos fallidos. No se consideraron aprobados
por el hecho de que la llamada a la API hubiese terminado.

## Alcance y aislamiento

- Tres PDF nuevos, tres preguntas por expediente, 19 incisos en total.
- El ámbito sólo aparece en la introducción del original. No se repite en las
  descripciones atómicas entregadas al recuperador y lector.
- Tres normas inventadas correctas y tres de poblaciones diferentes con reglas
  incompatibles. Sólo seis fragmentos en la pasada completa: esta prueba evalúa
  contexto, interpretación y contratos, no la recuperación dentro de una
  biblioteca grande ni la presión sobre el límite de 24 candidatos.
- Identificación fijada y validada contra las líneas extraídas del PDF para
  aislar las fases posteriores. No se evaluó la identificación mediante IA.
- `gpt-6-luna`, lector Fast, concurrencia configurada de cinco. Al haber tres
  preguntas por expediente, esta muestra permite hasta tres lecturas simultáneas;
  no es una nueva prueba de carga de cinco lectores.
- E5 preparado antes de medir las búsquedas, conservado en memoria dentro de cada
  proceso. Sólo se copiaron sus archivos públicos desde la instalación. No se
  abrió ni modificó ninguna base de datos viva.
- La rúbrica no se entregó al lector, recuperador, redactor ni verificador.
  La credencial existente se cargó con `Settings.load()` sin registrarla.

## Comprobación del contenido

| Expediente | Comprobaciones del resultado final |
| --- | --- |
| Rural disperso | Conserva los tres requisitos y los tres documentos exigidos, sin pedir su entrega para una consulta informativa. Incluye bandeja principal, spam, promociones y contacto posterior. Ofrece la copia correcta y, tras corregir la fuente, informa siete días hábiles desde el mensaje de resultado. No aplica la regla urbana de treinta días. |
| Técnicos temporales | Jornada de siete horas, pausa de veinte minutos tras la cuarta hora. Conserva los cuatro criterios de reconocimiento, comité competente y prueba de validación sin rechazo automático. La copia de Circular 88 queda localizada y se informa el formulario de la intranet. No pide datos declarados ni aplica reglas de administrativos permanentes. |
| Laboratorio | Cinco días hábiles para reserva e inducción de treinta minutos. Incidente: aviso inmediato, detener actividad y contacto alternativo por teléfono interno. Copia de Resolución 729 y cancelación con 48 horas. No exige permiso animal ni vuelve a pedir la fecha declarada. |

Las seis preguntas informativas no generan pendientes de evidencia. En las tres
preguntas que solicitan copia queda únicamente una actuación de cumplimiento
para incluir el archivo en la comunicación; no bloquea la aprobación por falta de
evidencia y no afirma que el documento ya haya sido enviado. Las nueve revisiones
del borrador terminan con `checks.status=passed`; los borradores siguen sujetos
a revisión humana.

## Corrección y retiro del permiso

La fuente rural inicial permite reconsideración, pero deliberadamente no contiene
el plazo. El lector conserva un pendiente específico sobre ese plazo y no toma
el plazo urbano de la norma distractora.

Después se agregó una versión 2 con un artículo nuevo que fija siete días hábiles.
Las lecturas de fuentes y redacción quedaron `stale=true` antes de recalcular,
en 0,069 s. Tras recalcular, todas las citas rurales corresponden a la versión 2,
desaparece la brecha de plazo y el borrador incorpora el artículo nuevo. El backend
conserva el resultado anterior bajo `stale`; este ensayo de servicios no constituye
una comprobación visual de que el navegador lo oculte.

Al retirar el permiso de la colección rural, las consultas de fuentes y redacción
devuelven `results=[]`, `stale=true` en 0,098 s. No exponen el identificador de la
fuente retirada ni la cita anterior. Al recalcular con las otras colecciones, no
se elige ninguna norma distractora: cero soportes y cero párrafos de respuesta,
con pendientes específicos para cada inciso. El permiso sólo se restauró en el
fixture aislado para verificar los arreglos posteriores.

Quedan dos observaciones de presentación, sin fuga de evidencia: después del
retiro, la copia ausente del alcance consultable se etiqueta `document_missing`
aunque su explicación dice que no está entre los candidatos; y el camino sin
soportes añade un pendiente genérico además de los específicos. No se debe leer
esa etiqueta como prueba de inexistencia del documento o de falta en toda la
biblioteca.

## Tiempos observados

Una ejecución por escenario final; no son percentiles ni una comparación con
`master`. La primera cita se mide cuando el servicio guarda el primer resultado
con soporte validado. El mapa completo se mide hasta recuperar el resultado
actual de todas las preguntas. Redacción incluye planificación, escritura y
verificación, y se mide después del mapa.

| Expediente y evidencia final | Primera cita | Mapa completo | Redacción verificada |
| --- | ---: | ---: | ---: |
| Rural, intento 06 | 7,02 s | 25,05 s | 19,69 s |
| Técnicos, intento 06 | 5,00 s | 9,72 s | 32,98 s |
| Laboratorio, intento 04 | 5,75 s | 14,65 s | 18,02 s |

En el intento 06 también se midió el intervalo completo desde iniciar fuentes
hasta disponer del borrador verificado: rural 44,78 s; técnicos 42,76 s. Incluye
el pequeño trabajo de guardar evidencia del ensayo entre etapas. No se instrumentó
ese mismo intervalo continuo en el intento 04 y no se presenta una suma como si
fuera una medición independiente.

La corrección rural intermedia tardó 15,05 s en fuentes y 17,57 s en redacción.
Tras revocar el permiso, el resultado sin respaldo tardó 8,80 s y el borrador de
pendientes 0,91 s; no es una mejora de rendimiento comparable a responder con
citas, porque el camino sin soportes no solicita redacción al modelo.

## Evidencia y reproducción

La evidencia local está en
`output/qa/rag-general-correcciones-20261116/nuevos/`:

- `validate_synthetic.py`: constructor del corpus y ejecución real aislada.
- `rubric-not-sent.json`, tres PDF e `inputs/`: originales y rúbrica separada.
- `attempts/attempt-01-initial`: primera pasada, incluido bloqueo de la Circular.
- `attempts/attempt-02-correct`: cambio de versión, invalidación y recálculo.
- `attempts/attempt-03-revoke`: revocación, ocultación del payload y recálculo.
- `attempts/attempt-04-final`: detectó la incompatibilidad de usos mixtos; el
  laboratorio queda correcto en esta pasada.
- `attempts/attempt-05-retry`: selección vacía por argumento de PowerShell sin
  comillas; no realizó llamadas a la API. Se añadió una aserción al harness.
- `attempts/attempt-06-retry`: rural y técnicos correctos tras arreglar el
  contrato mixto; conserva las huellas del código al iniciar el proceso.
- `audit_saved.py` y `audit-results.json`: verificación de los nueve resultados
  finales, 19 incisos, identidad de fuentes, citas, pendientes y cambios de estado.

Auditoría local, sin API:

```powershell
.\scripts\dev-python.ps1 output/qa/rag-general-correcciones-20261116/nuevos/audit_saved.py
```

Reintento de los dos expedientes afectados, sólo dentro del fixture y con llamadas
reales a la API:

```powershell
.\scripts\dev-python.ps1 output/qa/rag-general-correcciones-20261116/nuevos/validate_synthetic.py --phase retry --only 'NUEVO-RURAL,NUEVO-TECNICOS'
```

Esta muestra prueba comportamientos generales en documentos nuevos, pero no
garantiza que una IA nunca omita una condición. La comprobación de identificadores
obliga a declarar qué se contestó o falta; la suficiencia semántica, la aplicabilidad
y la aprobación final todavía requieren controles y revisión humana.

## Revisión final real, sin aprobación automática

Se ejecutaron `ReviewService` y `OpenAIReviewEngine` contra la API para una
pregunta de cada expediente, reutilizando los resultados aislados vigentes:

| Pregunta | Contenido revisado | Incisos | Tiempo del servicio |
| --- | --- | ---: | ---: |
| Rural P3 | Copia normativa y plazo corregido | 2 | 10,45 s |
| Técnicos P2 | Criterios, autoridad y falta de evaluación | 3 | 5,67 s |
| Laboratorio P2 | Incidente y contacto alternativo | 2 | 3,57 s |

Las tres respuestas estructuradas resultaron `passed`, con los siete incisos y
sus índices de párrafo válidos. La auditoría independiente confirmó que los
textos conservan los criterios, la norma correspondiente y las citas; no se
pidieron datos ya declarados en la introducción. La revisión dejó intactos los
párrafos y pendientes. La copia mantiene la entrega como tarea de cumplimiento
abierta y no bloqueante. Todos los expedientes conservan **cero aprobaciones**.

Se registró una llamada `review.assess` por pregunta. Estos tiempos sólo miden la
revisión final, no la búsqueda y redacción ni una mejora frente a master.
Los tres textos eran correctos; esta prueba no estima la tasa de detección de
omisiones ni sustituye una evaluación adversarial más amplia.

La evidencia y huellas del código están en `nuevos/review-api-01/`. El harness
`validate_review_api.py` usa únicamente la base ficticia y no llama a `approve`.
La auditoría `audit_review_api.py` verifica los resultados guardados sin API.
