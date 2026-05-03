# Wave 4 Orchestration Retrospective

**Session:** Phase 13 W4 — S4a (Snapshot Writer) + S4b (Whale/Insider VAE)
**Date:** 2026-04-24
**Outcome:** All 49 tests green, code complete. Session took ~3h instead of ~45min.

---

## Incident 1 — Background Agent Silent-Hang (S4b)

### What happened

S4b (Opus 4.7, background) was dispatched in parallel with S4a to implement `whale_pressure.py`, `insider_pressure.py`, and extend `engine.py` / `yaml_config.py`. After S4a completed normally with a summary (~30min), S4b showed:

- Transcript file: 0 bytes
- `TaskOutput` status: `running`
- No completion notification after 50+ minutes

### Root cause

The agent wrote all target files correctly and ran tests (confirmed later: 40/40 pass), but lost its output channel before emitting the final `tool_result`. The background runtime terminated before flushing the transcript buffer. This is a known runtime failure mode — see `lessons.md` entry 2026-04-24 — but the recovery protocol was not applied proactively.

### What went wrong in orchestration

1. **Passive waiting**: orchestrator polled `TaskOutput` once, saw `status: running`, and waited instead of verifying file existence independently.
2. **No time-boxed checkpoint**: no trigger to re-evaluate after 15–20 min. The 50-min wait was pure overhead.
3. **Recovery protocol existed but wasn't applied**: lessons.md had the exact protocol (Glob → timestamp → targeted pytest → conclude if green). It was only applied after user intervention.

### Correct response (for future sessions)

- After dispatching a background agent, set a mental 15-min checkpoint.
- At checkpoint: `Glob` for expected files → if they exist with post-dispatch timestamps → run targeted tests immediately.
- If tests are green: conclude agent DONE, proceed with merge. Do not wait for a summary.
- `TaskOutput` `status: running` is insufficient signal. File presence + passing tests is sufficient.

---

## Incident 2 — Background Pytest Producing 0-Byte Output

### What happened

Two separate background Bash commands to run `pytest tests/ -q` each produced 0-byte output files. Monitor waited 4+ minutes without receiving any lines.

### Root cause

`run_in_background` + `Monitor` combination is unreliable for long-running subprocesses on this environment (Windows + OneDrive sync active). The process may run to completion but the output pipe is either not flushed to the temp file, or OneDrive lazy-syncs the write, making the file appear empty to the Read tool.

### What went wrong

Background pytest was used as a shortcut to "do other things while tests run." In practice it blocked the orchestrator waiting for Monitor to emit lines that never came, which is worse than just running pytest synchronously.

### Correct response

- For test suites <90s: run synchronously, wait for output, proceed.
- For test suites >90s that are truly parallelizable with other work: accept that the output may be delayed and do not block on Monitor. Instead, re-read the output file after a fixed delay.
- Do not use `run_in_background` + `Monitor` expecting real-time streaming on this platform — it does not reliably stream.

---

## Incident 3 — Overlap Files Creating a Merge Bottleneck

### What happened

Three files (`engine.py`, `yaml_config.py`, `config/config.example.yaml`) needed changes from both agents (S4a writes DI wiring; S4b writes new signals). Both agents were instructed to skip these files; the orchestrator handled the final merge.

This was the correct call — but the merge could only happen after S4b was confirmed done. Because S4b's completion was invisible (Incident 1), the merge was blocked for 50 min even though S4b's portion of the overlap changes was trivial (3 fields + 2 methods).

### Root cause

The bottleneck was not the merge itself (which took ~15 min once unblocked) but the dependency on a silent agent's "completion signal" to authorize the merge.

### Correct response

For overlap files with small, well-specified changes:
- Define exact diffs for the orchestrator-side merge at planning time (not agent-produced).
- If agent has not signaled completion by checkpoint, verify files + tests first, then proceed with the planned diff regardless.
- Do not treat "agent silence = agent incomplete." Treat "files present + tests green = agent complete."

---

## Incident 4 — Codex Rescue Injected into an Already-Complete Workflow

### What happened

After S4b silent-hang was noticed, user ran `/codex:rescue` which diagnosed "3 missing integration points" in the already-complete code. This caused a second audit loop and re-verification of changes that were already correct.

### Root cause

Codex rescue was called before verifying whether S4b had actually completed. If file inspection + targeted tests had been run first (as per Incident 1 protocol), rescue would not have been needed and would not have diagnosed false gaps.

### Correct response

Before calling `/codex:rescue` on a stalled agent: run the diagnostic checklist first. Rescue is for code that is wrong or incomplete, not for agents whose output channel is broken.

---

## Systemic Gaps

| Gap | Symptom | Fix |
|-----|---------|-----|
| No time-boxed checkpoint for background agents | 50-min passive wait | Add 15-min checkpoint to dispatch protocol |
| `run_in_background` + Monitor unreliable on Windows/OneDrive | 0-byte pytest output | Run short tests synchronously; accept async delay for long ones |
| Recovery protocol not applied proactively | Needed user intervention to unstick | Checkpoint must trigger file inspection + targeted tests automatically |
| Overlap-file merge blocked on completion signal | 50-min merge delay | Orchestrator-side diffs should not depend on agent summary to authorize merge |
| Rescue tool called before state verification | Double audit of already-correct code | Verify file presence + tests before escalating to rescue |

---

## Protocol Changes

The following changes are applied to the project orchestration protocol going forward:

**Background agent dispatch checklist (NEW)**
1. Note dispatch time.
2. At T+15min: `Glob` for all expected output files.
3. If files exist with post-dispatch timestamps: run targeted tests.
4. If tests pass: conclude DONE regardless of transcript/summary state.
5. Only after all 3 checks fail → consider `TaskStop` + re-dispatch.

**Overlap file handling (CLARIFICATION)**
- Orchestrator-side merge diffs must be fully specified at planning time.
- Merge authorization: file presence + tests green, not agent summary.

**Background pytest (RULE)**
- Tests <90s: always run synchronously.
- Tests >90s in background: do not use Monitor for streaming; re-read output file after fixed delay.

---

*Captured from session transcript. Related lessons.md entry: 2026-04-24 — Background Agent silent-hang.*
