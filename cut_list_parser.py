"""Pure cut-list parsing, board grouping, and HTML rendering helpers."""
import html as html_text
import re


GROUP_COLORS = ("#38bdf8", "#f59e0b")

# Round-tripped rendered lines look like: '> Cut 3: 18.0000" description'
_DISPLAY_RE = re.compile(r'^[>\s]*Cut\s+\d+:\s*(\d+\.?\d*)\s*"?\s*(.*)$')

# Length-first format: '<length> <description>' or '<length>" <description>'.
# Requiring whitespace, quote, or end-of-line after the number prevents lumber
# labels like '2x4 stud 48' from being mis-parsed as a 2.0-inch cut.
_LEADING_RE = re.compile(r'^(\d+\.?\d*)(?:\s*"\s*|\s+|$)(.*)$')

_NUMBER_RE = re.compile(r'(\d+\.?\d*)')


def parse_cut_list_lines(lines):
    """Parse raw text lines into [(cut_number, length_in, description), ...] and log messages."""
    cuts = []
    warnings = []
    next_num = 1
    for line in lines:
        clean_line = line.strip()
        if not clean_line:
            continue

        display_match = _DISPLAY_RE.match(clean_line)
        if display_match:
            length = float(display_match.group(1))
            description = display_match.group(2).strip(' ,:"')
            if length > 0:
                cuts.append((next_num, length, description))
                next_num += 1
            continue

        leading_match = _LEADING_RE.match(clean_line)
        if leading_match:
            length = float(leading_match.group(1))
            description = leading_match.group(2).strip(' ,:"')
            if length > 0:
                cuts.append((next_num, length, description))
                next_num += 1
            continue

        data_part = clean_line.rsplit(':', 1)[-1] if ':' in clean_line else clean_line
        matches = list(_NUMBER_RE.finditer(data_part))
        if matches:
            try:
                match = matches[-1]
                length = float(match.group(1))
                start, end = match.span(1)
                description = (data_part[:start] + data_part[end:]).strip(' ,:"')
                if length > 0:
                    cuts.append((next_num, length, description))
                    next_num += 1
            except (ValueError, IndexError):
                warnings.append(f"Could not parse number from: '{data_part}'")
        else:
            warnings.append(f"No number found in line: '{line}'")

    return cuts, warnings


def group_cuts_by_board(cut_list, board_length, kerf):
    """Assign each cut to a sequential board group and compute used length per group.

    Reserves one leading truing-cut kerf per board (0.0" overage), so N cuts on a
    board consume `kerf + sum(length + kerf) = sum(length) + (N + 1) * kerf`.
    """
    cut_groups = []
    group_used_map = {}
    if not cut_list:
        return cut_groups, group_used_map
    truing_kerf = max(0.0, float(kerf))
    group_index = 0
    group_used = truing_kerf
    cuts_in_group = 0
    for _, length, _ in cut_list:
        needed = length + truing_kerf
        if cuts_in_group > 0 and group_used + needed > board_length + 1e-9:
            group_used_map[group_index] = group_used
            group_index += 1
            group_used = truing_kerf
            cuts_in_group = 0
        group_used += needed
        cuts_in_group += 1
        cut_groups.append(group_index)
    group_used_map[group_index] = group_used
    return cut_groups, group_used_map


def render_cut_list_html(cut_list, cut_groups, active_index):
    """Render color-coded cut-list HTML with the active cut highlighted."""
    html_lines = []
    for i, (num, length, desc) in enumerate(cut_list):
        color = GROUP_COLORS[cut_groups[i] % len(GROUP_COLORS)]
        line_text = html_text.escape(f"Cut {num}: {length:<9.4f}\" {desc}")
        if i == active_index:
            html_lines.append(
                f"<div style='background-color:#334155;'><b><span style='color:{color};'>&gt; {line_text}</span></b></div>"
            )
        else:
            html_lines.append(f"<span style='color:{color};'>&nbsp; {line_text}</span>")
    return "<br>".join(html_lines)
