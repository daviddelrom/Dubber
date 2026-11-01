---
type: constitution
title: Dubber — Constitution
description: Ratified non-negotiable principles for future development.
tags: [sdd, constitution]
timestamp: 2026-11-01T13:42:00Z
topic: sdd
status: ratified
version: v1.0.0
---

# Dubber — Constitution

> Ratificada: 2026-11-01 · Última modificación: 2026-11-01. Estas reglas son los límites verificables para el trabajo futuro.

## Principios

1. **Stack:** Python 3.11+, FastAPI, SQLite/SQLModel y Jinja/HTMX son el stack actual. Sus dependencias y versión mínima están en `pyproject.toml`. Un cambio de framework web, motor de datos o lenguaje requiere una decisión documentada antes del merge.
2. **Calidad:** `.venv/bin/python -m pytest` debe pasar antes del merge. Los cambios de comportamiento incluyen pruebas del comportamiento afectado; las integraciones con `mkvmerge` se validan con archivos MKV reales cuando sea viable. No se fija cobertura mínima ni linter mientras el proyecto no los configure.
3. **Límites de arquitectura:** la lógica de `dubber/core/` permanece independiente de la web y de la base de datos. El acceso a datos, trabajos y HTTP se mantiene en `db/`, `jobs/` y `web/`, respectivamente; un cambio que cruce estos límites debe justificarlo en revisión. Detalle: `02-DOCS/wiki/project/architecture.md`.
4. **Ramas y autoría:** todo cambio de código se desarrolla en una rama y se integra mediante pull request; no se trabaja directamente en la rama predeterminada. Los commits y el PR pertenecen a la persona responsable, no se atribuyen a una IA.
5. **Seguridad local:** el servidor solo escucha en `127.0.0.1`; los procesos externos se invocan con argumentos separados, nunca mediante shell; no se guardan secretos en el repositorio. Estos puntos deben seguir cubiertos por pruebas o revisión.
6. **Mezclas seguras:** una coincidencia dudosa o con duración desconocida requiere aprobación explícita. Una salida temporal solo sustituye al resultado final cuando `mkvmerge` termina correctamente; cancelar o fallar no debe dejar un resultado parcial presentado como válido.
7. **UX de trabajos largos:** escaneos y mezclas muestran estado y progreso; errores y cancelaciones quedan visibles para la persona usuaria.
8. **Decisiones:** cada decisión técnica significativa se registra con fecha, opciones consideradas y motivo en `02-DOCS/wiki/project/decisions.md` o, si afecta el proceso SDD, en `02-DOCS/wiki/sdd/decisions.md`.

## Definición de hecho

Un cambio está listo para merge cuando:

- [ ] `.venv/bin/python -m pytest` pasa y se han añadido pruebas para el comportamiento nuevo o modificado.
- [ ] La revisión confirma los principios aplicables, en particular seguridad y mezcla segura.
- [ ] Se actualizó la documentación pertinente y se registraron las decisiones significativas.
- [ ] El cambio está en una rama y se propone mediante pull request.

## Enmiendas

| Fecha | Versión | Cambio | Motivo |
|---|---|---|---|
| 2026-11-01 | v1.0.0 | Ratificada la propuesta inicial. | Acordar reglas verificables para el desarrollo futuro. |
