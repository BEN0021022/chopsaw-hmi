"""Unit tests for pure cut-list parsing, board grouping, and typed SequenceState."""
import unittest

from cut_list_parser import (
    group_cuts_by_board,
    parse_cut_list_lines,
    render_cut_list_html,
)
from sequence_state import SequenceStage, SequenceState


class CutListParserTests(unittest.TestCase):
    def test_parses_length_first_lumber_dimensions_and_round_trip(self):
        lines = [
            "78.75 Roof Side #1",
            "2x4 stud 48",
            "2x6 header: 62.5",
            '> Cut 3: 18.0000" Window #2',
            '12.5" trim piece',
            "   ",
            "no numbers here",
        ]
        cuts, warnings = parse_cut_list_lines(lines)
        self.assertEqual(
            cuts,
            [
                (1, 78.75, "Roof Side #1"),
                (2, 48.0, "2x4 stud"),
                (3, 62.5, ""),
                (4, 18.0, "Window #2"),
                (5, 12.5, "trim piece"),
            ],
        )
        self.assertEqual(len(warnings), 1)
        self.assertIn("no numbers here", warnings[0])

    def test_group_cuts_by_board_and_render_html(self):
        cuts = [(1, 60.0, "A"), (2, 60.0, "B"), (3, 40.0, "C")]
        groups, used = group_cuts_by_board(cuts, board_length=144.5, kerf=0.1)
        self.assertEqual(groups, [0, 0, 1])
        self.assertAlmostEqual(used[0], 120.2)
        self.assertAlmostEqual(used[1], 40.1)
        html = render_cut_list_html(cuts, groups, active_index=1)
        self.assertIn("&gt; Cut 2:", html)
        self.assertIn("#38bdf8", html)
        self.assertIn("#f59e0b", html)


class SequenceStateTests(unittest.TestCase):
    def test_stage_transitions_and_mapping_compat(self):
        state = SequenceState(stage=SequenceStage.SEARCH_PROFILE, cuts=[24.0], kerf=0.12)
        self.assertEqual(state.stage, SequenceStage.SEARCH_PROFILE)
        self.assertEqual(state["stage"], "SEARCH_PROFILE")
        self.assertIn("stage", state)
        state.transition(SequenceStage.MOVE, now=123.5)
        self.assertEqual(state.stage, SequenceStage.MOVE)
        self.assertEqual(state.at, 123.5)
        with self.assertRaises(KeyError):
            _ = state["nonexistent_key"]
        with self.assertRaises(ValueError):
            state.transition("NOT_A_REAL_STAGE")


if __name__ == "__main__":
    unittest.main()
