# Provider recipes

Tool names differ slightly between agents (some prefix them with the connector name). Match by the suffix: `images_generate`, `generate_image`, and so on. If a tool's parameters differ from what is written here, trust the tool's own schema.

| | Magnific | Higgsfield |
|---|---|---|
| Default model for catalog work | `seedream-5-pro` (very faithful to garments), resolution `2k` | `nano_banana_pro`, resolution `2k` |
| Reusable person | library character (`library_create`, type `character`) | reference element (`manage_reference_elements`, action `create`) |
| How the person is passed | `references: [{type: "character", identifier: "<library id>"}]` and mention `@<name>` in the prompt | put `<<<element_id>>>` inside the prompt text |
| Source photo passed as | `references: [{type: "image", identifier: "<creation id>"}]` | `medias: [{value: "<media id>", role: "image_references"}]` |
| Cost check | shown on the queued creation; `account_balance` for balance | `generate_image` with `get_cost: true` |

Use the merchant's chosen model from setup if they picked a different one. Check the model supports the chosen aspect ratio (`images_models_list` on Magnific, `models_explore` action `get` on Higgsfield) and fall back to the closest supported ratio, telling the merchant.

## Upload

### Magnific
1. `creations_request_upload` with `mimeType` (e.g. `image/jpeg`) and `count` = number of files of that type. One call per MIME type.
2. PUT each file's bytes to its `proxyUploadUrl`:
   `curl -s -o /dev/null -w "%{http_code}" -X PUT -H "Content-Type: image/jpeg" --data-binary @"<file>" "<proxyUploadUrl>"` (quote the URL, expect `200`). At most 3 uploads in parallel. A failed PUT gets a fresh target, never a retry on the same URL. Targets expire after about an hour, so request them per batch and use them at once.
3. `creations_finalize_upload` with `fileName` (required, the first file's name), `uploads: [{path, fileName}, ...]` and `visible: false`, at most 15 per call. Pair returned identifiers with files by path and save the mapping to a file immediately.

### Higgsfield
1. `media_upload` with `files: [{filename, content_type}, ...]` (up to 20).
2. PUT each file to its `upload_url` with curl (same command shape as above, expect `200`).
3. `media_confirm` with `type: "image"` and `media_ids` (up to 20). Save `file -> media id` immediately.
4. Without file access (chat apps), use `media_upload_widget` and ask the merchant to pick the same files.

## House model

Prompt for the 4 candidates (fill from setup answers; keep it plain):
```
Full-body e-commerce catalog photo of a <age range> <gender> model, the whole person from the top of the head to the feet in frame, nothing cropped, clear empty space above the head and below the feet, the model small enough in the frame to fit entirely. <Her/His> face is fully visible, sharp and in focus, looking straight at the camera with a calm friendly neutral expression. <body type>, <skin tone and look>, <hair or hijab>. Standing straight facing the camera, arms relaxed along the body, wearing a plain fitted <long-sleeve top and straight trousers / modest: long-sleeve ankle-length dress> in a neutral beige colour and <footwear>. <background block from prompt-template.md>. Real unretouched skin texture, natural proportions. Shot on an 85mm lens, soft studio light.
```
The face is the whole point of the house model: reject any candidate whose head is cropped or face is unclear, and regenerate (tested: without the framing sentences, all 4 candidates cropped the head off).
- Magnific: `images_generate` with `count: 4`, `aspectRatio: "2:3"`, the default model. Then `creations_show` and `creations_wait`. After the pick: `library_create` with `name` (e.g. `house-model`, letters, digits, `-` and `_` only), `type: "character"`, `gender`, `images: [{creationIdentifier: "<picked>"}]`. Save the returned numeric `id` and `name`.
- Higgsfield: `generate_image` with `params: {model: "nano_banana_pro", prompt, aspect_ratio: "2:3", count: 4}`. Wait with `jobs_wait` (`jobs: [{index, job_id}]`, at most 12 per call). After the pick: `manage_reference_elements` with `action: "create"`, `category: "character"`, `name: "house-model"`, `medias: [{id: "<picked job id>", url: "<its image url>", type: "image_job"}]`. Save the element id. Only elements with status `completed` are usable.
- Uploaded reference photos: upload as above, then create the character from the uploaded ids (Magnific `creationIdentifier`; Higgsfield `type: "media_input"`).

## Generate

### Magnific
`images_generate` with:
```
mode: "<model slug>"            # default seedream-5-pro
resolution: "2k"
aspectRatio: "<from shoot>"
count: 1
prompt: "<filled template>"
references: [{type: "image", identifier: "<source creation id>"},
             {type: "character", identifier: "<house model id>"}]   # worn / held modes only
folderReference: "<only if the merchant named a Magnific project>"
```
Queue every photo of the batch, then call `creations_show` once with the new identifiers (never the source ids), then `creations_wait` in groups of up to 8 until all are terminal.

Download: `creations_register_download` with up to 8 completed identifiers (if it returns `originals[]`, use those), then `creations_get` for full-resolution `url`s, then `curl -s -L -o "<output path>" "<url>"`. URLs are signed and expire after about two days.

### Higgsfield
`generate_image` with:
```
params: {
  model: "<model id>",           # default nano_banana_pro
  prompt: "<filled template, with <<<house model element id>>> where the model is described>",
  medias: [{value: "<source media id>", role: "image_references"}],
  aspect_ratio: "<from shoot>",
  resolution: "2k",
  count: 1
}
```
Do not put the element id in `medias`; the placeholder in the prompt injects it. Use `generate_image_batch` for 2-12 different photos in one call when available. Wait with `jobs_wait` (`jobs: [{index, job_id}]`, groups of up to 12); download each result URL with curl. On a timeout, do not resubmit blindly: check the job ids first.

Never pass `use_unlim` or free-generation flags unless the merchant asks.
