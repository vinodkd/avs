"""
Review step (Pass 2): serve a local HTML page showing candidate marks,
collect accept/reject decisions, apply them to the marks table.

Uses Python's stdlib http.server — no FastAPI or external dependencies.
The browser POSTs decisions back to the local server when the user clicks Submit.
"""

import base64
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from rich.console import Console

from axedup import config
from axedup.models.db import get_session
from axedup.models.schema import Clip, Mark, MarkStatus, Session


def open_review(session_id: str, console: Console | None = None) -> None:
    """
    Generate a review page for *session_id*, open it in the browser,
    wait for the user to submit decisions, then apply them to the DB.
    """
    _log = _logger(console)

    with get_session() as db:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            raise ValueError(f"Session {session_id} not found")

        clips = {c.id: c for c in db.query(Clip).filter(Clip.session_id == session_id).all()}
        all_marks = (
            db.query(Mark)
            .filter(Mark.clip_id.in_(clips.keys()))
            .filter(Mark.status.in_([MarkStatus.CANDIDATE, MarkStatus.ACCEPTED]))
            .order_by(Mark.in_s)
            .all()
        )

    if not all_marks:
        _log("[yellow]No candidate marks found. Run 'analyze' first.[/yellow]")
        return

    # Group by source — show separate sections for each analysis method.
    # Accepted marks from prior reviews are included so users can compare methods.
    _SECTION_LABELS = {
        "motion_peak":     "Proxy motion analysis",
        "motion_peak_jpg": "JPEG motion analysis",
        "telemetry_peak":  "Telemetry peaks",
    }
    mark_groups: dict[str, list[Mark]] = {}
    for source, label in _SECTION_LABELS.items():
        group = [m for m in all_marks if m.source == source]
        if group:
            mark_groups[label] = group

    total = len(all_marks)
    _log(f"Building review page for {total} candidate(s) across {len(mark_groups)} section(s) …")
    html_bytes = _build_html(mark_groups, clips).encode("utf-8")

    server = _ReviewServer(("127.0.0.1", 0), _ReviewHandler, html_bytes=html_bytes)
    port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://localhost:{port}"
    _log(f"Opening review at [link]{url}[/link]")
    webbrowser.open(url)

    _log("Waiting for your decisions … (submit the form to continue)")
    submitted = server.done.wait(timeout=600)   # 10-minute timeout
    server.shutdown()

    if not submitted or not server.decisions:
        _log("[yellow]Timed out or no submission received. No changes made.[/yellow]")
        return

    _apply_decisions(server.decisions, console)


def _apply_decisions(decisions: dict[str, bool], console: Console | None) -> None:
    """Write accepted/rejected status back to the marks table."""
    _log = _logger(console)
    accepted = rejected = 0

    with get_session() as db:
        for mark_id, is_accepted in decisions.items():
            mark = db.query(Mark).filter(Mark.id == mark_id).first()
            if mark:
                mark.status = MarkStatus.ACCEPTED if is_accepted else MarkStatus.REJECTED
                if is_accepted:
                    accepted += 1
                else:
                    rejected += 1

    _log(f"[green]{accepted} accepted[/green], {rejected} rejected.")


# ---------------------------------------------------------------------------
# Minimal HTTP server
# ---------------------------------------------------------------------------

class _ReviewServer(HTTPServer):
    def __init__(self, *args, html_bytes: bytes, **kwargs):
        super().__init__(*args, **kwargs)
        self.html_bytes = html_bytes
        self.decisions: dict[str, bool] = {}
        self.done = threading.Event()


