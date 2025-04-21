# TrackTracker for NTS Radio

A utility for scraping track listings from NTS Radio episodes and creating Spotify playlists from them, as well as generating reports on top tracks played.

## Features

- Create Spotify playlists from single NTS Radio episodes
- Create full archive playlists containing all tracks from all episodes of a show
- Generate weekly reports of the most played tracks and artists on NTS Radio

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/tracktracker.git
   cd tracktracker
   ```

2. Install the required packages:
   ```
   pip install -r requirements.txt
   ```

3. Set up Spotify API credentials:
   - Create a Spotify Developer account and register an application
   - Set the following environment variables:
     ```
     export SPOTIPY_CLIENT_ID="your-client-id"
     export SPOTIPY_CLIENT_SECRET="your-client-secret"
     export SPOTIPY_REDIRECT_URI="http://localhost:8080"
     ```

## Usage

### Creating Spotify Playlists

For a single episode:
```
python -m tracktracker.cli playlist https://www.nts.live/shows/show-name/episodes/episode-name-date
```

For a complete show archive:
```
python -m tracktracker.cli playlist https://www.nts.live/shows/show-name --archive
```

### Generating Weekly Reports

To generate a report of tracks played over the past 7 days:
```
python -m tracktracker.cli report
```

To specify a different time period:
```
python -m tracktracker.cli report --days 14
```

The report will be saved as a CSV file named `nts_weekly_report_Xdays.csv` in your current directory, where X is the number of days.

## Command-line Options

### Common Options

- `-v`, `--verbose`: Enable verbose output for debugging

### Playlist Command Options

- `-a`, `--archive`: Create or update a complete archive playlist for the show instead of a single episode

### Report Command Options

- `-d DAYS`, `--days DAYS`: Number of days to look back (default: 7)

## CSV Report Format

The weekly report CSV contains the following sections:

1. **Top Tracks**: The most played tracks across all shows
2. **Top Artists**: The most played artists across all shows 
3. **Track Plays**: Detailed information about each track play including:
   - Artist
   - Track Title
   - Show Name
   - Episode Title
   - Broadcast Date

## Backwards Compatibility

For backwards compatibility, you can also run the application without specifying a command:

```
python -m tracktracker.cli https://www.nts.live/shows/show-name/episodes/episode-name-date
```

This is equivalent to:

```
python -m tracktracker.cli playlist https://www.nts.live/shows/show-name/episodes/episode-name-date
```

## License

MIT

## API Changes (April 2025)

NTS Radio has updated its API, affecting certain TrackTracker functionality. The following changes have been made to keep TrackTracker working:

1. **Weekly Reports**: Weekly reports now use the `/api/v2/live` endpoint instead of the previously used `/api/v2/latest` endpoint. Reports contain show information but no longer include track analysis as track data is not available from this API endpoint.

2. **Episode Scraping**: Episode scraping has been updated to work with the new API structure, where tracklists are now included directly in the episode data.

### Running TrackTracker with the Latest Updates

1. **Generate a weekly report** (shows only, no track analysis):
   ```
   python -m tracktracker.cli report
   ```
   You can specify a different number of days to look back:
   ```
   python -m tracktracker.cli report --days 14
   ```

2. **Create a playlist from a single episode**:
   ```
   python -m tracktracker.cli playlist https://www.nts.live/shows/show-name/episodes/episode-name-date
   ```
   Note: This requires setting up Spotify API credentials as described in the Installation section.

3. **Create a complete show archive playlist**:
   ```
   python -m tracktracker.cli playlist https://www.nts.live/shows/show-name --archive
   ```
   Note: This requires setting up Spotify API credentials as described in the Installation section.

### Spotify Authentication

Remember to set up your Spotify API credentials before using the playlist features:

```
export SPOTIFY_CLIENT_ID="your-client-id"
export SPOTIFY_CLIENT_SECRET="your-client-secret"
export SPOTIFY_REDIRECT_URI="http://localhost:8888/callback"
```

These can be obtained by creating a Spotify Developer account and registering an application.
