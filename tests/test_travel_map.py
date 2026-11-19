from io import BytesIO
import math
from unittest.mock import Mock

from PIL import Image
import pytest

from src.publish import travel_map


def test_map_filters_missing_and_invalid_coordinates():
    assert travel_map.valid_map_places([
        {'latitude': 0, 'longitude': 0},
        {'latitude': None, 'longitude': 1},
        {'latitude': float('nan'), 'longitude': 1},
        {'latitude': 91, 'longitude': 1},
        {'latitude': 1, 'longitude': 181},
    ]) == [{'latitude': 0.0, 'longitude': 0.0}]
    assert travel_map.render_travel_map([]) is None


@pytest.mark.parametrize('places', [
    [{'latitude': 37.7, 'longitude': -122.4}],
    [{'latitude': 37.7, 'longitude': -122.4}, {'latitude': 40.7, 'longitude': -74}],
    [{'latitude': 0, 'longitude': 179}, {'latitude': 0, 'longitude': -179}],
    [{'latitude': 90, 'longitude': 0}, {'latitude': -90, 'longitude': 0}],
])
def test_viewport_includes_points_and_downloads_only_visible_tiles(places):
    zoom, left, top, points = travel_map._viewport(places)
    assert all(0 <= x <= travel_map.WIDTH and 0 <= y <= travel_map.HEIGHT for x, y in points)
    columns = math.floor((left + travel_map.WIDTH - 1) / 256) - math.floor(left / 256) + 1
    rows = math.floor((top + travel_map.HEIGHT - 1) / 256) - math.floor(top / 256) + 1
    assert columns * rows <= 20
    if places[0]['longitude'] == 179:
        assert zoom >= 7


def test_render_png_caches_tiles_and_preserves_visible_attribution(tmp_path, monkeypatch):
    monkeypatch.setattr(travel_map, 'CACHE_DIR', tmp_path)
    tile = Image.new('RGB', (256, 256), '#d0e0d0')
    output = BytesIO()
    tile.save(output, format='PNG')
    response = Mock(content=output.getvalue())
    get = Mock(return_value=response)
    monkeypatch.setattr(travel_map.requests, 'get', get)
    places = [{'latitude': 37.7, 'longitude': -122.4, 'visits': 3}]
    result = travel_map.render_travel_map(places)
    calls = get.call_count
    assert 0 < calls <= 20
    assert travel_map.render_travel_map(places) == result
    assert get.call_count == calls
    assert 'digital-data-dump' in get.call_args.kwargs['headers']['User-Agent']
    image = Image.open(BytesIO(result))
    assert image.size == (1000, 600)
    assert image.getpixel((999, 599)) == (255, 255, 255)


def test_map_http_failure_remains_visible(tmp_path, monkeypatch):
    monkeypatch.setattr(travel_map, 'CACHE_DIR', tmp_path)
    response = Mock()
    response.raise_for_status.side_effect = travel_map.requests.HTTPError('Tile unavailable')
    monkeypatch.setattr(travel_map.requests, 'get', Mock(return_value=response))
    with pytest.raises(travel_map.requests.HTTPError, match='Tile unavailable'):
        travel_map.render_travel_map([{'latitude': 37.7, 'longitude': -122.4}])
