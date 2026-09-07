# Validación de la entrega 1 — 7 de septiembre de 2026

## Código y persistencia

25 pruebas Python aprobadas en el runtime propio. Cubren lectura nativa, detección de OCR, límites, citas adulteradas, jerarquías, pausa y reanudación en SQLite real, edición humana, escritura obsoleta, protección entre orígenes y rutas del original/imagen. Ruff sin hallazgos y los tres módulos JavaScript pasan `node --check`.

Las pruebas automatizadas sustituyen OpenAI por dobles explícitos. Se observó un aviso de deprecación de `BlockingPortal` emitido por Starlette/AnyIO dentro del cliente de pruebas; no es un error de ejecución del proyecto.

## OpenAI real

Modelo configurado: `gpt-5.6-luna`. Se ejecutaron exclusivamente documentos ficticios. El caso reservado se ejecutó por separado después de las instrucciones iniciales.

| Caso | Observado | Resultado |
|---|---|---|
| Principal | 3 solicitudes en las páginas esperadas; fecha literal | Conforme |
| Subapartados | Padre, dos apartados en distintas páginas y otra solicitud | Conforme |
| Sin fecha | 1 solicitud; nombre y fecha ausentes | Conforme |
| Escaneado | 1 solicitud, OCR señalado y advertencia de revisión | Conforme |
| Sin solicitudes | Detención explícita; ninguna petición inventada | Conforme |
| Reservado | 2 solicitudes, referencias y fecha esperadas | Conforme |

Evidencia local: `output/qa/live-all.json` y `output/qa/live-reservado.json`. Los scripts registran cantidad, coincidencia de términos de la referencia humana en las citas, relaciones, fecha, método de extracción y duración. La fuente de cada cita se comprueba por código. Estas comprobaciones no sustituyen una evaluación semántica amplia ni prueban suficiencia jurídica.

## Aplicación en navegador

Se recorrió la aplicación real en `127.0.0.1:8770` con Playwright:

- Crear el ejemplo ficticio, completar el análisis con IA real y localizar la solicitud de acta en página 2.
- Editar el título de esa solicitud, guardar y recargar: versión y texto conservados.
- Detener y volver a iniciar únicamente el servidor nuevo: la revisión continuó en versión 6, con el título humano conservado. Después se confirmó desde la pantalla y llegó a versión 8.
- Cargar `sin_fecha.pdf` mediante el selector real de archivos, analizarlo, incorporar una solicitud manual con referencia de líneas y guardarla. Retirar luego esa incorporación de prueba y conservar nuevamente la única solicitud del ejemplo.
- Cambiar la solicitud seleccionada y verificar que el original se alinea con su página.
- Revisar consola y red: sin errores ni advertencias de consola; las solicitudes del recorrido respondieron correctamente.
- Inspeccionar 320, 768, 1024 y 1440 píxeles: sin desbordamiento horizontal. Inspección visual de las capturas de móvil y escritorio.
- Axe con reglas WCAG 2 A/AA y 2.1 AA: sin infracciones en la vista confirmada y la vista de revisión verificadas. Inspección de etiquetas, estructura y acceso por teclado. No equivale a una auditoría completa con lector de pantalla.

Capturas: `output/playwright/`. Los seis PDFs ficticios también se renderizaron e inspeccionaron en `output/qa/examples.png`, incluyendo todas sus páginas.

## Límites de esta evidencia

Esta es la primera entrega local. Se evaluaron seis escenarios ficticios y dos expedientes en el navegador; aún hace falta ampliar el conjunto con documentos representativos del trabajo real. El OCR requiere contraste con la imagen. No se validaron corpus normativos, redacción de respuestas, generación de oficios, Drive, correo ni funcionamiento multiusuario: corresponden a etapas posteriores.

## Fase 4 — 7 de septiembre de 2026

