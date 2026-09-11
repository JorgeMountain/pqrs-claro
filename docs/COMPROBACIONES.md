# Comprobaciones y estados de las fuentes

La búsqueda, el borrador y la revisión usan la misma pregunta, incluidos sus padres,
hijos y referencias a otros numerales. Encontrar un respaldo no aprueba la respuesta.

El [criterio de suficiencia](SUFICIENCIA.md) precisa cuándo los pasajes permiten responder
con atribución sin reabrir comprobaciones genéricas por metadatos del catálogo. Una
brecha concreta conserva su bloqueo; una advertencia administrativa ajena al alcance
de lo respondido no se convierte en evidencia faltante.

Los controles sobre negaciones, periodos, atribución y precisión de las citas, junto
con el ajuste acotado de borradores nuevos, se explican en [Calidad de borradores](CALIDAD_BORRADORES.md).

## Qué cambia en el segundo bloque

1. **Entender lo pedido.** Se distingue consultar información, entregar un documento
   existente y realizar una actuación. Preguntar quién expidió un certificado no pide
   expedir uno nuevo. La firma y el envío de la respuesta que se está preparando son
   tareas posteriores; no se exigen como prueba para redactar esa misma respuesta.
2. **Precisar lo pendiente.** Cada comprobación tiene una clave estable, motivo,
   documentos/versiones, alcance y preguntas afectadas. Los controles comunes de un
   mismo archivo se muestran una vez, conservando su aplicación por pregunta.
   Al redactar, el modelo referencia esas claves en vez de crear otra tarea con una
   paráfrasis. Un pendiente adicional debe explicar qué diferencia concreta quedó
   sin cubrir; no puede cambiar la etapa ni reabrir una comprobación por repetirla.
3. **Conservar las comprobaciones.** El sistema registra el hecho, pasaje original,
   documento/versión, soporte y atribución disponibles. Una declaración extraída de un
   oficio se identifica como tal; no se transforma en una revisión humana.
4. **Reutilizar con alcance.** Una persona puede registrar cómo comprobó un hecho o
   justificar por qué una comprobación anterior aplica a preguntas concretas. La
   aplicación no aprueba el borrador. Si cambia la pregunta, contexto o fuente,
   la aplicación afectada deja de cerrar el pendiente.

## Qué muestran los estados

| Estado | Significado |
| --- | --- |
| Respaldo encontrado | Hay un pasaje seleccionado que puede sustentar contenido, con su atribución y límites. |
| Confirmación pendiente | Falta una comprobación concreta o completar una búsqueda acotada. |
| Documento faltante | La búsqueda acotada no localizó el archivo en el ámbito consultado; no certifica inexistencia institucional. |
| Error de análisis | Hubo un problema de lectura, extracción o evaluación. Un archivo conservado sin texto no se presenta como ausente. |

Los estados pueden coexistir. Una pregunta con respaldo y una confirmación pendiente
muestra ambos. Las tareas posteriores de preparación y entrega se presentan aparte.

## Dónde se conserva

- `data/biblioteca.sqlite`: fuentes, fragmentos, versiones y resultados de búsqueda.
- `data/comprobaciones.sqlite`: comprobaciones atribuidas, aplicaciones por pregunta y
  revocaciones con historial. Los registros son acumulativos; retirar uno conserva su historia.
- Las bases de borradores y revisión mantienen las claves y el alcance de los pendientes.
- Los originales se conservan en la biblioteca; las citas se cotejan con sus líneas y bytes.

Una confirmación humana puede ser escrita sin adjuntar otro archivo cuando se trate de
un hecho concreto, indicando responsable y cómo lo conoce. Esto no sustituye un archivo
solicitado, una lectura fallida ni los controles documentales de versión o procedencia.

## Cómo comprobar el cambio sin alterar un expediente

`scripts/validate_pending_workflow.py` prepara una copia aislada, conserva las huellas de
las bases vivas y compara por pregunta los respaldos, pendientes y errores. Permite
ejecutar fuentes, borradores y evaluación de revisión con IA. No aprueba, firma ni envía.
Los resultados privados permanecen en `output/qa/`, fuera de Git.

`node --experimental-vm-modules scripts/check_review_approval.mjs` comprueba el
formulario de aprobación con los módulos reales: una actuación posterior abierta
no bloquea el contenido, pero evidencia abierta, cambios sin guardar o una evaluación
fallida sí lo bloquean. La prueba no ejecuta eventos ni registra aprobaciones.

Antes de aplicar los resultados a un expediente real se revisan los párrafos y sus citas,
incluyendo respuestas que antes funcionaban, diferencias de periodo y atribución, archivos
presentes sin lectura y actuaciones futuras. Las comprobaciones registradas durante una
prueba no se atribuyen a funcionarios ni constituyen aprobación institucional.

Este bloque no conecta OnBase. Un catálogo local o el acceso limitado de una cuenta no
equivale a consultar toda la documentación institucional.
