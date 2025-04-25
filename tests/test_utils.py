"""Tests for the utils module."""

import pytest
from unittest.mock import patch, mock_open

from tracktracker import utils


def test_parse_url_valid():
    """Test parse_url with a valid NTS URL."""
    url = "https://www.nts.live/shows/guests/episodes/test-episode"
    result = utils.parse_url(url)
    assert result == url


def test_parse_url_invalid():
    """Test parse_url with an invalid URL."""
    url = "https://example.com/not-nts"
    with pytest.raises(ValueError):
        utils.parse_url(url)


def test_deduplicate_tracks_empty():
    """Test deduplicate_tracks with an empty list."""
    tracks = []
    result = utils.deduplicate_tracks(tracks)
    assert result == []


def test_deduplicate_tracks_no_duplicates():
    """Test deduplicate_tracks with no duplicates."""
    tracks = [
        {"artist": "Artist1", "title": "Title1"},
        {"artist": "Artist2", "title": "Title2"},
    ]
    result = utils.deduplicate_tracks(tracks)
    assert result == tracks


def test_deduplicate_tracks_with_duplicates():
    """Test deduplicate_tracks with duplicates."""
    tracks = [
        {"artist": "Artist1", "title": "Title1"},
        {"artist": "Artist1", "title": "Title1"},  # Exact duplicate
        {"artist": "Artist1", "title": "Title1 (Live)"},  # Different enough
        {"artist": "Artist2", "title": "Title2"},
    ]
    result = utils.deduplicate_tracks(tracks)
    assert len(result) == 3
    assert result[0] == tracks[0]
    assert result[1] == tracks[2]
    assert result[2] == tracks[3]


def test_clean_playlist_name():
    """Test clean_playlist_name."""
    name = "Artist Name - Show! (20/04/2023)"
    result = utils.clean_playlist_name(name)
    assert result == "Artist Name - Show 20042023" 