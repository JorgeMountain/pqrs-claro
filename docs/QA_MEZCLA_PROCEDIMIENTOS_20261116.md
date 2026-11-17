# Comprobación de reglas de procedimientos distintos

Se reforzó únicamente la comprobación de borradores y de revisiones guardadas. La
instrucción compartida `PROCEDURE_SCOPE_CHECK_GUIDANCE` exige relacionar cada regla
con su objeto, supuesto, etapa, población, autoridad y efecto. Dos citas literales
del mismo documento no permiten combinar trámites por compartir vocabulario.

El comprobador debe señalar `procedure_scope_mixing` con el párrafo y la
transferencia concreta. Una comparación correctamente delimitada o una explicación
de por qué otra regla no aplica no debe bloquearse. Se conservan los controles de
vigencia, procedencia, permisos y cobertura. No se cambió el lector de fuentes ni
se reescribieron textos como parte de esta verificación.

## Evidencia API aislada

Se hicieron cinco comprobaciones únicas, sin reintentos del proveedor ni reparación
del texto, usando el modelo configurado en el proyecto:

| Entrada | Resultado esperado | Resultado observado |
|---|---|---|
| C04/P4 conservado: mezcla revisión con otra forma de examen | Requiere cambios | `procedure_scope_mixing` |
| Feria cultural ficticia: traslada inscripción inicial a reconsideración | Requiere cambios | `procedure_scope_mixing` |
| Feria cultural: distingue las dos vías | Acepta el contenido | `passed`, sin incidencias |
| Facturación ficticia: impone inspección técnica para revisar cargo duplicado | Requiere cambios | `procedure_scope_mixing` |
| Facturación: conserva autoridad y plazo de cada procedimiento | Acepta el contenido | `passed`, sin incidencias |

Las cinco entradas permanecieron intactas. C04/P4 no se cuenta como respuesta
corregida: ahora su defecto queda detectado y pendiente de modificación. No hubo
aprobación ni cierre de controles. Este contraste pequeño no garantiza detectar
cualquier combinación de procedimientos futura.

Los JSON de entrada/salida y las huellas de código están en
`output/qa/rag-general-correcciones-20261116/procedure-scope-check/`.
El script reproducible es `check_procedure_scope.py`, en la misma carpeta raíz de
QA. El script no sobrescribe resultados existentes y no autoriza una segunda
llamada por ejemplo. Sus tiempos son descriptivos; no son una comparación de
rendimiento del flujo completo.

## Regresión local

Pasaron 156 pruebas de requisitos, borrador y revisión; Ruff no reportó incidencias.

```powershell
.\scripts\dev-python.ps1 -m pytest tests/test_request_requirements.py tests/test_draft_engine.py tests/test_rag_review_requirements.py tests/test_review_resolved_requirement_gap.py tests/test_review_engine.py -q
```

La auditoría consolidada del subconjunto C02/C04/C05 registra 14 de 15 núcleos
correctos y 12 rúbricas completas, frente a 9 y 7 del baseline reevaluado con el
mismo criterio. El archivo `audit-accepted-v3-2-02-04-05.json` separa estado del
checker, calidad semántica, rúbrica y reutilización verificada por bytes. Solo
C04/P4 se volvió a comprobar con esta última instrucción; los demás estados
conservan su procedencia anterior.
