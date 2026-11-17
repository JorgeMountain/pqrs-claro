# Documentación del proyecto

Para una primera instalación usa [ENTREGA.md](ENTREGA.md). El
[README principal](../README.md) resume el flujo actual y los comandos; las normas
para colaborar están en [CONTRIBUTING.md](../CONTRIBUTING.md).

## Incorporación y arquitectura

- [Instalación y entrega a otra persona](ENTREGA.md).
- [Entender el proyecto y empezar a colaborar](GUIA_PARA_ENTENDER_Y_COLABORAR.md).
- [Arquitectura y estructura con diagramas](GUIA_VISUAL_PQRS_CLARO.md).
- [Recorrido detallado del código](RECORRIDO_CODIGO.md): contiene explicaciones
  históricas señaladas por fecha; para el inicio actual prevalecen la guía de
  entrega y el README.
- [Funcionamiento general](COMO_FUNCIONA.md) y [arranque en un puerto](INTEGRACION_UN_PUERTO.md).

## Trabajo con expedientes

- [Bandeja y gestores](BANDEJA_GESTORES.md), [expedientes y papelera](EXPEDIENTES.md).
- [Revisión inicial y rutas](REVISION_INICIAL_FIAGA.md), [contexto y decisiones](CONTEXTO_REVISION_Y_RUTAS.md).
- [Clasificación con JEV](JEV_CLASIFICACION.md).
- [Preparación de respuestas](PREPARACION_AUTOMATICA.md), [análisis incremental](ANALISIS_INCREMENTAL.md).
- [Citas por ubicación](CITAS_POR_UBICACION.md), [comprobaciones](COMPROBACIONES.md)
  y [suficiencia de la respuesta](SUFICIENCIA.md).
- [Oficio editable](OFICIO_EDITABLE.md), [generación y anexos](FASE7.md).

## Fuentes e integraciones

- [Correcciones del RAG integradas, alcance y validación](INTEGRACION_CORRECCIONES_RAG_20261117.md).
- [Recuperación de fuentes](RECUPERACION.md) y [búsqueda semántica local](busqueda-semantica-local.md).
- [Seguimiento y mediciones de optimización del RAG](OPTIMIZACION_RAG.md).
- [Cobertura, incisos y pendientes del recorrido RAG](RAG_COBERTURA_GENERAL.md).
- [Contexto del escrito original](CONTEXTO_ORIGINAL_PQRS.md) y
  [selección de documentos y pasajes contiguos](RECUPERACION_GENERAL_CONTEXTO.md).
- [Unidades de respuesta y detalles que debe conservar el borrador](UNIDADES_RESPUESTA_RAG.md).
- [Disponibilidad, autenticidad y entrega de copias](DISPONIBILIDAD_AUTENTICIDAD_ENTREGA.md),
  [vigencia de copias certificadas](VIGENCIA_COPIAS_CERTIFICADAS.md) y
  [cotejos de firma y trazabilidad](VIGENCIA_Y_COTEJOS_DOCUMENTALES.md).
- [Consolidación de controles de procedencia y autenticidad](PROCEDENCIA_Y_AUTENTICIDAD_SIN_DUPLICADOS.md).
- [Piloto de claridad entre procedimientos](CLARIDAD_PROCEDIMIENTOS_RAG.md).
  `PQRS_PROCEDURE_SCOPE_PILOT=false` es el valor predeterminado. La bandera controla
  la lectura independiente de referentes en borrador y revisión; las comprobaciones
  compartidas de cobertura y pendientes forman parte del recorrido habitual.
- [Biblioteca integrada](BIBLIOTECA_RECORRIDO.md), [preparación de biblioteca](PREPARACION_BIBLIOTECA.md).
- [Históricos](HISTORICOS.md), [OCR local](OCR_LOCAL.md), [Gmail](GMAIL.md).
- [Drive](DRIVE.md) y [opciones de almacenamiento](ALMACENAMIENTO.md): describen
  alcance y propuestas; no implican sincronización institucional automática.

## Planes, decisiones e informes fechados

[PLAN.md](PLAN.md), [FASE4.md](FASE4.md), [FASE5.md](FASE5.md) y
[FASE6.md](FASE6.md) registran etapas de construcción. La
[propuesta de recorrido](PROPUESTA_RECORRIDO.md), el
[piloto sin bloqueo inicial](PILOTO_SIN_BLOQUEO_INICIAL.md) y el
[laboratorio LAYA](LAYA_LAB.md) explican alternativas con alcance propio.

[VALIDACION.md](VALIDACION.md), los archivos `QA_*.md`,
[medición de redacción](MEDICION_REDACCION_20261009.md) y
[optimización](OPTIMIZACION_RENDIMIENTO_20261009.md) conservan evidencia de sus
fechas. Sus cifras no se presentan como resultados de una nueva instalación.
Los informes y capturas nuevos de trabajo se guardan localmente en `output/qa/`.

Los ensayos del RAG conservan sus muestras, criterios y decisiones de cada ronda.
Las indicaciones de candidato o de trabajo local describen el estado al medir.

- [Correcciones generales y comparación con la referencia](RESULTADOS_CORRECCIONES_RAG_20261116.md)
  y [continuación sobre omisiones y regresiones](RESULTADOS_OMISIONES_GENERALES_20261116.md).
- [Validación con expedientes ficticios nuevos](VALIDACION_RAG_CONTEXTOS_NUEVOS_20261116.md).
- [Pruebas de copias, intención y revisión](QA_COPIAS_Y_REVISION_20261116.md) y
  [pruebas de unidades en el texto guardado](QA_UNIDADES_REVISION_20261116.md).
- [Comprobación documental de mezcla de procedimientos](QA_MEZCLA_PROCEDIMIENTOS_20261116.md)
  y [resultados del piloto de lectura independiente](RESULTADOS_PROCEDIMIENTOS_RAG_20261116.md).
- [Diseño del inventario de autoridades, alternativas y pendientes](INVENTARIO_AUTORIDADES_Y_PENDIENTES.md)
  y [resultados de sus variantes](RESULTADOS_INVENTARIO_PENDIENTES_20261117.md).

La [validación de la entrega del 26 de octubre](VALIDACION_ENTREGA_20261026.md)
registra las pruebas, correcciones y comprobación de una copia limpia realizadas
al preparar este repositorio para otra persona.
