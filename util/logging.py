"""util/logging.py — lightweight structured logging + a model-call cost meter.

Dependency-free (no game imports) so any module can use it. The CallMeter
accumulates token/cost/latency across a match for the per-match budget guard
and the UI's cost readout (01 §12).
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field

_CONFIGURED = False


def get_logger(name: str = "jjk") -> logging.Logger:
    """Return a process-wide logger that writes a readable line to stderr."""
    global _CONFIGURED
    logger = logging.getLogger(name)
    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                                                datefmt="%H:%M:%S"))
        root = logging.getLogger("jjk")
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        root.propagate = False
        _CONFIGURED = True
    return logger


@dataclass
class CallRecord:
    model_id: str
    provider: str
    call_type: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_s: float
    ok: bool


@dataclass
class CallMeter:
    """Accumulates model-call stats for one match (token/cost/latency/budget)."""
    records: list[CallRecord] = field(default_factory=list)

    @property
    def calls(self) -> int:
        return len(self.records)

    @property
    def total_cost(self) -> float:
        return sum(r.cost_usd for r in self.records)

    @property
    def total_tokens(self) -> int:
        return sum(r.input_tokens + r.output_tokens for r in self.records)

    def add(self, record: CallRecord) -> None:
        self.records.append(record)

    def summary(self) -> str:
        return (f"{self.calls} calls | {self.total_tokens} tokens "
                f"| ~${self.total_cost:.4f}")


# A module-level default meter so a single match can be metered without threading
# the object everywhere. Stage B's engine swaps in a per-match meter.
DEFAULT_METER = CallMeter()


def estimate_cost(price_in: float, price_out: float,
                  input_tokens: int, output_tokens: int) -> float:
    """USD cost from per-1M-token prices (0 for local models)."""
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000.0
