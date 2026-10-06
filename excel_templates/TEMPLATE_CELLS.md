# Excel report templates

## paut_weld.xlsx — PAUT weld report (form 100-UTFORM-010 rev 1.3)

Built from the reference report `PPI-31-37575-W5&W6-6inch.xlsx` by clearing the job data and
removing the lookup sheets (setup export, Probe Table, Scope and Encoder, Cal Block Table, All
Probes). The app writes final values into the cells through Excel; the
template has no lookups. The cell map lives in `reports/services/excel_report.py`.

Sheets:

- **Report** (page 1): header, project information, equipment and group settings, material
  and calibration blocks, results rows 41–52, notes, technician and reviewer.
- **Indication**: master page, copied once for each results row that has a flaw Type. The
  app fills the Weld Number (C57), Indication Number (L57), Notes (C60) and the picture area
  (A12:Z56).
- **Continuation**: results rows 15–47, used only when the results don't fit on the Report
  page.
- **Encoded Scan Plan Images** (last page, only when the report has a scan plan): the reference
  form's own sheet, still password protected. Pictures can be added and its Notes (C20, C37) and
  Page (G4) cells are unlocked; everything else, including the header links to the Report sheet
  and the locked "Insert Scan Plan Image Here" text, is as in the reference. The app puts each
  scan plan drawing in its box (top row: first index offset, bottom row: second; left: 90°
  skew, right: 270°), the plan's notes in C20, "x of y" in G4, and a white cover over unused
  boxes.

The header cells on Indication and Continuation link to the Report sheet
(`=IF(Report!X2="","",Report!X2)`), so editing the Report header in the downloaded file
updates every page. The page numbers (X4 / Z4) on each sheet are written by the app.

To change the template's look, edit it in Excel and keep the cell positions. If cells move,
update the cell map in `excel_report.py` to match.

## paut_corrosion.xlsx — PAUT corrosion report (form 598-PAUTFORM-009 Rev 0)

A copy of `598-PAUTFORM-009 Rev_0 10.7.xlsx` with its sample job values (client, location, work
order on Summary) cleared; the sheets keep their protection (no password), formulas, procedure
dropdown and headers / footers. The app unprotects each sheet, fills it and protects it again.
The cell map lives in `reports/services/corrosion_report.py`.

Sheets:

- **Summary** (page 1): the title ("…on Selected Areas On" + the equipment description), the
  header, Examination Scope, Summary of Results and Notes. Total Pages (AO6) is counted.
- **Setup Information**: master page, copied once per setup. The method (AG2) picks its
  description from the Formulas sheet (B5); a method the form doesn't list leaves it blank. The
  setup's first image goes in B10:AO44.
- **Horizontal Drawing / Vertical Drawing**: masters, copied once per drawing: landscape
  pictures on the horizontal page, portrait ones on the vertical page.
- **Thickness Table**: never printed (the results are the technician's Summary of Results).
- **Images**: master, copied once per two scan images (picture, caption, description each);
  a last page with one image hides its second half.
- **Formulas**: the method descriptions; hidden in the output.
