"""Shared sidebar navigation — three top-level items.

Uses proper Quasar QItem/QItemSection structure so QDrawer's built-in mini mode
hides text labels and keeps only the icon strip visible.
"""
from nicegui import ui


_NAV_ITEMS = [
    # (item_id, label, material-icon, url-or-None)
    ('home',     'Home',         'home',       '__home__'),
    ('session',  'Current edit', 'movie_edit',  '__session__'),
    ('settings', 'Settings',     'settings',    '/settings'),
]


def sidebar(active: str, session_id: str | None = None, status: str | None = None) -> None:
    """Render the sidebar. Must be called inside a ui.left_drawer() context.

    Uses QItem/QItemSection so Quasar's mini mode automatically hides text,
    leaving a 48-px icon strip that is always reachable.
    """
    items = []
    for item_id, label, icon, url_tmpl in _NAV_ITEMS:
        if url_tmpl == '__home__':
            url = '/'
        elif url_tmpl == '__session__':
            url = f'/session/{session_id}' if session_id else None
        else:
            url = url_tmpl
        items.append((item_id, label, icon, url))

    with ui.list().props('dense padding').style('width:100%; padding-top:0.25rem'):

        # Brand row — icon always visible, "AxEdUp" hidden in mini mode
        with ui.item().style(
            'padding:0.5rem 0; border-bottom:1px solid #2a2a2a; margin-bottom:0.25rem; cursor:default'
        ):
            with ui.item_section().props('avatar'):
                ui.icon('videocam').style('color:#5a9a5a; font-size:1.3rem')
            with ui.item_section():
                ui.label('AxEdUp').style('color:#eee; font-size:0.95rem; font-weight:700')

        for item_id, label, icon, url in items:
            is_active = item_id == active
            is_future = False
            has_link  = item_id == 'session' and session_id
            clickable = url is not None and not is_active

            color  = '#ffffff' if is_active else ('#5a9a5a' if has_link else ('#383838' if is_future else '#666'))
            weight = '600' if is_active else '400'

            item_style = (
                f'color:{color}; border-radius:4px; margin:1px 4px;'
                + (' cursor:pointer;' if clickable else ' cursor:default;')
            )
            bg = 'background:rgba(255,255,255,0.06);' if is_active else ''

            with ui.item(
                on_click=(lambda u=url: ui.navigate.to(u)) if clickable else None,
            ).props(
                ('clickable v-ripple' if clickable else '')
            ).style(item_style + bg):

                with ui.item_section().props('avatar'):
                    ui.icon(icon).style(f'color:{color}; font-size:1.1rem')

                with ui.item_section():
                    with ui.row().style('align-items:center; gap:0.35rem'):
                        ui.label(label).style(
                            f'color:{color}; font-size:0.875rem; font-weight:{weight}'
                        )
                        if is_future:
                            ui.badge('soon').props('outline').style(
                                'font-size:0.58rem; color:#383838; border-color:#383838'
                            )
