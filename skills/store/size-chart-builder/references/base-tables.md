# Base tables (typical starting points)

The files `assets/base-typical-*.csv` are typical body measurements for common size labels. They are starting points, NOT universal truth. Sizing differs by brand, country, factory and fabric. Egyptian and Gulf factories often cut smaller than European charts for the same label. Always tell the merchant this in one line when you use a base table, and prefer their own measurements whenever they have them.

| File | Rows | Columns |
|---|---|---|
| `assets/base-typical-women-tops.csv` | XS to XXL | eu, uk, us, bust, waist, hip (cm, body) |
| `assets/base-typical-women-dresses.csv` | XS to XXL | eu, uk, us, bust, waist, hip (cm, body) |
| `assets/base-typical-women-bottoms.csv` | XS to XXL | eu, uk, us, waist, hip (cm, body) |
| `assets/base-typical-men-tops.csv` | XS to XXL | eu, uk, us (chest in inches as label), chest, waist, neck (cm, body) |
| `assets/base-typical-men-bottoms.csv` | waist 28 to 38 | eu, waist, hip (cm, body). Size label is the waist in inches |
| `assets/base-typical-women-shoes.csv` | EU 35 to 42 | eu, uk, us, foot_length (cm) |
| `assets/base-typical-men-shoes.csv` | EU 39 to 46 | eu, uk, us, foot_length (cm) |

How to adjust a base table to the brand fit:

- `runs-small` (the cut is tighter than the label): keep the table and set `--fit-note runs-small`, OR shift the labels one row down (the M row becomes S) if the merchant measured a sample and confirmed it. Never shift without a measured sample.
- `runs-large`: the opposite.
- Shoes: foot length is the safest guidance. EU/UK/US conversions vary by brand by up to one size; say so in the fit note when the merchant has not checked a pair.
- Egyptian market labels (for example 1, 2, 3 or 40, 42, 44 on abayas and modest wear) do not map cleanly to EU. Ask for one measured sample per label instead of mapping.