La suite completa tiene **63 pruebas aprobadas**. Las pruebas nuevas verifican citas exactas y secciones TXT/DOCX, PDF de 41 y 300 páginas y rechazo de 301, versiones originales, ámbito por expediente, revisión y vigencia, exclusión de oficios anteriores, referencias inventadas, documentos solicitados ausentes, recuperación de checkpoints y cambios de fuentes durante una búsqueda. Los errores por solicitud permiten reintentar sin repetir evaluaciones ya terminadas. Ruff y comprobación sintáctica JavaScript aprobados. Persiste únicamente el aviso externo de deprecación de Starlette/AnyIO descrito antes.

Se ejecutó OpenAI real con las tres solicitudes y dos fuentes **ficticias** del caso principal; se repitió después del ajuste que evita duplicar el pendiente documental. P1 recuperó la regla de procedimiento/requisitos; P2 recuperó fecha y estado del registro y conservó la necesidad de contrastar el estado actual con su fecha de corte; P3 mantuvo pendiente el acta completa y la verificación de su existencia. Ninguna norma sustituyó al acta. Las tres citas coinciden literalmente con las líneas conservadas, la versión y el expediente correspondientes.

Evidencia reproducible del resultado guardado: `output/qa/live-sources.json`. La comprobación de solo lectura se ejecuta con:

```powershell
.\scripts\dev-python.ps1 scripts/check_sources_live.py 2db7a4324374499b9ab488055e4c4442
```

En el navegador real se verificaron: acceso a biblioteca, selección por solicitud, carga TXT desde el selector, revisión atribuida, nueva versión, consulta de la versión anterior y conservación de su revisión. El listado principal muestra solamente la última versión. El ejemplo `sin_fecha` contiene una fuente ficticia de QA en dos versiones, restringida a ese expediente. No se incorporaron normas ficticias a la biblioteca general.

Se corrigió un desbordamiento de las cuatro etapas a 320 px. Sin desbordamiento horizontal en 320, 768 y 1440 px tras el ajuste. Axe WCAG 2 A/AA y 2.1 AA no encontró infracciones en la vista de resultados y el diálogo de historial inspeccionados; no equivale a una auditoría completa de accesibilidad. Capturas: `output/playwright/fase4-desktop-final.png`, `fase4-mobile-final.png` y `fase4-source-history.png`.

### Comprobación después del apagado informado

El servidor estaba detenido. Se reinició y las cuatro bases SQLite pasaron `PRAGMA quick_check`. Se conservaban identificaciones y resultados, pero faltaban dos originales: `sin_fecha` y la petición sobre el acta 2212. Se restauraron desde copias existentes **solo después de comprobar coincidencia SHA-256 exacta** con los registros. La segunda copia provenía del proyecto anterior, que no se modificó. La comprobación posterior confirmó los cuatro originales de expedientes y las cuatro versiones de fuentes presentes. También se restauró un script auxiliar generado cuyo contenido estaba ilegible.

Las escrituras de nuevos originales ahora ejecutan `flush` y `fsync` antes del registro en SQLite. Las rutas del original y de su imagen detectan archivos ausentes o alterados y explican que debe restaurarse la copia, sin borrar el expediente ni producir una imagen incorrecta. Esto mejora la persistencia y detección de fallos; no reemplaza un respaldo externo probado.

Esta fase está validada como piloto local con ejemplos controlados. Todavía no se ha medido recuperación sobre un corpus institucional representativo; no se ha implementado conector Drive/SharePoint, respaldo automático, búsqueda semántica, redacción o exportación de respuestas.

## Ampliación del archivo histórico

Suite completa: **103 pruebas aprobadas**; Ruff, sintaxis JavaScript y comprobación de diferencias sin errores. El único aviso es la deprecación externa de Starlette/AnyIO ya descrita. Axe no encontró infracciones en las vistas históricas de escritorio/móvil inspeccionadas; se corrigió el acceso por teclado al texto desplazable. Sin desbordamiento horizontal a 320 px.

