"""Branch-and-Bound 1D cutting-stock optimizer and job summary helpers."""
from dataclasses import dataclass
import math
import time
from typing import Iterable, Sequence

from cut_list_parser import group_cuts_by_board

_SCALE = 10_000  # 0.0001 in fixed-point units (matches HMI 4-decimal precision)


@dataclass(frozen=True)
class CutListSummary:
    cut_count: int
    board_count: int
    board_length_in: float
    kerf_in: float
    total_cut_in: float
    total_used_in: float
    total_stock_in: float
    waste_in: float
    utilization_pct: float
    largest_offcut_in: float
    oversized_count: int


@dataclass(frozen=True)
class OptimizationResult:
    cuts: list[tuple[int, float, str]]
    before: CutListSummary
    after: CutListSummary
    boards_saved: int
    optimal: bool
    elapsed_ms: float
    oversized: list[tuple[int, float, str]]


def summarize_cut_list(
    cuts: Sequence[tuple[int, float, str]],
    board_length: float,
    kerf: float,
) -> CutListSummary:
    """Compute board count, linear material, utilization, and largest remnant."""
    if not cuts or board_length <= 0:
        return CutListSummary(
            cut_count=len(cuts),
            board_count=0,
            board_length_in=float(board_length),
            kerf_in=float(kerf),
            total_cut_in=0.0,
            total_used_in=0.0,
            total_stock_in=0.0,
            waste_in=0.0,
            utilization_pct=0.0,
            largest_offcut_in=0.0,
            oversized_count=0,
        )

    _, group_used_map = group_cuts_by_board(cuts, board_length, kerf)
    board_count = len(group_used_map)
    total_cut_in = sum(length for _, length, _ in cuts)
    total_used_in = sum(group_used_map.values())
    total_stock_in = board_count * board_length
    remainders = [max(0.0, board_length - used) for used in group_used_map.values()]
    waste_in = sum(remainders)
    utilization_pct = (total_used_in / total_stock_in * 100.0) if total_stock_in > 0 else 0.0
    oversized_count = sum(1 for _, length, _ in cuts if length + kerf > board_length + 1e-9)
    return CutListSummary(
        cut_count=len(cuts),
        board_count=board_count,
        board_length_in=float(board_length),
        kerf_in=float(kerf),
        total_cut_in=total_cut_in,
        total_used_in=total_used_in,
        total_stock_in=total_stock_in,
        waste_in=waste_in,
        utilization_pct=utilization_pct,
        largest_offcut_in=max(remainders) if remainders else 0.0,
        oversized_count=oversized_count,
    )


def format_summary_text(summary: CutListSummary) -> str:
    """Compact one-line job summary suitable for AUTO and CUT LISTS headers."""
    if summary.cut_count == 0:
        return "No cuts loaded"
    feet = summary.total_cut_in / 12.0
    waste_pct = max(0.0, 100.0 - summary.utilization_pct)
    text = (
        f"{summary.cut_count} cuts  •  {summary.board_count} "
        f"{'board' if summary.board_count == 1 else 'boards'} "
        f'({summary.board_length_in:g}")  •  {feet:.1f} ft  •  '
        f"{waste_pct:.1f}% waste  •  best offcut {summary.largest_offcut_in:.1f}\""
    )
    if summary.oversized_count:
        text += f"  •  {summary.oversized_count} OVERSIZED"
    return text


def _heuristic_pack(sizes: Sequence[int], cap: int, best_fit: bool) -> list[list[int]]:
    """Fast FFD / BFD initial incumbent packing over descending item indices."""
    bins: list[list[int]] = []
    rems: list[int] = []
    for idx, size in enumerate(sizes):
        chosen = -1
        chosen_rem = cap + 1
        for b, rem in enumerate(rems):
            if rem >= size:
                if not best_fit:
                    chosen = b
                    break
                if rem < chosen_rem:
                    chosen = b
                    chosen_rem = rem
        if chosen >= 0:
            bins[chosen].append(idx)
            rems[chosen] -= size
        else:
            bins.append([idx])
            rems.append(cap - size)
    return bins


def _score_bins(bins: Sequence[Sequence[int]], sizes: Sequence[int], cap: int) -> tuple[int, int]:
    """Return (board_count, -sum_of_squared_remainders) so smaller tuple is strictly better."""
    rem_sq = 0
    for group in bins:
        rem = cap - sum(sizes[i] for i in group)
        rem_sq += rem * rem
    return (len(bins), -rem_sq)


