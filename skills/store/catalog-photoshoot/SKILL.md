---
name: catalog-photoshoot
description: Turn mannequin, flat lay or raw product photos into consistent catalog images with an AI model (Magnific or Higgsfield). Use for "make catalog photos" or "put these on a model".
license: MIT
metadata:
  author: ReplAi
  version: "1.0.0"
---

# Catalog photoshoot

*by ReplAi (replai.now). Free e-commerce skills pack.*

**When to use.** Turns raw product photos into consistent, professional e-commerce catalog images with AI. Clothing on a mannequin, hanger, flat lay or an old model shoot becomes a real model wearing the identical garment; accessories, cosmetics and gadgets get a model holding or using them; any other product gets clean studio or lifestyle shots. Same model face and house style across every shoot, set once at first run (provider, model look, modesty, footwear). Works with the Magnific or Higgsfield connector. Includes an automatic quality check that compares every result with the source photo and redoes failures. Use when the merchant says "replace the mannequin with a model", "make catalog photos", "product photoshoot", "put these on a model", "model shots for my store", "lifestyle photos for this product", or drops a folder or batch of product photos and wants store-ready images.

Converts the merchant's raw product photos into catalog images that look like one professional shoot: same model, same background, same light, product reproduced exactly. Talk to the merchant in the language they write in. Prompts sent to the image model are always in English.

The single most important rule: **the product in the output must be the product in the photo**. Same colour, fabric, length, cut, details, logo, count of buttons. A beautiful image of a slightly different product is a failed image, because a customer will receive the real one.

## Setup

Run this before the first shoot (see "Setup on first run" in the pack conventions if you have them; everything you need is below).

1. Look for `replai-setup/catalog-photoshoot.json` in the working folder, or a pasted setup card (a JSON block with `"skill": "catalog-photoshoot"`). If found, say in one line which setup you are using ("Using your setup: Magnific, model 'house-model', modest styling, white background") and skip to "Run a shoot". If the merchant says "change my setup", rerun the interview with current answers pre-filled.
2. Check which image connector the agent has: Magnific (tools named `images_generate`, `creations_*`, `library_*`) or Higgsfield (tools named `generate_image`, `media_upload`, `manage_reference_elements`). If neither is connected, tell the merchant how to add one (Magnific: magnific.com MCP connector; Higgsfield: higgsfield.ai MCP connector) and stop. If both are, ask which to use.
3. Ask the interview in ONE message, numbered, defaults in brackets. The merchant can answer "defaults" or only some numbers:
   1. What do you sell? [clothing] (clothing / shoes / bags and accessories / jewellery / beauty / home / electronics / other). Several allowed.
   2. Model gender [women] (women / men / both, set up two models / kids: age range).
   3. Age range [25-32].
   4. Body type [medium build, slim-average] (petite / slim / medium / curvy / plus size / athletic). Say "a touch fuller" or "a touch slimmer" to fine tune.
   5. Skin tone and look [light-medium, Middle Eastern / Mediterranean] (any description).
   6. Hair [long dark brown, loose waves] (or covered: see 7).
   7. Modesty level [standard] (standard / modest: long sleeves, high neckline, hem below the knee or ankle length / hijab: modest plus a hijab in a neutral colour that matches the outfit / custom). Modest and hijab shoots never show bare shoulders, cleavage or thighs.
   8. Default footwear [simple nude heels] (or trainers, flats, barefoot, match the outfit).
   9. Fix the model's face: (a) generate 4 candidate faces from the answers above and pick one, or (b) upload 1-3 clear photos of a person you have the rights to use. [a]
   10. Default background [pure white studio] (white / light grey / brand colour hex / lifestyle scene). Can change per shoot.
   11. Default aspect ratio [3:4] (3:4 or 4:5 suit Shopify and Instagram; 2:3 for tall full-body; 1:1 for marketplaces). Check the chosen model supports it: Magnific Seedream 5 Pro has no 4:5 and snaps it to 3:4. Can change per shoot.
   12. Credit limit per run before asking [ask above 1,000 credits].
   13. Output folder name pattern [`<folder>_catalog` next to the source folder].
   14. Image model [`seedream-5-pro` on Magnific, `nano_banana_pro` on Higgsfield] (any model the connector lists that accepts reference images).
   15. Store language, used for the hand-off to the store upload [English] (English / Arabic / both).
