# CloneDub V11 overnight handoff

Coordination contract for the V11 pro-dub overnight work.

## Roles

- **Claude Code** = implementation. Follows the master plan and Codex's continuation prompts exactly.
- **Codex** = review, gates, debug decisions. Reviews every phase before the next one starts.

## Branch rule

- ONE shared branch: `v11/pro-dub-overnight`. No separate phase branches.
- Never push `main`.
- After each implementation step: commit scoped V11 files only, push to the same
  branch, report to Codex (commit hash, commands, output paths, metrics, changes,
  blockers/decisions needed).

## Untouchable

- Android app files (`app/`, APK, Gradle) — pre-existing local modifications stay
  uncommitted and unpushed.
- Kaggle files and Kaggle hours.
- Existing production outputs (V1/V2, `rask_success_reference`, old workdirs) —
  read-only.
- No full 45-min runs, no LatentSync, until the 60s and 3-min gates pass.

## Artifact locations

All V11 artifacts live under `D:\CloneDub\work\v11_*`. Repo tracks only
`tools/clonedub_v11_*.py`, the master plan, and this handoff file.

| phase | status | artifacts |
|---|---|---|
| Phase 1 evaluator | done, gate passed (V1 correctly FAILs) | `D:\CloneDub\work\v11_eval_v1_vs_benchmark\` |
| Phase 2 rewrite | done, style approved for pilot | `D:\CloneDub\work\v11_rewrite_900_960\` |
| Phase 3 TTS bake-off | done, awaiting listening + Codex review | `D:\CloneDub\work\v11_tts_bakeoff_900_960\` (report: `phase3_report.md`) |
| Phase 4 planning | in progress | `D:\CloneDub\work\v11_phase4_plan_900_960\` |

## Phase 3 result snapshot (900-960s window)

Benchmarks: original active speech 52.73s, Rask 50.99s, old V1 35.97s (+9.1 dB over-hot, FAIL).

- `edge_swara`: active 42.89s, coverage 0.81, three OVERRUN flags (free)
- `azure_ananya`: active 40.76s, coverage 0.77, one OVERRUN flag (paid, trivial)
- `eleven_v2`: active 41.88s, coverage 0.79, lowest silent-while-original-speaks 17.57s (736 credits)
- `fish_girl`: active 41.56s, coverage 0.79, only one tempo flag (free-tier model)
- All FAIL vs benchmark — expected at Phase 3. Mix loudness now ~0.0 dB vs Rask (fixed).

Codex decision: no more paid TTS until the Phase 4 planner says exactly which
blocks to regenerate. Realistic next candidates: **eleven_v2** and **fish_girl**.

## Next step

Phase 4 preparation only: `tools/clonedub_v11_phase4_plan.py` reads the Phase 3
per-block spoken-vs-target data + `script_blocks.json` and outputs a rewrite
adjustment plan (`phase4_plan.md` / `phase4_plan.json`) — which blocks need
fuller text, shorter text, no stretching, and which candidate(s) to regenerate.
