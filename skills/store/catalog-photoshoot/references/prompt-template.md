# Prompt template

Build the prompt from blocks. Fill every `{SLOT}`, delete blocks that do not apply, keep the rest word for word. These sentences were tuned through many rounds of real catalog feedback; change only what the merchant asks for.

## Worn mode (a model wears the product)

```
{BACKGROUND} Ignore the background of the reference image. {SUBJECT} wearing the EXACT same {PRODUCT_NOUN}: {PRODUCT}. Same color, same fabric, same length and hemline, same sleeves or lack of sleeves, every detail preserved. Do not change or redesign the product.

{LENGTH_AND_NO_LIST}

{VIEW}

{FRAMING}

Pose: {POSE} Legs close together, no wide stance, no hands on hips or waist, the product stays fully visible and is not covered by hands, arms or hair.

Model: {MODEL}

{MODESTY}

{SHEER}

{SKIN}

{LIGHTING}
```

## Held / used mode (a model holds or uses the product)

```
{BACKGROUND} Ignore the background of the reference image. {MODEL_SHORT} holding the EXACT same product as in the reference image: {PRODUCT}. {SCALE} Same shape, same color, same label and logo placement, same cap, same materials and finish; every detail preserved, the label text unchanged and readable where it is readable in the reference. Do not change or redesign the product.

{FRAMING}

Pose: {POSE} The product faces the camera and is fully visible; fingers never cover the label or logo. Natural relaxed hands with five fingers each.

Model: {MODEL}

{MODESTY}

{SKIN}

{LIGHTING}
```

## Product-only mode

Packshot:
```
Professional e-commerce packshot of the EXACT same product as in the reference image: {PRODUCT}. {SCALE} Same shape, color, materials, finish, label and logo; every detail preserved; do not redesign it. {ANGLE} The product is centered with even margins, sharp from front to back. {BACKGROUND} Ignore the background of the reference image. Lighting: soft large softbox from above and the front, gentle highlight on glossy surfaces, true-to-life colors, neutral white balance. Shot on a 100mm macro lens, real product photography, no CGI or 3D render look.
```
Lifestyle:
```
Lifestyle product photo of the EXACT same product as in the reference image: {PRODUCT}. {SCALE} Same shape, color, materials, finish, label and logo; every detail preserved; do not redesign it. Scene: {SCENE}. The product is the clear hero, in sharp focus, placed naturally in the scene, with realistic contact shadows and reflections. Ignore the background of the reference image. Natural light, true-to-life colors, real editorial photography, no CGI look, no added text.
```

## Slots

**{SUBJECT}**
- mannequin, dress form, hanger, flat lay or ghost: `Replace the mannequin in the reference image with a real {GENDER_NOUN}` (say "the garment shown flat" for flat lays: `Show the garment from the reference image on a real {GENDER_NOUN}`).
- real person already wearing it: `Replace the person in the reference image with a different real {GENDER_NOUN}`. Describe the product extra carefully, since the old pose and body are not kept.

**{PRODUCT_NOUN}**: garment / shoes / bag / jewellery / hat / outfit.

**{PRODUCT}**: the one-sentence description from the analysis step, e.g. `identical sage green linen wrap midi dress with a V neckline, three-quarter puff sleeves, a self-tie belt knotted at the left hip and a flared skirt`.

**{LENGTH_AND_NO_LIST}** (clothing; omit when not needed):
- `LONG MIDI LENGTH: the hem ends at mid-calf, well below the knees; the knees are completely covered and only the lower calves and ankles are visible. Do not shorten it.`
- For back views: `The backs of the knees are completely covered.`
- Back NO list example: `The back is completely plain: NO buttons, NO placket, NO knot, NO tie, NO slit; those details exist only on the front.`
- Stronger form after a failed attempt: `LENGTH IS CRITICAL: the hem sits exactly halfway between the knee and the ankle. It is NOT a knee-length dress.` and use a straight standing pose.

**{SCALE}** (non-clothing): `Real size: a 50 ml bottle about 11 cm tall, roughly the height of the model's palm.` Always state real size; generators make products too big or too small.

**{VIEW}**
- front: `Same camera angle as the reference image: front view, the model faces the camera, showing the front of the product.`
- back: `Same camera angle as the reference image: back view, the model is seen from behind, facing away, showing the back of the product exactly as in the reference. The hair or scarf never covers the back details.`
- side: `Same camera angle as the reference image: side profile view showing the side of the product exactly as in the reference.`

**{FRAMING}**
- full body: `Full body from head to feet, nothing cropped, space above the head and below the feet, model centered.`
- three-quarter: `Framed from the top of the head to just below the knees, model centered.`
- waist up: `Framed from the top of the head to the hips, model centered.`
- shoes: `Framed from the knees down to the floor, both shoes fully visible and sharp.`
- jewellery close-up: `Close-up framed on the {neck / ear / wrist / hand}, the jewellery sharp and filling the center of the frame, skin softly lit.`
- held product: `Framed from the head to the waist, the product held at chest height.`

