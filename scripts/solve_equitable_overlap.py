#!/usr/bin/env python3

import argparse
import html
import itertools
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


DEFAULT_SLOT_HOURS = [0, 3, 6, 9, 12, 15, 18, 21]
DEFAULT_MAX_SLOTS_PER_DAY = 2
DEFAULT_WEEKS = 3
DEFAULT_DAYS_PER_WEEK = 5
DEFAULT_TARGET_WORKDAY_SPAN_HOURS = 8.0
DEFAULT_WEIGHTS = {
    "alpha": 40.0,
    "beta": 1.0,
    "eta": 1.25,
    "delta": 0.8,
}
DEFAULT_RECOMMENDATION = {
    "max_served_fraction_drop_vs_timing_fair": 0.02,
}
STANDARD_WORK_START_HOUR = 9.0
STANDARD_WORK_END_HOUR = 17.0


@dataclass
class ProtectedWindow:
    start_local: float
    duration_hours: float


@dataclass
class Member:
    name: str
    timezone: float
    fragmentation_weight: float
    protected_windows: List[ProtectedWindow]


@dataclass
class Edge:
    pair: Tuple[int, int]
    weekly_demands: List[float]


@dataclass
class Scenario:
    team_name: str
    weeks: int
    days_per_week: int
    slot_hours_utc: List[float]
    max_slots_per_day: int
    target_workday_span_hours: float
    weights: Dict[str, float]
    recommendation: Dict[str, float]
    full_team_sync_required: List[int]
    members: List[Member]
    edges: List[Edge]


def load_json(path: Optional[str]) -> Dict[str, object]:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return json.load(sys.stdin)


def local_hour(utc_hour: float, tz_offset: float) -> float:
    return (utc_hour + tz_offset) % 24.0


def raw_local_hour(utc_hour: float, tz_offset: float) -> float:
    return utc_hour + tz_offset


def in_window(hour: float, start: float, duration: float) -> bool:
    end = (start + duration) % 24.0
    if duration >= 24:
        return True
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def format_hour(hour: float) -> str:
    normalized = hour % 24.0
    whole = int(normalized)
    minutes = int(round((normalized - whole) * 60))
    if minutes == 60:
        whole = (whole + 1) % 24
        minutes = 0
    return f"{whole:02d}:{minutes:02d}"


def format_timezone(offset: float) -> str:
    sign = "+" if offset >= 0 else "-"
    absolute = abs(offset)
    whole = int(absolute)
    minutes = int(round((absolute - whole) * 60))
    return f"UTC{sign}{whole:02d}:{minutes:02d}"


def format_boundary_hour(hour: float) -> str:
    if math.isclose(hour, 24.0):
        return "24:00"
    return format_hour(hour)


def format_pattern(slot_hours: Sequence[float], pattern: Sequence[int], tz_offset: float = 0.0) -> str:
    if not pattern:
        return "none"
    slot_duration_hours = infer_slot_duration(slot_hours)
    intervals = local_pattern_intervals(slot_hours, pattern, tz_offset, slot_duration_hours)
    return ", ".join(
        f"{format_boundary_hour(start)}-{format_boundary_hour(end)}"
        for start, end in intervals
    )


def infer_slot_duration(slot_hours: Sequence[float]) -> float:
    if len(slot_hours) < 2:
        return 24.0
    normalized = sorted({hour % 24.0 for hour in slot_hours})
    diffs = []
    for idx, hour in enumerate(normalized):
        nxt = normalized[(idx + 1) % len(normalized)]
        diff = (nxt - hour) % 24.0
        if diff > 0:
            diffs.append(diff)
    return min(diffs) if diffs else 24.0


def split_wrapped_interval(start: float, end: float) -> List[Tuple[float, float]]:
    normalized_start = start % 24.0
    normalized_end = end % 24.0
    duration = end - start
    if duration >= 24.0:
        return [(0.0, 24.0)]
    if math.isclose(duration, 0.0):
        return []
    if normalized_end > normalized_start:
        return [(normalized_start, normalized_end)]
    return [(normalized_start, 24.0), (0.0, normalized_end)]


