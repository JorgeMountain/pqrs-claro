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
