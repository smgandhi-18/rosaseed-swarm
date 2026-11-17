# How the code and the numbers were verified

The harness was written with Claude Code (an AI coding agent) under my direction; the
agents inside the experiment use a local open model (qwen3:8b through Ollama). This file
records, per part, what was written, which tests check it, and what I checked by hand.
Run all tests with `.venv/bin/python -m pytest -q`.

## 1. Inputs and builds

| What | How it is checked |
|---|---|
| RosaSeed source = public preprint release, commit 865bec6 | `setup/get_rosaseed.sh` fails unless `git rev-parse HEAD` starts with 865bec6 |
| 20 RosaSeed binaries + stock BWA-MEM2 | each `work/bin/<name>.flags` records the exact `-D` flags and source commit; by hand: grepped each build log for the expected flags (e.g. the `frc0` builds contain no `-DENABLE_F_RC_CHOICE`) |
| chr22 = T2T-CHM13v2.0 chromosome 22 (GenBank CP068256.2) | NCBI reports 51,324,926 bp; the downloaded FASTA has 51,324,926 bases |
| Read sets A and B | wgsim with fixed seeds 11 and 22; 100,000 pairs each; 200,000 primary records per SAM |

## 2. Evaluator (`swarm/evaluate.py`)

- `tests/test_evaluate.py` scores a handmade 12-record SAM (`tests/data/tiny.sam`) with
  known answers: forward and reverse reads, soft and hard clips, a deletion, a read 21 bp
  off, a wrong chromosome, an unmapped read, and secondary and supplementary records that
  must be ignored. Expected: 10 primary reads, 9 mapped, 7 correct; 8 correct at 21 bp.
- By hand: on real BWA-MEM2 output, 19k of the 24k MAPQ-0 reads are misplaced while only
  5 reads with MAPQ >= 30 are; that pattern (errors concentrated in repeats) is what a
  correct evaluator should show.

## 3. Accuracy rule (`swarm/metrics.py`)

- Accuracy = reads correct AND MAPQ > 0, over all reads. Valid = at most 0.05 points
  below BWA-MEM2 on the same read set. Chosen after the baseline run (default RosaSeed
  differs from BWA-MEM2 mainly in where it puts MAPQ-0 reads) and before any search run.
- `tests/test_metrics.py`: BWA-MEM2 reference from the calibration numbers, default
  RosaSeed valid on both sets, exact boundary of the margin, crashes never valid.

## 4. Runner, store, queue, tools

- `tests/test_runner.py`: GNU time parsing, timeout kills the process group, one retry
  after a crash, no retry after a timeout.
- `tests/test_store.py`: round trip, cache hits only within the same condition, repeat and
  read set, failed runs never cached, data survives reopening (resume), partial runs are
  deleted before a rerun.
- `tests/test_tools.py`: speedup and validity reported to the agent, invalid or
  out-of-region configs rejected without using budget, budget exhaustion, repeated configs
  served from cache but still charged, log sorted fastest first, claims recorded.

## 5. Timing fairness

- Each alignment runs pinned to one 6-core die (`taskset`, `-t 6`), the model runs on the
  GPU with its CPU threads on another die, and the fourth die is left unused.
- Calibration (`results/baseline.md`): run-to-run SD 0.02 s on 6.7 s. A busy neighbouring
  die added 0.10 s (more than 2 SD), so alignments run one at a time for every condition.

## 6. Agents and analysis

- `tests/test_planner.py`: the planner's JSON is accepted only with exactly 3 regions,
  known fields, allowed values and ranges inside the space; region checks reject
  out-of-region configs.
- `tests/test_tools.py` also checks that a claim is refused while runs are left (every
  condition uses its full budget) and that an Ollama reply with string-encoded tool
  arguments is parsed.
- Dry run (budget 6, `results/dry/`, transcripts `results/transcripts/dry-*`) found three
  problems, all fixed before the experiment:
  1. the single agent claimed with runs left, then re-submitted the claim 32 times until
     the turn limit (claims are now refused until the budget is used, and a claim ends
     the agent);
  2. the planner's reply failed to parse twice, so the swarm silently fell back to a
     fixed split (now JSON mode, three attempts, and every raw reply and parse error is
     saved in `results/transcripts/swarm_<r>_planner.json`; `planner_fallback` says
     whether the fallback was used);
  3. transcripts were written only at the end (now one line per turn).
- Analysis never trusts agent claims: `scripts/analyze.py` recomputes everything from
  the store, re-runs the top 3 valid configs 3 times on held-out set B, and labels each
  claim by comparing it with the log and with a fresh set-B run.
