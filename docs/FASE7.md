# Fase 7 · Generar el oficio desde lo aprobado

Esta fase convierte las respuestas revisadas en un oficio editable en Word y su copia en PDF. Toma la versión aprobada en la fase 6, conserva sus párrafos y fuentes, y permite preparar los anexos que se acompañarán al documento.

La generación no vuelve a consultar a la IA ni reescribe la respuesta. Tampoco firma, radica, envía o acredita la entrega del oficio.

## El recorrido en la página

1. Terminar **6. Revisar y aprobar**: todas las respuestas deben tener una aprobación vigente. Los cambios y aportes locales pendientes deben guardarse y pasar por la revisión correspondiente, o descartarse expresamente.
2. Pulsar **Continuar a generar oficio** o abrir **7. Generar oficio**. Si falta una aprobación, la pantalla indica qué solicitud requiere atención.
3. Comprobar el **membrete activo** y completar ciudad, fecha del oficio, destinatario, asunto y nombre y cargo de quien suscribe. Con el membrete institucional configurado, institución y dependencia quedan fijadas como Universidad de Antioquia y Facultad de Ingeniería. El asunto y destinatario identificados se proponen para revisar; la fecha se inicia con el día local del equipo y puede corregirse. El contacto y los números de oficio y petición son opcionales. Los nombres de quienes preparan y suscriben quedan vacíos para diligenciarlos.
4. Indicar quién prepara el documento y elegir los anexos que se incluirán. Solo se ofrecen originales citados por las respuestas aprobadas; no se adjunta automáticamente toda la biblioteca.
5. Pulsar **Preparar vista previa** y comprobar los datos, las respuestas, sus referencias y los anexos elegidos.
6. Pulsar **Generar Word y PDF**. El sistema crea el Word, lo convierte a PDF y comprueba el contenido antes de habilitar las descargas.
7. Revisar las páginas del PDF y descargar Word, PDF o el paquete con ambos archivos y los anexos seleccionados.

El nombre de quien aprobó una respuesta no se usa automáticamente como firmante. El formulario registra los datos del bloque de firma, pero no inserta una firma manuscrita o digital.

## Membrete institucional

El piloto utiliza el DOCX original de la carpeta **Membretes** de Drive, cotejado con los oficios anteriores. Conserva su logotipo, encabezado, pie, tamaño de papel y márgenes. Se reemplaza todo el cuerpo del modelo, incluidos los nombres de sus firmantes antiguos. El documento nuevo contiene exclusivamente los datos expresos del formulario, las solicitudes, las respuestas aprobadas y sus referencias y anexos.

La plantilla original y su registro viven en `data/templates/`, fuera de Git. La vista previa muestra su nombre y enlace a Drive; el manifiesto conserva su identidad y SHA-256. Cambiar el membrete exige nueva vista previa y generación. Un archivo de plantilla ausente, alterado o incompatible bloquea la operación con una explicación. La instalación sin registro de plantilla mantiene el formato neutral original; una configuración inválida nunca cae silenciosamente en ese formato.

La conversión comprueba tanto el contenido aprobado como las partes institucionales. La configuración y su procedencia se explican en [DRIVE.md](DRIVE.md).

## Qué se conserva

El oficio sigue el membrete y el estilo de los antecedentes 00995, 00949 y 00988: identificación, saludo e introducción breve, antecedentes cuando existan, respuestas por numeral y literal, conclusión cuando esté revisada, cierre y anexos realmente incluidos. La fecha de recepción es opcional y se incorpora solo si la persona la confirma; no se deduce de la fecha del documento ni de su carga al sistema.

En la revisión, cada párrafo permite elegir **Respuesta al numeral**, **Antecedentes compartidos** o **Conclusión**. Su ubicación entra en la misma evaluación y aprobación que el texto y las citas. Cada numeral debe conservar al menos una respuesta concreta. Las versiones antiguas, sin esa selección, mantienen sus párrafos como respuesta; guardar esa misma opción no retira su aprobación.

El armado es determinista. Solo reúne antecedentes con texto y referencias exactamente iguales, indica a qué numerales corresponden y conserva todos sus marcadores de trazabilidad. Las respuestas y conclusiones no se resumen ni se reescriben al exportar. La numeración conserva los rótulos originales; las citas de la petición se reconstruyen por página y línea para evitar duplicar solapamientos, y los fragmentos discontinuos se presentan separados. Las descripciones identificadas sirven de respaldo para expedientes antiguos sin citas originales.

La vista previa consume la misma secuencia de bloques que Word/PDF. Los soportes, versiones, ubicaciones y vínculos por párrafo se conservan dentro del expediente y del modelo canónico. El oficio entregable no imprime marcas bibliográficas numeradas, una sección de referencias ni etiquetas técnicas de alcance o de página/línea. Las menciones naturales a oficios o normas se mantienen cuando forman parte de la respuesta revisada; un antecedente no se presenta automáticamente como una comprobación nueva. El generador tampoco añade una conclusión administrativa, firma o declaración de entrega por sí mismo.

