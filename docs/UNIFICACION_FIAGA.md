# Unificación de PQRS y FIAGA

Fecha: 27 de septiembre de 2026. El código parte de `55ed94a` en ambas copias.

## Uso principal y desarrollo

- Principal: `C:/Users/jorge/Desktop/AgenteO/pqrs-claro`, datos en su `data/`, puerto 8772.
- Desarrollo: `C:/Users/jorge/Desktop/AgenteO/pqrs-claro-fiaga`, con datos separados.
- El laboratorio de texto/PDF de 8775 sigue siendo una herramienta opcional de desarrollo.
- Los puertos 8773, 8774 y 8776 son vistas de desarrollo y QA, no accesos al expediente principal.

El acceso habitual es `scripts/start-unificado.ps1` (o los accesos que lo delegan).
Activa la revisión inicial y JEV. La clave de Vercel se conserva en `.env.jev.local`,
excluido de Git; OpenAI mantiene su configuración previa. No se publican claves ni datos.

## Comportamiento integrado

Tras identificar solicitudes se analiza automáticamente el trámite. JEV propone el tipo
de cada petición; OpenAI evalúa datos, lenguaje, antecedentes y tratamiento especial.
La revisión de lenguaje identifica al emisor de las expresiones ofensivas y no atribuye
automáticamente al solicitante un insulto relatado o citado. Los casos mixtos y ambiguos
requieren valorar el contexto. Se mantiene la revisión humana antes de preparar respuestas.

Los expedientes antiguos no se reprocesan al arrancar. Sus documentos, respuestas y decisiones
permanecen guardados, pero el nuevo flujo exige revisión inicial vigente para continuar,
aprobar o exportar. Una revisión previa desactualizada debe actualizarse explícitamente.
Las dos tablas nuevas son `intake_reviews` e `intake_history`; no se fusionan datos de prueba.

## Respaldo y validación

Respaldo local privado:
`../pqrs-claro-fiaga/output/unificacion-20260927-153642/`.
Incluye código y configuración de ambas copias, bundle Git, bases SQLite respaldadas mediante
su API, documentos y datos de las vistas QA. Dependencias reinstalables y cachés no se duplican.
Las 41 bases copiadas pasaron `integrity_check`.

En una copia de los datos principales se comprobaron 48 originales PDF y las 32 tablas
existentes sin cambios en sus filas; solo se añadieron las dos tablas de revisión inicial.
Esta prueba de conservación no realizó llamadas de IA ni consultas a Gmail.
Evidencias: `manifest.json`, `validation.json` y `tests.xml` en el respaldo.

Para evitar respuestas excesivas en casos pequeños, el límite de salida se calcula por
número de peticiones (mínimo 4.000, máximo 22.000 tokens). Las respuestas incompletas se
rechazan; el límite no garantiza que toda llamada finalice. Las pruebas sintéticas de
cita, insulto directo y mensaje mixto respondieron según lo esperado con OpenAI.

## Recuperación

Si hubiera una regresión, detener el proceso principal antes de recuperar datos. No copiar
bases SQLite por encima de una instancia activa. El respaldo incluye el código anterior
en `pqrs-claro/code.zip` y los datos en `pqrs-claro/data/`. Conservar aparte los datos actuales
antes de cualquier restauración para no perder trabajo posterior a la integración.
El bundle Git conserva los commits anteriores; el ZIP incluye los cambios que estaban
sin commit. Las carpetas `.runtime` continúan disponibles en ambos proyectos.

## Estado de activación

La integración está preparada en la rama de desarrollo. La batería general pasó con
1.244 pruebas aprobadas y una omitida por modelo semántico local no instalado. Además,
las comprobaciones posteriores de arranque, límite de respuesta y rechazo de proveedor
pasaron, al igual que las 18 pruebas JavaScript de revisión inicial.

La prueba HTTP real del recorrido encontró una restricción externa de Vercel:
HTTP 403, `no_providers_available`, indicando que JEV no admite usuarios con créditos
gratuitos. No se atribuye el fallo a una clave inválida ni a ausencia de texto. El código
presenta un mensaje concreto y no hace una sustitución automática por OpenAI.
La activación principal queda pendiente de elegir explícitamente otro clasificador o
habilitar créditos de pago para JEV. No se han fusionado las bases ni activado cambios
sobre los expedientes principales. El caso de prueba se conserva solo en `validation-data`.
