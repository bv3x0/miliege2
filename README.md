# TrackTracker for NTS Radio

A utility for scraping track listings from NTS Radio episodes and creating Spotify playlists from them, as well as generating reports on top tracks played. Now with website integration!

## Features

- Create Spotify playlists from single NTS Radio episodes
- Create full archive playlists containing all tracks from all episodes of a show
- Generate weekly reports of the most played tracks and artists on NTS Radio
- Add shows to the website to showcase their playlists
- Batch update all playlists with new episodes automatically

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
     export SPOTIFY_CLIENT_ID="your-client-id"
     export SPOTIFY_CLIENT_SECRET="your-client-secret"
     export SPOTIFY_REDIRECT_URI="http://localhost:8888/callback"
     ```

   Alternatively, you can create a `.env` file in the project root with these values:
   ```
   SPOTIFY_CLIENT_ID=your-client-id
   SPOTIFY_CLIENT_SECRET=your-client-secret
   SPOTIFY_REDIRECT_URI=http://localhost:8888/callback
   ```

   Use the config command to generate a sample `.env` file:
   ```
   python -m tracktracker.cli config --create-env
   ```

## Configuration

TrackTracker uses a centralized configuration system powered by Pydantic. The configuration can be managed through:

1. **Environment variables** - Set values directly in your environment
2. **`.env` file** - Create a file named `.env` in the project root with key-value pairs
3. **Command-line interface** - Use the `config` command to view and manage settings

### Configuration Command

View the current configuration:
```
python -m tracktracker.cli config --show
```

Create a sample `.env` file with the current settings:
```
python -m tracktracker.cli config --create-env
```

### Available Configuration Options

- **Spotify Settings**:
  - `SPOTIFY_CLIENT_ID` - Your Spotify API client ID
  - `SPOTIFY_CLIENT_SECRET` - Your Spotify API client secret
  - `SPOTIFY_REDIRECT_URI` - Redirect URI for OAuth flow (default: `http://127.0.0.1:8888/callback`)

- **Path Settings**:
  - `TRACKTRACKER_CACHE_DIR` - Directory for cache files (default: `~/.tracktracker`)
  - `TRACKTRACKER_DATA_DIR` - Directory for data files (default: `website/src/data`)
  - `TRACKTRACKER_SHOW_IMAGES_DIR` - Directory for show images (default: `website/public/show-images`)

- **API Settings**:
  - `LOG_LEVEL` - Logging level (default: `INFO`)

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

For a large show archive (process in smaller chunks to avoid rate limits):
```
python -m tracktracker.cli playlist https://www.nts.live/shows/show-name --archive --chunk-size 5
```

For a complete show archive and add it to the website:
```
python -m tracktracker.cli playlist https://www.nts.live/shows/show-name --archive --website
```

### Adding a Show to the Website

To add a show to the website:
```
python -m tracktracker.cli website https://www.nts.live/shows/show-name https://open.spotify.com/playlist/playlist-id
```

This will prompt you for:
- Short title for the show
- Path to artwork file (JPG)
- Apple Music playlist URL (optional)

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

### Batch Updating All Playlists

To check for new episodes for all shows and update their playlists:
```
python -m tracktracker.cli batch-update
```

This will:
1. Check each show in the website data for new episodes
2. Add new tracks from new episodes to the relevant playlists
3. Update the playlist descriptions with the latest date
4. Update the website data with the latest end dates
5. Generate a summary of the updates

## Command-line Options

### Common Options

- `-v`, `--verbose`: Enable verbose output for debugging

### Playlist Command Options

- `-a`, `--archive`: Create or update a complete archive playlist for the show instead of a single episode
- `-w`, `--website`: Add the show to the website after creating the playlist
- `-c`, `--clear-cache`: Clear the track search cache before running to ensure fresh results
- `--strict`: Use strict matching criteria when searching for tracks on Spotify
- `--chunk-size`: Process episodes in chunks of this size to avoid rate limits (e.g., `--chunk-size 5`)

### Website Command Options

- `nts_url`: URL to an NTS Radio show
- `spotify_url`: URL to the Spotify playlist for the show

### Report Command Options

- `-d DAYS`, `--days DAYS`: Number of days to look back (default: 7)

### Batch Update Command Options

- `-v`, `--verbose`: Enable verbose output for debugging

### Config Command Options

- `--show`: Show the current configuration settings
- `--create-env`: Create a template `.env` file with current settings
- `-v`, `--verbose`: Enable verbose output for debugging

## Website Integration

TrackTracker now supports integration with the website to showcase NTS Radio shows and their playlists. The website component:

1. Displays show information in a grid format
2. Shows details about each show when selected
3. Provides links to NTS Radio, Spotify, and Apple Music
4. Embeds Spotify and Apple Music players for listening directly on the website

When you add a show to the website using the `--website` flag or the `website` command, TrackTracker:

1. Collects show information from the NTS API
2. Prompts you for additional information (short title, artwork, Apple Music link)
3. Copies the artwork to the website's public/show-images directory
4. Creates the necessary embed codes for Spotify and Apple Music
5. Updates the shows.json data file used by the website

### Running the Website Locally
To run the website after updating the show data:
```
cd website
npm install
npm run dev
```

### Deploying the Website to GitHub Pages
The website is automatically deployed to GitHub Pages whenever changes are pushed to the repository:

1. Make your changes to the website code or data
2. Commit and push your changes to the main branch:
```
git add website/
git commit -m "Update website content"
git push
```
3. GitHub Actions will automatically build and deploy the website
4. The website will be available at https://[your-github-username].github.io/tracktracker/

You can also manually trigger a deployment from the GitHub Actions tab in your repository.

This approach uses GitHub Actions CI/CD, which is the modern, secure way to deploy websites. The deployment is handled entirely through GitHub's infrastructure, with no need to handle tokens or credentials manually.

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

4. **Add a show to the website**:
   ```
   python -m tracktracker.cli website https://www.nts.live/shows/show-name https://open.spotify.com/playlist/playlist-id
   ```
   You'll be prompted for additional information needed for the website.

5. **Batch update all playlists**:
   ```
   python -m tracktracker.cli batch-update
   ```
   This will check for new episodes for all shows in the website data and update their playlists accordingly.

### Spotify Authentication

Remember to set up your Spotify API credentials before using the playlist features. Set environment variables:

```
export SPOTIFY_CLIENT_ID="your-client-id"
export SPOTIFY_CLIENT_SECRET="your-client-secret"
export SPOTIFY_REDIRECT_URI="http://localhost:8888/callback"
```

Or create a `.env` file in the project root:
```
SPOTIFY_CLIENT_ID=your-client-id
SPOTIFY_CLIENT_SECRET=your-client-secret
SPOTIFY_REDIRECT_URI=http://localhost:8888/callback
```

You can also use the config command to generate a template `.env` file:
```
python -m tracktracker.cli config --create-env
```

These credentials can be obtained by creating a Spotify Developer account and registering an application.