# Word template tags

Reports are generated with [docxtpl](https://docxtpl.readthedocs.io/): the `.docx` templates
in this folder contain Jinja tags that are filled from the report. Edit the templates in Word;
the values come from `reports/services/report_render.py::build_context`.

## Tag syntax

| Tag | Use |
|---|---|
| `{{ client }}` | Insert a value. |
| `{%p for s in setups %}` … `{%p endfor %}` | Repeat the paragraphs (and tables) between two tag-only paragraphs. |
| `{%tr for r in scans %}` … `{%tr endfor %}` | Repeat a table row; each tag sits alone in its own row. |
| `{%p if figures.drawings %}` … `{%p endif %}` | Keep a block only when there is something to show. |
| `{{r t.text }}` | Insert formatted (rich) text. |

Rules that avoid broken templates:
- Type each tag in one go, and don't format part of a tag (Word splits differently
  formatted text into separate runs, which breaks the tag).
- `{%p … %}` and `{%tr … %}` tags must be the only thing in their paragraph / row.
- Units are written in the template where the value is a bare number: `{{ s.x_res }}` already
  adds `"` when needed, so don't type another `"` after it.

## Variables

**Report**

| Variable | Content |
|---|---|
| `client`, `location`, `work_order`, `project_number`, `project_type`, `equipment_id` | Report fields (`project_number` shows `N/A` when blank). |
| `document_title`, `document_title_upper` | Report title, and the same in capitals for the cover. |
| `report_date_long` | e.g. `3 September, 2026` (cover and footer). |
| `test_dates` | e.g. `8/13/2026 – 8/25/2026`, or one date when there is no end date. |
| `procedures` | Each setup's procedure once, in setup order (falls back to the report's Procedure lines). |
| `examination_scope`, `executive_summary`, `access`, `work_scope`, `asset_description` | Multi-paragraph text (blank line = new paragraph). |
| `x_axis_reference`, `y_axis_reference` | Scan direction references. |
| `prepared_by`, `examined_by`, `reviewed_by` | People ticked for each role in the editor's Personnel section: `p.name`, `p.certification`. |
| `techniques` | List of technique bullets: `{{r t.text }}`. |

**Setups** — `{%p for s in setups %}`, one "Equipment Details" section each

`s.title`, `s.equipment_type`, `s.scope_model`, `s.scope_serial`, `s.x_res`, `s.y_res`,
`s.transducer_model`, `s.transducer_serial`, `s.foc_depth`, `s.wave_mode`, `s.freq`,
`s.elements`, `s.cal_material`, `s.material_temp`, `s.cal_block`, `s.surface_prep`,
`s.tr_min`, `s.tr_max`, `s.procedure`, `s.images` (calibration screenshots).

`s.title` is the setup's Technique title (e.g. "HydroFORM"), falling back to its beam
formation or probe model; `s.procedure` falls back to the report's Procedure; `s.images` are
the setup's calibration screenshots at 3.45" wide (two per line).

**Results** — `{%tr for r in scans %}`

Keys follow the report type's `results_columns` (`reports/report_types.py`); for HIC:
`results_title`, `r.scan_id`, `r.orientation`, `r.x_range`, `r.y_range`, `r.avg_thk`,
`r.min_thk`, `r.is_min` (true for the thinnest reading, which is highlighted yellow),
`r.comments`.

**Photo summary** — `{%p for r in scan_images %}`, one image block each

`r.image`, `r.scan_id`, `r.comments`. Built from the editor's Photo summary uploads in
results-table order: each image's comments come from the results row with the same Scan ID;
images not tied to a row follow, labelled with their own label.

**Figures** — lists of `f.title` + `f.images`
- `figures.drawings`: the editor's Equipment drawings uploads (shown under DRAWING).

## Fields Word updates on open

The generated file asks Word to update fields when opened, which refreshes the table of
contents, "Total Pages", page numbers and the page reference in the cover summary.