- By hand: read the dry-run transcripts end to end (planner regions, explorer tool calls,
  critic's held-out runs and verdicts) and checked the critic's numbers against the
  store rows.

## 7. Critic probe (planted errors)

In the experiment the explorers' claims may all be correct, which would leave the
critic untested. `scripts/critic_probe.py` re-runs the critic on each swarm repeat with
three planted wrong claims (inflated speedup, config never run, overstated accuracy)
mixed in with the real ones, and records which it rejects. Planted claims are filed
under a separate condition so they cannot affect the experiment's numbers.

## 8. Bugs found during the main run

- **Planner parser too strict (my bug).** In swarm repeat 1 the planner's three replies
  described sensible regions but wrote `"early_exit": true` instead of `[true]`, the
  string `"true"`, or a min/max range for `cap`; all three were rejected and the swarm fell
  back to a fixed split. Found by reading the saved raw replies, not by looking at scores.
  Fixed (`_normalise_rule`), tested on the exact replies (`tests/test_planner.py`), and the
  affected repeat is kept as condition `swarm-plannerbug` instead of being deleted. The
  run was stopped and resumed; random and single repeats already finished were unaffected.
- **Single agent repetition loop (model behaviour, kept as data).** In the main run the
  single agent repeated one config 23 of 24 times despite a "repeat of an earlier run"
  note. The rules were not changed mid-experiment. A labelled follow-up
  (`single-norepeat`, `swarm-norepeat`) refuses exact repeats without charging, to see
  whether a tool-level guardrail matters more than coordination.

## 9. Independent review (fresh reviewer, read-only) and fixes

A separate reviewer read the whole repo with no knowledge of my reasoning. No critical
findings. Important ones and what was done:

| Finding | Fix |
|---|---|
| Default-RosaSeed reference drifted 2.5 % between calibration batches, so a fixed reference makes set-A speedups about 2 % high and the 0.67 % floor too optimistic | Held-out check now alternates default and candidate runs (D, C, D, C, D, C) and uses the session-wide SD of all those default runs as the floor; set-A numbers are labelled as approximate in the summary (`tests/test_analyze.py`) |
| Swarm alignments overlap other explorers' model calls; other conditions don't | Measured directly (`scripts/measure_llm_overlap.py`, `results/llm_overlap.json`); the held-out headline numbers are unaffected because no model runs during them |
| A repeat could finish with fewer runs or no claim without the summary showing it | Summary shows runs used and wrong-or-missing claims; tool errors are caught (`tests/test_robustness.py`); model calls retry with backoff; turn limit scales with budget |
| Claims labelled with looser tolerances than the critic was told to use | Labels now use exactly the critic's rules (0.01 tolerance, 1.007 gate) plus validity on B |
| Nothing prevented two scripts timing alignments at once | File lock around every alignment (`RunLock`, tested) |
| Accuracy rule ignores confident wrong placements | Rule unchanged (it was fixed before the search), but every final config's confident errors on B are reported next to BWA-MEM2's and the default's |

Minor findings fixed: SAM deleted even if scoring fails; variants excluded from the main
tables; planner fallback shown in `results.csv`; critic probe stops with a clear message
instead of an IndexError. The rename to `swarm-plannerbug` was checked in all four tables.

## 10. The objective was gameable (found by verification), and the v2 rule

The first full run (rule v1) reported settings about 2x faster than default RosaSeed on
held-out reads for all three methods. The analysis also reports confident errors (MAPQ > 0,
wrong place) for every final setting, because the independent reviewer pointed out that
v1 does not penalise them. Those numbers showed the 2x settings make about 2,600-3,500
confident errors on set B against 628 for the default and 431 for BWA-MEM2. Across all
165 distinct settings tried, confident errors fall steadily as `--rs-cap` rises
(cap 50: ~3,000-3,500; 200: ~2,000; 1000: ~1,000; 2000: ~500). Low caps skip repetitive
seeds, so the aligner sees one candidate for a repeat read and reports it confidently
instead of with MAPQ 0; v1 rewarded the ~20 % of those that land right and ignored the rest.

Every search method exploited this, so v1 results are reported as a finding, not as a
speedup at equal quality. Rule v2 (decided with the user before any v2 run) adds: confident
errors at most default RosaSeed's + 100 (617 on set A, 728 on set B). Only 17 of the 165
settings already logged would pass, the best at about 1.14x. v2 runs are stored as
`<condition>-v2`; agents see `confident_errors` and the limit in every result. The prompt
states the rule but gives no hint about which settings cause the errors.
`tests/test_metrics.py` checks the limits, a gamed setting that v1 accepts and v2 rejects,
and the exact boundary.

## 11. Critic probe result (v1): the LLM critic did not verify

With 3 planted wrong claims per repeat mixed into the real ones, the critic rejected 3 of
9 planted claims and 6 of 9 real ones (7 of which were correct). Its verdicts did not
depend on the truth: in repeat 1 it rejected everything with the same false reason
("speedup below 1.007"); in repeats 2 and 3 it accepted everything, including a setting
that was never run, with the reason "claimed config was run, speedup and accuracy match
log". It did not call `read_log` in a way that could have shown that. All planted errors
were caught by the deterministic labelling in `scripts/analyze.py`
(`results/critic_probe.csv`, transcripts `results/transcripts/probe-swarm_*`).

## 12. Round 2 (rule v2) and the overlap check

- Round 2 ran all three conditions × 3 repeats under v2 with the condition order shuffled
  per repeat (seeded). Held-out results (`results/v2/summary.md`): random 1.09× in 3 of 3
  repeats, swarm 1.06× in 1 of 3, single agent nothing valid in 3 of 3. The swarm's
  failures trace to the planner's regions (all caps ≤ 500 or ≤ 1000 in repeats 1 and 2;
  valid configurations need 2000 or 5000), checked by hand in
  `results/transcripts/swarm-v2_*_planner.json`.
