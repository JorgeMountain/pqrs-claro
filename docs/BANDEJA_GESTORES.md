# Bandeja de expedientes y gestores del piloto

La entrada principal abre **Mi trabajo**. Desde el menú se puede consultar el **Pool del equipo**, los pendientes, los borradores y los expedientes finalizados. Cada fila corresponde a un expediente completo. Las peticiones internas conservan su identificación, fuentes, revisión y respuesta dentro de ese expediente.

## Recepción e inicio

- La carga acepta hasta 20 PDF, cada uno con su propio asunto, radicado opcional y fecha límite manual. La fecha de recepción es común a la carga. Un archivo crea un expediente; no se agrupan documentos automáticamente por persona.
- Al recibir o importar desde Gmail se conserva el documento sin llamar al modelo. Vincular un correo al expediente existente conserva esa relación.
- En **Nuevo expediente** o **Subir documento**, selecciona el archivo y elige el destino. **Agregar al pool** guarda hasta 20 PDF sin asignar. **Iniciar análisis** recibe un PDF, lo asigna al gestor activo y abre el preanálisis. Después de revisar el original, el gestor confirma cuándo comenzar la identificación. Los correos y sus PDF adjuntos ofrecen la misma elección al incorporarlos.
- Los errores de análisis mantienen el responsable y permiten continuar/reintentar. Los expedientes anteriores conservan su contenido y su avance; se pueden tomar sin reiniciar análisis ya hechos.

## Seguimiento

La barra de **Estado y avance** sigue el mismo orden y los mismos colores que el expediente. **Preanálisis** usa verde claro, **Identificación** verde oscuro, **Redacción** azul y **Borrador** morado. El color sólido indica avance guardado, las rayas sobre el color señalan la etapa actual y el gris indica una etapa pendiente o sin avance guardado. La etiqueta morada «Por revisar» o «Por actualizar» indica que el gestor tiene una revisión pendiente.

Al asignar el expediente, el primer tramo aparece en verde claro con rayas diagonales mientras el preanálisis está por realizar, en curso o pendiente de confirmación. Las otras tres etapas aparecen en gris.

En **Seguimiento del expediente** puedes consultar el estado de cada tramo. Si ya hay peticiones identificadas y falta la ficha de preanálisis, el primer tramo aparece en verde claro con la indicación «Análisis anterior guardado · sin ficha de preanálisis». Si hubo cambios después de generar el oficio, Borrador aparece en morado con rayas hasta que se actualice la versión.

Las tarjetas muestran identificador interno (no radicado oficial), asunto, recepción, canal, responsable, estado de gestión, última actividad, fecha límite registrada y estado del análisis. Detalles y gestión permite editar recepción, asignar/reasignar, cambiar estado con motivo y consultar el historial. La fecha límite no se calcula mediante una regla legal.

La gestión es independiente de la identificación y no cambia sus versiones ni aprobaciones. Los estados Pendiente, Lista para revisión y Finalizada son registros manuales; no envían documentos ni sustituyen la revisión humana. Finalizar requiere explicar el resultado. Exportar un PDF no finaliza automáticamente un expediente.

El selector permite simular gestores locales y añadir nombres. No autentica usuarios ni proporciona separación de permisos. La asignación usa una revisión propia y una transacción SQLite para evitar que dos gestores tomen simultáneamente el mismo expediente.

## Tiempos de gestión

Abre **Tiempos de gestión** en el menú lateral. **Por expediente** muestra la duración de cada PQRS, la espera en el pool y el tiempo activo estimado. Despliega el número del expediente para consultar las fechas, las reasignaciones, los días u horas en estado pendiente, el desglose por gestor y los motivos del trabajo externo. **Por gestor** reúne sus expedientes, los que tienen medición, cuántos finalizó y la mediana desde el alta hasta el cierre de los que finalizó. El periodo se elige por fecha de alta en Bogotá. **Descargar CSV** exporta todas las filas de la vista filtrada con las duraciones en segundos.

