| ID | sha8 | clase | cuar | motivo GT | leído inicio→fin (días) | span/desfase | veredicto motor | códigos | severidad | cobertura | puntaje |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `F01` | `8b682a83` | falsa |  | FIRMA_MEDICO | 2026-07-14 → 2026-07-14 (1) | 1/0 | **COHERENTE** | — | — | 0.85 | 100 |
| `F02` | `5c66d97e` | falsa |  | DX_INEXISTENTE | — → 2026-05-18 (1) | —/— | **COHERENTE** | — | — | 0.39 | 100 |
| `F03` | `28c4a946` | falsa | SÍ | TIPOGRAFIA_MIXTA | — → — (4) | —/— | **COHERENTE** | — | — | 0.31 | 100 |
| `F04` | `e0ee54fd` | falsa |  | FECHAS_INCOHERENTES | — → — (2) | —/— | **COHERENTE** | — | — | 0.39 | 100 |
| `F05` | `8aeee4cd` | falsa |  | DIAS_VS_DIAGNOSTICO | 2025-11-10 → 2025-11-11 (2) | 2/0 | **COHERENTE** | — | — | 0.85 | 100 |
| `F06` | `9dcb4e35` | falsa |  | SIN_MOTIVO_REGISTRADO | 2025-09-15 → — (2) | —/— | **COHERENTE** | — | — | 0.54 | 100 |
| `F07` | `9603c77b` | falsa |  | DX_NOMBRE_DISTINTO | 2026-04-20 → 2026-04-20 (1) | 1/0 | **COHERENTE** | — | — | 0.85 | 100 |
| `F08` | `ed2a4eeb` | falsa |  | FIRMA_MEDICO | 2025-10-31 → 2025-11-01 (2) | 2/0 | **COHERENTE** | — | — | 0.85 | 100 |
| `F09` | `d5b72739` | falsa |  | DX_INEXISTENTE, DX_FORMATO | 2026-06-05 → 2026-07-06 (2) | 32/30 | **REVISAR** | T01_DURACION_VS_RANGO | GRAVE | 0.92 | 60 |
| `F10` | `717d3aad` | falsa |  | DX_INEXISTENTE | 2026-06-09 → 2026-06-10 (2) | 2/0 | **COHERENTE** | — | — | 0.92 | 100 |
| `F11` | `d86ae595` | falsa | SÍ | DX_INEXISTENTE | — → 2026-05-14 (2) | —/— | **COHERENTE** | — | — | 0.46 | 100 |
| `F12` | `d08cba3f` | falsa |  | SIN_MOTIVO_REGISTRADO | — → — (—) | —/— | **SIN_DATOS** | — | — | 0.08 | 100 |
| `F13` | `99d74f47` | falsa |  | DX_NOMBRE_DISTINTO | — → — (—) | —/— | **SIN_DATOS** | — | — | 0.08 | 100 |
| `F14` | `758d3aff` | falsa |  | SIN_MOTIVO_REGISTRADO | — → — (2) | —/— | **COHERENTE** | — | — | 0.39 | 100 |
| `F15` | `58c1e091` | falsa | SÍ | DX_NOMBRE_DISTINTO | — → — (—) | —/— | **SIN_DATOS** | — | — | 0.08 | 100 |
| `R01` | `d86ae595` | real | SÍ | — | — → 2026-05-14 (2) | —/— | **COHERENTE** | — | — | 0.46 | 100 |
| `R02` | `f858510e` | real |  | — | 2026-06-10 → — (—) | —/— | **COHERENTE** | — | — | 0.39 | 100 |
| `R03` | `b68fe146` | real |  | — | 2026-06-10 → — (—) | —/— | **COHERENTE** | — | — | 0.39 | 100 |
| `R04` | `38f40c48` | real |  | — | 2026-07-12 → — (—) | —/— | **COHERENTE** | — | — | 0.31 | 100 |
| `R05` | `087739e6` | real |  | — | — → — (—) | —/— | **SIN_DATOS** | — | — | 0.08 | 100 |
| `R06` | `eddf194a` | real |  | — | 2026-06-09 → 2026-06-10 (2) | 2/0 | **COHERENTE** | — | — | 0.85 | 100 |
| `R07` | `d6482e2a` | real |  | — | 2026-07-10 → 2026-07-23 (14) | 14/0 | **COHERENTE** | — | — | 0.85 | 100 |
| `R08` | `100e7770` | real |  | — | 2026-06-06 → 2026-06-06 (1) | 1/0 | **COHERENTE** | — | — | 0.85 | 100 |
| `R09` | `aa3512d4` | real |  | — | 2026-06-07 → 2026-10-10 (126) | 126/0 | **COHERENTE** | — | — | 0.85 | 100 |
| `R10` | `e25d5211` | real |  | — | — → — (2) | —/— | **COHERENTE** | — | — | 0.31 | 100 |
| `R11` | `c672e270` | real |  | — | 2026-07-18 → 2026-07-19 (2) | 2/0 | **COHERENTE** | — | — | 0.85 | 100 |
| `R12` | `942de664` | real |  | — | 2026-05-25 → 2026-05-27 (3) | 3/0 | **COHERENTE** | — | — | 0.85 | 100 |
| `R13` | `b6e8beb6` | real |  | — | 2026-05-24 → 2026-06-22 (30) | 30/0 | **COHERENTE** | — | — | 0.92 | 100 |
| `R14` | `691e0af0` | real |  | — | — → 2026-06-11 (3) | —/— | **COHERENTE** | — | — | 0.39 | 100 |
| `R15` | `28c4a946` | real | SÍ | — | — → — (4) | —/— | **COHERENTE** | — | — | 0.31 | 100 |
| `R16` | `272d0d3d` | real |  | — | — → — (—) | —/— | **SIN_DATOS** | — | — | 0.08 | 100 |
