# Social appraisal timing, 2026-10-26

Social chat previously built its mood note before appraising the current incoming
message. With emotion enabled, the reply therefore used the previous state even
though the current message was appraised after generation. Voice calls already
appraise their committed input before building the request.

The existing `_feel(text, person)` call now runs once after social-rule observation
and reunion processing, before the mood note is read. The old end-of-reply call is
removed. No emotion flag, prompt, model, threshold or permission changes. Blocked,
forget, remember-again and leave-me-alone branches retain their existing early
returns; the leave branch keeps its existing rejection event.

`python scripts/verify_emotion_timing.py` checks current-turn tone, exactly-once
appraisal, disabled/missing/failed engine behavior and the fixed early-return
paths. It uses a temporary real FriendMemory database and fake emotion/model
edges; the inner-memory hook is replaced so no owner state is read. This verifies
event order, not improved conversation quality or subjective experience. No live
brain, account, audio device or owner's memory was used.
