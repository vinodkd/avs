"""Shared formatting utilities used across CLI, UI, and processing modules."""


def fmt_duration(secs: float) -> str:
    """'1h 4m 3s', '4m 3s', or '3s'."""
    m, s = divmod(int(secs), 60)
    h, m = divmod(m, 60)
    if h:
        return f'{h}h {m}m {s}s'
    return f'{m}m {s}s' if m else f'{s}s'


def fmt_timestamp(ts: float) -> str:
    """'4:03' — minutes:seconds suitable for a player display."""
    m, s = divmod(int(ts), 60)
    return f'{m}:{s:02d}'