def merge_intervals(intervals: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    if not intervals:
        return []
    merged: List[List[float]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1] + 1e-9:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def format_interval(interval: Tuple[float, float]) -> Dict[str, str]:
    return {
        "start": format_boundary_hour(interval[0]),
        "end": format_boundary_hour(interval[1]),
        "start_hour": round(interval[0], 4),
        "end_hour": round(interval[1], 4),
    }


def interval_rects(
    intervals: Sequence[Tuple[float, float]],
    x_start: float,
    y_start: float,
    px_per_hour: float,
    row_height: float,
    fill: str,
    stroke: Optional[str] = None,
    opacity: float = 1.0,
) -> List[str]:
    rects = []
    for start, end in intervals:
        width = max(0.0, (end - start) * px_per_hour)
        if width <= 0.0:
            continue
        style = [f'fill="{fill}"', f'fill-opacity="{opacity}"']
        if stroke:
            style.append(f'stroke="{stroke}"')
            style.append('stroke-width="1"')
        rects.append(
            f'<rect x="{x_start + start * px_per_hour:.1f}" y="{y_start:.1f}" '
            f'width="{width:.1f}" height="{row_height:.1f}" {" ".join(style)} rx="4" />'
        )
    return rects


def local_pattern_intervals(
    slot_hours: Sequence[float],
    pattern: Sequence[int],
    tz_offset: float,
    slot_duration_hours: float,
) -> List[Tuple[float, float]]:
    intervals: List[Tuple[float, float]] = []
    for slot_idx in pattern:
        start = slot_hours[slot_idx] + tz_offset
        end = start + slot_duration_hours
        intervals.extend(split_wrapped_interval(start, end))
    return merge_intervals(intervals)


def protected_local_intervals(member: Member) -> List[Tuple[float, float]]:
    intervals: List[Tuple[float, float]] = []
    for window in member.protected_windows:
        intervals.extend(
            split_wrapped_interval(window.start_local, window.start_local + window.duration_hours)
        )
    return merge_intervals(intervals)


def count_starts(slots: Sequence[int]) -> int:
    if not slots:
        return 0
    ordered = sorted(slots)
    starts = 1
    for prev, cur in zip(ordered, ordered[1:]):
        if cur != prev + 1:
            starts += 1
    return starts


def all_patterns(slot_hours: Sequence[float], max_slots_per_day: int) -> List[Tuple[int, ...]]:
    patterns = [tuple()]
    slot_indices = list(range(len(slot_hours)))
    for size in range(1, max_slots_per_day + 1):
        patterns.extend(itertools.combinations(slot_indices, size))
    return patterns


def member_slot_profile(member: Member, utc_hour: float) -> Tuple[bool, float]:
    hour = local_hour(utc_hour, member.timezone)
    for window in member.protected_windows:
        if in_window(hour, window.start_local, window.duration_hours):
            return False, math.inf
    if 9.0 <= hour < 17.0:
        return True, 0.25
    if 7.0 <= hour < 9.0 or 17.0 <= hour < 19.0:
        return True, 1.25
    if 6.0 <= hour < 7.0 or 19.0 <= hour < 21.0:
        return True, 3.0
    return False, math.inf


def inequity(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return sum(abs(value - mean) for value in values)


def normalize_input(payload: Dict[str, object]) -> Scenario:
    team_name = str(payload.get("team_name", "equitable-overlap-team"))
    weeks = int(payload.get("weeks", DEFAULT_WEEKS))
    if weeks < 1 or weeks > 3:
        raise ValueError("This minimal exact solver currently supports weeks in the range 1..3.")
    days_per_week = int(payload.get("days_per_week", DEFAULT_DAYS_PER_WEEK))
    slot_hours_utc = [float(x) for x in payload.get("slot_hours_utc", DEFAULT_SLOT_HOURS)]
    max_slots_per_day = int(payload.get("max_slots_per_day", DEFAULT_MAX_SLOTS_PER_DAY))
    target_workday_span_hours = float(
        payload.get("target_workday_span_hours", DEFAULT_TARGET_WORKDAY_SPAN_HOURS)
    )

    weights = dict(DEFAULT_WEIGHTS)
    weights.update(payload.get("weights", {}))

    recommendation = dict(DEFAULT_RECOMMENDATION)
    recommendation.update(payload.get("recommendation", {}))

    raw_full_team_sync = payload.get("full_team_sync", {})
    if raw_full_team_sync is None:
        raw_full_team_sync = {}
    if not isinstance(raw_full_team_sync, dict):
        raise ValueError("'full_team_sync' must be an object when provided.")
    raw_required_joint_slots = raw_full_team_sync.get("required_joint_slots_per_week", 0)
    if isinstance(raw_required_joint_slots, list):
        if len(raw_required_joint_slots) != weeks:
            raise ValueError(
                "'full_team_sync.required_joint_slots_per_week' list length must match 'weeks'."
            )
        full_team_sync_required = [int(value) for value in raw_required_joint_slots]
    else:
        full_team_sync_required = [int(raw_required_joint_slots)] * weeks
    for required_slots in full_team_sync_required:
        if required_slots < 0:
            raise ValueError("Full-team sync requirements must be non-negative.")
        if required_slots > max_slots_per_day:
            raise ValueError(
                "Full-team sync requirement cannot exceed 'max_slots_per_day' in this solver."
            )

    raw_members = payload.get("members")
    if not isinstance(raw_members, list) or not raw_members:
        raise ValueError("Input must include a non-empty 'members' list.")

    members: List[Member] = []
    member_index: Dict[str, int] = {}
    for idx, raw_member in enumerate(raw_members):
        if not isinstance(raw_member, dict):
            raise ValueError("Each member must be an object.")
        name = str(raw_member["name"])
        member_index[name] = idx
        raw_windows = raw_member.get("protected_windows", [{"start_local": 12, "duration_hours": 2}])
        windows = [
            ProtectedWindow(
                start_local=float(window["start_local"]),
                duration_hours=float(window["duration_hours"]),
            )
            for window in raw_windows
        ]
        members.append(
            Member(
                name=name,
                timezone=float(raw_member["timezone"]),
                fragmentation_weight=float(raw_member.get("fragmentation_weight", 1.0)),
                protected_windows=windows,
            )
        )

    raw_edges = payload.get("collaboration_edges")
    edges: List[Edge] = []
    if raw_edges is None:
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                edges.append(Edge(pair=(i, j), weekly_demands=[4.0] * weeks))
    else:
        if not isinstance(raw_edges, list) or not raw_edges:
            raise ValueError("'collaboration_edges' must be a non-empty list when provided.")
        for raw_edge in raw_edges:
            if not isinstance(raw_edge, dict):
                raise ValueError("Each collaboration edge must be an object.")
            left, right = raw_edge["members"]
            i = member_index[str(left)]
            j = member_index[str(right)]
            if "weekly_demands" in raw_edge:
                weekly_demands = [float(x) for x in raw_edge["weekly_demands"]]
                if len(weekly_demands) != weeks:
                    raise ValueError("'weekly_demands' length must match 'weeks'.")
            else:
                weekly_demands = [float(raw_edge.get("weekly_demand", 4.0))] * weeks
            edges.append(Edge(pair=(i, j), weekly_demands=weekly_demands))

    return Scenario(
        team_name=team_name,
        weeks=weeks,
        days_per_week=days_per_week,
        slot_hours_utc=slot_hours_utc,
        max_slots_per_day=max_slots_per_day,
        target_workday_span_hours=target_workday_span_hours,
        weights=weights,
        recommendation=recommendation,
        full_team_sync_required=full_team_sync_required,
        members=members,
        edges=edges,
    )


def precompute_pattern_metrics(scenario: Scenario, patterns: Sequence[Tuple[int, ...]]) -> List[Dict[str, object]]:
    member_profiles = [
        [member_slot_profile(member, hour) for hour in scenario.slot_hours_utc]
        for member in scenario.members
    ]
    metrics = []
    for pattern in patterns:
        team_starts_daily = count_starts(pattern)
        member_timing = []
        member_starts = []
        member_overflow = []
        edge_overlap = []
        joint_full_team_slot_indices = []

        for i, member in enumerate(scenario.members):
            attended = []
            timing = 0.0
            for slot_idx in pattern:
                feasible, cost = member_profiles[i][slot_idx]
                if feasible:
                    attended.append(slot_idx)
                    timing += cost
            member_timing.append(scenario.days_per_week * timing)
            member_starts.append(scenario.days_per_week * count_starts(attended))
            if attended:
                raw_hours = [
                    raw_local_hour(scenario.slot_hours_utc[slot_idx], member.timezone)
                    for slot_idx in attended
                ]
                daily_span = max(raw_hours) - min(raw_hours)
                overflow = max(0.0, daily_span - scenario.target_workday_span_hours)
            else:
                overflow = 0.0
            member_overflow.append(scenario.days_per_week * overflow)

        for edge in scenario.edges:
            i, j = edge.pair
            overlap_slots = 0
            for slot_idx in pattern:
                feasible_i, _ = member_profiles[i][slot_idx]
                feasible_j, _ = member_profiles[j][slot_idx]
                if feasible_i and feasible_j:
                    overlap_slots += 1
            edge_overlap.append(scenario.days_per_week * overlap_slots)

        for slot_idx in pattern:
            jointly_feasible = True
            for member_profile in member_profiles:
                feasible, _ = member_profile[slot_idx]
                if not feasible:
                    jointly_feasible = False
                    break
            if jointly_feasible:
                joint_full_team_slot_indices.append(slot_idx)

        metrics.append(
            {
                "team_starts": scenario.days_per_week * team_starts_daily,
                "member_timing": tuple(member_timing),
                "member_starts": tuple(member_starts),
                "member_overflow": tuple(member_overflow),
                "edge_overlap": tuple(edge_overlap),
                "joint_full_team_slots": len(joint_full_team_slot_indices),
                "joint_full_team_slot_indices": tuple(joint_full_team_slot_indices),
            }
        )
    return metrics


def evaluate_schedule(
    schedule: Sequence[int],
    scenario: Scenario,
    patterns: Sequence[Tuple[int, ...]],
    metrics: Sequence[Dict[str, object]],
    strategy: str,
) -> Dict[str, object]:
    n_members = len(scenario.members)
    timing_totals = [0.0] * n_members
    start_totals = [0.0] * n_members
    overflow_totals = [0.0] * n_members
    total_team_starts = 0.0
    total_demand = 0.0
    total_served = 0.0
    total_slack = 0.0

    for week_idx, pattern_idx in enumerate(schedule):
        metric = metrics[pattern_idx]
        total_team_starts += float(metric["team_starts"])
        for i in range(n_members):
            timing_totals[i] += float(metric["member_timing"][i])
            start_totals[i] += float(metric["member_starts"][i])
            overflow_totals[i] += float(metric["member_overflow"][i])
        for edge_idx, edge in enumerate(scenario.edges):
            demand = edge.weekly_demands[week_idx]
            overlap = float(metric["edge_overlap"][edge_idx])
            served = min(demand, overlap)
            total_demand += demand
            total_served += served
            total_slack += demand - served

    composite = [
        timing_totals[i]
        + scenario.members[i].fragmentation_weight * (start_totals[i] + overflow_totals[i])
        for i in range(n_members)
    ]
    timing_ineq = inequity(timing_totals)
    composite_ineq = inequity(composite)
    joint_full_team_slots_per_week = [
        int(metrics[pattern_idx]["joint_full_team_slots"]) for pattern_idx in schedule
    ]
    meets_full_team_sync = all(
        joint_full_team_slots_per_week[week_idx] >= scenario.full_team_sync_required[week_idx]
        for week_idx in range(scenario.weeks)
    )

    if strategy == "serve_demand_only":
        objective = scenario.weights["alpha"] * total_slack + 0.25 * total_team_starts
    elif strategy == "timing_fair_only":
        objective = (
            scenario.weights["alpha"] * total_slack
            + scenario.weights["beta"] * sum(timing_totals)
            + scenario.weights["eta"] * total_team_starts
            + scenario.weights["delta"] * timing_ineq
        )
    else:
        objective = (
            scenario.weights["alpha"] * total_slack
            + scenario.weights["beta"] * sum(composite)
            + scenario.weights["eta"] * total_team_starts
            + scenario.weights["delta"] * composite_ineq
        )

    weekly_patterns_utc = [format_pattern(scenario.slot_hours_utc, patterns[idx]) for idx in schedule]
    local_patterns_by_member = {
        member.name: [
            format_pattern(scenario.slot_hours_utc, patterns[idx], member.timezone)
            for idx in schedule
        ]
        for member in scenario.members
    }

    return {
        "strategy": strategy,
        "pattern_indices": list(schedule),
        "objective": round(objective, 4),
        "served_fraction": round(0.0 if total_demand == 0 else total_served / total_demand, 4),
        "timing_mean": round(sum(timing_totals) / n_members, 4),
        "starts_mean": round(sum(start_totals) / n_members, 4),
        "overflow_mean": round(sum(overflow_totals) / n_members, 4),
        "composite_inequity": round(composite_ineq, 4),
        "team_starts": round(total_team_starts, 4),
        "joint_full_team_slots_per_week": joint_full_team_slots_per_week,
        "meets_full_team_sync": meets_full_team_sync,
        "weekly_patterns_utc": weekly_patterns_utc,
        "local_patterns_by_member": local_patterns_by_member,
    }


def best_exact_schedule(
    scenario: Scenario,
    patterns: Sequence[Tuple[int, ...]],
    metrics: Sequence[Dict[str, object]],
    strategy: str,
    allowed_pattern_indices_by_week: Optional[Sequence[Sequence[int]]] = None,
) -> Dict[str, object]:
    best = None
    if allowed_pattern_indices_by_week is None:
        allowed_pattern_indices_by_week = [range(len(patterns)) for _ in range(scenario.weeks)]
    for schedule in itertools.product(*allowed_pattern_indices_by_week):
        result = evaluate_schedule(schedule, scenario, patterns, metrics, strategy)
        if best is None or float(result["objective"]) < float(best["objective"]):
            best = result
    assert best is not None
    return best


def rotation_heuristic(
    scenario: Scenario,
    patterns: Sequence[Tuple[int, ...]],
    metrics: Sequence[Dict[str, object]],
    allowed_pattern_indices_by_week: Optional[Sequence[Sequence[int]]] = None,
) -> Dict[str, object]:
    n_members = len(scenario.members)
    cumulative_timing = [0.0] * n_members
    chosen = []
    if allowed_pattern_indices_by_week is None:
        allowed_pattern_indices_by_week = [range(len(patterns)) for _ in range(scenario.weeks)]
    for week_idx in range(scenario.weeks):
        best_score = None
        best_idx = 0
        for pattern_idx in allowed_pattern_indices_by_week[week_idx]:
            metric = metrics[pattern_idx]
            week_timing = [float(x) for x in metric["member_timing"]]
            updated = [cumulative_timing[i] + week_timing[i] for i in range(n_members)]
            slack = 0.0
            for edge_idx, edge in enumerate(scenario.edges):
                demand = edge.weekly_demands[week_idx]
                overlap = float(metric["edge_overlap"][edge_idx])
                slack += max(0.0, demand - overlap)
            score = (
                scenario.weights["alpha"] * slack
                + sum(week_timing)
                + 0.75 * inequity(updated)
                + 0.4 * float(metric["team_starts"])
            )
            if best_score is None or score < best_score:
                best_score = score
                best_idx = pattern_idx
        chosen.append(best_idx)
        for i in range(n_members):
            cumulative_timing[i] += float(metrics[best_idx]["member_timing"][i])
    return evaluate_schedule(chosen, scenario, patterns, metrics, "rotation_heuristic")


def choose_recommendation(
    results: Dict[str, Dict[str, object]],
    max_drop: float,
    sync_active: bool,
    sync_feasible: bool,
    binding_for_selected_strategy: Optional[bool],
) -> Dict[str, str]:
    timing = results["timing_fair_only"]
    frag = results["fragmentation_aware"]
    served_drop = float(timing["served_fraction"]) - float(frag["served_fraction"])
    sync_suffix = ""
    if sync_active and not sync_feasible:
        sync_suffix = (
            " The requested recurring full-team sync is infeasible on the current UTC grid and "
            "protected-hour configuration, so this recommendation is the best unconstrained fallback."
        )
    elif sync_active and binding_for_selected_strategy is False:
        sync_suffix = " The requested recurring full-team sync is feasible and non-binding for this strategy."
    elif sync_active and binding_for_selected_strategy is True:
        sync_suffix = " The requested recurring full-team sync changes the schedule but this remains the best constrained option."
    if served_drop > max_drop:
        return {
            "selected_strategy": "timing_fair_only",
            "reason": (
                "Fragmentation-aware scheduling paid too much served-demand loss relative "
                "to the allowed threshold, so timing-fair is the safer default."
                f"{sync_suffix}"
            ),
        }
    if (
        float(frag["composite_inequity"]) < float(timing["composite_inequity"])
        or float(frag["overflow_mean"]) < float(timing["overflow_mean"])
        or float(frag["starts_mean"]) < float(timing["starts_mean"])
    ):
        return {
            "selected_strategy": "fragmentation_aware",
            "reason": (
                "Fragmentation-aware scheduling improves fairness, day stretch, or repeated "
                "starts without paying an excessive coverage penalty."
                f"{sync_suffix}"
            ),
        }
    return {
        "selected_strategy": "timing_fair_only",
        "reason": (
            "Timing-fair already performs comparably, so the simpler schedule is recommended."
            f"{sync_suffix}"
        ),
    }


def build_recommended_visual(
    scenario: Scenario,
    patterns: Sequence[Tuple[int, ...]],
    metrics: Sequence[Dict[str, object]],
    selected_result: Dict[str, object],
    show_joint_sync_highlight: bool,
) -> Dict[str, object]:
    slot_duration_hours = infer_slot_duration(scenario.slot_hours_utc)
    week_specs = []
    pattern_indices = [int(idx) for idx in selected_result["pattern_indices"]]
    for week_idx, pattern_idx in enumerate(pattern_indices, start=1):
        pattern = patterns[pattern_idx]
        metric = metrics[pattern_idx]
        joint_sync_pattern = tuple(metric["joint_full_team_slot_indices"])
        members = []
        for member in scenario.members:
            active_intervals = local_pattern_intervals(
                scenario.slot_hours_utc,
                pattern,
                member.timezone,
                slot_duration_hours,
            )
            joint_sync_intervals = local_pattern_intervals(
                scenario.slot_hours_utc,
                joint_sync_pattern,
                member.timezone,
                slot_duration_hours,
            )
            protected_intervals = protected_local_intervals(member)
            members.append(
                {
                    "name": member.name,
                    "timezone": format_timezone(member.timezone),
                    "label": (
                        f"{member.name} ({format_timezone(member.timezone)}, "
                        f"standard {format_hour(STANDARD_WORK_START_HOUR)}-"
                        f"{format_hour(STANDARD_WORK_END_HOUR)})"
                    ),
                    "standard_work_hours_local": {
                        "start": format_hour(STANDARD_WORK_START_HOUR),
                        "end": format_hour(STANDARD_WORK_END_HOUR),
                    },
                    "active_blocks_local": [format_interval(interval) for interval in active_intervals],
                    "joint_sync_blocks_local": [
                        format_interval(interval) for interval in joint_sync_intervals
                    ],
                    "protected_windows_local": [
                        format_interval(interval) for interval in protected_intervals
                    ],
                }
            )
        week_specs.append(
            {
                "week": week_idx,
                "utc_pattern": format_pattern(scenario.slot_hours_utc, pattern),
                "joint_sync_utc_pattern": format_pattern(
                    scenario.slot_hours_utc,
                    joint_sync_pattern,
                ),
                "members": members,
            }
        )

    return {
        "title": f"Recommended schedule for {scenario.team_name}",
        "strategy": str(selected_result["strategy"]),
        "slot_duration_hours": round(slot_duration_hours, 4),
        "timezone_reference": "Local time is shown separately for each member row.",
        "standard_work_hours_local": {
            "start": format_hour(STANDARD_WORK_START_HOUR),
            "end": format_hour(STANDARD_WORK_END_HOUR),
            "fill": "#d1d5db",
        },
        "highlighted_overlap_blocks": {
            "fill": "#2563eb",
        },
        "joint_sync_highlight": {
            "active": show_joint_sync_highlight,
            "fill": "#16a34a",
        },
        "weeks": week_specs,
    }


def render_recommended_svg(visual: Dict[str, object]) -> str:
    week_specs = list(visual["weeks"])
    members_per_week = len(week_specs[0]["members"]) if week_specs else 0
    px_per_hour = 18.0
    label_width = 250.0
    axis_height = 44.0
    row_height = 28.0
    row_gap = 10.0
    week_gap = 28.0
    panel_width = label_width + 24.0 * px_per_hour
    panel_height = axis_height + members_per_week * (row_height + row_gap) + 64.0
    width = 32.0 + len(week_specs) * panel_width + max(0, len(week_specs) - 1) * week_gap + 32.0
    height = 72.0 + panel_height

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}" role="img" aria-label="{html.escape(str(visual["title"]))}">',
        '<rect width="100%" height="100%" fill="#f8fafc" />',
        f'<text x="32" y="34" font-family="Helvetica, Arial, sans-serif" font-size="22" '
        f'font-weight="700" fill="#0f172a">{html.escape(str(visual["title"]))}</text>',
        f'<text x="32" y="56" font-family="Helvetica, Arial, sans-serif" font-size="13" '
        f'fill="#334155">Recommended strategy: {html.escape(str(visual["strategy"]))}. '
        f'Grey = standard local work hours (09:00-17:00). Blue = chosen overlap blocks'
        f'{"; green = recurring full-team sync blocks." if bool(visual["joint_sync_highlight"]["active"]) else "."}</text>',
    ]

    for week_idx, week in enumerate(week_specs):
        panel_x = 32.0 + week_idx * (panel_width + week_gap)
        panel_y = 72.0
        grid_x = panel_x + label_width
        svg_parts.append(
            f'<rect x="{panel_x:.1f}" y="{panel_y:.1f}" width="{panel_width:.1f}" '
            f'height="{panel_height:.1f}" rx="12" fill="#ffffff" stroke="#cbd5e1" />'
        )
        svg_parts.append(
            f'<text x="{panel_x + 16:.1f}" y="{panel_y + 24:.1f}" font-family="Helvetica, Arial, sans-serif" '
            f'font-size="16" font-weight="700" fill="#0f172a">Week {int(week["week"])}</text>'
        )
        svg_parts.append(
            f'<text x="{panel_x + 16:.1f}" y="{panel_y + 44:.1f}" font-family="Helvetica, Arial, sans-serif" '
            f'font-size="13" fill="#475569">UTC pattern: {html.escape(str(week["utc_pattern"]))}</text>'
        )
        if bool(visual["joint_sync_highlight"]["active"]):
            svg_parts.append(
                f'<text x="{panel_x + 16:.1f}" y="{panel_y + 60:.1f}" font-family="Helvetica, Arial, sans-serif" '
                f'font-size="12" fill="#166534">Full-team sync: {html.escape(str(week["joint_sync_utc_pattern"]))}</text>'
            )
        for hour in range(25):
            x = grid_x + hour * px_per_hour
            stroke = "#cbd5e1" if hour % 3 == 0 else "#e2e8f0"
            svg_parts.append(
                f'<line x1="{x:.1f}" y1="{panel_y + 54:.1f}" x2="{x:.1f}" y2="{panel_y + panel_height - 20:.1f}" '
                f'stroke="{stroke}" stroke-width="1" />'
            )
            if hour < 24:
                svg_parts.append(
                    f'<text x="{x + 2:.1f}" y="{panel_y + 68:.1f}" font-family="Helvetica, Arial, sans-serif" '
                    f'font-size="11" fill="#64748b">{hour:02d}</text>'
                )
        for row_idx, member in enumerate(week["members"]):
            y = panel_y + axis_height + row_idx * (row_height + row_gap)
            svg_parts.append(
                f'<text x="{panel_x + 16:.1f}" y="{y + 18:.1f}" font-family="Helvetica, Arial, sans-serif" '
                f'font-size="12" fill="#0f172a">{html.escape(str(member["label"]))}</text>'
            )
            svg_parts.append(
                f'<rect x="{grid_x:.1f}" y="{y:.1f}" width="{24.0 * px_per_hour:.1f}" height="{row_height:.1f}" '
                'fill="#ffffff" stroke="#cbd5e1" rx="4" />'
            )
            standard_interval = (
                STANDARD_WORK_START_HOUR,
                STANDARD_WORK_END_HOUR,
            )
            svg_parts.extend(
                interval_rects(
                    [standard_interval],
                    grid_x,
                    y,
                    px_per_hour,
                    row_height,
                    fill="#d1d5db",
                    opacity=1.0,
                )
            )
            protected_windows = [
                (
                    float(block["start_hour"]),
                    float(block["end_hour"]),
                )
                for block in member["protected_windows_local"]
            ]
            if protected_windows:
                svg_parts.extend(
                    interval_rects(
                        protected_windows,
                        grid_x,
                        y + 3.0,
                        px_per_hour,
                        row_height - 6.0,
                        fill="#fecaca",
                        stroke="#ef4444",
                        opacity=0.55,
                    )
                )
            active_blocks = [
                (
                    float(block["start_hour"]),
                    float(block["end_hour"]),
                )
                for block in member["active_blocks_local"]
            ]
            svg_parts.extend(
                interval_rects(
                    active_blocks,
                    grid_x,
                    y + 4.0,
                    px_per_hour,
                    row_height - 8.0,
                    fill="#2563eb",
                    stroke="#1d4ed8",
                    opacity=0.95,
                )
            )
            if bool(visual["joint_sync_highlight"]["active"]):
                joint_sync_blocks = [
                    (
                        float(block["start_hour"]),
                        float(block["end_hour"]),
                    )
                    for block in member["joint_sync_blocks_local"]
                ]
                svg_parts.extend(
                    interval_rects(
                        joint_sync_blocks,
                        grid_x,
                        y + 8.0,
                        px_per_hour,
                        row_height - 16.0,
                        fill="#16a34a",
                        stroke="#15803d",
                        opacity=0.95,
                    )
                )

    legend_y = height - 18.0
    legend_x = 32.0
    svg_parts.extend(
        [
            f'<rect x="{legend_x:.1f}" y="{legend_y - 12:.1f}" width="14" height="14" fill="#d1d5db" rx="3" />',
            f'<text x="{legend_x + 20:.1f}" y="{legend_y:.1f}" font-family="Helvetica, Arial, sans-serif" '
            'font-size="12" fill="#475569">Standard hours</text>',
            f'<rect x="{legend_x + 140:.1f}" y="{legend_y - 12:.1f}" width="14" height="14" fill="#fecaca" '
            'stroke="#ef4444" rx="3" />',
            f'<text x="{legend_x + 160:.1f}" y="{legend_y:.1f}" font-family="Helvetica, Arial, sans-serif" '
            'font-size="12" fill="#475569">Protected windows</text>',
            f'<rect x="{legend_x + 310:.1f}" y="{legend_y - 12:.1f}" width="14" height="14" fill="#2563eb" '
            'stroke="#1d4ed8" rx="3" />',
            f'<text x="{legend_x + 330:.1f}" y="{legend_y:.1f}" font-family="Helvetica, Arial, sans-serif" '
            'font-size="12" fill="#475569">Recommended overlap</text>',
        ]
    )
    if bool(visual["joint_sync_highlight"]["active"]):
        svg_parts.extend(
            [
                f'<rect x="{legend_x + 490:.1f}" y="{legend_y - 12:.1f}" width="14" height="14" fill="#16a34a" '
                'stroke="#15803d" rx="3" />',
                f'<text x="{legend_x + 510:.1f}" y="{legend_y:.1f}" font-family="Helvetica, Arial, sans-serif" '
                'font-size="12" fill="#475569">Full-team sync</text>',
            ]
        )
    svg_parts.append("</svg>")
    return "".join(svg_parts)


