# Quality check

Compare every generated image with its source photo. Grade PASS / MINOR / FAIL. FAIL = a customer would notice the product differs, or a modesty or safety rule is broken.

## Clothing
- **Length and hemline** relative to the body (mid-thigh, knee, below knee, mid-calf, ankle). The most common failure: generators shorten dresses, skirts and coats.
- **Invented details**: buttons, knots, sashes, plackets copied onto the back; storm flaps, yokes, slits, pockets that do not exist; lining showing.
- **Missing details**: trims and piping colours, button count and colour, cuffs, ruffles, belts, vents, embroidery.
- **Neckline** shape and height (front and back), **sleeves** shape and length, cropped vs full length.
- **Colour and pattern**: hue, stripe count, direction, width and placement, print scale, contrast colours.
- **Fabric**: rib, knit gauge, denim wash, sheen, opacity.
- **Fit**: oversized stays oversized, fitted stays fitted.

## Non-clothing
- **Shape and proportions**: bottle silhouette, cap shape, bag structure, heel height and shape, sole thickness.
- **Scale**: product size relative to the hand or body is believable and matches the real size.
- **Label, logo and text**: same placement, not misspelled, not invented. If text cannot be reproduced exactly, it is better blurred than wrong: flag it.
- **Materials and finish**: metal colour (gold vs rose gold vs silver), matte vs glossy, stone count and colour, stitching.
- **Hands** (held mode): five fingers, natural grip, not covering the label.

## Everything
- View matches the source (front stays front, back stays back).
- Modesty level from setup is respected on every image.
- Background matches the shoot setting (white is white, not grey or cloudy). Mention a background issue once rather than failing every image for it.
- Same house model face across the batch.
- Pose is different from every other image in the batch.
- File opens and is the expected size.

## Known fixes
| Defect | Fix in the redo prompt |
|---|---|
| Dress or coat too short | exact hem position in capitals, "the knees are completely covered", straight standing pose |
| Front details on the back | describe the back alone and add an explicit NO list |
| Invented slits or pockets | add "NO side slits, NO pockets" to the product sentence |
| Satin turned see-through | remove the sheer block, add the "heavy and fully opaque" sentence |
| Product too large or small | stronger {SCALE} sentence with centimetres and a body comparison |
| Label text garbled | "the label text exactly as in the reference" or ask the merchant to accept a softened label |
| Busy pose hides sleeves | switch to an arms-down pose |
| Plastic skin | remove any quality buzzwords; keep the {SKIN} block verbatim |