class _ReviewHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/":
            self._respond(200, "text/html; charset=utf-8", self.server.html_bytes)
        else:
            self._respond(404, "text/plain", b"Not found")

    def do_POST(self) -> None:
        if self.path == "/submit":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            self.server.decisions = json.loads(body)
            self._respond(200, "application/json", b'{"ok":true}')
            self.server.done.set()
        else:
            self._respond(404, "text/plain", b"Not found")

    def _respond(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass  # suppress request logging to keep terminal clean


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def _find_thumbnail(clip_id: str, timestamp_s: float) -> Path | None:
    """Return the thumbnail file closest to *timestamp_s*."""
    thumb_dir = config.THUMB_DIR / clip_id
    if not thumb_dir.exists():
        return None
    idx = max(1, round(timestamp_s / config.THUMB_INTERVAL))
    for offset in range(6):
        for sign in ([0] if offset == 0 else [1, -1]):
            candidate = thumb_dir / f"{idx + sign * offset:04d}.jpg"
            if candidate.exists():
                return candidate
    return None


def _thumb_b64(path: Path | None) -> str:
    """Return a data: URI for the thumbnail, or a grey placeholder."""
    if path and path.exists():
        data = base64.b64encode(path.read_bytes()).decode()
        return f"data:image/jpeg;base64,{data}"
    # 1×1 grey pixel as placeholder
    return "data:image/gif;base64,R0lGODlhAQABAIAAAMLCwgAAACH5BAAAAAAALAAAAAABAAEAAAICRAEAOw=="


def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s"


def _build_html(mark_groups: dict[str, list[Mark]], clips: dict[str, Clip]) -> str:
    total = sum(len(m) for m in mark_groups.values())
    sections_html = ""

    for label, marks in mark_groups.items():
        cards_html = ""
        for mark in marks:
            clip = clips.get(mark.clip_id)
            mid = (mark.in_s + mark.out_s) / 2
            thumb_src = _thumb_b64(_find_thumbnail(mark.clip_id, mid))
            dur = mark.out_s - mark.in_s
            time_range = f"{_fmt_time(mark.in_s)} – {_fmt_time(mark.out_s)}"
            score_pct = int((mark.score or 0) * 100)
            clip_name = clip.filename if clip else "unknown"
            prior = mark.status == MarkStatus.ACCEPTED
            prior_badge = '<span class="prior-badge">previously accepted</span>' if prior else ""

            cards_html += f"""
        <div class="card" id="card-{mark.id}" data-id="{mark.id}" data-accepted="true">
          <img class="thumb" src="{thumb_src}" alt="{time_range}">
          <div class="meta">
            <div class="time">{time_range} <span class="dur">({dur:.1f}s)</span></div>
            <div class="clip-name">{clip_name}</div>
            {prior_badge}
            <div class="score-bar">
              <div class="score-fill" style="width:{score_pct}%"></div>
              <span class="score-label">{(mark.score or 0):.3f}</span>
            </div>
          </div>
          <div class="actions">
            <button class="btn accept active" onclick="toggle('{mark.id}', true)">✓ Accept</button>
            <button class="btn reject" onclick="toggle('{mark.id}', false)">✗ Reject</button>
          </div>
        </div>"""

        sections_html += f"""
    <section class="mark-section">
      <h2 class="section-title">{label} <span class="section-count">{len(marks)} clip(s)</span></h2>
      <div class="grid">{cards_html}</div>
    </section>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AxEdUp Review</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #111; color: #eee; font-family: system-ui, sans-serif;
          padding: 1rem 1.5rem 6rem; }}
  h1 {{ font-size: 1.2rem; color: #aaa; margin-bottom: 0.25rem; }}
  .subtitle {{ color: #555; font-size: 0.85rem; margin-bottom: 1.5rem; }}
  .mark-section {{ margin-bottom: 2.5rem; }}
  .section-title {{ font-size: 1rem; color: #ccc; margin-bottom: 0.75rem;
                    padding-bottom: 0.4rem; border-bottom: 1px solid #2a2a2a; }}
  .section-count {{ color: #555; font-size: 0.8rem; font-weight: 400; }}
  .grid {{ display: grid;
           grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
           gap: 1rem; }}
  .card {{ background: #1e1e1e; border-radius: 8px; overflow: hidden;
           border: 2px solid #2a7a2a; transition: border-color 0.15s; }}
  .card.rejected {{ border-color: #5a2020; opacity: 0.55; }}
  .thumb {{ width: 100%; aspect-ratio: 16/9; object-fit: cover;
            display: block; background: #222; }}
  .meta {{ padding: 0.6rem 0.75rem 0.4rem; }}
  .time {{ font-size: 0.95rem; font-weight: 600; color: #fff; }}
  .dur {{ color: #777; font-size: 0.8rem; font-weight: 400; }}
  .clip-name {{ color: #555; font-size: 0.72rem; margin-top: 0.15rem;
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .prior-badge {{ display: inline-block; margin-top: 0.3rem; font-size: 0.68rem;
                  color: #7a9a7a; background: #1a2a1a; border-radius: 3px;
                  padding: 0.1rem 0.4rem; }}
  .score-bar {{ position: relative; background: #2a2a2a; border-radius: 3px;
                height: 6px; margin-top: 0.5rem; }}
  .score-fill {{ height: 100%; background: #3a9a3a; border-radius: 3px; }}
  .card.rejected .score-fill {{ background: #7a3a3a; }}
  .score-label {{ position: absolute; right: 0; top: -1.1rem;
                  font-size: 0.7rem; color: #666; }}
  .actions {{ display: flex; gap: 0.5rem; padding: 0.6rem 0.75rem; }}
  .btn {{ flex: 1; padding: 0.35rem 0; border: none; border-radius: 4px;
          font-size: 0.82rem; cursor: pointer; transition: all 0.12s; }}
  .btn.accept {{ background: #1a3a1a; color: #5a9a5a; }}
  .btn.accept.active {{ background: #2a7a2a; color: #fff; }}
  .btn.reject {{ background: #2a1a1a; color: #7a4a4a; }}
  .btn.reject.active {{ background: #7a2a2a; color: #fff; }}
  .footer {{ position: fixed; bottom: 0; left: 0; right: 0;
             background: #1a1a1a; border-top: 1px solid #333;
             padding: 0.9rem 1.5rem; display: flex;
             justify-content: space-between; align-items: center; }}
  .summary {{ color: #888; font-size: 0.9rem; }}
  .summary span {{ color: #eee; font-weight: 600; }}
  .btn-submit {{ background: #2a7a2a; color: #fff; border: none;
                 padding: 0.6rem 2rem; border-radius: 6px; font-size: 1rem;
                 cursor: pointer; font-weight: 600; }}
  .btn-submit:hover {{ background: #3a9a3a; }}
  .btn-submit:disabled {{ background: #333; color: #666; cursor: default; }}
  #done-msg {{ display:none; color: #5a9a5a; font-size: 1rem; font-weight: 600; }}
</style>
</head>
<body>
<h1>AxEdUp — Clip Review</h1>
<p class="subtitle">{total} candidate(s) total · all accepted by default</p>
{sections_html}
<div class="footer">
  <div class="summary">
    <span id="acc-count">{total}</span> accepted &nbsp;·&nbsp;
    <span id="rej-count">0</span> rejected
  </div>
  <div id="done-msg">✓ Decisions applied — you can close this tab.</div>
  <button class="btn-submit" id="submit-btn" onclick="submitDecisions()">
    Apply Decisions →
  </button>
</div>
<script>
  const state = {{}};
  document.querySelectorAll('.card').forEach(c => state[c.dataset.id] = true);

  function toggle(id, accepted) {{
    state[id] = accepted;
    const card = document.getElementById('card-' + id);
    card.classList.toggle('rejected', !accepted);
    card.querySelector('.btn.accept').classList.toggle('active', accepted);
    card.querySelector('.btn.reject').classList.toggle('active', !accepted);
    updateCounts();
  }}

  function updateCounts() {{
    const vals = Object.values(state);
    const acc = vals.filter(v => v).length;
    document.getElementById('acc-count').textContent = acc;
    document.getElementById('rej-count').textContent = vals.length - acc;
  }}

  function submitDecisions() {{
    const btn = document.getElementById('submit-btn');
    btn.disabled = true;
    btn.textContent = 'Applying…';
    fetch('/submit', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(state)
    }})
    .then(r => r.json())
    .then(() => {{
      btn.style.display = 'none';
      document.getElementById('done-msg').style.display = 'block';
    }})
    .catch(err => {{
      btn.disabled = false;
      btn.textContent = 'Apply Decisions →';
      alert('Error: ' + err);
    }});
  }}
</script>
</body>
</html>"""


def _logger(console: Console | None):
    return console.log if console else print
