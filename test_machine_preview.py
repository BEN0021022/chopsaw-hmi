"""Pure planning regressions; examples must exercise the execution coordinator."""
import unittest
from dataclasses import replace
from automation_supervision import AutomationCoordinator, Outcome, Span
from machine_preview import example_scenarios, evaluate, preview_cut_list
from cycle_diagnostics import CycleDiagnostics


class PreviewTests(unittest.TestCase):
    def test_examples_match_execution_policy(self):
        for scenario in example_scenarios():
            with self.subTest(scenario=scenario.title):
                result = evaluate(scenario.context, scenario.action)
                self.assertEqual(result.code, scenario.expected)
                coordinator = AutomationCoordinator(scenario.context.geometry)
                coordinator.material = scenario.context.material
                self.assertEqual(result, coordinator.decide(scenario.context, scenario.action))

    def test_lookahead_stops_before_first_unsupported_cut(self):
        context = example_scenarios()[0].context
        snapshot = context
        rows = preview_cut_list(context, [12, 20, 1], .125)
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(rows[0].position, 27.875)
        self.assertTrue(rows[0].decision.proceeds)
        self.assertAlmostEqual(rows[1].position, 7.75)
        self.assertFalse(rows[1].decision.proceeds)
        self.assertEqual(context, snapshot)
        self.assertEqual(context.material.stock, Span(-20, 40))

    def test_forecast_clearance_is_minimum_push(self):
        rows = preview_cut_list(example_scenarios()[0].context, [20], .125)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1].decision.outcome, Outcome.ADAPT)
        self.assertAlmostEqual(rows[-1].decision.target, 10.55)

    def test_forecast_unknown_contact_and_invalid_inputs(self):
        context = example_scenarios()[0].context
        for context in (replace(context, fresh=False),
                        replace(context, material=replace(context.material, contact=False))):
            rows = preview_cut_list(context, [12], .125)
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0].decision.proceeds)
        context = example_scenarios()[0].context
        self.assertEqual(preview_cut_list(context, [float('nan')], .1)[0].decision.code, 'INVALID_LENGTH')
        self.assertEqual(preview_cut_list(context, [1], -.1)[0].decision.code, 'INVALID_KERF')


class DiagnosticTests(unittest.TestCase):
    def test_acknowledged_waits_vs_limits_and_feedback_gap(self):
        recorder = CycleDiagnostics()
        def observe(phase, at, fresh=True):
            recorder.observe({'fresh':fresh, 'sequence':'SAW_WAIT', 'controller':phase,
                              'timing_source':'controller hash acknowledged'},
                             {'board.settle':300, 'main.engage_delay':200,
                              'saw.down_timeout':4000}, at)
        observe('CLAMP_DELAY', 10)
        observe('CLAMP_DELAY', 10.2)
        recorder.observe({'fresh':True, 'sequence':'SAW_ACK', 'controller':'CLAMP_DELAY'},
                         {'board.settle':300, 'main.engage_delay':200}, 10.3)
        self.assertEqual(len(recorder.phases), 0, 'Host ACK stage must not split the physical wait')
        observe('DESCEND', 10.5)
        self.assertEqual(len(recorder.phases), 1)
        self.assertEqual(recorder.phases[0]['expected_ms'], 500)
        self.assertEqual(recorder.phases[0]['observed_ms'], 500)
        self.assertEqual(recorder.phase_rows(10.7)[-1]['timing_kind'], 'travel limit')
        observe('DESCEND', 11, False)
        self.assertTrue(recorder.phases[-1]['interrupted'])
        count = len(recorder.phases)
        observe('DESCEND', 20, False)
        self.assertEqual(len(recorder.phases), count)
        observe('READY', 21)
        self.assertEqual(recorder.phase_rows(21)[-1]['observed_ms'], 0)

    def test_events_are_bounded_and_unknown_config_is_not_a_target(self):
        recorder = CycleDiagnostics()
        recorder.observe({'fresh':True, 'controller':'SPINUP'}, {}, 0)
        self.assertIsNone(recorder.phase_rows(1)[-1]['expected_ms'])
        for index in range(2100): recorder.note('TEST', str(index), index)
        self.assertEqual(len(recorder.events), 2000)
        self.assertGreater(recorder.report(2100)['dropped_events'], 0)


if __name__ == '__main__': unittest.main()