def _lower_bound(sizes: Sequence[int], cap: int) -> int:
    """Compute a fast, admissible lower bound on the number of boards required."""
    if not sizes:
        return 0
    total = sum(sizes)
    l1 = math.ceil(total / cap)
    half = cap // 2
    # Items strictly larger than cap / 2 can never share a board with each other.
    big_count = 0
    for s in sizes:
        if s > half:
            big_count += 1
        else:
            break
    return max(l1, big_count)


def _max_possible_rem_sq(total_waste: int, bin_count: int, cap: int) -> int:
    """Upper bound on sum(rem_b^2) for distributing total_waste across bin_count bins <= cap."""
    if total_waste <= 0 or bin_count <= 0:
        return 0
    full_empty, partial = divmod(total_waste, cap)
    return full_empty * cap * cap + partial * partial


def _solve_branch_and_bound(
    sizes: Sequence[int],
    cap: int,
    time_limit_s: float,
) -> tuple[list[list[int]], bool]:
    """Find minimum-board packing (tie-broken by max sum(rem^2)) with symmetry breaking."""
    n = len(sizes)
    if n == 0:
        return [], True
    if n == 1:
        return [[0]], True

    # Seed incumbent with the better of BFD and FFD.
    bfd = _heuristic_pack(sizes, cap, best_fit=True)
    ffd = _heuristic_pack(sizes, cap, best_fit=False)
    best_bins = bfd if _score_bins(bfd, sizes, cap) <= _score_bins(ffd, sizes, cap) else ffd
    best_count, best_neg_rem_sq = _score_bins(best_bins, sizes, cap)
    best_rem_sq = -best_neg_rem_sq

    total_size = sum(sizes)
    lb_global = _lower_bound(sizes, cap)

    # Precompute suffix totals and smallest remaining item for tight pruning.
    suffix_sum = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        suffix_sum[i] = suffix_sum[i + 1] + sizes[i]
    min_tail = [0] * (n + 1)
    min_tail[n] = cap + 1
    for i in range(n - 1, -1, -1):
        min_tail[i] = sizes[i] if sizes[i] < min_tail[i + 1] else min_tail[i + 1]

    # If the heuristic already achieved the theoretical maximum rem^2 at the lower bound,
    # no strictly better solution can exist.
    if best_count == lb_global:
        max_sq = _max_possible_rem_sq(best_count * cap - total_size, best_count, cap)
        if best_rem_sq >= max_sq:
            return best_bins, True

    deadline = time.perf_counter() + max(0.005, float(time_limit_s))
    timed_out = False
    nodes = 0

    rems: list[int] = []
    current_bins: list[list[int]] = []
    assign = [-1] * n

    def dfs(idx: int) -> None:
        nonlocal best_bins, best_count, best_rem_sq, timed_out, nodes
        if timed_out:
            return
        nodes += 1
        if (nodes & 1023) == 0 and time.perf_counter() >= deadline:
            timed_out = True
            return

        if idx == n:
            bcount = len(rems)
            rem_sq = sum(r * r for r in rems)
            if bcount < best_count or (bcount == best_count and rem_sq > best_rem_sq):
                best_count = bcount
                best_rem_sq = rem_sq
                best_bins = [list(group) for group in current_bins]
            return

        open_bins = len(rems)
        rem_total = suffix_sum[idx]
        smallest = min_tail[idx]
        usable_slack = 0
        for r in rems:
            if r >= smallest:
                usable_slack += r
        deficit = rem_total - usable_slack
        min_extra = (deficit + cap - 1) // cap if deficit > 0 else 0
        min_total_bins = open_bins + min_extra
        if min_total_bins > best_count:
            return

        # Symmetry breaking for identical consecutive lengths: never place into an
        # earlier bin index than the previous identical item.
        start_bin = assign[idx - 1] if (idx > 0 and sizes[idx] == sizes[idx - 1]) else 0
        size = sizes[idx]

        # Try existing bins in tightest-fit order (best-fit branching) while skipping
        # duplicate remaining capacities at this depth.
        candidates: list[tuple[int, int]] = []
        seen_rem: set[int] = set()
        for b in range(start_bin, open_bins):
            r = rems[b]
            if r >= size and r not in seen_rem:
                seen_rem.add(r)
                candidates.append((r, b))
        candidates.sort()

        for _, b in candidates:
            rems[b] -= size
            current_bins[b].append(idx)
            assign[idx] = b
            dfs(idx + 1)
            current_bins[b].pop()
            rems[b] += size
            if timed_out:
                return

        # Option: open a new board (only if we can still beat or tie best_count).
        if open_bins < best_count:
            # Don't open a new board if we are already tied at best_count and cannot
            # possibly beat best_rem_sq even with ideal waste concentration.
            if open_bins + 1 == best_count:
                total_waste = best_count * cap - total_size
                if _max_possible_rem_sq(total_waste, best_count, cap) <= best_rem_sq:
                    return
            rems.append(cap - size)
            current_bins.append([idx])
            assign[idx] = open_bins
            dfs(idx + 1)
            current_bins.pop()
            rems.pop()

    dfs(0)
    return best_bins, not timed_out


