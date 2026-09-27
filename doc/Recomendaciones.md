# IACad — Recomendaciones adicionales

> Opciones, lecciones y alternativas encontradas investigando en internet (septiembre de 2026). Complementan el [Planning](Planning.md) y el [Modelo de datos](Modelo.md).
>
> **Leyenda de prioridad:** 🟢 Adoptar · 🟡 Evaluar · ⚪ Vigilar
>
> Las versiones, estrellas y licencias son una foto a fecha 2026-09-26; conviene revisarlas antes de fijarlas. Lo marcado *(no verificado)* no se pudo confirmar en fuente primaria. Nada de esto es asesoramiento legal.

---

## 1. Proyectos similares de los que aprender

### 1.1 Servidores MCP e integraciones de agentes con CAD

| Proyecto | ★ / Licencia | Enfoque | Qué copiar | Qué evitar |
|---|---|---|---|---|
| [jdilla1277/agentcad](https://github.com/jdilla1277/agentcad) | 138 / Apache-2.0 | CLI + MCP sobre build123d. Cada `run` versionado guarda un STEP y métricas; `check-spec spec.json`, `diff 1 2`, piezas con ID estable. | **Es el más parecido a IACad.** JSON en stdout y progreso en stderr, verificación contra especificación, diff entre versiones, previsualización de 4 vistas, visor con comparación A/B. | Ejecuta código Python libre. |
| [pzfreo/build123d-mcp](https://github.com/pzfreo/build123d-mcp) | 94 / Apache-2.0 | Sesión persistente; render PNG/SVG/DXF, medición, detección de taladros, imprimibilidad, snapshots, `last_error`, `install_skill`. | Snapshots para guardar y restaurar, `last_error`, instalación del skill. Sus autores afirman que la puntuación en CADGenBench subió de 0,360 a 0,457 y la validez del 88 % al 100 % *(auto-reportado)*. | — |
| [neka-nat/freecad-mcp](https://github.com/neka-nat/freecad-mcp) | 2.5k / MIT | Herramientas CRUD + `execute_code` (hilo de la GUI, asíncrono o headless con freecadcmd), `run_fem_analysis`. | Captura **opcional por llamada** (`include_screenshot`, 9 vistas con nombre) y modo `--only-text-feedback`. | Timeouts por ejecutar en el hilo de la GUI. |
| [jingcheng-chen/rhinomcp](https://github.com/jingcheng-chen/rhinomcp) | 1.1k / MIT | Decenas de herramientas tipadas, operaciones por lotes, undo/redo, búsqueda en la documentación de la API. | Contratos JSON Schema validados antes de ejecutar; la ejecución de código se puede **desactivar por variable de entorno**; guías servidas como prompt y como recurso MCP; error explícito si no coinciden las versiones del plugin y el servidor. | — |
| [ReshefElisha/jarvis-onshape-mcp](https://github.com/ReshefElisha/jarvis-onshape-mcp) | 172 / MIT *(según el README)* | ~60 herramientas; cada cambio devuelve `{ok, status, feature_id, error_message, changes, hints}`, con diferencias de bbox, masa y número de piezas. | Formato de respuesta con `changes` y `hints`; `list_entities` con IDs estables y normales; imágenes multivista, recorte y **comparación con una imagen de referencia**; skill "vision-decompose" que propone un árbol de features para que el usuario lo confirme. | Limitado por lo que permite la API de Onshape. |
| [armpro24-blip/cad-cae-copilot](https://github.com/armpro24-blip/cad-cae-copilot) | 63 / MIT | build123d + CalculiX; referencias estables `@face:*`, diff antes/después, `require()` como aserciones de diseño. | Aserciones que hacen fallar la construcción (equivalen a nuestros `checks`), procedencia de cada resultado, modos de aprobación. | — |
| [KanJieTeam/kjdraw](https://github.com/KanJieTeam/kjdraw) | 64 / Apache-2.0 | Dibujo 2D para agentes; IDs estables, `expectedRevision`, undo/redo. | Concurrencia optimista (nuestro `expected_revision`); "el texto del modelo nunca prueba que el CAD sea correcto". | — |
| [ahujasid/mcp-for-blender](https://github.com/ahujasid/mcp-for-blender) | 29.4k / MIT | Herramientas de escena + ejecución de Python. | "Safe mode": revisa el script antes de ejecutarlo y devuelve el motivo del bloqueo. | Socket sin autenticación. |
| [earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad) | 16.4k / MIT | Colección de **skills** (STEP/STL/3MF, visor, planos, DXF, fabricabilidad, G-code). | Organizar el conocimiento en skills temáticos. | En Windows, Smart App Control bloquea la DLL de OCP sin firmar. |
| [Adam-CAD/CADAM](https://github.com/Adam-CAD/CADAM) | 5.2k / GPL-3.0 | La IA escribe OpenSCAD y la app extrae los parámetros como deslizadores. | Parámetros como ciudadanos de primera: se cambian sin volver a llamar a la IA. | Licencia GPL si se reutiliza código. |
| Zoo — [Zookeeper / Text-to-CAD](https://zoo.dev/research/zookeeper) | Comercial | Agente que escribe, ejecuta y depura KCL, revisa snapshots multivista y usa herramientas de masa y volumen. | Confirma el enfoque "la IA escribe texto paramétrico y lo verifica". Zoo **abandonó** generar B-Rep directamente desde texto en favor de código KCL. | Motor geométrico en la nube (no sirve para uso offline). |

Otros de interés: [mixelpixx/KiCAD-MCP-Server](https://github.com/mixelpixx/KiCAD-MCP-Server) (electrónica, 2.5k ★), [U-C4N/Autocad-MCP](https://github.com/U-C4N/Autocad-MCP) (AutoCAD COM + ezdxf; detalles *(no verificados)*), [Pan-Chera/Multi-Agent-CAD](https://github.com/Pan-Chera/Multi-Agent-CAD) (build123d multi-agente).

### 1.2 Investigación sobre LLM y CAD (arXiv)

| Trabajo | Hallazgo útil para IACad |
|---|---|
| [DeepCAD (2105.09492)](https://arxiv.org/abs/2105.09492) | Trata el CAD como secuencia de sketch + extrusión; dataset de 178k modelos. |
| [Fusion 360 Gallery (2010.02392)](https://arxiv.org/abs/2010.02392) | Construcción paso a paso como decisiones, igual que las llamadas a herramientas. |
| [Text2CAD (2409.17106)](https://arxiv.org/abs/2409.17106) | 660k prompts, de vagos a expertos: útil para el benchmark. |
| [Query2CAD (2406.00144)](https://arxiv.org/abs/2406.00144) | 53,6 % de acierto a la primera; el refinamiento añade 23 %, **casi todo en la primera ronda**. Hay que limitar los bucles de corrección. |
| [CADCodeVerify (2410.05340)](https://arxiv.org/abs/2410.05340) | Un modelo de visión formula y responde preguntas de verificación sobre el render y luego corrige. Introduce el benchmark CADPrompt. |
| [CAD-Assistant (2412.13810)](https://arxiv.org/abs/2412.13810) | Un VLM planifica y llama a herramientas de FreeCAD (render, secciones) y verifica tras cada paso. |
| [CAD-Recode (2412.14042)](https://arxiv.org/abs/2412.14042) | Representar el CAD como código ejecutable funciona mejor, y los LLM lo pueden leer y editar. |
| [CAD-GPT (2412.19663)](https://arxiv.org/abs/2412.19663) | Los modelos fallan en planos de sketch, puntos de inicio y direcciones de extrusión: conviene **hacerlos explícitos** (ver [Modelo §5.4](Modelo.md)). |
| [Text-to-CadQuery (2505.06507)](https://arxiv.org/abs/2505.06507) | Con código CadQuery, los modelos más grandes rinden mejor. |
| [CADSmith (2603.26512)](https://arxiv.org/abs/2603.26512) | **La imagen sola no corrige errores de cota.** Combina medidas exactas del kernel, un juez visual y búsqueda en la documentación: IoU 0,81→0,96 *(auto-reportado)*. |
| [BenchCAD (2605.10865)](https://arxiv.org/abs/2605.10865) | Los modelos sustituyen barridos y lofts por extrusiones simples: hay que medirlo en las evaluaciones. |
| [CADIR (2608.00891)](https://arxiv.org/abs/2608.00891) | Grafo de construcción con referencias estables y diagnósticos detallados. |
| [TraceCAD (2608.03062)](https://arxiv.org/abs/2608.03062) | Un registro que enlaza requisitos, pasos y fallos casi duplica el éxito de las reparaciones. Justifica el `brief` y el journal. |

---

## 2. Recomendaciones de diseño para el agente

1. 🟢 **Pocas herramientas, bien descritas y en orden fijo.** Unas 10 herramientas MCP genéricas con documentación bajo demanda (`help`). La documentación de OpenCode advierte de que las herramientas MCP consumen contexto rápidamente. Mantener el orden fijo ayuda al *prompt caching*.
2. 🟢 **Salida estructurada doble.** Declarar `outputSchema` y devolver `structuredContent` además del texto, según la [especificación MCP de tools](https://modelcontextprotocol.io/specification/latest/server/tools). Los errores recuperables van como resultado con `isError: true` (el agente puede corregirlos); los errores de protocolo quedan para peticiones mal formadas.
3. 🟢 **Cada cambio informa de qué ha cambiado:** IDs creados, deltas de bbox, volumen y número de caras, checks y pistas, como hace jarvis-onshape.
4. 🟢 **Primero números, después imagen.** Checks exactos (bbox, volumen, espesor, holguras) antes que el render (CADSmith). Render solo cuando se pida o como opción por llamada (freecad-mcp).
5. 🟢 **Limitar las rondas de autocorrección a 2–3** (Query2CAD): el grueso de la mejora llega en la primera.
6. 🟢 **IDs legibles**, no UUIDs. La guía de Anthropic sobre [cómo escribir herramientas para agentes](https://www.anthropic.com/engineering/writing-tools-for-agents) observa que los IDs legibles reducen las alucinaciones.
7. 🟢 **Revisión explícita en cada llamada** (`doc` + `expected_revision`) y flujo *proponer → confirmar* (`dry_run`), como kjdraw y rhinomcp.
8. 🟢 **Brief con requisitos trazables** en el proyecto (TraceCAD) y **checks como tests de diseño** (cad-cae-copilot, agentcad).
9. 🟢 **Preguntar antes de suponer.** OpenCode **no anuncia *elicitation*** de MCP en su cliente (según su código fuente), así que el skill debe indicar al agente que use su herramienta `question`.
10. 🟢 **Respuestas concisas y paginadas.** `response_format: concise|detailed`, `limit`/`cursor` en las consultas de topología y avisos de truncado.
11. 🟢 **Conocimiento distribuido en capas**: skill (flujo), recursos MCP (`iacad://docs/{tema}`), prompts MCP y herramienta de búsqueda en la documentación. OpenCode v1 ya expone `list_mcp_resources` y `read_mcp_resource`.
12. 🟡 **Preguntas de verificación visual** (CADCodeVerify): tras el render, el agente escribe 3–5 preguntas ("¿tiene 4 taladros en la cara vertical?") y las responde mirando la imagen.
13. 🟡 **Comparación con una imagen de referencia**, cuando el usuario aporta un boceto o una foto (jarvis-onshape `compare_to_reference`).
14. 🟡 **Descomposición previa**: el agente propone un árbol de features y lo confirma con el usuario antes de modelar piezas complejas.
15. 🟢 **Benchmark propio de evaluación** (`evals/`) inspirado en Text2CAD, CADPrompt y BenchCAD. Métricas: tasa de ejecución válida, IoU o Chamfer frente a un modelo de referencia, cotas exactas cumplidas, llamadas, tokens y errores; vigilar la sustitución de barridos y lofts por extrusiones.

---

## 3. Stack tecnológico recomendado

### 3.1 Núcleo
| Componente | Versión (sep-2026) | Licencia | Prioridad | Nota |
|---|---|---|---|---|
| [OCCT](https://github.com/Open-Cascade-SAS/OCCT) | 8.0.1 | LGPL-2.1 + excepción | 🟢 | Nuevo `BRepGraph` (grafo de topología con IDs e historial): evaluarlo para los nombres persistentes. |
| [OCP](https://github.com/CadQuery/OCP) (`cadquery-ocp-novtk`) | 8.0.1.0.0 | Apache-2.0 | 🟢 | Wheels para CPython 3.11–3.14 en Windows, macOS y Linux. |
| [build123d](https://build123d.readthedocs.io) | 0.13.0 | Apache-2.0 | 🟢 | Usar el modo *Algebra* (sin estado oculto). Pre-1.0: fijar la versión exacta. |
| [bd_warehouse](https://github.com/gumyr/bd_warehouse) | 0.3.0 | Apache-2.0 | 🟢 | Tornillería ISO/DIN, rodamientos, roscas, engranajes: el agente puede pedir "tornillo M3×10 ISO 4762". |
| [manifold3d](https://github.com/elalish/manifold) | 3.5.4 | Apache-2.0 | 🟡 | Booleanas de malla robustas y rápidas (imprimibilidad, 3MF, mallas importadas). |
| [planegcs](https://github.com/spookylukey/planegcs) | 0.8.0 | LGPL-2.1+ | 🟡 | Solver de croquis de FreeCAD con wheels Python 3.12/3.13 para Windows. Para la fase de restricciones. |
| slvs (SolveSpace) | 3.2 | GPL-3 en el repositorio; MIT en los metadatos de PyPI (conflicto) | ⚪ | Evitar hasta que se aclare la licencia. |
| CadQuery | 2.8.0 | Apache-2.0 | ⚪ | Sigue en OCCT 7.9 y no convive con build123d. Se copia su sintaxis de selectores y la idea de su solver de ensamblajes. |

### 3.2 Infraestructura Python (versiones por fijar en la Fase 0)
🟢 `uv` (entornos y empaquetado) · **Pydantic v2** (modelos → JSON Schema) · **Typer** (CLI) · **SDK MCP oficial para Python** · **Pint** (unidades) · **Lark** (gramática de `.iacs` y de expresiones) · **structlog** (logs JSON) · **pytest + Hypothesis** (tests *property-based* de geometría) · **ruff + pyright** · **MkDocs** (documentación).

### 3.3 Formatos
| Formato | Herramienta | Nota |
|---|---|---|
| STEP AP214/AP242, IGES, BREP | OCCT (XDE) | AP214 por defecto. Para PMI (cotas y tolerancias semánticas), `write.step.schema=AP242DIS`. IGES no es *thread-safe*. |
| glTF/GLB, OBJ, STL | build123d / OCCT | GLB también alimenta el visor. |
| 3MF | build123d `Mesher` / [lib3mf](https://github.com/3MFConsortium/lib3mf) 2.5.0 (BSD-2) | Recomendado para impresión 3D frente a STL: incluye unidades, colores y varios objetos. |
| DXF | [ezdxf](https://ezdxf.readthedocs.io) 1.4.4 | 2D completo; MESH/POLYFACE para 3D. |
| DWG | [LibreDWG](https://www.gnu.org/software/libredwg/) 0.14 (GPL-3, **solo por CLI**) | La escritura R2004 está soportada; R2010+ es experimental. |
| DWG (alternativa) | [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter) + [`ezdxf.addons.odafc`](https://ezdxf.readthedocs.io/en/stable/addons/odafc.html) | Freeware propietario. Según la FAQ de ODA, **solo para uso no comercial** si no eres miembro. |
| SVG/PDF (planos) | build123d `project_to_viewport` + ExportSVG/ExportDXF | Líneas visibles y ocultas con tipos de línea ISO/ANSI. |
| IFC | IfcOpenShell 0.8.5 (LGPL-3) | 🟡 Plugin para arquitectura (BIM). |
| USD | usd-core 26.8 | ⚪ Pipelines de render y visualización. |
| URDF/MJCF | XML propio + MuJoCo para validarlo | 🟡 Robótica. |

> ⚠️ **Limitación importante de DXF/DWG:** las entidades 3DSOLID, BODY, REGION y SURFACE guardan datos **ACIS** (kernel propietario de Spatial), según la [FAQ de ezdxf](https://ezdxf.readthedocs.io/en/stable/faq.html). No existe librería libre que escriba sólidos ACIS con superficies curvas. Con herramientas libres solo se puede escribir **3DSOLID poliédrico** (`ezdxf.acis.body_from_mesh`) o MESH/POLYFACE. **Los sólidos exactos deben entregarse en STEP.** DXF/DWG quedan para planos 2D y mallas. Hay que dejarlo claro en la documentación y en los mensajes del agente.

### 3.4 Simulación
| Herramienta | Licencia | Modo | Prioridad |
|---|---|---|---|
| [Gmsh](https://gmsh.info) 4.15.2 | GPL-2+ (no se puede embeber en software cerrado distribuido) | **Subproceso**; lleva su propio OCCT, así que se le pasan archivos STEP/BREP | 🟢 |
| [CalculiX](http://www.calculix.de) 2.23 | GPL-2+ | Subproceso con archivos `.inp` (formato Abaqus) | 🟢 |
| scikit-fem 12.0.2 | BSD-3 *(no verificado)* | En proceso, para cálculos rápidos | 🟡 |
| Netgen/NGSolve | LGPL *(no verificado)* | Alternativa de mallado importable | 🟡 |
| MuJoCo 3.14.0 | Apache-2.0 *(no verificado)* | Cinemática y dinámica de ensamblajes | 🟡 |
| code_aster, Elmer, OpenFOAM | GPL | Workers opcionales en Linux, WSL o Docker | ⚪ |
| FreeCAD FEM (1.1.3) | LGPL | Referencia del pipeline Gmsh/Netgen → CalculiX/Elmer; posible worker `FreeCADCmd` | ⚪ |
| Drake | BSD-3 | **Sin soporte para Windows** | ⚪ |

### 3.5 Render
- 🟢 **Blender CLI** como subproceso (`blender -b -P script.py -- args`), fijado a la **4.5 LTS**. Cycles en CPU funciona totalmente headless; en GPU con OPTIX, CUDA o HIP si hay tarjeta. **Ya tienes Blender con MCP instalado en este entorno**, así que se puede usar para prototipar la escena de render.
- 🟢 **PyVista `off_screen`** para capturas técnicas rápidas (aristas, secciones) del bucle de verificación del agente.
- 🟡 **Playwright + el propio visor** para capturas idénticas a lo que ve el usuario.
- ⚪ Mitsuba 3 (3.9.1) y LuxCore (2.11.2) como motores alternativos. ❌ pyrender (sin mantenimiento desde 2021).

### 3.6 Visor de solo lectura
| Opción | Licencia | Uso recomendado |
|---|---|---|
| [three-cad-viewer](https://github.com/bernhard-42/three-cad-viewer) 5.0.7 | MIT | 🟢 Base del visor propio: picking de vértice, arista, cara y sólido; medición; planos de corte; árbol. |
| [ocp_viewer](https://github.com/bernhard-42/vscode-ocp-cad-viewer) 1.1.3 (standalone, `python -m ocp_viewer` en `127.0.0.1:3939`) | *(no verificado)* | 🟢 Prototipo rápido en las Fases 1–2, antes de tener el visor propio. |
| [yet-another-cad-viewer](https://github.com/yeicor-3d/yet-another-cad-viewer) 0.12.1 | *(no verificado)* | 🟡 Alternativa con recarga en caliente y hosting estático. |
| [Online 3D Viewer](https://github.com/kovacsv/Online3DViewer) 0.18.0 | MIT | ⚪ Ver archivos exportados arbitrarios (STEP, IFC, 3MF…). |
| [`<model-viewer>`](https://github.com/google/model-viewer) 4.3.1 | Apache-2.0 | ⚪ Enlaces para compartir GLB (incluye AR). |
| xeokit | **AGPL-3.0** | ❌ Evitar salvo que se compre la licencia comercial. |

Idea diferencial 🟢: al pasar el ratón sobre una cara o arista, el visor muestra su **nombre persistente** (`@cuerpo/face:end`) con un botón para copiarlo. El usuario puede decirle a la IA "redondea `@cuerpo/edge:…`" sin ambigüedad, sin que el visor modifique nada.

---

## 4. Licencias: regla práctica

| Tipo | Ejemplos | Cómo integrarlo |
|---|---|---|
| Permisivas (MIT, BSD, Apache) | build123d, OCP, manifold3d, ezdxf, lib3mf, three-cad-viewer | Libremente, en el mismo proceso |
| LGPL | OCCT, planegcs, IfcOpenShell, Netgen | Enlace dinámico (wheels sin modificar); incluir avisos en NOTICE y publicar cualquier modificación que se haga a la librería |
| GPL / AGPL | Gmsh, CalculiX, LibreDWG, Blender, code_aster, OpenFOAM | **Solo como proceso externo**, intercambiando archivos o por CLI |
| Propietario gratuito | ODA File Converter | Opcional y configurable por el usuario; revisar los términos de uso |

🟢 Añadir a la CI una comprobación automática de licencias de dependencias (p. ej. `pip-licenses`) que falle si entra una dependencia GPL importada en el proceso.

---

## 5. Alternativas estratégicas

| Estrategia | A favor | En contra | Veredicto |
|---|---|---|---|
| **A. build123d + OCP propio** (recomendada) | Control total del formato y de la API para agentes; stack moderno; Apache-2.0; el mayor ecosistema MCP | Hay que construir nombres persistentes, solver de restricciones y planos | 🟢 Adoptar |
| **B. FreeCAD headless como backend** | Ya tiene solución al problema de nombres topológicos (1.0), ensamblajes (OndselSolver), TechDraw, FEM | ~0,5 GB; Python 3.11 embebido; formato FCStd (zip + XML, no texto plano); API pensada para la GUI; varias vulnerabilidades de parseo corregidas en 1.1.3 | 🟡 Solo como worker opcional (FEM, planos) intercambiando STEP |
| **C. CadQuery** | Selectores conocidos por los LLM; solver de ensamblajes | Fijado a OCCT 7.9; API encadenada con estado, frágil entre llamadas | ⚪ Inspiración |
| **D. Zoo KCL** | Lenguaje de texto paramétrico diseñado para IA (MIT) | Motor geométrico en la nube de Zoo | ❌ No sirve offline; buena referencia de diseño de lenguaje |
| **E. OpenSCAD / Manifold** | Simple, CLI madura, muy presente en los datos de entrenamiento | Solo mallas, sin STEP ni B-Rep; sin release estable desde 2021 | ❌ Para el núcleo; 🟡 manifold3d como librería auxiliar |
| **F. Kernels Rust (truck, Fornjot)** | Seguridad y WASM | truck en 0.x; Fornjot cerrado | ⚪ Vigilar |

---

## 6. Integración con OpenCode: detalles prácticos

Versión instalada en este equipo: **OpenCode 1.18.32 (v1)**. Existe una **v2 (2.0.x)** con formato de configuración incompatible; hay que soportar ambas.

**MCP local (v1)**, en `opencode.json` del proyecto de diseño:
```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "iacad": {
      "type": "local",
      "command": ["uv", "run", "--project", "D:/Proyectos/IACad", "iacad", "mcp"],
      "enabled": true,
      "environment": { "IACAD_WORKSPACE": "." },
      "timeout": 30000
    }
  }
}
```
- Las herramientas aparecen con prefijo: `iacad_exec`, `iacad_render`… Se pueden gobernar con `"permission": { "iacad_*": "allow" }` o por agente.
- En **v2** van en `mcp.servers.iacad`, se usa `disabled` en lugar de `enabled`, y **`codemode` está activo por defecto** (las herramientas se invocan como `tools.iacad.exec(...)`). Hay que probar ambos modos.
- Hay dudas sobre timeouts: la documentación indica 5 s para *descubrir* herramientas, y el código fuente usa 30 s y lo aplica también a las llamadas *(no verificado en 1.18.32)*. Por eso las operaciones largas (FEA, render final) deben devolver un `job_id` en vez de bloquear.
- **Imágenes**: según el código fuente de OpenCode, el contenido `image` de MCP se adjunta al modelo. Límite v1: 2000×2000 px y ~5 MB en base64; las imágenes mayores se omiten. **Recomendación:** renders de 1024×1024 px como máximo, devueltos como imagen MCP y también guardados en disco, para que el agente pueda abrirlos con `read` si su cliente no admite imágenes MCP.
- `opencode serve` + `opencode run --attach` evita el arranque en frío del MCP en ejecuciones repetidas (útil para el benchmark).

**Skill**: `.opencode/skills/iacad/SKILL.md` (también se aceptan `.claude/skills/` y `.agents/skills/`; global en `~/.config/opencode/skills/`).
```markdown
---
name: iacad
description: Diseña piezas, ensamblajes y planos CAD con IACad (headless) vía MCP o CLI. Úsalo cuando el usuario pida crear, modificar, verificar, renderizar o exportar un diseño CAD (STEP, STL, 3MF, DXF, DWG).
license: Apache-2.0
compatibility: opencode
metadata:
  version: "0.1"
---
## Flujo
1. Aclarar requisitos con la herramienta question …
```
- `name` debe cumplir `^[a-z0-9]+(-[a-z0-9]+)*$`, coincidir con el nombre de la carpeta y tener como máximo 64 caracteres. `description` admite hasta 1024 caracteres.
- Mantener `SKILL.md` breve y enlazar `references/commands.md`, `references/selectors.md`, `references/recipes.md` y `references/errors.md` para cargarlos bajo demanda.
- 🟡 Crear skills temáticos adicionales, como hace text-to-cad: `iacad-drawings`, `iacad-3dprint`, `iacad-fea`.

**Agente dedicado** 🟡 `.opencode/agents/cad-designer.md`:
```markdown
---
description: Diseñador CAD que usa IACad para crear y verificar diseños
mode: primary
temperature: 0.2
permission:
  edit: ask
  bash: ask
---
Eres un ingeniero de diseño mecánico. Usa siempre el skill iacad …
```

**Comandos** 🟡 `.opencode/commands/cad-nuevo.md` → `/cad-nuevo soporte para NEMA17`:
```markdown
---
description: Inicia un diseño CAD nuevo con IACad
agent: cad-designer
---
Crea un proyecto IACad para: $ARGUMENTS. Aclara primero los requisitos y registra el brief.
```

**Plugin** ⚪ `.opencode/plugins/iacad-autoview.ts`: con el *hook* `tool.execute.after`, abrir o refrescar el visor tras cada `iacad_exec` y registrar métricas de uso para el benchmark. Nota: en v2 los plugins de v1 **no se ejecutan**.

🟢 **Portabilidad**: al ser MCP estándar, el mismo servidor sirve para Claude Code, Cursor u otros clientes. Conviene documentar al menos un segundo cliente.

---

## 7. Otras ideas de valor

| Idea | Prioridad | Descripción |
|---|---|---|
| Recetas paramétricas | 🟢 | Plantillas de diseño (caja con tapa, soporte en L, brida, engranaje, carcasa para PCB) como scripts `.iacs` parametrizados en el skill. |
| `iacad diff` semántico | 🟢 | Diff por features, parámetros y geometría (Δ volumen, Δ bbox) entre revisiones o commits de git. |
| Integración con git | 🟡 | *textconv* o *merge driver* para `.iacad` que muestre diffs semánticos en `git diff`. |
| Checks de fabricación | 🟡 | Voladizos y puentes para FDM, espesor mínimo, radios de herramienta en CNC, ángulos de desmoldeo. |
| Informe de entrega automático | 🟢 | `iacad report`: Markdown o PDF con brief, requisitos verificados, renders, BOM, masas y archivos exportados con su hash. |
| Importar boceto o foto de referencia | 🟡 | Guardar la imagen en `assets/` y usar `render --compare-to` para la comparación visual. |
| Tolerancias y ajustes ISO 286 | 🟡 | Calcular diámetros de taladros y ejes a partir de ajustes (H7/g6…), con tablas normalizadas. |
| Chapa metálica | ⚪ | Plugin `sheet_metal` (pliegues, desarrollos a DXF). |
| Ejecución de scripts en sandbox | 🟡 | Si se habilita la feature `script`: subproceso con límites de CPU, memoria y tiempo, sin red y con el sistema de archivos restringido; validación previa tipo "safe mode". |
| Telemetría local anónima | ⚪ | Contar errores por código para mejorar mensajes y documentación (opcional, desactivada por defecto). |

---

## 8. Resumen de las 10 recomendaciones más importantes

1. **build123d 0.13 (modo Algebra) sobre OCP/OCCT 8**, detrás de un `KernelAdapter` propio, en Python 3.12–3.13.
2. **Pocas herramientas MCP genéricas**, con `structuredContent`, errores accionables y documentación bajo demanda.
3. **Nombres persistentes + selectores con `expect` + huellas** desde el primer día. Es el mayor riesgo técnico.
4. **Checks numéricos y asserts en el documento** antes que la revisión visual; como mucho 2–3 rondas de corrección.
5. **Brief con requisitos trazables** y journal enlazado a revisiones y exportaciones.
6. **STEP para sólidos; DXF/DWG solo para 2D y mallas** (limitación ACIS). DWG mediante LibreDWG por CLI.
7. **Herramientas GPL (Gmsh, CalculiX, Blender, LibreDWG) solo como subprocesos**, con control de licencias en CI.
8. **Visor web read-only con three-cad-viewer**, que muestre IDs persistentes copiables; `ocp_viewer` como prototipo.
9. **Configuración para OpenCode v1 y v2**, skill en `.opencode/skills/iacad/`, imágenes de ≤1024 px y trabajos largos asíncronos.
10. **Benchmark de agentes desde la Fase 1** para medir y mejorar herramientas, errores y skill con datos.
