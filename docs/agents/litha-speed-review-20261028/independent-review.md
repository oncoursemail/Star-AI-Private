# Independent Litha context wire review

The baseline was the actual `launcher/litha_context.py` and `launcher/litha.py` from Git commit `79489ad0d62aba4aa6323de93531a27fb3c171f2`. The reviewer loaded their `git show` bytes into an isolated in-memory package, with a stub key module. Both baseline and current context builders read temporary synthetic files; both actual `ask_stream` / request encoders produced captured requests through an injected SSE response. Socket connection attempts were blocked. No real credential, provider, model, tokenizer or GPU was used. All attached source files were synthetic.

The retained verifier's four cases were independently exercised against those actual baseline modules, rather than relying only on its reconstructed prior formatting. The question was `Explain the selected source.` in both versions. All old capsules fit the existing 65,536-character limit.

| Retained case | Source bytes | Old capsule characters | Actual prior request bytes | Current request bytes | Reduction |
|---|---:|---:|---:|---:|---:|
| Many short lines | 14,400 | 53,000 | 61,443 | 37,268 | 39.35% |
| Long lines | 24,000 | 24,569 | 25,821 | 25,616 | 0.79% |
| Unicode and escaping | 9,600 | 17,600 | 28,143 | 20,768 | 26.21% |
| Empty selected file | 0 | 358 | 1,572 | 1,499 | 4.64% |

`python -B scripts/verify_litha_context_wire.py` also passed its two retained test groups independently. They check lossless JSON transport, source/metadata preservation and rejection of invalid Unicode before reading the engine key.

## Additional ad hoc evidence

These three extra cases are independent audit probes, not additional retained cases in the wire verifier. Each used three 8,192-byte files: exactly 24,576 bytes of supported UTF-8 source in total. Whole repeated source units plus ASCII padding avoided cutting a UTF-8 character. All three were accepted by the actual old builder under its existing capsule limit.

| Additional source pattern | Old capsule characters | Actual prior request bytes | Current request bytes | Reduction |
|---|---:|---:|---:|---:|
| ASCII helper/comment lines | 38,366 | 42,156 | 33,491 | 20.55% |
| Quotes, backslashes and markup characters | 44,210 | 52,302 | 46,397 | 11.29% |
| Greek/CJK/emoji comment lines | 24,830 | 70,587 | 31,682 | 55.12% |

Across all seven cases, the decoded source JSON, file order, numbered line values, metadata and SHA-256 values matched. The untrusted-data wrapper and its no-authority wording matched. Other request options, model selection and non-context messages matched; the default non-context prompt was unchanged. No source was truncated, and file-selection rules or permissions were not expanded.

Compacting the embedded capsule removes JSON whitespace outside source strings. Compact UTF-8 transport additionally avoids expanding Unicode into ASCII escape sequences. Transport-only savings do not reduce the decoded model input; no token reduction, inference latency, native performance or coding-quality improvement was measured.

The existing attachment is already an immutable snapshot. After each probe changed its temporary files, request assembly still produced identical bytes with `_read` patched to fail if called. This confirms no request-time reread; it does not make the snapshot a live view of later edits.

The additional probes used three distinct files all named `helper.js`. Their existing source `file` numbers remain distinct (1, 2 and 3), while displayed basenames alone are ambiguous. No duplicate-basename schema, prompt or UI change was made in this review. The reviewer made no production edits.

## Separate frontend review

The final `LithaChat` renderer was independently reviewed at source SHA-256 `845ec5596f9f7a285ab7f0a4138f4bb49ab5acec7573e4b4c6808a72fe0a892b`. The portable render verifier passed 129 checks; the existing chat verifier passed 59 and main-hook verifier passed 14. These overlap and are not an aggregate acceptance score.

The optional renderer baseline file was independently compared byte-for-byte with `git show 79489ad:launcher/web/js/litha.js` (SHA-256 `a660a0a73592a678e2aca0e90bdd49ee6a02c59cf979b17fec6f425315cd9ecd`). The comparison run passed 132 checks against that exact prior production module. Its 100-frame, Home/dock, 200-settled-message fixture reproduced 3,030 to zero settled-message formatter calls, 202 to zero whole-list replacements, 606 to 200 HTML assignments, and 4,268,940 to 78,890 assigned UTF-16 code units.

Source review found no scoped blocker in the bounded per-view row cache, retained node identity, scroll-follow rules or incomplete-response handling. Incomplete partial text remains visible with an escaped warning, is marked unsuccessful and excluded from later assistant history; stale events cannot complete that turn. No portrait, selected source, model prompt or permissions were changed by this review. These are inert DOM operation counts, not native rendering, parsing, selection, latency, GPU or coding-quality measurements. Native acceptance remains a separate requirement.

## Final backend completion gate

The final backend source was reviewed at SHA-256 `acf4a45c61164569b27ead3e1084f0ca08d70fd5438621b00ee3113795910f37`. `python -B scripts/verify_litha_completion.py` independently passed all seven groups, including immediate stop without an extra read, output-limit partial text followed by exactly one incomplete session receipt, unsupported finish reasons, invalid text, valid Unicode and empty-reply failure. Typed incomplete results preserve partial text without promoting a later `[DONE]` marker to success.

An additional fake-response probe found that ASCII JSON can contain an escaped lone surrogate even when its wire bytes decode as UTF-8. The author added strict UTF-8 encodability validation before yielding decoded text. The independent high/low-surrogate reproductions now reject with the static protocol error and close their response; the retained valid literal backslash-u case remains supported. No production edit was made by the reviewer.

This is the final scoped source gate. Earlier artifacts built from `79489ad` do not contain this correction and require rebuilding before being described as this candidate. No real socket, key, provider, model, GPU or native UI was exercised by these completion checks.