def optimize_cut_list(
    cuts: Sequence[tuple[int, float, str]],
    board_length: float,
    kerf: float,
    *,
    time_limit_s: float = 0.25,
    longest_last: bool = True,
) -> OptimizationResult:
    """Optimize cut order via BFD-seeded Branch-and-Bound for minimum boards & best offcut.

    - Uses exact 0.0001" fixed-point math matching `group_cuts_by_board`.
    - Ties at minimum board count favor concentrating scrap into one long usable remnant.
    - Orders boards tightest-first (largest usable remnant last) and, when
      `longest_last=True`, orders cuts within each board shortest-to-longest so the
      longest piece is cut last (maximizing pusher clearance from the blade/clamp).
    """
    started = time.perf_counter()
    before = summarize_cut_list(cuts, board_length, kerf)
    if not cuts or board_length <= 0:
        return OptimizationResult(
            cuts=list(cuts),
            before=before,
            after=before,
            boards_saved=0,
            optimal=True,
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
            oversized=[],
        )

    cap = round(board_length * _SCALE)
    fit_items: list[tuple[int, float, str, int]] = []
    oversized: list[tuple[int, float, str]] = []
    for num, length, desc in cuts:
        need = round((length + kerf) * _SCALE)
        if need <= cap:
            fit_items.append((num, float(length), desc, need))
        else:
            oversized.append((num, float(length), desc))

    # Sort descending by required length (preserving original order on ties).
    fit_items.sort(key=lambda item: -item[3])
    sizes = [item[3] for item in fit_items]

    packed_indices, optimal = _solve_branch_and_bound(sizes, cap, time_limit_s)

    # Sort boards so fullest boards cut first and the board with the biggest
    # reusable remnant cuts last.
    board_groups: list[tuple[int, list[tuple[int, float, str, int]]]] = []
    for group in packed_indices:
        members = [fit_items[i] for i in group]
        # Within each board: shortest -> longest keeps the longest piece last
        # so the pusher stays further from the clamp/blade keepout zone.
        members.sort(key=lambda item: item[1], reverse=not longest_last)
        used = sum(item[3] for item in members)
        board_groups.append((used, members))
    board_groups.sort(key=lambda entry: -entry[0])

    reordered: list[tuple[int, float, str]] = []
    next_num = 1
    for _, members in board_groups:
        for _, length, desc, _ in members:
            reordered.append((next_num, length, desc))
            next_num += 1
    for _, length, desc in oversized:
        reordered.append((next_num, length, desc))
        next_num += 1

    after = summarize_cut_list(reordered, board_length, kerf)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return OptimizationResult(
        cuts=reordered,
        before=before,
        after=after,
        boards_saved=max(0, before.board_count - after.board_count),
        optimal=optimal,
        elapsed_ms=elapsed_ms,
        oversized=oversized,
    )


def format_cuts_as_lines(cuts: Iterable[tuple[int, float, str]]) -> list[str]:
    """Serialize cuts back to clean editor lines ('<length> <desc>')."""
    lines = []
    for _, length, desc in cuts:
        length_str = f"{length:.4f}".rstrip("0").rstrip(".")
        lines.append(f"{length_str} {desc}".strip() if desc else length_str)
    return lines
