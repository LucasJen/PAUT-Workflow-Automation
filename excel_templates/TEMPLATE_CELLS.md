# Excel report templates

## paut_weld.xlsx — PAUT weld report (form 100-UTFORM-010 rev 1.3)

Built from the reference report `PPI-31-37575-W5&W6-6inch.xlsx` by clearing the job data and
removing the lookup sheets (setup export, Probe Table, Scope and Encoder, Cal Block Table, All
Probes) and its scan plan sheet. The app writes final values into the cells through Excel; the
template has no lookups. The cell map lives in `reports/services/excel_report.py`.

Sheets:

- **Report** (page 1): header, project information, equipment and group settings, material
  and calibration blocks, results rows 41–52, notes, technician and reviewer.
- **Indication**: master page, copied once for each results row that has a flaw Type. The
  app fills the Weld Number (C57), Indication Number (L57), Notes (C60) and the picture area
  (A12:Z56).
- **Continuation**: results rows 15–47, used only when the results don't fit on the Report
  page.
- **Scan Plan** (last page, only when the report has a scan plan): the Indication layout with
  the report's scan plan drawings side by side in the picture area (A12:Z56), the Scan Plan
  name (C57), Pipe Size (L57) and Notes (C60). The reference's own scan plan sheet is password
  protected, so this page is built from the Indication sheet instead.

The header cells on Indication and Continuation link to the Report sheet
(`=IF(Report!X2="","",Report!X2)`), so editing the Report header in the downloaded file
updates every page. The page numbers (X4 / Z4) on each sheet are written by the app.

To change the template's look, edit it in Excel and keep the cell positions. If cells move,
update the cell map in `excel_report.py` to match.
