# TrackTracker

Track archiving and playlist management tool for radio shows.

## Components

TrackTracker consists of two main components:

1. **Python Backend**: Archives tracks from radio shows
2. **Web Frontend**: Displays archived playlists and shows

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   cd website && npm install
   ```

2. Configure .env file:
   ```
   SPOTIFY_CLIENT_ID=your_client_id
   SPOTIFY_CLIENT_SECRET=your_client_secret
   ```

## Workflow

### Archiving Shows

Run the tracktracker commands to archive shows:

```bash
python -m tracktracker.cli [commands]
```

### Updating Website

After archiving shows:

1. Update the show data in `website/src/data/shows.json`
2. Test locally:
   ```bash
   cd website
   npm run test
   ```
3. Push changes to main branch:
   ```bash
   git add .
   git commit -m "Update with new show"
   git push origin main
   ```
4. GitHub Actions will automatically deploy to GitHub Pages!

## Website

Local development:
```bash
cd website
npm run dev
```

The website is deployed to GitHub Pages at:
https://bv3x0.github.io/tracktracker/