**{ANGLE}** (packshot): `Front view, straight on.` / `Three-quarter view from slightly above.` / `Top-down flat view.`

**{BACKGROUND}**
- white (default): `Professional e-commerce catalog photo on a very bright, luminous pure white seamless studio background: solid #FFFFFF, high-key, the backdrop lit separately so it reads as clean paper-white everywhere, no gray cast, no off-white, no gradient, no vignette. Soft, natural shadows only: a gentle light contact shadow under the feet or product that fades into the white, and a very faint diffused shadow behind, never dark or hard.`
- light grey: same sentence with `a soft light grey (#EDEDED) seamless studio background, evenly lit, no gradient`.
- brand colour: `on a seamless studio background in solid {HEX} ({colour name}), evenly lit, no gradient, soft natural shadows.`
- lifestyle (model): `Photographed in {SCENE}, softly out of focus behind the model so the product stays the hero.`

**{MODEL}** (built once at setup, stored in the setup file as `model_block`): `The same person as the character reference {CHARACTER_TOKEN}: take only the face, hair and body from it, never the clothing or background. {age range} {gender noun} with a {body type sentence}. {skin and look}, {eyes if specified}, {hair or hijab}, calm neutral expression. Wearing {footwear}.`
- `{CHARACTER_TOKEN}` is `@<name>` on Magnific and `<<<element_id>>>` on Higgsfield.
- Body type wording that worked: `healthy medium build, just a touch fuller than a typical fashion model, soft natural curves; still slender-average overall, not curvy, not plus size, not skinny`. Change it in small steps only; big jumps overshoot.
- Footwear is dropped for shoes shoots (the product is the shoes) and for framings that do not show feet.

**{MODEL_SHORT}**: `A real {age range} {gender noun}, the same person as the character reference {CHARACTER_TOKEN},`

**{MODESTY}**
- standard: delete the block.
- modest: `Modest styling: long sleeves to the wrist, high neckline, hem below the knee or ankle length, loose fit; no bare shoulders, no cleavage, no bare thighs. If the product itself is short-sleeved, layer a plain fitted long-sleeve top in a matching neutral colour underneath without hiding the product's details.`
- hijab: the modest block plus `She wears a neatly wrapped plain hijab in a neutral colour that matches the outfit, covering the hair and neck, framing the face; the hijab never covers the product's neckline details.`
- Never apply modesty layering to products whose details it would hide; in that case ask the merchant (for example sleeveless dresses for a modest brand: layer, or use product-only mode).
- Hijab setups with necklaces or earrings: the hijab block covers the neck and ears, which hides the product. For jewellery close-ups replace "covering the hair and neck" with "covering the hair, with the neckline area left visible so the necklace sits on top of the outfit", or use product-only mode; ask the merchant once per brand.

**{SKIN}**: `Skin must look like a real unretouched photograph: natural skin texture with visible pores, subtle uneven tone, tiny natural imperfections, realistic hands, knees and elbows, natural matte-to-soft sheen, no airbrushing, no plastic or waxy skin, no CGI or 3D render look, no beauty filter.`

**{LIGHTING}**: `Lighting: bright high-key studio lighting, soft diffused softbox light on the model, a separate even light on the backdrop, natural exposure on the skin, neutral white balance. Shot on a full-frame camera with an 85mm lens, real editorial fashion photography, true-to-life colors.` (For lifestyle backgrounds: `soft natural daylight` instead of the studio sentence.)

## Sheer and lingerie

- Sheer garments (mesh, tulle, see-through lace): add `{SHEER}` = `Tasteful, non-explicit catalog image: under the sheer fabric the model wears matching opaque seamless underwear in the same color as the garment, and nothing explicit is visible through the lace or mesh.` This keeps images shop-safe and avoids generator blocks.
- Opaque garments with only lace trims or cups (satin slips, etc.): do NOT use the sheer block; it makes the whole garment see-through. Instead add after the product sentence: `The {fabric} is heavy and fully opaque: the body of the garment is solid and NOT see-through; only the {cups / trims} are lace.`
- Modest and hijab setups: lingerie and swimwear go to product-only mode (packshot on a ghost mannequin or flat), never on a model. Tell the merchant once.
- Kids: never lingerie or swimwear on a model; product-only mode.

## Words that hurt

- `8k`, `ultra detailed`, `soft glow`, `airbrushed`, `flawless skin`: plastic-looking skin.
- Weight syntax `(word:1.4)`: ignored by these models, adds noise.
- `midi` without an exact hem position: shortened dresses.
- `curvy` or `plus size` when the merchant asked for "a bit fuller": overshoots.
