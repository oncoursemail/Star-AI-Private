# Home action-session boundaries, 2026-10-26

The bounded Home brain loop now checks owner STOP, attention interruption and wall-clock expiry after a model response and around each tool call. A request already in progress is not forcibly cancelled, but its returned batch cannot start more work after interruption. A failed stop predicate closes the session. Owner STOP is not treated as an ordinary resumable attention pause.

`finish` requires a string summary, exact boolean success/goal completion and at most ten valid path strings. Numeric/string truthiness, malformed artifacts and invalid Unicode cannot create a successful result. Host results also require real booleans and valid text. Malformed batches and host/provider exceptions produce bounded unverified outcomes.

The model's direct `set_goal(status='done')` is refused with instructions to use `finish(goal_done=True)`. Only a verified finish exposes goal completion to `Life.record`, which can complete the selected goal. Owner/manual APIs, dropping/opening goals, tool schemas, persona text and feature defaults remain unchanged.

If a host action raises after it may have taken effect, the result is unknown. This session does not automatically replay it. Provider failure also has no automatic retry. The action log and actual environment need inspection before deciding whether to repeat work. This is not a transactional exactly-once guarantee across process restarts or later independent sessions.

Artifact checks refuse literal network paths and the existing protected control-folder paths before accepting file evidence. Broader host path-policy issues, mapped drives, environment expansion and junctions are not solved by this check. Existing verification remains a coarse action-count plus existing-file check, not proof of semantic task completion; an unrelated action or preexisting artifact can still be insufficient real evidence.

Validation: 13 new primary boundary cases and 10 independent reviewer cases pass using temporary files and scripted replies. They cover valid recovery, strict finish/result types, goal commit, preview, post-model and mid-batch STOP, time expiry, predicate failure, malformed batches, protected/network artifacts, tool budgets and uncertain side effects. The affected existing Home suite is run during integration. No model, account, real input, target-PC action, prompt/default change or evaluation-fixture edit was used.
