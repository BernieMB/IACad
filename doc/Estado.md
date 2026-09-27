# Estado de implementación

Actualizado: 2026-09-27. El [planning](Planning.md) describe el objetivo completo; **esta tabla indica lo que existe y ha pasado pruebas**. No sustituye a los requisitos.

| Fase / hito | Estado | Lo que funciona | Pendiente |
|---|---|---|---|
| 0 — fundamentos | En curso | Python 3.13 + `uv.lock`; OCCT/build123d importados, resta booleana y exportación STEP probadas en Windows; spike `BRepAlgoAPI_Cut.History()` (caras modificadas/generadas accesibles), ADR inicial, LICENSE/NOTICE, tests locales y workflow de CI Windows/Linux. | Ejecutar CI en remoto (git inicializado sin commits ni remoto); verificar conversor DXF→DWG (no instalado en este equipo). |
| 1 — MVP-0 | Funcional (ampliaciones pendientes) | `.iacad` JSON para proyectos y piezas; brief, requisitos y enlaces a piezas verificados por UID; parámetros de longitud y ángulo con unidades/expresiones seguras, comandos tipados, validación y rollback por transacción, revisiones + `dry_run`, bloqueo de escrituras entre procesos, journal JSONL, snapshots con undo/redo/checkpoint, registro de plugins (comandos y features), primitivos y booleanas, checks, CLI JSON, servidor MCP stdio, skill y caché B-Rep por operación con checksum. | Migraciones de formato, DSL `.iacs` avanzado, límites/expulsión de caché. Los parámetros del manifiesto aún no se propagan a las piezas. |
| 2 — modelado paramétrico | Iniciada | Croquis 2D XY/XZ/YZ (polilínea cerrada, rectángulo y círculo), extrusión y revolución `feature.revolve` con eje global coplanar, ángulo parametrizable (deg/rad), geometría de torneado exacta y booleanas, perfil exterior con huecos; consultas paginadas de caras/aristas (tipos geométricos, centro, área/longitud, nombres semánticos únicos de cajas/cilindros), selectores `|X`, `>Z`, `%PLANE`… con `expect` obligatorio; fillet y chamfer en aristas resueltas con rollback; export STEP/STL/3MF/GLB; previsualización técnica PNG iso/front/top/right/four por CLI y MCP. | Constraints de sketch, múltiples perfiles, loft/sweep/shell/pattern, naming completo del historial OCCT tras cambios arbitrarios, fingerprints/selección por procedencia del sketch, renderizado fotorrealista. |
| 3+ | No iniciadas | — | Visor solo lectura, ensamblajes, planos 2D/DWG, importación, simulación, render fotorrealista y escalabilidad. |

## Comandos implementados

`param.set` (kind=length|angle), `feature.box`, `feature.cylinder`, `feature.boolean`, `sketch.new`, `sketch.rectangle`, `sketch.circle`, `sketch.polyline`, `feature.extrude`, `feature.revolve`, `feature.fillet`, `feature.chamfer`, `check.add`, `project.brief`, `project.requirement`, `project.link`, `project.unlink`; CLI `new` (`--kind part|project`), `exec`, `query` (`summary`, `tree`, `params`, `brief`, `topology`), `validate`, `export` (STEP/STL/3MF/GLB), `render` (PNG), `history`, `undo`, `redo`, `checkpoint`, `restore`, `help`, `schema`, `mcp`; MCP `help`, `session` (`new`, `history`, `undo`, `redo`, `checkpoint`, `restore`), `exec`, `query`, `validate`, `export`, `render`.

Los comandos desconocidos devuelven `UNKNOWN_COMMAND`. En el manifiesto (`kind: project`) se verifica ruta relativa, UID y existencia del check/feature citado por `verified_by`, **no** que ese check pase: validar la pieza por separado. Se requiere un único cuerpo para exportar. Los checks geométricos fallidos se **informan** (`checks.failed > 0`) pero no bloquean guardar, para permitir diseños incompletos; sí bloquean `validate` y `export`. L1–L3 abortan y revierten la operación. Los sketches admiten un exterior y huecos interiores, sin constraints ni referencias a caras.

## Repetir la prueba vertical

```powershell
uv sync
uv run pytest -q
uv run iacad new parts/demo.iacad --name "Placa con orificio"
uv run iacad exec parts/demo.iacad --script examples/placa.iacs
uv run iacad query parts/demo.iacad summary
uv run iacad export parts/demo.iacad --format step --out out/demo.step
```

Las rutas relativas se interpretan desde el workspace (variable `IACAD_WORKSPACE` o directorio actual). Para conectarlo con OpenCode v1 en este repositorio existe `opencode.json`: reinicia OpenCode para que cargue el skill y el servidor MCP.

**Verificación local:** `uv lock --check`, `uv run --no-sync ruff check src tests examples` y `uv run --no-sync pytest -q` (45 tests: CLI/MCP por stdio e imagen PNG, proyectos y enlaces, caché, croquis/extrusión/revolución, round-trip STEP/3MF/GLB, topología, acabado, undo/redo y plugins) pasan en Windows 3.13.7. Se ha inspeccionado un PNG real de cuatro vistas. `opencode mcp list` informa `iacad connected`. `uv sync` no pudo sustituir el ejecutable `iacad.exe` bloqueado por esta sesión MCP activa: sincronizar después de cerrar OpenCode. El CI para Linux y Windows está definido, aún sin ejecutarse remotamente.