Se incorporó el lote aportado por el usuario a una colección separada, conservando originales y procedencias. El inventario privado y sus conteos están en `data/imports/`, fuera de Git. La verificación posterior confirmó coincidencia SHA-256 de todos los originales importados y `PRAGMA quick_check` correcto. Los duplicados exactos mantienen sus alias; los archivos diferentes no se fusionaron por tener números o nombres parecidos.

La lectura de esta importación fue nativa, sin OCR ni llamadas a OpenAI. Hay documentos con texto disponible, lecturas parciales, documentos pendientes de OCR y formatos conservados sin índice. Esos estados se registran y se muestran. Los documentos históricos no se habilitan en la búsqueda hasta vincular explícitamente su colección al expediente.

Las pruebas nuevas cubren ámbito antes de enviar contenido al proveedor, antecedentes atribuidos, anexos documentales, borradores, verificación reportada frente a documentada, lecturas parciales, incorporación por SHA, conservación posterior de alias, descarga de formatos sin lector y actualización de resultados al vincular/desvincular colecciones. La revisión humana registra su alcance sin cambiar automáticamente un estado de emisión desconocido.

Tres búsquedas léxicas de solo lectura sobre el corpus importado localizaron los oficios esperados en dos consultas. En la consulta sobre un acta recuperaron menciones y comunicaciones relacionadas; eso no demuestra haber encontrado el acta. Cada consulta tardó aproximadamente seis segundos en este equipo. Se confirmó que, sin la colección autorizada en el alcance de la solicitud, no se devuelve ninguno de esos fragmentos. Este muestreo no mide exhaustividad ni valida respuestas sustantivas; la evidencia privada está en `data/imports/.../retrieval-check.json`.

El recorrido de navegador verificó paginación, filtros, radicados conflictivos, borradores, enlaces de original e imagen y selección de colecciones. La vinculación se probó únicamente en el ejemplo ficticio y se dejó desactivada al terminar. No se modificaron expedientes reales ni se solicitaron evaluaciones con IA sobre el lote durante la importación.

## Validación documental de fase 4 — 7 de septiembre de 2026

Se ejecutó el grafo real de fuentes sobre una copia aislada del catálogo y una referencia documental fijada antes de las llamadas al modelo. La muestra incluye 12 solicitudes: seis proceden de peticiones originales y seis de preguntas reproducidas o resumidas dentro de respuestas anteriores. La identificación de fases 1–3 no se volvió a ejecutar: el punto de partida fueron solicitudes preparadas y cotejadas documentalmente.

La última ejecución completa, con `analysis_version=6` y `gpt-5.6-luna`, hizo 12 llamadas nuevas. Los 12 resultados terminaron correctamente; se recuperaron los 14 grupos de fuentes esenciales definidos para esas solicitudes. Las 34 citas seleccionadas coincidieron literalmente con las líneas, versiones y categorías conservadas. Se seleccionaron fuentes de 11 de los 14 grupos esenciales: recuperar el archivo entre los candidatos no equivale a utilizar su pasaje correcto en el resultado.

La revisión documental adicional de Codex identificó **un defecto funcional bloqueante**: una solicitud declara ausente un oficio que sí estaba entre sus candidatos, omitiendo el contraste disponible. Otras tres solicitudes conservan cobertura incompleta de los antecedentes esperados: sus alternativas seleccionadas no sustituyen completamente el contenido previsto en la referencia. También quedaron observaciones de contexto temporal, alias internos visibles en algunas advertencias y una explicación contradictoria sobre una petición usada como antecedente. No se observaron afirmaciones que dieran por probadas autenticidad, entrega, destrucción o inexistencia. Esta observación acotada no garantiza que otros casos estén libres de errores. **Las comprobaciones técnicas terminaron; la fase no queda cerrada funcional ni institucionalmente sin reservas.**

