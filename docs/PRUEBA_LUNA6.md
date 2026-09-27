# Prueba aislada de GPT-6 Luna (2026-09-27)

Los arranques `run-fiaga.py` (8773) y `run-fiaga-analysis-preview.py` (8776) usan OpenAI para la clasificación inicial. El modelo configurado en `.env.local` y el valor predeterminado de Settings es `gpt-6-luna`. Se conserva la clave existente.

La vista de pruebas activa es http://127.0.0.1:8776/; su `/api/config` confirma el modelo y proveedor. Los datos son los de `output/qa/fiaga-auto-analysis/data`. No se fusionó con el proyecto principal. El arranque unificado preparado para integración y las otras vistas históricas conservan su selección de proveedor anterior.

Se ejecutó la revisión inicial real de OpenAI con textos ficticios para comprobar clasificación y atribución del lenguaje. Esta prueba acotada no constituye una evaluación general de calidad. La confirmación humana sigue siendo necesaria. Los informes previos requieren reanálisis para reflejar el nuevo modelo.

Para revertir: configurar `PQRS_CLARO_MODEL=gpt-5.6-luna` en `.env.local` y reiniciar el servidor. Para volver a JEV, restaurar `initial_classification_provider="jev"` en el arranque correspondiente; su acceso depende del proveedor.

Actualización posterior: el usuario autorizó integrar el arranque principal con OpenAI. Véase UNIFICACION_FIAGA.md; la descripción anterior corresponde a la etapa de prueba aislada.
