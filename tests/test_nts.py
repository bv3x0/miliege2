"""Tests for the NTS scraper module."""

import pytest
from unittest.mock import patch, MagicMock

from tracktracker.scrapers import nts


def test_parse_nts_url_standard_format():
    """Test parse_nts_url with standard URL format."""
    url = "https://www.nts.live/shows/test-show/episodes/test-episode"
    result = nts.parse_nts_url(url)
    assert result == {"show_alias": "test-show", "episode_alias": "test-episode"}


def test_parse_nts_url_alternative_format():
    """Test parse_nts_url with alternative URL format."""
    url = "https://www.nts.live/shows/test-show/test-episode"
    result = nts.parse_nts_url(url)
    assert result == {"show_alias": "test-show", "episode_alias": "test-episode"}


def test_parse_nts_url_direct_episode():
    """Test parse_nts_url with direct episode URL."""
    url = "https://www.nts.live/test-episode"
    result = nts.parse_nts_url(url)
    assert result == {"show_alias": "test", "episode_alias": "test-episode"}


def test_parse_nts_url_invalid():
    """Test parse_nts_url with an invalid URL."""
    url = "https://example.com/not-nts"
    with pytest.raises(ValueError):
        nts.parse_nts_url(url)


@patch("tracktracker.scrapers.nts.requests.get")
def test_get_tracklist_from_episode_page(mock_get):
    """Test get_tracklist_from_episode_page."""
    # Mock response
    mock_response = MagicMock()
    mock_response.json.return_value = {"mock": "data"}
    mock_get.return_value = mock_response
    
    result = nts.get_tracklist_from_episode_page("test-show", "test-episode")
    
    # Check that the request was made correctly
    mock_get.assert_called_once()
    assert "https://www.nts.live/shows/test-show/episodes/test-episode" in mock_get.call_args[0][0]
    assert result == {"mock": "data"}


@patch("tracktracker.scrapers.nts.get_tracklist_from_episode_page")
@patch("tracktracker.scrapers.nts.parse_nts_url")
def test_scrape(mock_parse_url, mock_get_tracklist):
    """Test scrape function."""
    # Mock returns
    mock_parse_url.return_value = {"show_alias": "test-show", "episode_alias": "test-episode"}
    mock_get_tracklist.return_value = {"name": "Test Episode", "tracklist": []}
    
    result = nts.scrape("https://www.nts.live/shows/test-show/episodes/test-episode")
    
    # Check that the correct functions were called
    mock_parse_url.assert_called_once()
    mock_get_tracklist.assert_called_once_with("test-show", "test-episode")
    
    # Check the result
    assert "tracks" in result
    assert "episode_title" in result
    assert result["episode_title"] == "Test Episode"


def test_parse_tracklist_empty():
    """Test parse_tracklist with empty data."""
    data = {"name": "Test Episode"}
    result = nts.parse_tracklist(data)
    assert result["tracks"] == []
    assert result["episode_title"] == "Test Episode"


def test_parse_tracklist_with_tracks():
    """Test parse_tracklist with track data."""
    data = {
        "name": "Test Episode",
        "tracklist": [
            {
                "title": "Track Title 1",
                "mainArtists": [{"name": "Artist 1"}]
            },
            {
                "title": "Track Title 2",
                "mainArtists": [{"name": "Artist 2"}, {"name": "Artist 3"}]
            },
            {
                "title": "", # Should be skipped for missing title
                "mainArtists": [{"name": "Artist 4"}]
            }
        ]
    }
    
    result = nts.parse_tracklist(data)
    
    assert len(result["tracks"]) == 2
    assert result["tracks"][0] == {"artist": "Artist 1", "title": "Track Title 1"}
    assert result["tracks"][1] == {"artist": "Artist 2 & Artist 3", "title": "Track Title 2"} 