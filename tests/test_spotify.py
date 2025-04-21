"""Tests for the spotify module."""

import pytest
from unittest.mock import patch, MagicMock

from tracktracker import spotify


@patch("tracktracker.spotify.SpotifyOAuth")
@patch("tracktracker.spotify.spotipy.Spotify")
@patch("tracktracker.spotify.os.environ.get")
@patch("tracktracker.spotify.Path.home")
def test_authenticate(mock_home, mock_env_get, mock_spotify, mock_oauth):
    """Test authenticate function."""
    # Mock environment variables
    mock_env_get.side_effect = lambda k, default=None: {
        "SPOTIFY_CLIENT_ID": "test-client-id",
        "SPOTIFY_CLIENT_SECRET": "test-client-secret",
        "SPOTIFY_REDIRECT_URI": "test-redirect-uri"
    }.get(k, default)
    
    # Mock Path.home() and cache dir
    mock_home_path = MagicMock()
    mock_cache_dir = MagicMock()
    mock_home.return_value = mock_home_path
    mock_home_path.__truediv__.return_value = mock_cache_dir
    mock_cache_dir.exists.return_value = True
    mock_cache_dir.__truediv__.return_value = "/mock/path/spotify_token.json"
    
    # Mock return values
    mock_oauth.return_value = "mock-auth-manager"
    mock_spotify.return_value = "mock-spotify-client"
    
    # Call the function
    result = spotify.authenticate("test-scope")
    
    # Check the result
    assert result == "mock-spotify-client"
    
    # Check that OAuth was called with correct parameters
    mock_oauth.assert_called_once_with(
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="test-redirect-uri",
        scope="test-scope",
        cache_path="/mock/path/spotify_token.json"
    )
    
    # Check that Spotify was created with the OAuth manager
    mock_spotify.assert_called_once_with(auth_manager="mock-auth-manager")


@patch("tracktracker.spotify.SpotifyOAuth")
@patch("tracktracker.spotify.spotipy.Spotify")
@patch("tracktracker.spotify.Path.home")
def test_authenticate_error(mock_home, mock_spotify, mock_oauth):
    """Test authenticate function with an error."""
    # Mock Path.home() and cache dir
    mock_home_path = MagicMock()
    mock_cache_dir = MagicMock()
    mock_home.return_value = mock_home_path
    mock_home_path.__truediv__.return_value = mock_cache_dir
    mock_cache_dir.exists.return_value = True
    
    # Make the Spotify constructor raise an exception
    mock_spotify.side_effect = Exception("Auth error")
    
    # Call the function and check that it raises ValueError
    with pytest.raises(ValueError):
        spotify.authenticate("test-scope")


def test_create_playlist():
    """Test create_playlist function."""
    # Create a mock Spotify client
    mock_spotify = MagicMock()
    mock_spotify.me.return_value = {"id": "test-user-id"}
    mock_spotify.user_playlist_create.return_value = {"id": "test-playlist-id"}
    
    # Call the function
    result = spotify.create_playlist(mock_spotify, "Test Playlist", "Test Description")
    
    # Check the result
    assert result == "test-playlist-id"
    
    # Check that the Spotify API was called correctly
    mock_spotify.user_playlist_create.assert_called_once_with(
        user="test-user-id",
        name="Test Playlist",
        public=True,
        description="Test Description"
    )


def test_search_track_found():
    """Test search_track function when track is found."""
    # Create a mock Spotify client
    mock_spotify = MagicMock()
    mock_spotify.search.return_value = {
        "tracks": {
            "items": [
                {"uri": "spotify:track:123"}
            ]
        }
    }
    
    # Call the function
    result = spotify.search_track(mock_spotify, "Test Artist", "Test Title")
    
    # Check the result
    assert result == "spotify:track:123"
    
    # Check that the Spotify API was called
    assert mock_spotify.search.call_count == 1


def test_search_track_not_found():
    """Test search_track function when track is not found."""
    # Create a mock Spotify client
    mock_spotify = MagicMock()
    mock_spotify.search.return_value = {"tracks": {"items": []}}
    
    # Call the function
    result = spotify.search_track(mock_spotify, "Test Artist", "Test Title")
    
    # Check the result
    assert result is None
    
    # Check that the Spotify API was called for all search strategies
    assert mock_spotify.search.call_count == 3


@patch("tracktracker.spotify.search_track")
def test_add_tracks_to_playlist(mock_search_track):
    """Test add_tracks_to_playlist function."""
    # Set up mock search results
    mock_search_track.side_effect = [
        "spotify:track:123",  # First track found
        None                 # Second track not found
    ]
    
    # Create a mock Spotify client
    mock_spotify = MagicMock()
    
    # Create test tracks
    tracks = [
        {"artist": "Artist1", "title": "Title1"},
        {"artist": "Artist2", "title": "Title2"}
    ]
    
    # Call the function
    found_uris, not_found = spotify.add_tracks_to_playlist(
        mock_spotify, "test-playlist-id", tracks
    )
    
    # Check the results
    assert found_uris == ["spotify:track:123"]
    assert len(not_found) == 1
    assert not_found[0] == tracks[1]
    
    # Check that Spotify API was called to add the track
    mock_spotify.playlist_add_items.assert_called_once_with(
        "test-playlist-id", ["spotify:track:123"]
    ) 