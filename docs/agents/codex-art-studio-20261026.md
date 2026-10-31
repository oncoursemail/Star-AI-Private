# Editable painting sessions for STAR Home

Owner request: STAR should draw, develop creative hobbies and inspect what she
makes on her own PC. `star/art_studio.py` adds an executable painting activity;
it does not establish human consciousness or measure professional anime drawing
skill. No live model, GPU, reference image or painting application was used for
the development checks below.

## What the activity does

The Home activity **art studio**, under the existing `drawing` interest, makes
four visual painting passes: sketch, color, shadows and details. Each pass sees
the current rendered canvas and an optional explicitly selected reference, then
returns bounded brush data. Strokes have RGBA color, width, normalized points
and pressure. The raster renderer actually applies them to separate transparent
layers. A pass can decline to add strokes when they would make the picture worse.

This extends the existing simple MS Paint sketch activity rather than replacing
it. The new activity saves files directly; it does not pretend to drive Krita's
mouse, use a tablet, or make the existing small Paint sketcher an expert artist.

Three starting modes are available:

- `paint`: start from a blank 768×1024 canvas. A reference guides the visual
  planner without being copied onto the visible canvas.
- `reference`: start from an explicitly selected image and add editable paint
  layers. The source bytes stay unchanged in the project.
- `generate`: use the existing local Klein workflow for a base illustration,
  optionally guided by the selected reference, then perform the same paint
  passes. This additionally requires `allow_generation: true`, installed model
  files, observed free GPU memory and no detected game or queued ComfyUI job.
  It never installs a model, starts ComfyUI or invokes a paid service.

The output goes under the existing workspace's `gallery/art/art-<id>/`:

| File | Purpose |
| --- | --- |
| `painting.ora` | Editable OpenRaster file: four paint layers, base painting, optional hidden reference |
| `preview.png` | The merged visible painting |
| `strokes.json` | Ordered brush data that can be edited and replayed |
| `base.original` | Exact original bytes of the starting image |
| `base.png` | Normalized, orientation-corrected canvas pixels |
| `reference.original` | Exact approved reference bytes, when one was supplied |
| `receipt.json` | Provenance, artifact hashes and the scope of verification |

References must be selected in owner-controlled configuration and stored below
`workspace/art-input/`. Traversal and resolved paths outside that folder are
refused, as are paths into Home's control folder. Original bytes are preserved;
reference metadata is stripped from the normalized copies sent to the visual
planner. No generated file becomes STAR's official avatar or a public post.

OpenRaster stores the actual paint layers, not inferred body-part segmentation.
The generated/imported base remains one raster layer. A riggable VTuber model
still needs approved separated artwork and mouth shapes; this export does not
claim to provide those.

## Home wiring and configuration

`register_home_activities(registry)` discovers the activity through the existing
Home plug-in mechanism. It registers only when the setting is enabled and Home
has a configured vision-capable brain (`vision: true`). It declares GPU demand
for generation mode; CPU painting mode does not reserve GPU memory locally.

Default configuration remains disabled. For a separately configured capable
vision model, the owner can select the local creative workflow, for example:

```json
{
  "vision": true,
  "art_studio": {
    "enabled": true,
    "mode": "paint",
    "reference": "art-input/approved-reference.png",
    "allow_generation": false
  }
}
```

The existing goal supplies the brief. With no goal, it uses the configured
`brief`, then a general original anime illustration brief. The optional GPU
mode also accepts `port` (default 8188), `width` and `height` (default 768×1024),
and `min_free_mb` (default 7000). That free-memory threshold is a conservative
dispatch condition, **not a measured model requirement or a guarantee of fit**.

The activity checks the existing Home STOP file and attention interrupt before
passes, between brush segments, during exports and before the completed project
is atomically published. Dry runs execute no model or painting. The normal
Home action log records the session and pass counts. There are no new shell,
account, posting, purchase or credential tools. A model's JSON cannot execute
Python, name a filesystem target, alter configuration or choose a remote endpoint.

`python -m star.art_studio <project-directory>` inspects an existing export
without loading a model or opening an application. The `.ora` can be opened
through the existing scoped app/file controls when STAR or the owner chooses to
use Krita. The activity does not launch a window implicitly.

## What is verified

