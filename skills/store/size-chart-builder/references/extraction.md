# Turning any input into the standard CSV

Always end with `chart.csv` in the shape described in `csv-format.md`, show it to the merchant as a table, and ask "Is this right?" before rendering or saving anything.

## Supplier spec sheet (XLSX, CSV, Google Sheet export)

1. Preview it: `python3 scripts/tabular.py supplier.xlsx`. Find the size row or column (sheets are often transposed: sizes across the top, measurements down the side).
2. Map each supplier term to a standard name. Common supplier terms: "1/2 chest", "chest width", "pit to pit" = flat chest (keep flat, basis garment). "Body length", "HPS length", "total length" = length. "Waist relaxed" vs "waist extended": use relaxed and note the stretch. "Tolerance +/-1" rows are not sizes; drop them and mention the tolerance in the fit note.
3. Factory sheets often grade in one unit and print another; check the header unit and a sanity value (a women's M chest flat near 45-55 cm, a body bust near 85-95 cm).

## PDF

Read the table text. If the PDF is a scan, read it like a photo. Watch for columns that shifted during extraction: re-check one full row against the PDF.

## Photo of a spec sheet or a handwritten table

Read every number, then repeat the table back to the merchant before using it. Mark anything unreadable as blank and ask for it. Never guess a blurry digit.

## Photos of flat-measured garments

1. For each photo, note the size label, which measurement the tape shows, and the reading at the edge of the garment (not the tape end).
2. Ask the merchant to confirm any reading you are less than sure of, and which side of the tape is cm.
3. These are garment flat numbers: keep them flat in the CSV and run `body` for guidance.
4. One garment per size is enough; if two samples of the same size differ by more than 1 cm, tell the merchant (factory tolerance) and use the average only if they agree.

## Measurements typed in chat

Accept any order ("M chest 96 waist 80, L chest 100 waist 84"). Build the CSV, repeat it as a table, ask for confirmation.

## Base standard

Copy the matching `assets/base-typical-*.csv`, drop the columns the merchant does not want, and say it is a typical starting point.
