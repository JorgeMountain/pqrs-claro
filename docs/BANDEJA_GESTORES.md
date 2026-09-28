# Bandeja de expedientes y gestores del piloto

La entrada principal muestra Por asignar, Mis PQRS y Todas, además de la papelera existente. Cada tarjeta corresponde a un expediente completo. Las peticiones internas conservan su identificación, fuentes, revisión y respuesta dentro de ese expediente.

## Recepción e inicio

- La carga acepta hasta 20 PDF, cada uno con su propio asunto, radicado opcional y fecha límite manual. La fecha de recepción es común a la carga. Un archivo crea un expediente; no se agrupan documentos automáticamente por persona.
- Al recibir o importar desde Gmail se conserva el documento sin llamar al modelo. Vincular un correo al expediente existente conserva esa relación.
- Seleccionar un gestor y pulsar Tomar asigna el expediente. Iniciar gestión es una acción posterior que dispara el análisis de OpenAI ya configurado.
- Los errores de análisis mantienen el responsable y permiten continuar/reintentar. Los expedientes anteriores conservan su contenido y su avance; se pueden tomar sin reiniciar análisis ya hechos.

## Seguimiento

Las tarjetas muestran identificador interno (no radicado oficial), asunto, recepción, canal, responsable, estado de gestión, última actividad, fecha límite registrada y estado del análisis. Detalles y gestión permite editar recepción, asignar/reasignar, cambiar estado con motivo y consultar el historial. La fecha límite no se calcula mediante una regla legal.

La gestión es independiente de la identificación y no cambia sus versiones ni aprobaciones. Los estados Pendiente, Lista para revisión y Finalizada son registros manuales; no envían documentos ni sustituyen la revisión humana. Finalizar requiere explicar el resultado. Exportar un PDF no finaliza automáticamente un expediente.

El selector permite simular gestores locales y añadir nombres. No autentica usuarios ni proporciona separación de permisos. La asignación usa una revisión propia y una transacción SQLite para evitar que dos gestores tomen simultáneamente el mismo expediente.

## Datos y comprobaciones

Se añaden `managers`, `case_management` y `management_events` a la base de expedientes. No se migran documentos de las copias de desarrollo. La papelera conserva la gestión; el borrado definitivo también elimina esos registros.

Pruebas: recepción sin IA, asignación concurrente, inicio por responsable, historial, datos de recepción, versiones obsoletas, expedientes antiguos y papelera. Prueba visual con dos PDF ficticios, selector de gestor, inicio, Mis PQRS y cambio a pendiente; análisis simulado. Se comprobó que la bandeja no desbordara horizontalmente a 320, 768, 1024 y 1440 píxeles. Las pruebas no enviaron PQRS reales a OpenAI.

El respaldo previo se encuentra en `output/backups/bandeja-*/`, con sus bases y documentos. La evidencia `activation.json` en esa carpeta compara las tablas anteriores después del reinicio. El acceso habitual continúa siendo http://127.0.0.1:8772/.

## Actualización de fase 2 (28/09/2026)

Gmail conserva la recepción original del correo en Bogotá, con prioridad para correcciones manuales. La bandeja se actualiza mientras haya procesamiento y la última actividad incluye las demás etapas.

Finalizar exige que terminen los trabajos activos e impide nuevos análisis. La tarjeta ofrece Consultar. Para trabajar de nuevo, el gestor responsable abre Detalles y gestión, elige Cambiar estado y En gestión, e indica el motivo. La consulta y las descargas existentes permanecen disponibles.

La papelera compara también la revisión de gestión. Si otra pestaña tomó, reasignó o modificó el expediente, es necesario cancelar la confirmación antigua, actualizar la bandeja y revisar la acción de nuevo.
