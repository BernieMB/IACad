---
name: iacad
description: Diseña y verifica proyectos y piezas CAD paramétricas sin interfaz mediante IACad (MCP/CLI). Use when a user asks to create, extrude, revolve, fillet, chamfer, inspect geometry or export mechanical parts in STEP, STL, 3MF or GLB from OpenCode.
license: Apache-2.0
compatibility: opencode
metadata:
  version: "0.1"
---

# IACad: guía del agente (MVP)

Al crear un diseño:

1. Pregunta con la herramienta `question` por las medidas, unidades, material y formatos que falten **si son críticos**. Registra los supuestos en tu respuesta al usuario.
2. Usa `iacad_help` para descubrir los comandos disponibles; no inventes operaciones. Soporta proyectos, piezas, caja/cilindro, croquis 2D + extrusión o revolución, booleanas, fillet/chamfer, parámetros de longitud/ángulo, tres checks y export STEP/STL/3MF/GLB. El roadmap está en `doc/Estado.md`.
3. Crea un manifiesto con `iacad_session(action="new", doc="proyecto.iacad", name="…", kind="project")` y una pieza con `kind="part"` en `parts/nombre.iacad`. Guarda el `uid` devuelto por la creación de la pieza. Nunca sobrescribas archivos ajenos.
4. Define parámetros nombrados (`param.set`); para giros, declara `kind="angle"`, p. ej. `value="90 deg"` o `value="1.57 rad"`. Construye un taladro con `feature.cylinder` + `feature.boolean(op="cut")` o define un `sketch.new` en XY/XZ/YZ, añade un exterior cerrado con `sketch.rectangle`/`sketch.polyline` y círculos interiores con `sketch.circle`. Para extruir usa `feature.extrude` con `extent={"type":"distance","distance":"6 mm"}` o `{"type":"symmetric","distance":"50 mm"}`. Para tornear usa `feature.revolve` con eje global coplanar al sketch (`axis={"origin":[0,0,0],"dir":[0,1,0]}`) y `angle="360 deg"` o parámetro angular; rechaza perfiles que atraviesan el eje. Usa `expected_revision` después de leer la revisión anterior; haz checkpoint antes de cambios complejos.
5. Antes de redondear/achaflanar, consulta `iacad_query(doc="parts/nombre.iacad", what="topology", body="principal", kind="edge", limit=100)` (paginación con `cursor`). Usa los `ref` no nulos del resultado, por ejemplo `{"refs":["@base/edge:xmax&ymax"],"expect":"one"}`, o una query `{"query":{"scope":"principal","kind":"edge","where":"|Z and >X and >Y"},"expect":"one"}`. Solo se garantizan nombres semánticos de cajas y caras laterales/tapas de cilindros cuando son **únicos**. Si `REF_LOST` o `SELECTION_COUNT`, vuelve a inspeccionar; nunca adivines índices. Ejecuta primero `dry_run=true` en lotes inciertos. Si falla, revisa `error.code` y `error.hint`.
6. En el proyecto, usa `project.brief` para registrar la intención, `project.requirement` para cada requisito y `project.link(path="parts/nombre.iacad", uid="<uid de la pieza>")` para enlazarla. Actualiza `verified_by` con `parts/nombre.iacad#check:id` cuando exista el check; que exista **no garantiza que se cumpla**. Verifica pieza y proyecto con `iacad_query(what="summary"|"brief")` o `iacad_validate`; revisa validez, bbox en mm, volumen en mm³ y checks fallidos. Para la comprobación visual, llama `iacad_render(doc="parts/nombre.iacad", out="out/vistas.png", views="four")`: devuelve imagen PNG y ruta. Las imágenes son una previsualización; las cotas las confirma `validate`.
7. Exporta con `iacad_export(format="step"|"stl"|"3mf"|"glb", out="out/…")`; STEP conserva geometría exacta, STL/3MF son mallas (3MF incluye unidades) y GLB alimenta visores. Comunica revisión, cotas, checks y rutas al usuario.

**Ejemplos**: `examples/proyecto.iacs` registra brief/requisitos, `examples/placa.iacs` hace un taladro por booleana, `examples/placa_croquis.iacs` / `examples/perfil_l.iacs` usan croquis+extrusión, `examples/casquillo_revolucion.iacs` define un casquillo torneado y `examples/caja_redondeada.iacs` selecciona una arista semántica. Para ejecutar scripts por CLI: `uv run iacad exec parts/casquillo.iacad --script examples/casquillo_revolucion.iacs`. Desde MCP `iacad_exec` acepta `commands` (array JSON) o `script` (contenido textual, no ruta). Los arrays del script son **JSON**. `cache.hits`/`cache.misses` ayudan a entender la regeneración; la caché nunca es la fuente de verdad.

Convenciones: `feature.box` crea un prisma con origen en su esquina inferior; `feature.cylinder` crea un cilindro vertical +Z con centro XY en `origin`. Los números sin unidad están en las unidades del documento (mm por defecto), las cadenas pueden usar `mm`, `in`, `cm`, etc. **No ejecutes Python arbitrario para definir diseños.**

Referencia de comandos y ejemplos: `uv run iacad help`, `uv run iacad help feature.box`, `uv run iacad schema` y [`doc/Estado.md`](../../../doc/Estado.md).
