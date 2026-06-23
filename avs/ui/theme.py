"""Brand colour palette — periwinkle blue theme.

Call apply_theme() once at app startup (before ui.run).
All page CSS should use these constants so a single edit updates the whole app.
"""
from nicegui import ui

# Primary brand colour — periwinkle blue
ACCENT     = '#7a8fd8'
ACCENT_DIM = '#4a5fa8'

# Backgrounds
BG_PAGE    = '#111111'
BG_CARD    = '#1e1e1e'
BG_DARK    = '#0d0d0d'

# Text
TEXT_DIM   = '#aaaaaa'
TEXT_MUTED = '#666666'

# Stage state colours (UI chrome only — editorial mark colours are separate)
DONE       = '#7a8fd8'   # periwinkle
DONE_DIM   = '#4a5fa8'
RUNNING    = '#f0a040'   # amber — universal in-progress signal; not changed
ERROR      = '#e57373'


def apply_theme() -> None:
    """Set Quasar brand colours so all NiceGUI components (buttons, badges, etc.)
    use the periwinkle palette automatically."""
    ui.colors(
        primary=ACCENT,
        positive=ACCENT,
        secondary='#4a5fa8',
    )
