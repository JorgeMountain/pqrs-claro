# Colaborar con PQRS Claro

Empieza por el [README](README.md), la [guía de entrega](docs/ENTREGA.md) y el
[mapa del código](docs/GUIA_PARA_ENTENDER_Y_COLABORAR.md). El repositorio principal
es `pqrs-claro`; no necesitas los otros proyectos de la carpeta AgenteO.

## Entorno de desarrollo

Instala las dependencias con `scripts/setup.ps1` y configura credenciales propias
en `.env.local`. Para probar en el equipo donde ya existe una instalación, usa
otra carpeta de datos y un puerto libre:

```powershell
$env:PQRS_CLARO_DATA_DIR = Join-Path $PWD 'output/qa/mi-cambio'
.\scripts\start.ps1 -Port 8782
```

La variable de datos se lee del entorno del proceso, no de `.env.local`. Las
pruebas automatizadas ya usan sus propios directorios temporales. Un segundo
puerto con el mismo directorio seguiría trabajando sobre los mismos expedientes.

## Cambios y validación

1. Crea una rama con un nombre que describa el cambio.
2. Localiza la pantalla, ruta API, servicio y persistencia implicados. El mapa de
   módulos está en `docs/GUIA_PARA_ENTENDER_Y_COLABORAR.md`.
3. Conserva los originales, las revisiones y la confirmación humana. Navegar a
   una etapa guardada debe recuperar su resultado, sin volver a ejecutar IA.
4. Ejecuta las comprobaciones correspondientes al cambio. Para lógica de flujo,
   usa datos ficticios y dobles explícitos de proveedores. Para interfaz, comprueba
   también el comportamiento en navegador y en una ventana estrecha.
5. Describe el comportamiento resultante y la validación en el commit o PR.

```powershell
.\scripts\test.ps1
.\scripts\dev-python.ps1 -m ruff check src tests scripts
$jsTests = @(Get-ChildItem tests -Filter 'test_*.mjs' -File | ForEach-Object FullName)
node --test @jsTests
git diff --check
```

La interfaz es JavaScript modular sin compilación npm. Python y sus herramientas
usan `scripts/dev-python.ps1`, que carga `.runtime/`. Las dependencias se declaran
en `pyproject.toml` y las versiones resueltas se conservan en `uv.lock`.

## Qué incluir en Git

Incluye código, pruebas, documentación, recursos públicos de interfaz con su
licencia y ejemplos ficticios. Revisa `git diff --cached` antes de publicar.

Guarda los informes y capturas de trabajo en `output/qa/`; los ensayos desechables
pueden ir en `tmp/`. No incluyas `.env.local`, claves, tokens Gmail, bases SQLite,
originales de expedientes ni copias de bibliotecas. `.env.example` contiene opciones
vacías o de ejemplo. La [guía de entrega](docs/ENTREGA.md) explica cómo separar la
transferencia del código de una eventual migración de datos autorizada.