| Medida | Cómo se registra |
| --- | --- |
| Tiempo total | Tiempo calendario desde el alta en el sistema hasta el último cierre. En un expediente abierto, incluida una reapertura, llega hasta la hora de consulta. El alta corresponde a la creación del expediente en el sistema. |
| Espera en el pool | Intervalos documentados en estado recibido sin gestor asignado. El tiempo pendiente se calcula por separado a partir de los cambios de estado. |
| Activo estimado | Se activa automáticamente cuando el gestor seleccionado abre un expediente propio y trabaja en él en primer plano. Al salir a la bandeja, cambiar de pestaña o perder el foco, se detiene. El servidor cuenta una sola sesión por gestor entre todas sus pestañas. |
| Sin confirmar | Después de dos minutos sin interacción, aparece una pregunta. Los intervalos posteriores con la vista abierta quedan sin confirmar hasta que el gestor confirme que sigue trabajando. La confirmación reanuda la estimación desde ese momento. |
| Trabajo externo declarado | En el expediente, **Registrar trabajo externo** permite anotar por separado los minutos y el motivo de una llamada, consulta u otra actividad fuera de la pantalla. |

Por ejemplo, si una PQRS permanece cuatro horas abierta y dos gestores le dedican 15 y 20 minutos en pantalla, el informe muestra cuatro horas de duración y 35 minutos activos estimados. Reasignar conserva lo registrado a nombre de cada persona. El lector de IA y la generación de documentos pueden trabajar en paralelo a una sesión. Sus duraciones técnicas se consultan por separado.

La estimación usa la hora del servidor y señales periódicas de la vista. Un intervalo de más de 45 segundos sin comunicación queda fuera del cálculo. Para lecturas en otra pestaña (por ejemplo, el PDF original abierto por separado) se puede declarar el trabajo externo. Un expediente sin sesiones muestra **Sin medición**. Uno anterior a la instalación con sesiones posteriores muestra **Medición parcial**. Si el historial carece de las transiciones necesarias, el campo correspondiente muestra **Sin historial**. El informe excluye la papelera y vuelve a incluir el expediente si se restaura.

Desde la raíz del proyecto, ejecuta estas comprobaciones en PowerShell. La segunda abre Chrome mediante Playwright y usa expedientes ficticios.

```powershell
.\scripts\dev-python.ps1 -PythonArgs @('-m', 'pytest', 'tests/test_work_sessions.py', 'tests/test_management_times.py', '-q')
.\scripts\dev-python.ps1 -PythonArgs @('-m', 'pytest', 'tests/check_management_times_browser.py', '-q')
```

## Datos y comprobaciones

Se añaden `managers`, `case_management` y `management_events` a la base de expedientes. No se migran documentos de las copias de desarrollo. La papelera conserva la gestión; el borrado definitivo también elimina esos registros.

Pruebas: recepción sin IA, asignación concurrente, inicio por responsable, historial, datos de recepción, versiones obsoletas, expedientes antiguos y papelera. Prueba visual con dos PDF ficticios, selector de gestor, inicio, Mis PQRS y cambio a pendiente; análisis simulado. Se comprobó que la bandeja no desbordara horizontalmente a 320, 768, 1024 y 1440 píxeles. Las pruebas no enviaron PQRS reales a OpenAI.

El respaldo previo se encuentra en `output/backups/bandeja-*/`, con sus bases y documentos. La evidencia `activation.json` en esa carpeta compara las tablas anteriores después del reinicio. El acceso habitual continúa siendo http://127.0.0.1:8772/.

## Actualización de fase 2 (28/09/2026)

Gmail conserva la recepción original del correo en Bogotá, con prioridad para correcciones manuales. La bandeja se actualiza mientras haya procesamiento y la última actividad incluye las demás etapas.

Finalizar exige que terminen los trabajos activos e impide nuevos análisis. La tarjeta ofrece Consultar. Para trabajar de nuevo, el gestor responsable abre Detalles y gestión, elige Cambiar estado y En gestión, e indica el motivo. La consulta y las descargas existentes permanecen disponibles.

La papelera compara también la revisión de gestión. Si otra pestaña tomó, reasignó o modificó el expediente, es necesario cancelar la confirmación antigua, actualizar la bandeja y revisar la acción de nuevo.
