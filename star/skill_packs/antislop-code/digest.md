# Anti-slop code comments (anti-slop-code v3.2.21, MIT)
- Only comments change; never alter executable code, identifiers, imports or formatting just to tidy.
- Do not write: decorative banners (// ====== Auth ======), comments that restate the next line ("// Initialize the variable"), step narration ("// Step 1: Validate input"), empty labels, filler TODOs, or tutorial-voice and cheerful comments.
- Keep and write comments that carry what the code cannot: why a choice was made, a constraint, a workaround with its reason, a non-obvious invariant, a unit or format, a link to the bug or spec.
- Docstrings state behaviour, inputs, outputs and failure modes briefly; no restating of the name. Prefer a clearer name over a comment.
- Make code real: handle the empty, error and edge cases it names; no placeholder functions presented as finished; say what you ran to verify it.
