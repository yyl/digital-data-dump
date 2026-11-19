"""Static SVG chart of authored commits across the hours of a day."""

from ..github.models import ACTIVITY_TIMEZONE


def render_commit_hours(rows: list[dict]) -> str:
    """Render public and private counts without exposing repository details."""
    counts = {row['hour']: row for row in rows}
    peak = max((row['public_commits'] + row['private_commits'] for row in rows), default=0)
    scale = 200 / max(1, peak)
    elements = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="330" viewBox="0 0 1000 330" role="img">',
        '<title>Authored commits by hour</title>',
        f'<desc>Stacked public and private commit counts in {ACTIVITY_TIMEZONE}.</desc>',
        '<rect width="1000" height="330" fill="#fff"/>',
        '<g font-family="sans-serif" font-size="14" fill="#334155">',
        '<text x="56" y="28" font-size="20">Authored commits by hour</text>',
        '<rect x="720" y="15" width="14" height="14" fill="#2563eb"/>',
        '<text x="741" y="28">Public</text>',
        '<rect x="820" y="15" width="14" height="14" fill="#c2410c"/>',
        '<text x="841" y="28">Private</text>',
    ]
    for tick in (0, 0.5, 1):
        y = 250 - 200 * tick
        elements.extend([
            f'<line x1="56" y1="{y}" x2="968" y2="{y}" stroke="#e2e8f0"/>',
            f'<text x="46" y="{y + 5}" text-anchor="end">{peak * tick:g}</text>',
        ])
    for hour in range(24):
        row = counts.get(hour, {'public_commits': 0, 'private_commits': 0})
        x = 64 + hour * 38
        public_height = row['public_commits'] * scale
        private_height = row['private_commits'] * scale
        elements.extend([
            f'<rect x="{x}" y="{250 - public_height}" width="22" height="{public_height}" fill="#2563eb">'
            f'<title>{hour:02d}:00 public: {row["public_commits"]}</title></rect>',
            f'<rect x="{x}" y="{250 - public_height - private_height}" width="22" height="{private_height}" fill="#c2410c">'
            f'<title>{hour:02d}:00 private: {row["private_commits"]}</title></rect>',
            f'<text x="{x + 11}" y="273" text-anchor="middle">{hour:02d}</text>',
        ])
    elements.extend([
        f'<text x="512" y="309" text-anchor="middle">Hour of day · {ACTIVITY_TIMEZONE}</text>',
        '</g></svg>',
    ])
    return ''.join(elements)
