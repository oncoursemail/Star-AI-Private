# Litha — keyboard-free portrait handoff

The owner rejected the floating blue virtual keyboard. `portraits/working.png` replaces that expression with a focused face and no keyboard or props. The runtime expression key stays `type` for compatibility; `runtime-mapping.json` maps it to the new file. Remove `improved/type.png` when importing this set into Metallic Launcher.

The other seven portraits preserve the previously selected Solstice Architect identity: emerald-to-mint hair, curved ahoge, gold glasses and green/gold coat. This generated set supersedes the runtime expression set in draft #684. Historical references remain preserved there.

`portraits/manifest.json` records dimensions, alpha extrema and SHA-256 for all eight PNGs. `solstice-architect-fullbody.png` is the corresponding generated full-body concept, not a layered or rigged model. Only generated outputs are included; private input references, model weights and user data are excluded.

The replacement was produced with built-in image generation from the matched neutral portrait, without raster postprocessing. `working-prompt.txt` retains its generation instructions. These are illustrated launcher portraits, not evidence of a Live2D/VRM rig or native animation acceptance. Expression alignment and edges still need inspection in the running Windows application.

Code integration is tracked on the separate Metallic Launcher branch `codex/litha-quality-20261027`. This GitHub change uploads artwork for Claude's review; it does not install or publish the launcher.
