"""
V3 research phases.

Each module is one phase from the rebuild charter, runnable on its own and
reporting into RESEARCH_LOG.md. Shared constants live in research/config.py;
statistical primitives live in backtesting/metrics.py.

Signal before architecture: nothing here builds a pipeline. These scripts exist
to answer whether a hypothesis predicts returns, on a sample large enough to
mean it. See docs/v2_postmortem.md for why that ordering is non-negotiable.
"""
