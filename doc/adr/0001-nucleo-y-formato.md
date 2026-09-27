# ADR 0001: núcleo y formato del MVP

**Estado:** aceptada para Fases 0–1 · 2026-09-27

Python 3.12–3.13, build123d 0.13/OCCT 8 (tras un adaptador propio), y documentos `.iacad` JSON UTF-8 con versión `1.0` y features ordenadas. MCP por stdio y CLI invocan las mismas operaciones; la geometría de exportación se regenera, nunca se almacena en el documento.

La primera rebanada implementa piezas 3D (caja, cilindro, booleanas) y parámetros de longitud. Las demás features, el solver, nombres persistentes completos, visor, ensamblajes, planos y simulación siguen el calendario de [Planning.md](../Planning.md); no se aceptan silenciosamente comandos todavía no implementados. Registros JSONL y comprobación geométrica se incorporan desde la primera rebanada.

Motivación: verificar pronto un diseño real creado por un agente desde OpenCode y exportado como STEP sin acoplar la API pública a build123d. Alternativas y restricciones de licencia: [Recomendaciones.md](../Recomendaciones.md).
