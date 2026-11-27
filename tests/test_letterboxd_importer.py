from unittest.mock import MagicMock

import pytest

from src.letterboxd.importer import LetterboxdImporter
from src.letterboxd.tmdb_client import TMDBAPIError


def test_extract_tmdb_id_accepts_letterboxd_export_variants():
    assert LetterboxdImporter._extract_tmdb_id({"tmdbID": "11"}) == 11
    assert LetterboxdImporter._extract_tmdb_id({"tmdbId": "12"}) == 12
    assert LetterboxdImporter._extract_tmdb_id({"TMDB ID": "13"}) == 13
    assert LetterboxdImporter._extract_tmdb_id({"tmdbID": ""}) is None


def test_enrich_missing_runtime_updates_matching_movies():
    db = MagicMock()
    db.get_movies_missing_runtime.return_value = [
        {
            "letterboxd_uri": "https://letterboxd.com/film/the-substance/",
            "movie_name": "The Substance",
            "year": 2024,
            "tmdb_id": 933260,
        }
    ]
    db.update_movie_metadata.return_value = True

    importer = LetterboxdImporter(db=db)
    client = MagicMock()
    client.is_configured.return_value = True
    client.get_runtime.return_value = (933260, 141)

    count = importer.enrich_missing_runtime(client=client)

    assert count == 1
    client.get_runtime.assert_called_once_with(
        title="The Substance",
        year=2024,
        tmdb_id=933260,
    )
    db.update_movie_metadata.assert_called_once_with(
        letterboxd_uri="https://letterboxd.com/film/the-substance/",
        tmdb_id=933260,
        runtime_minutes=141,
    )


def test_enrich_missing_runtime_reports_unmatched_movies(capsys):
    db = MagicMock()
    db.get_movies_missing_runtime.side_effect = [
        [
            {
                "letterboxd_uri": "https://boxd.it/k3M2",
                "movie_name": "Synchronic",
                "year": 2019,
                "tmdb_id": None,
            },
            {
                "letterboxd_uri": "https://boxd.it/C6VM",
                "movie_name": "The Blackening",
                "year": 2022,
                "tmdb_id": None,
            },
        ],
        [
            {
                "letterboxd_uri": "https://boxd.it/C6VM",
                "movie_name": "The Blackening",
                "year": 2022,
                "tmdb_id": None,
            },
        ],
    ]
    db.update_movie_metadata.return_value = True

    importer = LetterboxdImporter(db=db)
    client = MagicMock()
    client.is_configured.return_value = True
    client.get_runtime.side_effect = [(123, 102), None]

    count = importer.enrich_missing_runtime(client=client)

    assert count == 1
    out = capsys.readouterr().out
    assert "Enriched runtime metadata for 1 watched movies" in out
    assert "Could not find TMDB runtime for 1 watched movies: The Blackening (2022)" in out


def test_enrich_missing_runtime_raises_when_movies_missing_and_unconfigured():
    db = MagicMock()
    db.get_movies_missing_runtime.return_value = [
        {
            "letterboxd_uri": "https://letterboxd.com/film/source-code/",
            "movie_name": "Source Code",
            "year": 2011,
            "tmdb_id": None,
        }
    ]
    importer = LetterboxdImporter(db=db)
    client = MagicMock()
    client.is_configured.return_value = False

    with pytest.raises(TMDBAPIError, match="1 watched movie"):
        importer.enrich_missing_runtime(client=client)


def test_enrich_missing_runtime_skips_cleanly_when_nothing_missing_even_unconfigured():
    db = MagicMock()
    db.get_movies_missing_runtime.return_value = []
    importer = LetterboxdImporter(db=db)
    client = MagicMock()
    client.is_configured.return_value = False

    assert importer.enrich_missing_runtime(client=client) == 0
    client.get_runtime.assert_not_called()


def test_enrich_missing_runtime_propagates_tmdb_error_after_saving_earlier_movies():
    db = MagicMock()
    db.get_movies_missing_runtime.return_value = [
        {
            "letterboxd_uri": "https://letterboxd.com/film/source-code/",
            "movie_name": "Source Code",
            "year": 2011,
            "tmdb_id": None,
        },
        {
            "letterboxd_uri": "https://letterboxd.com/film/the-firm/",
            "movie_name": "The Firm",
            "year": 1993,
            "tmdb_id": None,
        },
    ]
    db.update_movie_metadata.return_value = True
    importer = LetterboxdImporter(db=db)
    client = MagicMock()
    client.is_configured.return_value = True
    client.get_runtime.side_effect = [(45612, 93), TMDBAPIError("TMDB API authentication failed (HTTP 401)")]

    with pytest.raises(TMDBAPIError, match="HTTP 401"):
        importer.enrich_missing_runtime(client=client)

    db.update_movie_metadata.assert_called_once_with(
        letterboxd_uri="https://letterboxd.com/film/source-code/",
        tmdb_id=45612,
        runtime_minutes=93,
    )
