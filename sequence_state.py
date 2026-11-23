"""Typed state machine definitions for the native automatic cut-list sequence."""
from dataclasses import asdict, dataclass, field, fields
from enum import StrEnum
import time
from typing import Any

from automation_supervision import Decision, Span


class SequenceStage(StrEnum):
    # Acquisition & truing
    SEARCH_PROFILE = "SEARCH_PROFILE"
    SEARCH_ARM = "SEARCH_ARM"
    SEARCH = "SEARCH"
    TRUE_PROFILE = "TRUE_PROFILE"
    TRUE_ARM = "TRUE_ARM"

    # Positioning & cut cycle
    FEED_PROFILE = "FEED_PROFILE"
    FEED_ARM = "FEED_ARM"
    RESUME_POSITION_PROFILE = "RESUME_POSITION_PROFILE"
    MOVE = "MOVE"
    DISARM = "DISARM"
    WAIT_CUT_APPROVAL = "WAIT_CUT_APPROVAL"
    CLAMP = "CLAMP"
    SAW_ACK = "SAW_ACK"
    SAW_WAIT = "SAW_WAIT"
    PNEU_OFF = "PNEU_OFF"
    NEXT_ACTION = "NEXT_ACTION"

    # Unclamped operator cut & early return
    EARLY_RETURN_ARM = "EARLY_RETURN_ARM"
    EARLY_RETURN_WAIT = "EARLY_RETURN_WAIT"
    EARLY_RETURN_DISARM = "EARLY_RETURN_DISARM"
    RETURN_CUT_ACK = "RETURN_CUT_ACK"
    RETURN_CUT_WAIT = "RETURN_CUT_WAIT"
    WAIT_OPERATOR_CUT = "WAIT_OPERATOR_CUT"
    OPERATOR_ARM = "OPERATOR_ARM"
    OPERATOR_ARMED = "OPERATOR_ARMED"

    # Detector-zone cleanup & return to load
    FINISH_BOARD = "FINISH_BOARD"
    CLEAR_PROFILE = "CLEAR_PROFILE"
    CLEAR_ARM = "CLEAR_ARM"
    CLEAR_MOVE = "CLEAR_MOVE"
    CLEAR_VERIFY = "CLEAR_VERIFY"
    LOAD_ARM = "LOAD_ARM"
    LOAD_WAIT = "LOAD_WAIT"
    DONE = "DONE"

    # Human wait / intervention / recovery
    WAIT_NEW_BOARD = "WAIT_NEW_BOARD"
    BOARD_TOO_SHORT = "BOARD_TOO_SHORT"
    OPERATOR_REQUIRED = "OPERATOR_REQUIRED"
    CLEARANCE_REQUIRED = "CLEARANCE_REQUIRED"
    PAUSING = "PAUSING"
    PAUSED = "PAUSED"
    FAULT_RECOVERY = "FAULT_RECOVERY"


ACQUISITION_STAGES = frozenset({
    SequenceStage.SEARCH_PROFILE,
    SequenceStage.SEARCH_ARM,
    SequenceStage.SEARCH,
    SequenceStage.TRUE_PROFILE,
    SequenceStage.TRUE_ARM,
})

POSITIONING_STAGES = frozenset({
    SequenceStage.FEED_PROFILE,
    SequenceStage.FEED_ARM,
    SequenceStage.RESUME_POSITION_PROFILE,
    SequenceStage.MOVE,
    SequenceStage.DISARM,
})

CUT_CYCLE_STAGES = frozenset({
    SequenceStage.WAIT_CUT_APPROVAL,
    SequenceStage.CLAMP,
    SequenceStage.SAW_ACK,
    SequenceStage.SAW_WAIT,
    SequenceStage.PNEU_OFF,
    SequenceStage.NEXT_ACTION,
})

EARLY_RETURN_STAGES = frozenset({
    SequenceStage.EARLY_RETURN_ARM,
    SequenceStage.EARLY_RETURN_WAIT,
    SequenceStage.EARLY_RETURN_DISARM,
    SequenceStage.RETURN_CUT_ACK,
    SequenceStage.RETURN_CUT_WAIT,
    SequenceStage.WAIT_OPERATOR_CUT,
    SequenceStage.OPERATOR_ARM,
    SequenceStage.OPERATOR_ARMED,
})

CLEANUP_AND_BOARD_STAGES = frozenset({
    SequenceStage.FINISH_BOARD,
    SequenceStage.CLEAR_PROFILE,
    SequenceStage.CLEAR_ARM,
    SequenceStage.CLEAR_MOVE,
    SequenceStage.CLEAR_VERIFY,
    SequenceStage.LOAD_ARM,
    SequenceStage.LOAD_WAIT,
    SequenceStage.DONE,
    SequenceStage.WAIT_NEW_BOARD,
    SequenceStage.BOARD_TOO_SHORT,
    SequenceStage.OPERATOR_REQUIRED,
    SequenceStage.CLEARANCE_REQUIRED,
})


@dataclass
class SequenceState:
    """Explicit, typed state for one active native automatic cut-list run."""

    stage: SequenceStage
    at: float = field(default_factory=time.monotonic)
    cuts: list[float] = field(default_factory=list)
    kerf: float = 0.0
    index: int = -1
    next_index: int = 0
    board: int = 1
    semi: bool = False
    repeat: bool = False
    clear_between: bool = True
    clear_end: bool = False
    list_snapshot: tuple[Any, ...] = ()
    reference_signature: tuple[Any, ...] = ()
    move_id: int = 0
    edge_command: str = ""

    # Positioning / feed
    target: float | None = None
    resume_profile: int = 2
    cut_approved: bool = False
    done: int | None = None

    # Early return / clamped parallel return
    early_return: bool = False
    automatic_cut_return: bool = False
    cut_return_plan: Decision | None = None
    cut_return_mask: int = 0
    cut_return_target: int = 0
    cut_return_min: int = 0

    # Operator unclamped cut snapshot
    operator_stock: Span | None = None
    operator_cut_position: float | None = None
    operator_position: float | None = None
    operator_config: int | None = None
    operator_confirmed: bool = False
    adjusted_length: float | None = None

    # Board acquisition / rejection / cleanup
    reacquire: bool = False
    acquisition_rejection: dict[str, Any] | None = None
    clear_target: float | None = None
    clear_plan: Decision | None = None
    clear_since: float | None = None

    def __post_init__(self):
        if not isinstance(self.stage, SequenceStage):
            self.stage = SequenceStage(self.stage)

    def transition(self, next_stage: SequenceStage | str, now: float | None = None):
        self.stage = next_stage if isinstance(next_stage, SequenceStage) else SequenceStage(next_stage)
        self.at = time.monotonic() if now is None else now

    def clear_operator_snapshot(self):
        self.operator_stock = None
        self.operator_cut_position = None
        self.operator_position = None
        self.operator_config = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain JSON-friendly dictionary for diagnostics."""
        result = asdict(self)
        result["stage"] = str(self.stage)
        return result

    # Strict read-only mapping helpers so legacy test assertions like
    # `d.sequence['stage'] == 'SEARCH'` continue to work while rejecting unknown keys.
    def __getitem__(self, key: str) -> Any:
        if key not in _FIELD_NAMES:
            raise KeyError(key)
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        if key not in _FIELD_NAMES:
            return default
        value = getattr(self, key)
        return default if value is None else value

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in _FIELD_NAMES and getattr(self, key) is not None


_FIELD_NAMES = frozenset(f.name for f in fields(SequenceState))
