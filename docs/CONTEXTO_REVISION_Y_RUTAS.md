# Consolidación de pendientes — 29 de septiembre de 2026

## Decisiones iniciales en la redacción

La planificación, redacción, comprobación y reparación reciben la clasificación
confirmada de la petición, sus notas y las observaciones generales de la revisión
inicial. Este contexto se identifica como una decisión humana, no como evidencia
documental: no se incorpora al catálogo de pasajes citables ni resuelve por sí solo
una falta de respaldo. La revisión humana vigente sigue siendo obligatoria.

La clave de reutilización contiene el contexto de cada petición. Cambiar la nota
o clasificación de P1 obliga a actualizar P1, pero permite conservar P2 cuando sus
entradas son idénticas. Cambiar una observación general afecta a ambas. Se normaliza
la ausencia de decisiones sobre hechos a una lista vacía para que la preparación
de solicitudes listas y la redacción completa compartan resultados equivalentes.

La versión de reglas de borradores pasa de 11 a 12. Los resultados anteriores se
conservan, pero pueden aparecer como pendientes de actualización. Esta migración
no vuelve a consultar IA por sí sola; la preparación debe iniciarse expresamente.

## Rutas alternativas

«Buscar fuentes y redactar» permanece deshabilitado si el documento o alguna
petición tiene una ruta alternativa. «Guardar ruta alternativa» conserva las
selecciones y no inicia la preparación. Para continuar hay que cambiar expresamente
las rutas correspondientes y volver a marcar la confirmación de revisión.

No se transforma silenciosamente una ruta especializada, de complemento o de
rechazo en una decisión de continuar. Guardar un borrador sigue sin confirmar ni
iniciar IA. «Seleccionar fuentes» permanece disponible.

## Diagnóstico de identificación

Los nuevos errores del proveedor distinguen autenticación, permisos, límite de uso
o cuota, tiempo agotado, conexión, indisponibilidad del proveedor y rechazo de la
solicitud. Se guarda proveedor, etapa, categoría, estado HTTP cuando existe,
posibilidad de reintento y fecha; la interfaz muestra una explicación en español.

No se guarda el mensaje crudo, cuerpo, cabeceras ni credenciales de la excepción.
Un reintento limpia el diagnóstico anterior. Los errores históricos genéricos no
permiten reconstruir retroactivamente una causa que no se registró.

## Validación y límites

Resultado final: 1.300 pruebas Python aprobadas en 816,83 segundos, 55 pruebas
JavaScript aprobadas, Ruff global y comprobación de diferencias sin incidencias.
Permanece una advertencia de deprecación de Starlette/AnyIO, sin pruebas fallidas.

- Regresión aislada del contexto en planificación, escritura y comprobación;
  invalidación por petición y por notas compartidas; separación de los pasajes citables.
- Regresión de códigos HTTP, conexión y tiempo agotado; persistencia y limpieza
  del diagnóstico; exclusión de contenido privado del error del proveedor.
- Navegador real con controlador de producción y dos peticiones ficticias:
  ruta mixta conservada, confirmación explícita y preparación interceptada.
  Anchos 320, 768, 1024 y 1440 sin desbordamiento horizontal ni errores JavaScript.
- Limpieza de las incidencias de Ruff sin desactivar reglas globales. Los imports
  de fixtures compartidas de pytest se conservan explícitamente.

Evidencia local de navegador: `output/playwright/review-context/result.json` y
capturas `routes-*.png`; ejecutor aislado: `output/qa_review_context.py`.
No se analizaron ni confirmaron expedientes reales para estas pruebas.

Activación local: servidor unificado reiniciado en el puerto 8772 después de
comprobar cero trabajos activos y respaldar las bases SQLite mediante su API de
backup. Los 52 expedientes mantienen exactamente los mismos cuerpos persistidos
(comparación SHA-256 antes/después); los módulos servidos coinciden con el código
actual. Evidencia local: `output/playwright/review-context/activation.json`.

Continúan pendientes para una operación institucional: autenticación y permisos
reales, borradores compartidos entre dispositivos y una política operativa de
copias y recuperación. El selector de gestores del piloto no sustituye autenticación.
