# Fuentes y membrete de Drive

La revisión de **PQRS_Fuentes** incorporó las carpetas **Oficios anteriores**, **Normativa nacional** y **Normativa Universidad de Antioquia**. La carpeta **Membretes** aporta la plantilla del oficio. Los documentos generados por el sistema antiguo en la raíz no se incorporaron como respuestas institucionales verificadas.

## Organización de la biblioteca

La colección **Drive · Normativa y oficios anteriores** contiene once originales PDF: tres respuestas históricas, cinco normas nacionales y tres documentos normativos de la Universidad. Cada fuente conserva su SHA-256, carpeta, enlace de Drive y texto por página. Las respuestas anteriores se recuperan como antecedentes con citas; requieren contrastar hechos, período, alcance y soportes con la petición actual. Las normas mantienen vigencia por comprobar.

Se conservaron las 1.071 fuentes preexistentes con sus identificadores, originales, notas y revisiones intactos. Los nuevos archivos añaden 480 páginas y 1.022 fragmentos; el total del catálogo pasa a 1.082 originales. La colección ONMAN conserva la declaración anterior del usuario sobre la verificación de los archivos entregados. Esa declaración no se amplió automáticamente a los nuevos binarios de Drive.

La colección nueva quedó vinculada junto al archivo ONMAN en el expediente activo. Agregar fuentes cambia el conjunto consultable; el mapa anterior debe actualizarse antes de continuar con borradores y revisión. Para otros expedientes se elige la colección en **4. Fuentes → Antecedentes para consultar**. La biblioteca permite filtrar por colección y carpeta, abrir el original local y volver al archivo en Drive.

## Alcance del cotejo

Los once PDF se encontraron completos en el espejo local del proyecto anterior. Sus nombres, tamaños y fechas de modificación coinciden con el inventario consultado en Drive. Sus bytes coinciden con SHA-256 y MD5 registrados por ese espejo. Se comparó además el texto completo de los tres oficios con la lectura actual del conector: dos coinciden al normalizar espacios; el tercero presenta dos guiones extraídos como caracteres de control. No se obtuvo un checksum remoto nuevo. El cotejo de identidad no certifica emisión, contenido ni vigencia normativa.

La biblioteca actual lee los PDF conservando páginas y ubicaciones citables. Una prueba de recuperación local sobre su corpus completo encontró los tres oficios incorporados. No se ejecutó una nueva evaluación con IA sobre el expediente real durante esta incorporación.

## Importaciones posteriores

`scripts/import_drive_snapshot.py` recibe un inventario privado ya cotejado. Comprueba alcance, tipo, hash, tamaño y lectura de todos los originales antes de importarlos; guarda respaldo SQLite e inventario por lote en `data/imports/`. Repetir el mismo lote conserva los IDs, alias y revisiones. Agregar otro lote a esa colección recalcula sus totales sin sustituir las notas existentes. Si el mismo SHA ya pertenece a otra colección, exige conciliación explícita para evitar duplicarlo.

```powershell
.\scripts\dev-python.ps1 scripts/import_drive_snapshot.py <inventario-privado.json> --data-dir data
```

El manifiesto declara `collection` (id, título y descripción), `scope` (carpetas locales cotejadas), `verification_note` (contexto común) y `files`. Cada archivo aporta `local_original`, `sha256`, `title`, `drive_id`, `drive_url`, `drive_folder` y `category`; `notes` conserva aclaraciones específicas. No se aceptan instrucciones contenidas en los documentos como autorización de importación o revisión.

Esta operación es una incorporación puntual. La aplicación no tiene un sincronizador de Drive, no modifica sus carpetas y no altera permisos o documentos remotos.

## Plantilla activa

`data/templates/active.json` identifica el original local. Ejemplo de estructura, que debe completarse con el hash calculado sobre el DOCX autorizado:

```json
{
  "version": 1,
  "id": "udea-ingenieria-original",
  "name": "Membrete Facultad de Ingeniería",
  "filename": "membrete-ingenieria.docx",
  "sha256": "<SHA-256 de 64 caracteres>",
  "source_url": "https://docs.google.com/document/d/<identificador>/edit"
}
```

El original local de **MEMBRETE INGENIERIA.docx** coincide en nombre, tamaño, fecha UTC y texto del cuerpo con lo consultado en Drive; su encabezado y logotipo coinciden con los oficios anteriores entregados. Se conservaron copia inmutable y evidencia de procedencia local. Las dos adaptaciones en Google Docs quedan como referencias disponibles; la plantilla aplicada sigue el original DOCX.

El motor conserva las partes del paquete original, incluidas relaciones, estilos, encabezado y pie. Reemplaza únicamente el cuerpo y sanea los metadatos personales del documento nuevo. Los firmantes antiguos no se trasladan. La plantilla no es una fuente probatoria ni un fragmento para redactar respuestas: controla la presentación de la fase 7.

Los originales, la plantilla, los inventarios, las bases y la evidencia de QA son privados y permanecen fuera de Git. El repositorio conserva código, instrucciones y pruebas ficticias.
