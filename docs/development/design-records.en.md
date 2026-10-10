# Design Records

[中文](design-records.md) | English · [Documentation](../README.en.md)

`design_docs/` is an archive of the design process for developers:

| Directory/File | Contents |
|---|---|
| `Memory *Specification v1.0.md` | Original memory-system specification (Schema / Consolidation / Retrieval / Policy Matrix / Evaluation & Debug) |
| `Migration & Implementation Plan.md` | v1 -> v2 migration plan |
| `Memory Verification Loop.md` | Design of the proactive acquisition loop |
| `check_point/` | Key decision points: problems, diagnostic process, disproven hypotheses, and empirical data |
| `bug_report/` | Defect analysis |
| `logs/` | Archives of terminal output and runtime logs |

Difference from `docs/`: `docs/guides`, `architecture`, `reference`, and `development` contain maintained documentation; `plans`, `reports`, and `migration` are dated archives, while `design_docs/` contains process records, including disproven hypotheses and failed attempts. That information is important for understanding "why things are the way they are now", but is not suitable for user documentation.
