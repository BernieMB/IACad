# IACad

CAD paramétrico **sin interfaz de edición** para agentes que trabajan desde OpenCode. Ya permite crear proyectos con requisitos y piezas con primitivas, croquis con ranuras y polígonos regulares, extrusión, revolución, loft o barrido de croquis 2D, taladros ciegos/pasantes, corte por plano, espejo de cuerpos, vaciado y patrones lineales/circulares de sólidos, y exportación a STEP/STL/3MF/GLB. El historial editable se guarda en `.iacad` (JSON); los sólidos exportados y las mallas son derivados.

El diseño y las fases previstas están en [doc/Planning.md](doc/Planning.md), [doc/Modelo.md](doc/Modelo.md) y [doc/Requisitos.md](doc/Requisitos.md). Consulta [doc/Estado.md](doc/Estado.md) para saber exactamente qué funcionalidades ya funcionan.

## Instalar (Python 3.12 o 3.13)

```powershell
uv sync
uv run iacad help
uv run pytest -q
```

## Primera pieza

```powershell
uv run iacad new parts/demo.iacad --name "Placa con orificio"
uv run iacad exec parts/demo.iacad --script examples/placa.iacs
uv run iacad query parts/demo.iacad summary
uv run iacad export parts/demo.iacad --format step --out out/placa.step
uv run iacad export parts/demo.iacad --format stl --out out/placa.stl
uv run iacad export parts/demo.iacad --format 3mf --out out/placa.3mf
uv run iacad export parts/demo.iacad --format glb --out out/placa.glb
uv run iacad history parts/demo.iacad
uv run iacad undo parts/demo.iacad
uv run iacad redo parts/demo.iacad
```

También puedes enviar comandos JSON desde un agente con `iacad exec --commands '[{"cmd":"feature.box","args":{"id":"caja","body":"principal","length":"40 mm","width":"30 mm","height":"6 mm"}}]'`.

## Croquis y extrusión (primera rebanada de Fase 2)

```powershell
uv run iacad new parts/soporte.iacad --name "Perfil en L"
uv run iacad exec parts/soporte.iacad --script examples/perfil_l.iacs
uv run iacad query parts/soporte.iacad summary
uv run iacad export parts/soporte.iacad --format step --out out/soporte.step
```

`examples/placa_croquis.iacs` dibuja un rectángulo y un círculo interior en XY y extruye la placa con el orificio en una sola operación; `examples/perfil_l.iacs` dibuja un perfil en XZ y lo extruye simétricamente (normal del plano: **−Y**). En cada croquis se admite **un exterior y huecos interiores cerrados** (rectángulos, círculos, polilíneas, ranuras o polígonos regulares); restricciones geométricas, varios perfiles exteriores y referencias a caras son posteriores.

### Ranura paramétrica (orificio alargado)

```powershell
uv run iacad new parts/ranura.iacad --name "Placa ranurada"
uv run iacad exec parts/ranura.iacad --script examples/placa_ranura.iacs
uv run iacad export parts/ranura.iacad --format step --out out/ranura.step
```

`sketch.slot sketch=perfil id=ranura center='[30,15]' length=ranura_l width=ranura_a angle=giro` crea un contorno cerrado con dos extremos semicirculares. `length` es la **longitud total exterior** de la ranura, `width` es su anchura y el diámetro de cada extremo; requiere `length > width > 0`. `center` son las coordenadas **locales del croquis**; `angle` gira la ranura en su plano desde el eje local X (predeterminado `0 deg`) y admite expresiones/`param.set kind=angle`. Puede ser el contorno exterior o un hueco dentro de otro contorno, en XY/XZ/YZ y con offset. El ejemplo hace una placa 60 × 30 × 5 mm con ranura de 24 × 6 mm a 30° y volumen exacto `(1800−108−9π)·5 mm³`.

### Polígono regular (tuerca hexagonal)

```powershell
uv run iacad new parts/tuerca.iacad --name "Tuerca hexagonal"
uv run iacad exec parts/tuerca.iacad --script examples/tuerca_hexagonal.iacs
uv run iacad export parts/tuerca.iacad --format step --out out/tuerca.step
```

