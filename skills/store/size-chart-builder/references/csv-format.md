# Standard size chart CSV

Every input (supplier sheet, PDF, photo, chat message, base table) is turned into this one shape before any script runs. Save it as `chart.csv` (UTF-8).

```
size,eu,uk,us,chest_cm,waist_cm,hip_cm,length_cm,sleeve_cm
S,36,8,4,92,76,96,68,60
M,38,10,6,96,80,100,70,61
```

Rules:

- First column is `size`, one row per size, smallest first.
- Measurement columns end in the unit: `_cm` or `_in` (`chest_cm`, `waist_in`). Use lowercase and underscores: `foot_length_cm`, `leg_opening_cm`, `across_back_cm`.
- Optional size system columns, no unit suffix: `eu`, `uk`, `us`, `it`, `fr`, `jp`, `us_waist`.
- Numbers only in measurement cells. Commas as decimal marks are accepted (`92,5` reads as 92.5). Leave a cell blank if the value is unknown. Never guess a value to fill a gap.
- If the source gives a range (`88-92`), keep two columns (`chest_min_cm`, `chest_max_cm`) or use the midpoint and tell the merchant you did.
- Record what the numbers describe in the chat summary and in the render flag `--basis`: `body` (the shopper's body) or `garment` (the item itself).
- Garment widths measured flat (armpit to armpit) stay as flat numbers in the CSV. Run `body` to double them and get body guidance. Do not double them by hand and then run `body` again. `render --basis garment` doubles flat widths on the chart by itself; pass `--measured full` when the CSV already holds measurements all the way round. Headers like `Chest (cm)` are read as `chest_cm`.

Built-in labels (English and Arabic) exist for: size, eu, uk, us, it, fr, jp, us_waist, chest, bust, underbust, waist, hip, hips, seat, length, sleeve, shoulder, inseam, outseam, rise, thigh, neck, bicep, hem, leg_opening, foot_length, across_back, height. Any other name renders with a plain English label and a warning, so check the header (and translate it in the Arabic table by hand).
