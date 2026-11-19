"""Render visited places over cached OpenStreetMap tiles."""

from io import BytesIO
import math
from pathlib import Path
import tempfile
import time

from PIL import Image, ImageDraw, ImageFont
import requests

from ..config import Config

WIDTH, HEIGHT = 1000, 600
TILE_SIZE = 256
CACHE_SECONDS = 7 * 24 * 60 * 60
CACHE_DIR = Config.PROJECT_ROOT / '.cache' / 'map-tiles'
USER_AGENT = 'digital-data-dump (+https://github.com/yyl/digital-data-dump)'


def valid_map_places(places: list[dict]) -> list[dict]:
    """Keep places with finite geographical coordinates."""
    valid = []
    for place in places:
        try:
            latitude, longitude = float(place['latitude']), float(place['longitude'])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(latitude) and math.isfinite(longitude) and -90 <= latitude <= 90 and -180 <= longitude <= 180:
            valid.append({**place, 'latitude': latitude, 'longitude': longitude})
    return valid


def _project(latitude: float, longitude: float) -> tuple[float, float]:
    latitude = max(-85.05112878, min(85.05112878, latitude))
    sine = math.sin(math.radians(latitude))
    return (longitude + 180) / 360, 0.5 - math.log((1 + sine) / (1 - sine)) / (4 * math.pi)


def _viewport(places: list[dict]) -> tuple[int, float, float, list[tuple[float, float]]]:
    """Fit points within the image, taking the shorter arc across the dateline."""
    projected = [_project(place['latitude'], place['longitude']) for place in places]
    xs = sorted(point[0] for point in projected)
    gaps = [(xs[(i + 1) % len(xs)] + int(i == len(xs) - 1) - x, i) for i, x in enumerate(xs)]
    _, gap_index = max(gaps)
    start = xs[(gap_index + 1) % len(xs)]
    points = [(x + int(x < start), y) for x, y in projected]
    minimum_x, maximum_x = min(x for x, _ in points), max(x for x, _ in points)
    minimum_y, maximum_y = min(y for _, y in points), max(y for _, y in points)
    span_x, span_y = maximum_x - minimum_x, maximum_y - minimum_y
    zoom = 14
    while zoom > 0 and (span_x * TILE_SIZE * 2 ** zoom > WIDTH - 100 or span_y * TILE_SIZE * 2 ** zoom > HEIGHT - 100):
        zoom -= 1
    scale = TILE_SIZE * 2 ** zoom
    left = (minimum_x + maximum_x) / 2 * scale - WIDTH / 2
    top = (minimum_y + maximum_y) / 2 * scale - HEIGHT / 2
    return zoom, left, top, [(x * scale - left, y * scale - top) for x, y in points]


def _tile(zoom: int, x: int, y: int) -> Image.Image:
    path = CACHE_DIR / str(zoom) / str(x) / f'{y}.png'
    if path.exists() and time.time() - path.stat().st_mtime < CACHE_SECONDS:
        data = path.read_bytes()
    else:
        response = requests.get(
            f'https://tile.openstreetmap.org/{zoom}/{x}/{y}.png',
            headers={'User-Agent': USER_AGENT}, timeout=20,
        )
        response.raise_for_status()
        data = response.content
        # Verify downloaded image before retaining it as a cached tile.
        with Image.open(BytesIO(data)) as image:
            image.verify()
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary.write(data)
            temporary_path = Path(temporary.name)
        try:
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)
    with Image.open(BytesIO(data)) as image:
        return image.convert('RGB')


def render_travel_map(places: list[dict]) -> bytes | None:
    """Render one static map sized to the month's valid visited places."""
    places = valid_map_places(places)
    if not places:
        return None
    zoom, left, top, points = _viewport(places)
    image = Image.new('RGB', (WIDTH, HEIGHT), '#e9eff2')
    count = 2 ** zoom
    for x in range(math.floor(left / TILE_SIZE), math.floor((left + WIDTH - 1) / TILE_SIZE) + 1):
        for y in range(math.floor(top / TILE_SIZE), math.floor((top + HEIGHT - 1) / TILE_SIZE) + 1):
            if 0 <= y < count:
                tile = _tile(zoom, x % count, y)
                image.paste(tile, (round(x * TILE_SIZE - left), round(y * TILE_SIZE - top)))
    drawing = ImageDraw.Draw(image)
    for place, (x, y) in zip(places, points):
        visits = max(1, int(place.get('visits', 1)))
        radius = min(16, 6 + math.log2(visits) * 2)
        drawing.ellipse((x - radius, y - radius, x + radius, y + radius), fill='#dc3c32', outline='white', width=2)
    attribution = '\u00a9 OpenStreetMap contributors'
    font = ImageFont.load_default(size=14)
    box = drawing.textbbox((0, 0), attribution, font=font)
    text_width = box[2] - box[0]
    drawing.rectangle((WIDTH - text_width - 20, HEIGHT - 25, WIDTH, HEIGHT), fill='white')
    drawing.text((WIDTH - text_width - 10, HEIGHT - 21), attribution, fill='#333333', font=font)
    output = BytesIO()
    image.save(output, format='PNG', optimize=True)
    return output.getvalue()