`sketch.polygon sketch=perfil id=hexagono side_count=6 radius=radio angle=giro` crea un contorno cerrado de **3 a 64 lados**. `radius` es un circunradio (del centro a cada vértice) por defecto; con `radius_type=inradius` indica la apotema (centro a cada lado). `center` usa coordenadas locales del croquis, predeterminado `[0,0]`; `angle` gira el **primer vértice** desde +X local, predeterminado `0 deg`. Radio y ángulo admiten parámetros con unidades; `side_count` es un entero explícito en la definición del croquis. Se puede usar como exterior o como hueco, en XY/XZ/YZ con offset. El ejemplo extruye un hexágono de R10 mm y espesor 6 mm con agujero pasante R4 mm; volumen exacto `(150√3−16π)·6 mm³`.

### Revolución de un croquis (casquillo)

```powershell
uv run iacad new parts/casquillo.iacad --name "Casquillo hueco"
uv run iacad exec parts/casquillo.iacad --script examples/casquillo_revolucion.iacs
uv run iacad query parts/casquillo.iacad params
uv run iacad render parts/casquillo.iacad --views four --out out/casquillo.png
uv run iacad export parts/casquillo.iacad --format step --out out/casquillo.step
```

`feature.revolve` recibe un `axis` **explícito en coordenadas globales**, por ejemplo `{"origin":[0,0,0],"dir":[0,1,0]}`, y `angle` entre 0 y 360°. El eje debe estar en el plano del croquis; un perfil que lo atraviese se rechaza antes de guardarlo. El ejemplo gira un rectángulo XY a radios 5–10 mm sobre +Y: el volumen exacto esperado es `1500π mm³`. Declara giros editables con `param.set name=giro value="90 deg" kind=angle` (también admite `rad`); `query ... params` devuelve `parameters_deg` además de `parameters_mm`.

### Loft entre croquis paralelos (cono truncado)

```powershell
uv run iacad new parts/cono.iacad --name "Cono truncado"
uv run iacad exec parts/cono.iacad --script examples/cono_truncado.iacs
uv run iacad render parts/cono.iacad --views four --out out/cono.png
uv run iacad export parts/cono.iacad --format step --out out/cono.step
```

`sketch.new` admite `offset` en unidades de longitud: desplaza el croquis por la normal del plano (**XY → +Z**, **XZ → −Y**, **YZ → +X**). También afecta correctamente a extrusión y revolución; el eje de revolución debe estar en el plano **desplazado**. `feature.loft sections='["base","corona"]' ruled=true op=new_body body=principal` crea un sólido entre al menos dos secciones del **mismo tipo de plano**, con offsets distintos y ordenados. `ruled=true` (predeterminado) da caras rectas por tramos; `false` suaviza el paso entre tres o más secciones. Las secciones con huecos deben tener el mismo número de huecos; el kernel los empareja por proximidad y puede ser ambiguo cuando varios agujeros están muy juntos. El ejemplo une radios de 10 y 5 mm separados 20 mm: volumen exacto `3500π/3 mm³` (≈3665.19 mm³). El loft admite `op=new_body|join|cut|intersect` y se regenera al cambiar radios, altura u offsets.

### Barrido por trayectoria 3D (tubo acodado)

```powershell
uv run iacad new parts/tubo.iacad --name "Tubo acodado"
uv run iacad exec parts/tubo.iacad --script examples/tubo_acodado.iacs
uv run iacad render parts/tubo.iacad --views four --out out/tubo.png
uv run iacad export parts/tubo.iacad --format step --out out/tubo.step
```

`feature.sweep` barre un croquis cerrado (admite huecos) a lo largo de `path={"points":[[0,0,0],[0,0,10],[20,0,10]],"transition":"right"}`: **2–64 puntos globales 3D** con expresiones de longitud. El primer punto debe pertenecer al plano del croquis, incluso con `offset`, y el primer segmento debe seguir su normal (también en sentido inverso); se rechazan tramos de longitud nula. `transition="right"` (predeterminada) genera esquinas a inglete; `"round"` las redondea. No se expone la transición predeterminada `TRANSFORMED` de OCCT/build123d porque puede omitir tramos de una ruta en L sin dar error. El ejemplo barre una corona circular de radios 4 y 2 mm a lo largo de 10+20 mm: volumen exacto **360π mm³**. `op=new_body|join|cut|intersect` reutiliza las booleanas paramétricas. Este barrido utiliza rutas poligonales definidas en la feature; splines, guías y entidades de ruta independientes quedan para más adelante.