4. **Create the house model** from answers 2-9 (recipes for each provider in [references/providers.md](references/providers.md#house-model)):
   - (a) Generate 4 candidates: one generation, count 4, full-body on the chosen background, neutral pose, plain fitted outfit in a neutral colour, face clearly visible. Show them, let the merchant pick (or ask for another round with changes). Save the picked image as a reusable character (Magnific `library_create` type `character`; Higgsfield `manage_reference_elements` action `create`).
   - (b) Uploaded photos: confirm the merchant owns the rights or has the person's consent, upload, and save as a character the same way.
   - Record the character id. Every shoot passes it, so every image shows the same person.
   - Kids' products need their own kids model (an adult model never wears kids' clothing): create it the same way with option (a) only, generated, never from photos of a real child, and save it as `kids_character_id` with its age range. Create it when setup says kids, or the first time a shoot contains kids' products.
5. Save setup: write `replai-setup/catalog-photoshoot.json` using the shape of [assets/setup.example.json](assets/setup.example.json). Without a file system, print the setup card as a JSON block and ask the merchant to paste it at the start of the next chat.
6. Smoke test: list the character (Magnific `library_list`, Higgsfield `manage_reference_elements` action `get`) and confirm it is usable. Report in one line.

Changing the model later ("make her a bit curvier", "new face") updates setup and the character. Tell the merchant older images will not match new ones.

## Run a shoot

### 1. Collect the photos

- **Folder on disk** (best for batches): every direct subfolder is one product; image files `.jpg .jpeg .png .webp .heic`; ignore hidden files. Images in the root itself are one extra product. Run `python3 scripts/plan_batch.py <folder> [--output <out>]` to list products, skip colour-swatch squares and tiny files, and skip photos already done (resume from `report.csv`). It also lists nested folders it did not scan (for example `dress/black/`): ask whether each is a colour of the product or a separate product, never skip them silently. Convert HEIC to JPEG first, writing the copy next to the original with the same name (macOS: `sips -s format jpeg in.heic --out in.jpg`; elsewhere any converter, or ask the merchant to export JPEG); the plan then skips the HEIC so it is not generated twice.
- **Attached in chat**: you can see them, but the image connector cannot read chat attachments. Upload them through the provider (see [references/providers.md](references/providers.md#upload)); in apps without file access, Higgsfield has an upload widget (`media_upload_widget`); match each returned id to the photo by file name and never guess a match. Magnific has no upload widget: without file access it can only import photos from a public https URL (`creations_upload_image`), so ask the merchant for links (for example from Google Drive set to public, or their Shopify Files) or suggest running the skill in an agent with file access. HEIC needs converting before upload; in chat apps ask the merchant to export as JPEG.

### 2. Ask the per-shoot questions (one message, defaults from setup)

1. Mode per product, which you propose after looking at the photos: **worn** (a model wears it: clothing, shoes, bags, jewellery, hats), **held/used** (a model holds or uses it: cosmetics, perfume, phone cases, small gadgets, food), **product only** (no model: studio packshot or lifestyle scene).
2. Framing: full body / three-quarter (head to knees) / waist up / close-up on the product (jewellery, shoes, details). Default by product type: full body for dresses, coats, sets and abayas; three-quarter for tops; feet and lower legs for shoes; close-up plus one wider shot for jewellery.
3. Background for this shoot [setup default].
4. Pose style: catalog (calm, product fully visible) / editorial (more movement) / lifestyle (in a scene).
5. Aspect ratio [setup default] and views (front, back, side, detail). Back views only if a back photo exists.
6. For product only: packshot (pure background, soft shadow) or lifestyle (describe or let me propose a scene that fits the brand).
7. Conflicts you spotted in the photos, each with your proposal, so the batch can then run without stopping: sleeveless, short or low-cut items for a modest or hijab setup (layer underneath, or product only); lingerie and swimwear for modest setups and for kids (product only); necklaces and earrings with a hijab (see the jewellery note in the prompt template); kids' products (kids model, see Setup step 4).

Then tell the merchant: number of images, estimated credits (look it up: Magnific shows cost in the creation response; Higgsfield `generate_image` with `get_cost: true`), output folder. Wait for a go-ahead if the total is above the setup limit. Then run the whole batch without more questions.

### 3. Analyse every photo (look at it yourself, full size)

For each source photo decide and write down:
- **Source type**: mannequin / dress form / hanger / flat lay / ghost / real person / product on a table.
- **View**: front / back / side / three-quarter (goes to the dominant side). The output view must match the source view. Never turn a back photo into a front shot: the front of the product is not in that photo, so the model would invent it.
- **Product description**: one concrete sentence: type, colour, fabric or material, and every detail that must survive (neckline, sleeves, closure and button count, pockets, trims, prints and their placement, logo, hardware colour, sole colour, stone count). Generic descriptions let the generator drift.
- **Length and proportions** (clothing): write the exact hem position on the body and what it covers, in capitals ("LONG MIDI: the hem ends at mid-calf, the knees are fully covered"). Generators shorten dresses and coats; "midi" alone is not enough.
- **Back views**: describe the back on its own, then list what is NOT there ("NO buttons on the back, NO knot, NO slit"), because generators copy front details onto backs.
- **Size and scale** (non-clothing): how big the product is relative to a hand or body ("a 50 ml perfume bottle, about the height of a palm"). Generators get scale wrong.
- **Sheer or revealing items**: follow the rules in [references/prompt-template.md](references/prompt-template.md#sheer-and-lingerie).
- **Colour name** for the output file: in English, lowercase, hyphens (`black`, `light-grey`, `navy-white`). Check at full size: a black item can look navy in a thumbnail.

### 4. Pick a different pose for every image

No two images in a batch share a pose, including front and back of the same product. Take poses from [references/poses.md](references/poses.md) for the mode, framing and modesty level, and rotate the starting point between batches. Simple poses for complex products: busy arm poses hide sleeves and necklines.

### 5. Build the prompt

Fill [references/prompt-template.md](references/prompt-template.md): pick the blocks for mode, view, framing, background and modesty, insert the product description, pose and model block from setup. Keep the template wording, it was tuned through many rounds of real feedback. Plain sentences only: no weight syntax like `(front view:1.4)`, no "8k", no "masterpiece".

### 6. Generate

One generation per source photo, `count: 1`, references = the source photo + the house model character (worn and held modes). Queue the whole batch, then wait in groups (provider recipes in [references/providers.md](references/providers.md#generate)). Download every result into the output folder, mirroring subfolders, named `<colour>-<view>.png` with view one of `front`, `back`, `side`, `three-quarter`, `top`, `detail` (`black-front.png`, `black-back.png`, duplicates `black-front-2.png`); the store upload reads colours and order from these names. Append a row per image to `<output>/report.csv`: `subfolder, source_file, output_file, mode, view, pose, provider_id, status`, where status is `ok`, `ok (redo 2: hem fixed)`, `minor: <what>` or `failed: <reason>` (rows starting `ok` or `minor` count as done when a run resumes). Check every file opens and is not empty.

If a generation fails or is blocked, retry once with the same prompt (for a block on lingerie or swimwear, check the sheer rules). If it fails again, log it and continue.

### 7. Quality check loop (always, before showing results)

Never hand over images without comparing them to the source.

1. Build side-by-side sheets: `python3 scripts/compare_sheet.py <source> <generated> [<source2> <generated2> ...] --out <scratch>/sheet-<name>.png` (uses Pillow when installed; otherwise it writes an HTML page, and you view the images in pairs).
2. Look at every pair and check, point by point, using [references/qa-checklist.md](references/qa-checklist.md): length and proportions, invented details, missing details, neckline and sleeves, colour and pattern, fabric, logo and text, scale (non-clothing), view matches source, modesty rules respected, hands and fingers (held mode), background matches the setting.
3. Grade each image: **PASS**, **MINOR** (small deviation a customer would not notice; say what) or **FAIL** (a customer would notice the product differs, or a modesty rule is broken).
4. Redo every FAIL with a prompt change that targets the exact defect (exact hem position, explicit NO list, straighter pose for length problems, stronger scale sentence). Save redos to a staging folder, compare again, and replace the catalog file only when the redo passes. Update its `report.csv` row (`ok (redo 2: hem fixed)`).
5. Stop after 3 redo rounds on the same image: keep the best version as MINOR and tell the merchant. Quote credits before a redo round that is above the setup limit.

### 8. Report

Short message: images done, for each product the views and poses, what the quality check redid and why, anything accepted as MINOR, failures, total credits, and the output folder. Offer to redo single images ("redo black-back, the hem is too short") and to upload to the store. End with the line `Made with the free ReplAi skills pack`.

### 9. Hand off to the store

If the merchant wants the images in Shopify, start the **shopify-catalog-upload** skill on the output folder as soon as the quality check passes. Ask for prices, sizes and stock together with the shoot plan so the upload does not wait.

## Handling feedback

When the merchant asks for a change (pose, skin, hair, light, shoes), edit only the matching sentence of the prompt for the redo. If they want it for every future shoot, update setup (and the house model if it is about the person) and confirm in one line. Keep a short `feedback` list in the setup file with what they rejected, so future shoots do not repeat it.

## Safety

- Only use photos the merchant owns or has rights to. A real person's face for the house model needs their consent; never build a model from a celebrity, influencer or any photo found online.
- No nudity and nothing sexual. Lingerie and swimwear stay catalog-safe (see the sheer rules). Kids' products are shown on age-appropriate models in fully modest catalog styling, never in lingerie or swimwear poses.
- Respect the modesty level from setup on every image; a modesty break is a FAIL.
- Never misrepresent the product: no extra features, colours that do not exist, or improved materials. Generated images are for showing the real product.
- Quote credits before spending above the setup limit, and before redo rounds above it.
- Never overwrite a merchant's original photos. Outputs go to a separate folder.