Export is staged in a temporary child of the gallery, checked, then renamed
atomically. Partial exports are not presented as finished projects. Reopening
checks hashes, preserved source pixels, ordered brush replay, every layer's
pixels and metadata, layer compositing, merged preview and thumbnail/container
requirements. Archive entries, dimensions, input bytes, brush count, point count
and finite coordinate/pressure values are bounded. XML reads use `defusedxml`.

`verified: true` means the saved artifact matches the recorded painting process.
It does **not** mean anatomy, likeness, lighting or artistic intent was graded.
The activity leaves `goal_done` false. Empty or invisible brush results are
reported as unsuccessful. The receipt explicitly says artistic quality was not
assessed; hashes detect changes and are not authenticity signatures.

A visual model can produce poor coordinates or an ugly painting. Actual anime
quality, stable identity and improving artistic taste need observed outputs,
comparison with approved references, and feedback. No such quality result is
invented here. The brush engine is a basic pressure/alpha raster brush, not the
full Krita brush engine, an editable Krita vector system or a simulated person.

## Research and hardware findings

- The official [OpenRaster file layout](https://www.openraster.org/baseline/file-layout-spec.html)
  defines the ZIP container, first uncompressed `mimetype`, layer PNGs, thumbnail
  and merged image. The [layer specification](https://www.openraster.org/baseline/layer-stack-spec.html)
  defines ordering and attributes. Export uses baseline source-over layers;
  it adds no application-specific masks or unsupported effects.
- [Krita's OpenRaster documentation](https://docs.krita.org/en/general_concepts/file_formats/file_ora.html)
  identifies `.ora` as a layered interchange format. Native `.kra` features can
  go beyond that format. Interchange correctness was verified programmatically;
  a real Krita open/edit/save round trip has not yet been performed.
- [Krita's license page](https://krita.org/en/about/license/) distinguishes the
  GPL-licensed application from artwork made with it. This change writes data
  files and ships no Krita plugin. Artwork/reference rights and model licenses
  still need to match the actual selected inputs and deployment.
- [ComfyUI's server documentation](https://docs.comfy.org/development/comfyui-server/comms_routes)
  documents the existing prompt, queue, history, image upload/view and interrupt
  routes. This module reuses STAR's loopback `ComfyClient` and built-in workflows.
  The idle-queue check is not a distributed lock: a shared ComfyUI server still
  needs host-level resource coordination. Existing client cancellation can
  interrupt the active server workflow, so generation should use its intended
  locally managed worker rather than an unrelated shared service.
- The official [FLUX.2 Klein 4B card](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)
  lists Apache-2.0 and roughly 13 GB VRAM for its documented configuration.
  STAR's existing workflow names quantized fp8/fp4 files; that is a different
  configuration. No 8 GB RTX 4060 fit, latency or offload result was measured.
  The code reports missing models and allocation errors rather than promising
  that the upstream full model fits an 8 GB card.
- [Krita's scripting documentation](https://docs.krita.org/en/user_manual/python_scripting/krita_python_plugin_howto.html)
  describes installed plugins and their application resource location. No plugin
  was injected during this task. A later native brush adapter should use a
  reviewed integration instead of claiming a remote Krita API exists here.

Keep real inference and generation off while the sealed evaluation or another
protected workload is using the brain/GPU. These development checks used fake
model responses and fake GPU/client observations only. No model was downloaded.

## Reproducible checks

`python scripts/verify_art_studio.py`: **77 checks passed**. Coverage includes
strict stroke validation, actual raster changes, layered round trip, unchanged
original/reference bytes, stripped outbound metadata, read-only inspect CLI,
checksum/replay/opacity corruption, stopped and partially exported projects,
four-pass Home execution with a fake planner, disabled/dry-run/no-op behavior,
reference path confinement, plug-in readiness and fake ComfyUI game/VRAM/model/
queue/cancellation conditions. The fixtures are tiny verification rasters and
are not presented as anime artwork or evidence of artistic skill.

Ruff, compilation and Pyright passed. Existing `test_star_home.py`,
`test_home_wiring.py` and `test_windows_package_data.py`: **101 passed in 55.91
seconds**. No harness-owned tests, graders, baseline
answers, model weights or evaluation fixtures were edited.