def solve(payload: Dict[str, object]) -> Dict[str, object]:
    scenario = normalize_input(payload)
    patterns = all_patterns(scenario.slot_hours_utc, scenario.max_slots_per_day)
    metrics = precompute_pattern_metrics(scenario, patterns)
    unconstrained_results = {
        "serve_demand_only": best_exact_schedule(scenario, patterns, metrics, "serve_demand_only"),
        "timing_fair_only": best_exact_schedule(scenario, patterns, metrics, "timing_fair_only"),
        "rotation_heuristic": rotation_heuristic(scenario, patterns, metrics),
        "fragmentation_aware": best_exact_schedule(scenario, patterns, metrics, "fragmentation_aware"),
    }

    sync_active = any(required > 0 for required in scenario.full_team_sync_required)
    weekly_feasible_pattern_indices: List[List[int]] = []
    for required in scenario.full_team_sync_required:
        feasible_indices = [
            pattern_idx
            for pattern_idx, metric in enumerate(metrics)
            if int(metric["joint_full_team_slots"]) >= required
        ]
        weekly_feasible_pattern_indices.append(feasible_indices)
    sync_feasible = all(weekly_feasible_pattern_indices)

    mode = "unconstrained"
    binding_by_strategy: Dict[str, Optional[bool]] = {
        strategy_name: None for strategy_name in unconstrained_results
    }

    if sync_active and sync_feasible:
        mode = "full_team_sync"
        active_results = {
            "serve_demand_only": best_exact_schedule(
                scenario,
                patterns,
                metrics,
                "serve_demand_only",
                weekly_feasible_pattern_indices,
            ),
            "timing_fair_only": best_exact_schedule(
                scenario,
                patterns,
                metrics,
                "timing_fair_only",
                weekly_feasible_pattern_indices,
            ),
            "rotation_heuristic": rotation_heuristic(
                scenario,
                patterns,
                metrics,
                weekly_feasible_pattern_indices,
            ),
            "fragmentation_aware": best_exact_schedule(
                scenario,
                patterns,
                metrics,
                "fragmentation_aware",
                weekly_feasible_pattern_indices,
            ),
        }
        for strategy_name, constrained_result in active_results.items():
            binding_by_strategy[strategy_name] = (
                constrained_result["pattern_indices"]
                != unconstrained_results[strategy_name]["pattern_indices"]
            )
            constrained_result["constraint_binding_vs_unconstrained"] = binding_by_strategy[strategy_name]
    elif sync_active:
        mode = "fallback_unconstrained"
        active_results = unconstrained_results
    else:
        active_results = unconstrained_results

    preliminary_recommendation = choose_recommendation(
        active_results,
        float(scenario.recommendation["max_served_fraction_drop_vs_timing_fair"]),
        sync_active=sync_active,
        sync_feasible=sync_feasible,
        binding_for_selected_strategy=None,
    )
    selected_strategy = preliminary_recommendation["selected_strategy"]
    recommendation = choose_recommendation(
        active_results,
        float(scenario.recommendation["max_served_fraction_drop_vs_timing_fair"]),
        sync_active=sync_active,
        sync_feasible=sync_feasible,
        binding_for_selected_strategy=binding_by_strategy[selected_strategy],
    )
    selected_result = active_results[selected_strategy]
    recommended_visual = build_recommended_visual(
        scenario,
        patterns,
        metrics,
        selected_result,
        show_joint_sync_highlight=sync_active and sync_feasible,
    )

    for strategy_name, strategy_result in active_results.items():
        strategy_result["constraint_binding_vs_unconstrained"] = binding_by_strategy[strategy_name]
        strategy_result.pop("pattern_indices", None)

    constraint_status = {
        "mode": mode,
        "full_team_sync": {
            "active": sync_active,
            "required_joint_slots_per_week": scenario.full_team_sync_required,
            "feasible": sync_feasible,
            "weekly_feasible_pattern_counts": [
                len(pattern_indices) for pattern_indices in weekly_feasible_pattern_indices
            ],
            "binding_for_recommended_strategy": binding_by_strategy[selected_strategy],
            "binding_by_strategy": binding_by_strategy,
        },
    }
    if sync_active and not sync_feasible:
        constraint_status["full_team_sync"]["infeasible_reason"] = (
            "No recurring weekly pattern sequence on the current UTC grid can provide the requested "
            "number of jointly feasible full-team slots in every week."
        )

    status = "ok" if (not sync_active or sync_feasible) else "infeasible_full_team_sync"

    return {
        "team_name": scenario.team_name,
        "status": status,
        "config": {
            "weeks": scenario.weeks,
            "days_per_week": scenario.days_per_week,
            "target_workday_span_hours": scenario.target_workday_span_hours,
            "slot_hours_utc": scenario.slot_hours_utc,
            "max_slots_per_day": scenario.max_slots_per_day,
            "weights": scenario.weights,
            "full_team_sync_required": scenario.full_team_sync_required,
        },
        "constraint_status": constraint_status,
        "recommendation": recommendation,
        "recommended_visual": recommended_visual,
        "strategies": active_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Solve a recurring equitable-overlap schedule problem.")
    parser.add_argument("input", nargs="?", help="Path to input JSON. If omitted, read from stdin.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    parser.add_argument(
        "--visual-out",
        help="Optional path to write an SVG visual for the recommended strategy.",
    )
    args = parser.parse_args()

    result = solve(load_json(args.input))
    if args.visual_out:
        svg = render_recommended_svg(result["recommended_visual"])
        output_path = Path(args.visual_out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(svg, encoding="utf-8")
        result["recommended_visual"]["svg_path"] = str(output_path)
    if args.pretty:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
