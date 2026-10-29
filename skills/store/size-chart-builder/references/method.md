# Method by hand (when the agent cannot run code)

Use this when scripts cannot run. The results must match what `scripts/sizechart.py` would produce.

## 1. Validate

For each measurement column, read the values from the smallest size to the largest.

1. Size labels: letters must follow XXXS, XXS, XS, S, M, L, XL, XXL, XXXL (3XL), 4XL, 5XL. A skipped letter (S then L) is a gap: say "M missing". Numbers must increase; the smallest step is the normal step, and a jump of about two steps means a size is missing (36, 38, 42: 40 missing).
2. A value going DOWN from one size to the next is an error. Report the column, both sizes and both values.
3. The same value in two sizes: a warning for chest, bust, waist, hip, thigh, neck, shoulder, foot length; just a note for length, sleeve, inseam, rise.
4. Blank cells: warning, never fill them in yourself.
5. Uneven steps: list the steps (differences between neighbouring sizes). Take the median of the positive steps. A step is uneven when it differs from the median by more than the larger of 1 cm (0.5 in) and half the median. Only check this when there are at least 3 steps. Example: chest 92, 96, 100, 112 gives steps 4, 4, 12; median 4; limit max(1, 2) = 2; the 12 step is 8 away, so flag XL to XXL.

## 2. Convert units

- cm to inches: divide by 2.54. Inches to cm: multiply by 2.54.
- Round to the nearest 0.5, halves go up: 36.22 becomes 36, 37.80 becomes 38, 39.37 becomes 39.5, 91.44 becomes 91.5.
- Never convert twice (cm to in to cm) because rounding drifts.

## 3. Garment flat to body guidance

1. Width measured flat (armpit to armpit, waist edge to edge, hip edge to edge, thigh) times 2 = garment circumference. Lengths (length, sleeve, inseam, shoulder) are NOT doubled.
2. Pick the ease range from `assets/ease.json` by category (tops, dresses, bottoms), measurement and fit (stretch, fitted, regular, relaxed, oversized). Bust and chest share the chest row.
3. Body range = garment minus the ease maximum, up to garment minus the ease minimum. Round to 0.5.
4. Example: tops, regular fit, chest flat 50 cm. Garment 100 cm. Ease 8-12. Body chest 88-92 cm.
5. Label these as estimates from typical ease. A merchant who knows their pattern ease should give it, and that replaces the table.

## 4. Render by hand

Build an HTML table with a wrapper `div` styled `max-width:100%;overflow-x:auto` so only the table scrolls on a phone, not the page. Make the first column sticky (`position:sticky;left:0`, or `right:0` for Arabic). Give the header and size cells a light background AND dark text (`background:#f4f4f4;color:#111`) so they stay readable on dark themes. For a garment chart from flat widths, show widths doubled (chest flat 50 shows as 100) because the note tells shoppers they are doubled. For Arabic add `dir="rtl" lang="ar"` on the outer `div`. Under the table add the fit note and a how-to-measure list covering only the measurements in the table. Copy the wording from the `HOW` (body charts), `HOW_GARMENT` and `GARMENT_WIDTH` (garment charts: lay the item flat and measure across), `GENERAL` and `FIT` texts in `scripts/sizechart.py`. With Eastern Arabic digits, convert every number in the Arabic table (measurements, numeric sizes, EU/UK/US columns), not letter sizes. A custom fit note needs its own Arabic translation; never pair it with the default Arabic note.