Durante la validación se corrigieron recuperación de contestaciones frente a preguntas reproducidas, prioridad del archivo o correo solicitado, selección mediante identificadores cerrados, coherencia de roles y conservación de certificaciones expresamente pedidas. Los intentos anteriores y sus fallos permanecen archivados; los resultados finales no representan la tasa de éxito del primer intento. Hubo diez solicitudes de desarrollo y dos inicialmente reservadas dentro del mismo corpus. Las reservadas se observaron antes del último ajuste, por lo que la ejecución final no se presenta como evaluación sobre una reserva inédita ni como medida de generalización.

La suite completa terminó con **154 pruebas aprobadas**, Ruff y comprobación de diferencias sin errores. Se mantienen los límites de esas pruebas con dobles del proveedor; las llamadas reales anteriores se registran por separado. Persiste el aviso externo de deprecación ya descrito.

Los 12 resultados conservaron sus referencias, identificadores de ejecución y huellas de entrada al reabrir SQLite y después de reiniciar el servidor QA. Desvincular la colección o cambiar temporalmente metadatos de revisión marcó los resultados desactualizados; restaurar las entradas exactas restituyó su correspondencia, sin una llamada nueva al modelo. Los hashes lógicos de las tablas de expedientes y biblioteca de trabajo coinciden antes y después de las pruebas y del reinicio del servidor principal.

Se comprobó la presentación de faltantes, cita y original en navegador con los resultados QA. Se inspeccionaron escritorio y móvil a 320 px sin desbordamiento horizontal. Tras la última ejecución se abrió además la cita de página 6 de un PDF seleccionado, con imagen original cargada. No se repitió una auditoría completa de accesibilidad ni el recorrido de identificación. Un PDF escaneado de una página se leyó mediante OCR real y se contrastó visualmente; su resultado quedó como control separado, sin indexar ni aprobar el documento en el catálogo.

Los artefactos privados están en `output/validation-f4/`, fuera de Git: `INFORME.md`, `REVISION-INSTITUCIONAL.md`, referencia congelada, llamadas/resultados por intento, `semantic-final.json`, `restart-check.json`, `metadata-staleness.json` y comprobaciones de las bases de trabajo. La aprobación de fuentes concretas, su aplicabilidad y las certificaciones institucionales siguen pendientes. Tampoco se validaron redacción, exportación, respuesta oficial, conexión externa o restauración desde respaldo externo.

## Fase 5 — 7 de septiembre de 2026

Se implementó el grafo **planificar → redactar → comprobar**, con resultados incrementales por solicitud, citas por párrafo, pendientes visibles, historial, reintento y detección de entradas desactualizadas. La suite completa terminó con **238 pruebas aprobadas**. Ruff y análisis sintáctico de los cuatro módulos JavaScript afectados mediante Prettier terminaron sin errores. Persiste el aviso externo de Starlette/AnyIO descrito antes. Las pruebas automatizadas usan dobles del proveedor; las ejecuciones reales siguientes se registran por separado.

### Corrección de fuentes y verificación informada

La evaluación de fuentes, ahora versión 7, conserva los archivos candidatos no seleccionados para cotejo y reconcilia una propuesta de ausencia cuando el archivo nombrado ya está localizado. La interfaz abre esos documentos desde el pendiente o desde la lista de otros candidatos. La reproducción determinista sobre V04/V05/V11/V12 conservó los soportes seleccionados; en V05 corrigió el falso faltante del oficio 1436. Esto no demuestra cobertura completa en las otras tres solicitudes ni convierte candidatos en citas de respaldo.

Se conserva la verificación previa informada por el usuario sobre la colección histórica, atribuida a la comunicación de la persona que entregó los archivos. Se comprueba la aplicabilidad a la nueva solicitud sin imponer una revisión completa automática. También se distingue el archivo que contiene un texto de la autoría de ese pasaje: un correo puede reproducir alegaciones del peticionario.

### Ejecución real y revisión del contenido

