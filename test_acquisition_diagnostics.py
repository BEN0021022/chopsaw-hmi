"""Acquisition refusals keep the actual cause and a non-actuating snapshot."""
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import MethodType, SimpleNamespace as NS
from automation_supervision import Geometry,Clamp,Span,Material,Context,AutomationCoordinator,plan_board_feed
from cycle_diagnostics import CycleDiagnostics
from dry_run_control import NativeDryRun
from sequence_state import SequenceStage, SequenceState


def context():
    geometry=Geometry(verified=True,clamps=(Clamp('main',Span(8.75,9.75)),),
                      pusher_rear_extent=16.75,cut_keepout=1,margin=.5)
    return Context(geometry,Material(Span(-.12,82.1252),'estimated',True,3,'real edge acquisition'),
                   82.1252,fresh=True,reference_known=True,door_closed=True,saw_up=True,
                   trigger_off=True,clamps_off=True,sensor_clear=False,carriage_idle=True,fault_free=True)


class AcquisitionDiagnosticsTest(unittest.TestCase):
    def runner(self,folder,ctx):
        def forbidden(*args):raise AssertionError('Diagnostics attempted actuation')
        p=NS(armed=False,stopping=False,pending=None,profile_pending=None,
             x={'HOME_OFFSET':'-9963','ACQUIRE_CONTINUOUS':'0','REMAINING':'0'},
             inputs={'BOARD_EDGE':'0','SAW_UP':'0','SAW_DOWN':'1'},continuous_supported=lambda:True)
        owner=NS(carriage_tab=p,cut_history=NS(path=Path(folder)/'cut_history.csv'),log=NS(append=lambda text:None),send_command=forbidden)
        runner=NS(owner=owner,pending=None,data={'STATE':'OFF','CLAMP':'0','SAW':'0','TRIGGER':'0'},
                  sequence=SequenceState(stage=SequenceStage.DISARM,index=-1,next_index=0,cuts=[38.313,38.313],kerf=.12),
                  safe_link=lambda:True,diagnostics=CycleDiagnostics(),
                  supervision=NS(context=lambda:ctx,coordinator=AutomationCoordinator(ctx.geometry),last_decision=None))
        for name in ('acquisition_rejected','acquisition_rejection_message','advance_sequence',
                     '_advance_positioning','_handle_disarm','_advance_cleanup_and_board'):
            setattr(runner,name,MethodType(getattr(NativeDryRun,name),runner))
        return runner

    def test_reported_lengths_fit(self):
        first=plan_board_feed(context(),38.313,.12)
        self.assertEqual(first.code,'FEED_TARGET_AVAILABLE')
        after=replace(context(),position=first.target,material=replace(context().material,stock=Span(0,first.target)))
        self.assertEqual(plan_board_feed(after,38.313,.12).code,'FEED_TARGET_AVAILABLE')

    def test_specific_rejections_persist_and_capture_context(self):
        cases=[(replace(context(),material=replace(context().material,contact=False)),'MATERIAL_UNKNOWN','OPERATOR_REQUIRED'),
               (replace(context(),carriage_idle=False),'MACHINE_BUSY','OPERATOR_REQUIRED'),
               (replace(context(),position=20,material=Material(Span(-.12,20),'estimated',True)),'NEXT_BOARD_REQUIRED','BOARD_TOO_SHORT'),
               (replace(context(),sensor_clear=True),'DETECTOR_REFERENCE_MISMATCH','OPERATOR_REQUIRED')]
        for ctx,code,stage in cases:
            with self.subTest(code=code),tempfile.TemporaryDirectory() as folder:
                d=self.runner(folder,ctx);d.advance_sequence()
                self.assertEqual(d.sequence['stage'],stage)
                self.assertEqual(d.supervision.coordinator.paused.code,code)
                message=d.message;d.advance_sequence();self.assertEqual(d.message,message)
                self.assertIn(code,message);self.assertNotIn('waiting for suitable stock',message)
                files=list((Path(folder)/'diagnostics').glob('*.json'));self.assertEqual(len(files),1)
                report=json.loads(files[0].read_text())['acquisition_rejection']
                self.assertEqual(report['code'],code)
                self.assertEqual(report['context']['material']['contact'],ctx.material.contact)
                self.assertEqual(report['inputs_raw']['BOARD_EDGE'],'0')
                self.assertEqual(report['sequence_before_rejection']['stage'],'DISARM')

    def test_write_failure_does_not_hide_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'diagnostics').write_text('blocked path')
            d=self.runner(folder,replace(context(),material=replace(context().material,contact=False)))
            d.advance_sequence();self.assertIn('MATERIAL_UNKNOWN',d.message)
            self.assertIn('could not be saved',d.message)
            self.assertEqual(d.sequence['stage'],'OPERATOR_REQUIRED')


if __name__=='__main__':unittest.main()