- Every final configuration's confident errors on B are within the v2 limit (709-722
  against 728), recomputed by `scripts/analyze.py` from stored counts.
- `scripts/measure_llm_overlap.py`: 8 default runs alone vs 8 with three concurrent model
  generations, alternating: 6.64 s vs 6.68 s (+0.6 %), below the 1 % floor
  (`results/llm_overlap.json`). The first attempt at this measurement was cut short by my
  own stop watcher (it matched its trigger text in the unit's command line); it was rerun
  in the round-2 pipeline.
- Round 2 critic probe could only run in repeat 3 (repeats 1-2 had no valid run to plant
  claims from, so the script skips them and says so).

## 13. Second independent review (round-2 changes) and fixes

A fresh read-only reviewer checked the v2 changes. No critical findings; the v2 formula,
limits and tool fields were confirmed correct. Important findings:

| Finding | What was done |
|---|---|
| The planner and critic prompts never contained the v2 rule; only the searchers saw it. The first round-2 swarm therefore planned without knowing confident errors count, so "the plan trapped the swarm" was partly my omission | Planner and critic now get the rule under v2 (round-1 prompts unchanged). The first round-2 swarm runs are kept as `swarm-v2-uninformed` (and `swarm-norepeat-v2-uninformed`) and the swarm was rerun with the informed planner; both are reported |
| `analyze.py` and `critic_probe.py` could score a round under the wrong rule if `--rule` was forgotten | The rule now comes from the condition names (`-v2`); a mismatch stops the script; `results.csv` and `claims.csv` record the rule |
| Round-2 random search used the same seeds as round 1, so it re-timed the same 72 configurations | Disclosed (README). It is a paired re-scoring, not an independent sample; 17 of the 72 uniform draws (24 %) are valid, so 24 draws contain a valid one with probability 1 − 0.76^24 > 99 % (an earlier version said ~10 % and 92 %, using all logged configurations, which are skewed toward the agents' low-cap choices) |
| `run_experiment.py` could delete a running repeat's rows before rejecting a bad name | All names are checked before anything is deleted; a lock file allows one experiment process at a time |

Minor findings fixed: stale summary wording under v2, plot labels and end values for
variant conditions, probe clears old rows before skipping and checks labels per repeat,
`Refs` rejects v2 without limits, the identical-runs check covers the MAPQ counts, tool
descriptions under v2, and the noise sentence in the searcher prompt now matches each
round's original text (0.7 % in round 1, 1 % in round 2). New tests:
`tests/test_rules_wiring.py`.

## 14. Informed-planner rerun, and two more bugs

- Swarm rerun with the rule in the planner's and critic's prompts (`swarm-v2`,
  `swarm-norepeat-v2`): the planner kept every explorer at cap ≤ 500 in all three repeats
  (checked in `results/transcripts/swarm-v2_*_planner.json`); no valid configuration found.
- **Critic stalled (partly my bug).** With the longer prompt, the critic ran `read_log` and
  three held-out checks, then answered with empty text until the 20-turn limit, never
  calling `decide`, in 3 of 3 main repeats and 1 of 3 follow-up repeats. The loop's
  reminder for a text-only answer told every role to "call submit_claim", a tool the critic
  does not have. Fixed after the runs (`nudge_text`, `tests/test_rules_wiring.py`); the
  reported results are from the runs as they happened. Search-quality scores never depend
  on the critic.
- **Analysis hung on the plot.** The loop that nudges end-of-line labels apart never ended
  when two lines finished at the same value (floating-point rounding kept the gap a hair
  under the minimum). The CSVs and summary had already been written; the run was stopped,
  the loop replaced by a single step, a regression test added
  (`test_plot_finishes_when_lines_end_at_the_same_value`), and all analyses rerun from the
  stored runs (no new alignments needed).