Se fijó `output/validation-f5/reference.json` antes de las llamadas: **tres solicitudes ficticias y dos históricas**, en tres expedientes QA aislados. Una histórica procede de una pregunta reproducida en una contestación y la otra, de una petición original. No se volvió a ejecutar la identificación. Son casos conocidos usados como regresión; no constituyen una reserva inédita ni una medición amplia de precisión.

Se ejecutaron cinco evaluaciones de fuentes y dos intentos completos de borradores con `gpt-5.6-luna`. Se conservan 35 registros de etapas: cinco de fuentes y treinta de planificación/redacción/comprobación; el registro no cuenta por separado posibles reintentos de transporte del SDK. El segundo intento usó las fuentes guardadas y `draft_version=2`. Las cinco solicitudes terminaron sin error de ejecución y generaron **12 párrafos con 12 referencias**, cotejadas exactamente contra el catálogo QA. Los tres expedientes quedaron `partial`, por pendientes documentales o ajustes. La comprobación automática pasó tres solicitudes y señaló cambios en las dos históricas; ese resultado no equivale a aprobación semántica.

En el ejemplo ficticio se conservaron procedimiento y requisitos, recepción y estado con su fecha de corte; el acta sigue pendiente sin afirmar entrega ni inexistencia. V05 conserva el alcance 2015-1, distingue el mismo oficio de sus fragmentos y trata el oficio 1436 como localizado para cotejo. El comprobador señala una formulación imprecisa sobre alcance documental y fecha/actuación en otro párrafo histórico. V11 atribuye el contenido al texto aportado dentro del correo y conserva la aclaración de autoría; no lo convierte en verificación institucional. Persisten pendientes solapados y dos alertas locales de atribución demasiado restrictivas, que requieren valoración humana. **La fase está disponible como preparación de borradores con observaciones, no como generación autónoma de respuestas aprobadas.**

El primer intento, sus fallos y su revisión están conservados en `baseline-v1/` y `attempts/`. Los cambios posteriores corrigieron referencias de año con guion bajo, referencias bibliográficas materializadas por Python y reglas de identidad documental/autoría. La revisión final está en `semantic-review.json` y `.md`; no debe confundirse con la revisión del primer intento.

### Persistencia, interfaz y aplicación de trabajo

Los cinco resultados, huellas e identificadores de ejecución fueron idénticos tras reiniciar el servidor QA. Repetir la solicitud de preparación devolvió los mismos resultados sin invocar nuevamente al motor registrado. Las ocho tablas de expedientes y biblioteca de trabajo mantuvieron sus hashes lógicos y `quick_check=ok`, también después de reiniciar la aplicación principal en `127.0.0.1:8770`. Las nuevas rutas de borradores están disponibles; no se generaron borradores sobre expedientes vivos durante esta evaluación.

En navegador se comprobó selección por teclado, pendientes antes del texto, apertura del fragmento y original, cierre de diálogo con Escape y devolución del foco a la cita. El enlace del pendiente de V05 abrió el oficio 1436 y su imagen de página 1. Se inspeccionaron capturas de móvil y escritorio; no hubo desbordamiento horizontal en 320, 768, 1024 y 1440 px. Axe WCAG 2 A/AA y 2.1 AA no encontró infracciones en la vista de borrador con pendientes examinada a esos anchos. No equivale a una auditoría completa con lector de pantalla. Se corrigieron dos errores sintácticos de interfaz durante el desarrollo; la recarga final y el recorrido comprobado no registraron errores de página.

Evidencia privada: `output/validation-f5/INFORME.md`, referencia, llamadas por intento, resultados, revisión semántica, `restart-cache.json`, `live-integrity.json`, registros de navegador y capturas en `output/playwright/fase5-*`. La edición humana y aprobación corresponden a fase 6; exportación y oficio final, a fase 7. Continúan pendientes la ampliación representativa de la evaluación y la resolución de coberturas documentales ya señaladas en fase 4.
