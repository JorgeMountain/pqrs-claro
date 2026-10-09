# Continuar sin revisión inicial — piloto

El botón al final del paso 1 registra una excepción por expediente y prepara
respuestas aunque la revisión inicial sea antigua, tenga errores o proponga otra
ruta. Confirma las peticiones identificadas para poder preparar; no aprueba el
análisis inicial ni cambia sus rutas, observaciones o decisiones.

La excepción y su fecha se conservan en el historial de revisión inicial. Sigue
vigente al cambiar las colecciones, pero deja de aplicar si cambia el original o
las peticiones identificadas. Puede desactivarse con «Volver a exigir revisión
inicial». Los expedientes cerrados y los procesos en curso mantienen sus controles.

El redactor no recibe el análisis omitido como contexto humano confirmado.
La suficiencia de fuentes, pendientes y aprobación final mantienen sus validaciones.
El modo no envía comunicaciones ni sustituye el procedimiento institucional.

Validación: 36 pruebas Python de revisión inicial, contexto y excepción; 57 pruebas
JavaScript. Navegador real con APIs ficticias: continuar desde análisis desactualizado,
desactivar, ningún guardado de aprobación ni nueva consulta del análisis inicial,
y preparación interceptada. Anchos 320, 768, 1024 y 1440 sin desbordamiento.
No se ejecutó IA ni se confirmó un expediente real para probar esta función.
