from datetime import datetime

from src.foursquare.database import FoursquareDatabase
from src.publish.markdown_generator import MarkdownGenerator
from src.publish.publisher import Publisher


def test_monthly_place_ranking_keeps_distinct_venues_and_limits_report_to_three(tmp_path):
    db = FoursquareDatabase(str(tmp_path / "foursquare.db"))
    db.init_tables()
    with db.get_connection() as conn:
        conn.execute("INSERT INTO users (foursquare_user_id, last_updated_at) VALUES ('user', 1)")
        for place_id, name in (("a", "Cafe"), ("b", "Cafe"), ("c", "Park"), ("d", "Shop")):
            conn.execute("""
                INSERT INTO places (fsq_place_id, name, latitude, longitude, locality, last_updated_at)
                VALUES (?, ?, 37.5, -122.3, 'Town', 1)
            """, (place_id, name))
        count = 0
        for place_id, visits in (("a", 3), ("b", 2), ("c", 2), ("d", 1)):
            for _ in range(visits):
                count += 1
                conn.execute("""
                    INSERT INTO checkins (checkin_id, foursquare_user_id, place_fsq_id, created_at)
                    VALUES (?, 'user', ?, ?)
                """, (str(count), place_id, int(datetime.fromisoformat("2026-09-01T12:00:00+00:00").timestamp())))
        conn.execute("""
            INSERT INTO checkins (checkin_id, foursquare_user_id, place_fsq_id, created_at)
            VALUES ('outside-month', 'user', 'd', ?)
        """, (int(datetime.fromisoformat("2026-10-01T00:00:00+00:00").timestamp()),))

    publisher = Publisher(foursquare_db=db)
    places = publisher._get_foursquare_places("2026-09")
    assert [(place["fsq_place_id"], place["visits"]) for place in places] == [
        ("a", 3), ("b", 2), ("c", 2), ("d", 1),
    ]
    assert all(place["latitude"] == 37.5 and place["longitude"] == -122.3 for place in places)
    markdown = MarkdownGenerator()._generate_top_places_block(places)
    assert "| Cafe | Town | 3 |" in markdown
    assert "| Cafe | Town | 2 |" in markdown
    assert "| Park | Town | 2 |" in markdown
    assert "| Shop |" not in markdown
    assert publisher._get_foursquare_places("2026-11") == []


def test_travel_section_embeds_map_with_coordinate_coverage():
    markdown = MarkdownGenerator()._generate_foursquare_section({
        "checkins": 5, "unique_places": 3,
        "map_image": "wrap-up-09-2026-travel.svg",
        "map_coverage": "Mapped 2 of 3 places. One place has no coordinates.",
    })
    assert "![Places visited](wrap-up-09-2026-travel.svg)" in markdown
    assert "Mapped 2 of 3 places." in markdown
