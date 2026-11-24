import pytest
from unittest.mock import MagicMock, patch
import xml.etree.ElementTree as ET

from src.letterboxd.rss_syncer import LetterboxdRSSSyncer
from src.letterboxd.database import LetterboxdDatabase

RSS_XML_SAMPLE = b"""<?xml version='1.0' encoding='utf-8'?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:letterboxd="https://letterboxd.com" xmlns:tmdb="https://themoviedb.org">
	<channel>
		<title>Letterboxd - longyu</title>
		<link>https://letterboxd.com/longyu/</link>
		
		<item> 
            <title>The Substance, 2024 - \xe2\x98\x85\xe2\x98\x85</title> 
            <link>https://letterboxd.com/longyu/film/the-substance/</link> 
            <letterboxd:watchedDate>2026-03-19</letterboxd:watchedDate> 
            <letterboxd:filmTitle>The Substance</letterboxd:filmTitle> 
            <letterboxd:filmYear>2024</letterboxd:filmYear> 
            <tmdb:movieId>933260</tmdb:movieId>
            <letterboxd:memberRating>2.0</letterboxd:memberRating> 
            <dc:creator>longyu</dc:creator> 
        </item>

		<item> 
            <title>A Movie With No Rating, 2023</title> 
            <link>https://letterboxd.com/longyu/film/no-rating-movie/</link> 
            <letterboxd:watchedDate>2026-03-20</letterboxd:watchedDate> 
            <letterboxd:filmTitle>A Movie With No Rating</letterboxd:filmTitle> 
            <letterboxd:filmYear>2023</letterboxd:filmYear> 
            <dc:creator>longyu</dc:creator> 
        </item>

	</channel>
</rss>
"""

@pytest.fixture
def mock_db():
    db = MagicMock(spec=LetterboxdDatabase)
    db.upsert_watched.return_value = True
    db.upsert_rating.return_value = True
    db.movie_exists_on_date.return_value = False
    return db

def test_uri_normalization(mock_db):
    syncer = LetterboxdRSSSyncer(db=mock_db, rss_url="http://fake")
    assert syncer._normalize_uri("https://letterboxd.com/longyu/film/the-substance/") == "https://letterboxd.com/film/the-substance/"
    assert syncer._normalize_uri("https://letterboxd.com/film/already-normalized/") == "https://letterboxd.com/film/already-normalized/"

def test_parse_items(mock_db):
    syncer = LetterboxdRSSSyncer(db=mock_db, rss_url="http://fake")
    items = syncer._parse_items(RSS_XML_SAMPLE)
    
    assert len(items) == 2
    
    assert items[0]["movie_name"] == "The Substance"
    assert items[0]["year"] == 2024
    assert items[0]["watched_at"] == "2026-03-19"
    assert items[0]["rating"] == 2.0
    assert items[0]["tmdb_id"] == 933260
    assert items[0]["letterboxd_uri"] == "https://letterboxd.com/film/the-substance/"
    assert items[0]["username"] == "longyu"

    assert items[1]["movie_name"] == "A Movie With No Rating"
    assert items[1]["rating"] is None
    assert items[1]["letterboxd_uri"] == "https://letterboxd.com/film/no-rating-movie/"

def test_process_rss_data(mock_db):
    syncer = LetterboxdRSSSyncer(db=mock_db, rss_url="http://fake")
    stats = syncer._process_rss_data(RSS_XML_SAMPLE)

    assert stats["watched"] == 2
    assert stats["ratings"] == 1
    
    assert mock_db.ensure_user.call_count == 2
    assert mock_db.upsert_watched.call_count == 2
    assert mock_db.upsert_rating.call_count == 1
    first_watched_payload = mock_db.upsert_watched.call_args_list[0].args[0]
    assert first_watched_payload["TMDB ID"] == 933260

def test_malformed_xml(mock_db):
    syncer = LetterboxdRSSSyncer(db=mock_db, rss_url="http://fake")
    with pytest.raises(RuntimeError, match="Failed to parse"):
        syncer._process_rss_data(b"<badxml>")
    mock_db.init_tables.assert_not_called()

@patch("src.letterboxd.rss_syncer.urlopen")
def test_sync_network_error(mock_urlopen, mock_db):
    mock_urlopen.side_effect = OSError("Network Error")
    
    syncer = LetterboxdRSSSyncer(db=mock_db, rss_url="http://fake")
    with pytest.raises(RuntimeError, match="Failed to fetch"):
        syncer.sync()
    mock_db.init_tables.assert_not_called()