### Patrón lineal de taladros o salientes

```powershell
uv run iacad new parts/patron.iacad --name "Placa con cuatro taladros"
uv run iacad exec parts/patron.iacad --script examples/placa_patron_lineal.iacs
uv run iacad render parts/patron.iacad --views four --out out/patron.png
uv run iacad export parts/patron.iacad --format step --out out/patron.step
```

`feature.pattern_linear` usa un cuerpo-herramienta `source` ya creado, distinto del cuerpo `target`; admite `op=cut|join`, `count=2..64`, `spacing` positivo y `direction` 3D (se normaliza). **`count` incluye la primera instancia en la posición original**: el ejemplo talla 4 taladros de radio 2 mm en una placa de 60 × 20 × 5 mm con paso 12 mm, volumen `6000−80π mm³`. Por defecto `keep_tool=false` consume el cuerpo auxiliar (solo queda el destino); con `keep_tool=true` conserva ambos, lo cual afecta al requisito de un cuerpo para exportar. Cada copia debe modificar el destino y el resultado debe ser un solo sólido: una perforación fuera de la placa o un saliente sin conexión causa error y rollback. Tras el patrón se invalidan los `ref` semánticos del destino; vuelve a consultar `topology` antes de editar sus caras. Este primer patrón repite **el cuerpo-herramienta**, no una lista de features arbitrarias.

### Patrón circular alrededor de un eje

```powershell
uv run iacad new parts/brida.iacad --name "Brida de cuatro taladros"
uv run iacad exec parts/brida.iacad --script examples/brida_patron_circular.iacs
uv run iacad render parts/brida.iacad --views four --out out/brida.png
uv run iacad export parts/brida.iacad --format step --out out/brida.step
```

`feature.pattern_circular` también repite un **cuerpo-herramienta** contra `target`, con `op=cut|join`, `count=2..64`, `axis={"origin":[0,0,0],"dir":[0,0,1]}` global y `angle` parametrizable en grados o radianes. El eje no necesita estar dentro de un croquis, pero sí debe ser finito y no nulo. Con `angle=360 deg`, el paso es `360/count` y **no** se duplica la primera copia en 360°; con un arco menor se incluyen los dos extremos (`angle/(count-1)`). La herramienta original es la primera instancia, y se consume salvo `keep_tool=true`. El ejemplo hace 4 taladros R2 sobre un círculo de pernos R15 en una placa de 50 × 50 × 5 mm: volumen `12500−80π mm³`. Se comprueban efectos y validez de cada copia; si no corta o une, se revierte todo.

### Taladros directos pasantes y ciegos

```powershell
uv run iacad new parts/taladros.iacad --name "Placa taladrada"
uv run iacad exec parts/taladros.iacad --script examples/placa_taladros.iacs
uv run iacad export parts/taladros.iacad --format step --out out/taladros.step
```

`feature.hole id=pasante target=principal diameter="8 mm" axis='{"origin":[15,15,10],"dir":[0,0,-1]}'` resta un cilindro sobre un **eje global explícito**. `diameter` debe ser positivo; `axis.origin` admite coordenadas o parámetros de longitud y `axis.dir` es un vector 3D finito, sin unidades y no nulo (se normaliza). `mode=through` predeterminado prolonga la herramienta en ambos sentidos a través de toda la caja envolvente del cuerpo: el origen puede estar sobre una cara o en el interior. `mode=blind depth="4 mm"` mide la profundidad **desde el origen hacia `dir`** y crea un fondo plano; sitúa el origen en la cara de entrada. Si la profundidad supera el espesor local, el corte puede atravesar la pieza. Si el taladro no corta o divide el cuerpo en varios sólidos, falla y no se guarda. El ejemplo de placa 60 × 30 × 10 mm con un taladro Ø8 pasante y otro de 4 mm de profundidad tiene volumen exacto **`18000−224π mm³`**. Tras taladrar, las referencias semánticas anteriores del cuerpo dejan de atribuirse; consulta `topology` antes de seleccionar caras/aristas.

