# OmniPC readings for checking the Analysis page

The Analysis page builds every view and reading from the A-scan samples in the .nde file. To prove
the numbers match OmniPC, record what OmniPC shows for a few positions in real files and save them
here as JSON in `omnipc_readings/` (one file per .nde file). Tests compare against them and are
skipped on a PC that doesn't have the .nde file.

## How to record a point in OmniPC
1. Open the file, pick the group, and set **soft gain to 0 dB** (note it if you can't).
2. Put the scan cursor on a scan position and the angle / index cursor on a beam with a clear
   signal in gate A.
3. Write down the scan position number (or the scan position in the units shown), the beam
   (angle, or VPA / index position), and the readings OmniPC lists: A%, A^, SA^, DA^, PA^, ViA^
   (and B% etc. when gate B is used, or thickness on 0 deg files).
4. Note the units (in or mm) and whether depths are true depth or half path.

A couple of points per file is plenty: one strong reflector and one near the back wall works well.

## File format (`omnipc_readings/<any name>.json`)
```json
{
  "file": "001 Welds/FHR-101-44812-W1&2-2in/Fhr 101-44812 w1.nde",
  "group": 0,
  "units": "in",
  "notes": "Soft gain 0 dB, true depth",
  "points": [
    {
      "scan": 105,
      "beam": 12,
      "angle": 55.0,
      "gate": "A",
      "expected": {"A%": 78.4, "SA^": 1.234, "DA^": 0.512, "PA^": 0.456, "ViA^": 0.321},
      "tolerance": {"A%": 1.0, "SA^": 0.01, "DA^": 0.01, "PA^": 0.01, "ViA^": 0.01}
    }
  ]
}
```
- `file`: relative to `~/Desktop/Reports`, or a full path.
- `scan`: the scan position number (0 = first). Use `"scan_position"` (in the file's units) instead
  if that's what OmniPC showed.
- `beam`: the beam number (0 = first), or give just `angle` for a sectorial scan; for a raster file
  give `"index"` (the index position number).
- `expected` keys are OmniPC's reading names; leave out any you didn't record.
- `tolerance` is per reading, in the same units. Don't widen one to make a test pass: a difference
  is something to explain.
