# Validación de la entrega del repositorio

Revisión local del 26 de octubre de 2026 para compartir el código con otra persona.
La instalación y el flujo actual se describen en [ENTREGA.md](ENTREGA.md).

## Comprobaciones realizadas

| Comprobación | Resultado |
| --- | --- |
| Pruebas JavaScript (`tests/test_*.mjs`) | 209 correctas |
| Barrido completo Python al comenzar | 1.562 correctas; 2 expectativas antiguas detectadas |
| Repetición de los módulos FIAGA y piloto tras actualizar esas expectativas | Correcta; se conserva la invalidación de respuestas y oficio |
| Pruebas nuevas de arranque sin `output/` y conservación de una demo local | 2 correctas |
| Módulos de aplicación unificada y metadatos/redacción de errores | Correctos en las repeticiones focalizadas |
| Ruff sobre `src`, `tests` y `scripts` | Correcto |
| Comprobación de espacios de Git sobre cada commit | Correcta |
| Enlaces locales de README, CONTRIBUTING, índice y guía de entrega | Correctos |
| Revisión de secretos sobre candidatos y archivos preparados para cada commit | Sin claves configuradas ni coincidencias pendientes de patrones de credenciales |

El conjunto original tenía 1.564 casos Python. Los dos fallos iniciales pedían que
un cambio en la biblioteca invalidara la identificación, comportamiento anterior
a su separación de la búsqueda de fuentes. Se actualizaron y volvieron a ejecutar:

- FIAGA conserva la clasificación ante una fuente nueva, pero sigue rechazando
  la aprobación y descarga de un oficio cuyo respaldo quedó desactualizado.
- El piloto provoca ahora una identificación obsoleta cambiando su propia entrada;
  comprueba que la excepción explícita no aprueba el análisis y que puede revocarse.

Al combinar el barrido inicial, las repeticiones corregidas y las dos pruebas de
copia limpia, se verificaron los 1.566 casos Python actuales. No se hizo un segundo
barrido completo después de las correcciones focalizadas. Starlette emitió una
advertencia de deprecación sobre un alias de AnyIO utilizado por TestClient.

## Copia limpia y límites

Se materializó una copia desde el índice de Git, sin `.env.local` ni el `output/`
del desarrollador. En un proceso Python separado se importó el código de esa copia
y se comprobó con TestClient que sirven el HTML, los módulos, el CSS, el logo y el
snapshot mínimo. La API devolvió expedientes y biblioteca vacíos y modo unificado.

Se reutilizaron las dependencias ya instaladas para esta comprobación; no se
repitió la descarga del entorno en otro equipo. Tampoco se ejecutaron llamadas
reales de IA, conexiones Gmail, descargas del modelo semántico o conversión con
Word. Los documentos de trabajo, bases, exportaciones, temporales y credenciales
locales permanecen excluidos de Git.

La evidencia de ejecución local se conserva en `output/qa/handoff-20261026/`,
fuera de la entrega del código.
