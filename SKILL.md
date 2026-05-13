---
name: equitable-overlap
description: Use when asked to design or compare recurring work schedules for a team across time zones while balancing collaboration coverage, awkward-hour burden, fragmented days, and workday stretch. Trigger on requests about fair recurring overlap windows, timezone-friendly weekly schedules, protected hours, or tradeoffs across members, offices, or regions.
---

# Equitable Overlap

This skill turns a distributed team's constraints into recurring weekly overlap recommendations.

Use it for:

- recurring work-hour design across time zones
- fair meeting-window recommendations
- comparing candidate schedules and explaining tradeoffs
- showing who absorbs awkward hours or fragmented days
- testing whether a recurring full-team sync is feasible or non-binding

## Files In This Skill

- `README.md`
  - user-facing install steps
  - input and output specs
  - defaults
  - examples
- `scripts/solve_equitable_overlap.py`
  - minimal standalone exact solver used by this skill
- `examples/product-team.json`
  - sample structured input

Read `README.md` when you need the precise input schema or installation steps.

## How To Use The Skill

When enough structured information is available, call:

```bash
python3 scripts/solve_equitable_overlap.py examples/product-team.json --pretty --visual-out /tmp/equitable-overlap.svg
```

For user-provided data:

1. collect team members, time zones, protected windows, and collaboration needs
2. map the request into the JSON schema from `README.md`
3. run the solver
4. if possible, include `--visual-out /tmp/<team>-equitable-overlap.svg` so the recommendation has a readable visual
5. translate the JSON output into plain English
6. show the visual along with the written recommendation
7. present:
   - the recommended recurring schedule
   - the visual schedule by member
   - local-time windows by member
   - why it was chosen
   - who still bears the burden
   - one or two fallback options
8. if the user requires a recurring standup or all-hands, set `full_team_sync.required_joint_slots_per_week`
9. if the solver returns `status = infeasible_full_team_sync`, say so plainly and show the fallback unconstrained schedule plus the infeasibility reason

The visual should be treated as the default presentation mode for the recommended strategy:

- grey blocks = standard local work hours
- blue blocks = recommended recurring overlap blocks
- light red blocks = protected local windows
- green blocks = recurring full-team sync blocks when that constraint is active
- each member row should stay in local time so burden is easy to read

## Defaults

Unless the user specifies otherwise, use these defaults:

- horizon: `3` weeks
- workdays per week: `5`
- target workday span: `8` hours
- candidate UTC slots: `00:00, 03:00, 06:00, 09:00, 12:00, 15:00, 18:00, 21:00`
- max active UTC slots per day: `2`
- default protected window per member: local `12:00-14:00`
- default fragmentation weight per member: `1.0`
- if collaboration edges are omitted: fully connected team with weekly demand `4` per pair
- default recurring full-team sync requirement: `0` jointly feasible slots per week

## Recommendation Policy

The solver returns all four strategies:

- serve-demand only
- timing-fair only
- rotation heuristic
- fragmentation-aware

Prefer the `fragmentation_aware` recommendation when it materially lowers composite inequity, starts, or overflow without paying a large served-demand loss. Otherwise prefer `timing_fair_only`.

If a recurring full-team sync is requested:

- use `full_team_sync.required_joint_slots_per_week = 1` for a weekly standup-style requirement
- use `2` only if the team truly needs two recurring jointly feasible slots per week
- explain that this reduced solver repeats the same daily pattern on every weekday, so it does not enforce distinct weekdays for multiple syncs
- check `constraint_status.full_team_sync.binding_for_recommended_strategy`:
  - `false` means the sync requirement is feasible but did not change the schedule
  - `true` means it changed the chosen schedule
  - `null` means the requirement was inactive or infeasible

## What To Avoid

- Do not optimize only one meeting if the user is asking about recurring team structure.
- Do not give a recommendation without local-time translations.
- Do not present only raw time strings when a visual schedule would be clearer.
- Do not hide minority-site burden behind one scalar fairness score.
- Do not assume the same fairness policy fits every team.
