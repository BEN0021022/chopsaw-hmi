"""Geometry policies/coordinator only. No serial or hardware access."""
import unittest
from dataclasses import replace
from automation_supervision import *


def geometry(**changes):
    return replace(Geometry(True,(Clamp('main',Span(9,10)),),0,6,0,1,.25,Span(10.8,10.8),24,True),**changes)


def context(**changes):
    return replace(Context(geometry(),Material(Span(-20,40),'estimated',True,1),40,
                           True,True,True,True,True,True,False,True,True),**changes)


class Policies(unittest.TestCase):
    def test_manual_cycle_operator_positioned_stock(self):
        c=context(material=Material())
        self.assertTrue(assess_manual_cycle(c).proceeds)
        self.assertTrue(assess_manual_cycle(replace(c,clamps_off=False)).proceeds)
        self.assertFalse(assess_cut_holding(c).proceeds)
        for changes in ({'position':.5},{'position':9},{'fresh':False},
                        {'door_closed':False},{'reference_known':False},{'saw_up':False},
                        {'trigger_off':False},{'carriage_idle':False},{'fault_free':False}):
            with self.subTest(changes=changes):
                self.assertFalse(assess_manual_cycle(replace(c,**changes)).proceeds)

    def test_geometry_validation(self):
        for value in (float('nan'),float('inf'),-1):
            with self.subTest(value=value), self.assertRaises(ValueError): geometry(margin=value)
        with self.assertRaises(ValueError): Span(10,9)
        with self.assertRaises(ValueError): geometry(cut_keepout=0)
        with self.assertRaises(ValueError): geometry(clamps=(Clamp('main',Span(0,0)),))
        with self.assertRaises(ValueError): geometry(verified='false')

    def test_normal_holding(self):
        self.assertEqual(assess_main_clamp(context()).permitted_clamps,('main',))
        self.assertTrue(validate_next_action(context(),'cut').proceeds)

    def test_carriage_under_clamp_and_boundary(self):
        for position in (8,9,10,10.2499,10.25):
            with self.subTest(position=position):
                c=context(position=position,material=Material(Span(-20,position),'estimated',True))
                self.assertEqual(assess_main_clamp(c).code,'PUSHER_OVERLAP')
                self.assertFalse(assess_cut_holding(c).proceeds)
        self.assertTrue(assess_main_clamp(context(position=10.251)).proceeds)

    def test_footprint_not_just_cut_length(self):
        c=context(material=Material(Span(9.1,40),'estimated',True))
        self.assertEqual(assess_main_clamp(c).code,'NO_MATERIAL_COVERAGE')
        self.assertFalse(assess_cut_holding(c).proceeds)

    def test_unknown_material_and_unverified_geometry(self):
        self.assertEqual(assess_main_clamp(context(material=Material())).code,'MATERIAL_UNKNOWN')
        self.assertFalse(validate_next_action(context(geometry=Geometry()),'cut').proceeds)

    def test_no_hand_or_planned_clamp_bypass(self):
        g=geometry(clamps=(Clamp('outfeed',Span(-12,-11),'cut_piece',False,False,None),))
        d=assess_cut_holding(context(geometry=g))
        self.assertEqual(d.outcome,Outcome.OPERATOR_REQUIRED)
        self.assertEqual(d.permitted_clamps,())
        self.assertFalse(assess_cut_holding(context(geometry=geometry(clamps=(Clamp('main',Span(9,10),controller_channel=None),)))).proceeds)
        alternative=Clamp('outfeed',Span(-12,-11),'remaining_stock',True,True,2)
        self.assertEqual(assess_cut_holding(context(geometry=geometry(clamps=(alternative,)))).code,'HOLDING_EXECUTOR_UNAVAILABLE')

    def test_keepout_and_invalid_state(self):
        for changes in ({'position':.5},{'position':float('nan')},{'fresh':False},{'door_closed':False},
                        {'reference_known':False},{'saw_up':False},{'trigger_off':False},{'carriage_idle':False},{'fault_free':False}):
            with self.subTest(changes=changes): self.assertFalse(validate_next_action(context(**changes),'cut').proceeds)
        self.assertEqual(validate_next_action(context(),'unknown_operation').code,'UNKNOWN_ACTION')
        self.assertEqual(validate_next_action(context(material=Material(Span(2,40),'estimated',True)),'cut').code,'NO_STOCK_AT_CUT')
        self.assertEqual(assess_cut_holding(context(material=Material(Span(0,40),'estimated',False))).code,'PUSHER_CONTACT_UNKNOWN')

    def test_minimum_sensor_clearance_not_full_ejection(self):
        c=context(position=20,material=Material(Span(0,20),'estimated',True))
        d=plan_sensor_clearance(c)
        self.assertEqual(d.outcome,Outcome.ADAPT)
        self.assertAlmostEqual(d.target,10.55)
        self.assertGreater(d.target,0)

    def test_no_cleanup_when_clear(self):
        c=context(position=8,material=Material(Span(0,8),'estimated',True),sensor_clear=True)
        self.assertEqual(plan_sensor_clearance(c).code,'ACQUISITION_ZONE_CLEAR')
        self.assertIsNone(plan_sensor_clearance(c).target)

    def test_cleanup_guards_and_no_blind_retry(self):
        c=context(position=20,material=Material(Span(0,20),'estimated',True))
        cases=[replace(c,clamps_off=False),replace(c,sensor_clear=True),replace(c,sensor_clear=None),
               replace(c,material=replace(c.material,contact=False)),replace(c,material=Material()),
               replace(c,geometry=geometry(max_clear_push=5)),replace(c,geometry=geometry(automatic_clearance=False))]
        for case in cases:
            with self.subTest(case=case): self.assertFalse(plan_sensor_clearance(case).proceeds)

    def test_return_does_not_pull_remnant_and_stale_plan(self):
        a=AutomationCoordinator(geometry()); a.locate_stock(Span(0,20))
        d=a.decide(context(position=20),'clear_sensor'); self.assertTrue(a.still_valid(d))
        a.push(-2); self.assertEqual(a.material.stock,Span(-2,18)); self.assertFalse(a.still_valid(d))
        a.push(50); self.assertEqual(a.material.stock,Span(-2,18)); self.assertFalse(a.material.contact)
        self.assertFalse(a.decide(context(position=68),'clear_sensor').proceeds)
        a.configure(geometry(margin=.5)); self.assertFalse(a.material.located)

    def test_cut_commits_only_estimated_infeed_geometry(self):
        a=AutomationCoordinator(geometry()); a.locate_stock(Span(-5,40)); a.cut_completed()
        self.assertEqual(a.material.stock,Span(0,40))
        a.invalidate('guard opened'); a.cut_completed(); self.assertFalse(a.material.located)

    def test_feed_checks_next_cut_not_entire_queue(self):
        c=context(material=Material(Span(0,40),'estimated',True))
        d=plan_board_feed(c,20,.12)
        self.assertEqual(d.code,'FEED_TARGET_AVAILABLE')
        self.assertAlmostEqual(d.target,19.88)
        self.assertEqual(plan_board_feed(c,50,.12).code,'NEXT_BOARD_REQUIRED')
        # A future cut may need another board, but that cannot invalidate this one.
        a=AutomationCoordinator(c.geometry); a.material=c.material
        self.assertEqual(a.decide(c,'feed',length=20,kerf=.12).target,19.88)

    def test_feed_unknowns_and_quantized_keepout(self):
        c=context(material=Material(Span(0,40),'estimated',True))
        for changes in ({'fresh':False},{'clamps_off':False},{'reference_known':False},
                        {'material':Material()},{'material':replace(c.material,contact=False)}):
            self.assertFalse(plan_board_feed(replace(c,**changes),10,.12).proceeds)
        for length,kerf in ((None,.12),(float('nan'),.12),(10,-1)):
            self.assertEqual(plan_board_feed(c,length,kerf).code,'INVALID_LENGTH')
        self.assertEqual(plan_board_feed(c,38.88,.12).code,'NEXT_BOARD_REQUIRED')


if __name__=='__main__': unittest.main()