La transcripción de lo solicitado seguida de «Respuesta» toma como referencia el Oficio00995 (por ejemplo, página9). Otros ejemplos, como el Oficio00949, también sintetizan numerales dentro de la prosa. Es una pauta de presentación, no una obligación de repetir la petición completa en todos los tipos de oficio.

El oficio no incluye las discusiones internas sobre pendientes, los hallazgos del evaluador ni las notas de aprobación. La aplicación conserva esa trazabilidad y las huellas del contenido en el expediente local. Los nombres de archivos internos, rutas de este computador y códigos técnicos no se incorporan como citas del documento.

Los anexos mantienen los bytes del original conservado. El paquete usa nombres seguros y evita sobrescribir dos archivos con nombres iguales. Preparar ese paquete no demuestra que se haya entregado al peticionario.

## Qué ocurre si cambia algo

**Si cambian los datos del oficio**, se prepara una nueva vista previa y una nueva versión del documento. Esto no altera las respuestas aprobadas ni exige otra evaluación semántica por un cambio de ciudad, fecha o número de oficio. La versión guardada con los datos anteriores sigue identificada como tal y se puede descargar mientras sus respuestas y archivos permanezcan vigentes.

**Si cambia una respuesta, cita, aporte o fuente**, se vuelve a la fase 6. El oficio anterior permanece registrado con sus descargas bloqueadas. Después de comprobar y aprobar las respuestas, se genera una nueva versión del oficio. Los cambios locales de revisión sin guardar también bloquean la generación y descarga desde la pantalla.

**Si se interrumpe la generación**, se puede volver a pulsar **Generar Word y PDF**; si se recargó la página, primero se prepara otra vez la vista previa con los datos conservados. No se presenta un archivo incompleto como listo. Si se pide de nuevo exactamente la misma versión ya generada y sus archivos siguen íntegros, se reutilizan esos archivos.

Los datos del formulario se conservan temporalmente por expediente en la pestaña del navegador. No equivalen a una copia de seguridad externa.

## Cómo funciona detrás

```mermaid
flowchart LR
    A[Respuestas aprobadas en fase 6] --> B[Datos y vista previa del oficio]
    B --> C[Crear Word con el texto literal]
    C --> D[Convertir ese Word a PDF]
    D --> E[Comprobar texto y archivos]
    E --> F[Vista por páginas y descargas]
    A --> G[Huella de la versión aprobada]
    G --> E
```

**LangGraph** conserva las decisiones de revisión y aprobación de la fase 6. El generador consume esas copias aprobadas; no continúa una evaluación con IA ni decide si la respuesta es suficiente.

**Python** arma el documento, añade los datos de salida y referencias, verifica el texto y las huellas y prepara el paquete. El PDF se obtiene del mismo Word para mantener la presentación de ambos formatos.

**Word de escritorio**, en este equipo Windows, realiza la conversión en una instancia oculta e independiente. La aplicación informa si ese conversor no está disponible o falla. No sustituye el PDF con una simulación ni envía documentos a un servicio de conversión externo.

**La persona** revisa los datos del oficio y las páginas generadas antes de usarlos. La aprobación local, el bloque de firmante y la entrega institucional son actos diferentes.

## Archivos del proyecto

| Archivo | Responsabilidad |
|---|---|
| `office_models.py` | Datos permitidos para el oficio y la generación |
| `office_renderer.py` | Contenido canónico, Word y comprobación del PDF |
| `office_structure.py` | Reconstrucción literal de fragmentos por página y línea |
| `office_templates.py` | Registro, lectura y preservación del membrete local |
| `office_word.py` | Conversión local de Word a PDF |
| `office_service.py` | Versiones, vigencia, anexos y descargas |
| `office_store.py` | Registro persistente de generaciones |
| `office_api.py` | Rutas que utiliza la pantalla |
| `static/office*.js` | Formulario, vista previa y documentos descargables |

`data/oficios.sqlite` registra las generaciones. `data/oficios/` conserva los archivos, metadatos y trazabilidad. Ambas ubicaciones están fuera de Git. La verificación y los límites observados se documentan en [VALIDACION.md](VALIDACION.md).

## Límites de esta entrega

La conversión disponible requiere Windows y Word de escritorio. El piloto mantiene identidades declaradas, almacenamiento local y un solo proceso de aplicación. No incorpora firma electrónica, radicación, correo, entrega automática ni respaldo externo.

Se aplican límites explícitos de tamaño, cantidad de anexos y páginas. Si el contenido los supera o no se puede conservar fielmente, la generación falla con una explicación; no se recortan párrafos para producir un documento aparentemente completo.
