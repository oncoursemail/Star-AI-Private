# Continuation verification

The working branch began at `star/next` commit `0b171017`. While this change was
being tested, Claude's remaining Home work landed at `8155f4c9`. It was merged
into this task branch with explicit reconciliation of call events and hearing
ownership. Existing upstream tests were retained without edits.

## Results

- Full offline suite on the first integrated tree, Python 3.12 with the declared
  runtime dependencies and two workers: **13,647 passed, 400 skipped, 541
  subtests passed, 8 failed**, in 670.46 seconds. This was not a green full run.
- Three shell-launcher failures came from Windows resolving `bash` to the WSL
  launcher. All three passed with Git Bash first in this test process's PATH.
- The desktop doctor failed because the isolated environment initially lacked
  the declared desktop dependency `keyring`. It passed after that dependency
  was installed in the local environment.
- The voice-status test saw existing application settings. It passed with a
  disposable application-data directory and the null keyring backend. No real
  settings or credentials were altered.
- Research cancellation, resource-planner HTTP and background-priority timing
  failures all passed when rerun unchanged outside the full concurrent run.
  Their sensitivity remains a limitation; reruns do not make the full run green.
- After reconciling `8155f4c9`, the Home/watch/senses selection passed **136
  tests**; the Home/emotion/social selection passed **235 tests**. These
  selections overlap and must not be added as independent totals.
- Retained standalone verifiers passed: personal credentials **73**, allowance
  wallet **69**, watch hearing **22**, adult voice **10**. They use temporary
  storage and inert devices, not live accounts or model inference.
- The focused stream-episode regression selection passed **9 tests**.
- Python compilation, repository correctness lint and whitespace checks passed.
- Pinned Pyright 1.1.414 with the same package-free Python 3.12 interpreter:
  clean upstream `8155f4c9` had 579 errors; this branch has 577. No file/rule
  count increased. The two reductions are the microphone `ready` property and
  stream-episode action IDs. The repository's stored type baseline still fails
  against the existing upstream backlog; no baseline was expanded.
- Twelve emote exports passed square dimensions, RGBA and file-size checks;
  a contact sheet was inspected on light and dark backgrounds.

The broader suite was not repeated after the merge; checks were directed at the
changed behavior and merge conflicts. No evaluation fixtures, regression
expectations, protected workflows or type baselines were changed by this task.

## Live work still required

No production Live2D rig was generated. The painted sheet and emotes are art
proposals, not owner-approved runtime defaults. No actual microphone, camera,
Discord friend, target game, RTX 4060 workload or subjective voice audition was
tested. No passwords were saved in the real vault, bank connected, allowance
funded, payment made or payout account configured. Emotion defaults remain off
until their measured decision rules pass. The sealed evaluation was left alone.

The new credential and wallet APIs are trusted-host foundations. They are not
model tools and do not remove the existing computer host's password/payment
restrictions. Review, provider setup and native acceptance are separate steps.