### Corte paramétrico por plano (conservar un lado)

```powershell
uv run iacad new parts/recorte.iacad --name "Placa recortada"
uv run iacad exec parts/recorte.iacad --script examples/placa_cortada.iacs
uv run iacad export parts/recorte.iacad --format step --out out/recorte.step
```

`feature.split id=recorte target=principal plane='{"origin":[20,0,0],"normal":[1,0,1]}' keep=positive` corta **todo el sólido** con un plano global: `origin` admite longitudes y parámetros; `normal` es un vector 3D finito, sin unidades y no nulo (se normaliza). `positive` (predeterminado) conserva los puntos donde `dot(normal, punto−origin) ≥ 0`; `negative` conserva el lado contrario. El resultado **sustituye al cuerpo `target`** y mantiene su ID, por lo que sigue siendo exportable como un único cuerpo; la mitad descartada no se guarda. Se rechazan planos fuera del sólido, lados vacíos y resultados con varios sólidos, con rollback. El ejemplo recorta una caja 40 × 30 × 10 mm con `x+z=20`: volumen **7500 mm³**, bbox X **10..40 mm**. Tras recortar se invalidan las referencias semánticas anteriores del destino; vuelve a consultar `topology`.

### Espejo de un cuerpo respecto de un plano

```powershell
uv run iacad new parts/simetria.iacad --name "Placa simétrica"
uv run iacad exec parts/simetria.iacad --script examples/placa_simetrica.iacs
uv run iacad export parts/simetria.iacad --format step --out out/simetria.step
```

`feature.mirror id=espejo source=principal body=reflejado plane='{"origin":[0,0,0],"normal":[1,0,0]}'` refleja **todo el sólido** sobre el plano global que pasa por `origin` y es perpendicular a `normal` (vector 3D finito, sin unidades y no nulo; se normaliza). Las coordenadas de `origin` aceptan parámetros de longitud. El original **se conserva** y el espejo recibe un ID de cuerpo nuevo, sin nombres topológicos heredados; ambos pueden combinarse con `feature.boolean` (`op=union|cut|intersect`). El ejemplo refleja una media placa sobre YZ (`x=0`) y hace `op=union`, con volumen exacto **1536 mm³**. Para exportar STEP/STL/3MF/GLB en esta fase debe quedar **un solo cuerpo**. Tras unir o intersectar cuerpos, vuelve a consultar la topología: los nombres de origen del destino se invalidan para no atribuir a la pieza original caras creadas por la copia.

### Vaciado de un sólido (caja abierta)

```powershell
uv run iacad new parts/caja_vaciada.iacad --name "Caja abierta"
uv run iacad exec parts/caja_vaciada.iacad --script examples/caja_vaciada.iacs
uv run iacad query parts/caja_vaciada.iacad summary
uv run iacad export parts/caja_vaciada.iacad --format step --out out/caja_vaciada.step
```

`feature.shell` toma un cuerpo `target`, un `thickness` positivo y `remove_faces` con `expect` obligatorio. Admite `direction="inward"` (predeterminado: conserva las dimensiones exteriores) y `"outward"` (expande el exterior). El ejemplo abre `@base/face:zmax` en una caja de 40 × 30 × 20 mm con paredes de 2 mm; el volumen exacto es **7152 mm³**. Para seleccionar por geometría, usa `remove_faces='?principal/faces[+Z]' expect=one` o, desde JSON/MCP, `{"query":{"scope":"principal","kind":"face","where":"+Z"},"expect":"one"}`. El vaciado admite varias caras abiertas con `refs` y `expect` apropiado. **Después de vaciar, vuelve a consultar la topología:** las referencias semánticas de la primitiva se invalidan para no atribuir a la tapa retirada el nuevo aro de la abertura. Si el espesor es imposible, falla sin alterar la pieza.

### Inspeccionar y editar aristas

```powershell
uv run iacad new parts/caja.iacad --name "Caja redondeada"
uv run iacad exec parts/caja.iacad --script examples/caja_redondeada.iacs
uv run iacad query parts/caja.iacad topology --body principal --kind edge --limit 20
```

`feature.fillet` y `feature.chamfer` requieren una selección de aristas con `expect` (cardinalidad obligatoria). Para una arista de caja se puede usar `@base/edge:xmax&ymax`; para un conjunto, una consulta como `|Z and >X` con `expect` adecuado. Las referencias geométricas se vuelven a resolver en cada regeneración: si una arista deja de existir o deja de ser única, la operación falla y el documento no cambia. **Los nombres completos después de cambios arbitrarios de topología aún están pendientes**; consulta `ref` y filtros en `iacad query ... topology` antes de editar.

### Previsualización técnica headless

```powershell
uv run iacad render parts/caja.iacad --views four --size 768 --out out/caja-cuatro-vistas.png
```

También se admiten `iso`, `front`, `top` y `right`. `iacad_render` entrega el PNG como imagen MCP y como ruta, para que el agente lo examine. Se trata de un render técnico rápido de la malla, **no de una medida exacta**; `iacad validate` proporciona cotas y propiedades calculadas por el kernel.

Para probar cambios reversibles: `uv run iacad checkpoint parts/demo.iacad antes_de_editar`; después se puede usar `uv run iacad restore parts/demo.iacad antes_de_editar`. Las revisiones se guardan bajo `.iacad/revisions/` y no alteran la definición paramétrica.

## Proyecto y requisitos

```powershell
uv run iacad new proyecto.iacad --name "Placa mecanica" --kind project
uv run iacad exec proyecto.iacad --script examples/proyecto.iacs
uv run iacad query proyecto.iacad brief
```

Para enlazar `parts/demo.iacad`, envía al proyecto el comando `project.link` con `path: "parts/demo.iacad"` y el **`uid` que devolvió `iacad new`** para la pieza. La validación impide confirmar rutas fuera del proyecto, piezas faltantes y UIDs incorrectos. `project.requirement` puede actualizar un requisito existente y añadir referencias de evidencia como `parts/demo.iacad#check:cotas`; comprueba por separado si el check pasa.

La caché descartable de B-Rep vive en `.iacad/cache/`. La respuesta de `exec` y `validate` indica `cache.hits` y `cache.misses`; los archivos de caché se verifican con SHA-256 antes de pedir a OCCT que los lea.

`iacad mcp` inicia un servidor MCP por **stdio**. Para conectarlo a OpenCode v1 copia el ejemplo de [`examples/opencode.v1.json`](examples/opencode.v1.json) a la configuración de tu proyecto y ajusta `--project` a la ruta de este repositorio. Tras cambiar esa configuración, **reinicia OpenCode** para cargar el servidor y el [skill](.opencode/skills/iacad/SKILL.md).

Si trabajas **dentro de una sesión de OpenCode que ya lanzó el MCP**, Windows puede bloquear `.venv/Scripts/iacad.exe` durante `uv sync`. En ese caso, `uv lock` actualiza el lockfile y `uv run --no-sync pytest -q` permite verificar mientras sigues conectado; para instalar las nuevas dependencias, cierra OpenCode y ejecuta `uv sync` antes de abrirlo otra vez.

Las rutas de documento, script y exportación deben estar dentro del directorio de trabajo (o de `IACAD_WORKSPACE`). `iacad exec` y `iacad validate` comprueban geometría sin guardar cambios si falla algún comando. `--dry-run` nunca escribe el documento.

Los **plugins** pueden ampliar el registro de comandos y features con un *entry point* `iacad.plugins`: la función registrada recibe `(register_command, register_feature)`. Consulta [`examples/plugin_sphere.py`](examples/plugin_sphere.py); el paquete externo declara en su `pyproject.toml`:

```toml
[project.entry-points."iacad.plugins"]
esfera = "plugin_sphere:setup"
```

Licencia del código original: Apache-2.0. OCCT/build123d conservan sus propias licencias (consulta `NOTICE`).
