# TrackTracker Simplified Workflow

This document outlines the simplified workflow for using TrackTracker. This approach decouples the scraping/data generation from the website display, making it easier to maintain and more secure.

## Important Update: Data Format Changes (May 2025)

The following changes have been made to the data format:

1. **Show URL Field**: Renamed from `nts` to `url` to support multiple sources beyond NTS Radio
2. **Source Field**: Added new `source` field to indicate the platform (NTS, Mixcloud, etc.)
3. **Image Paths**: Changed format to use paths without leading slashes:
   - Correct: `"art": "show-images/image.jpg"`
   - Incorrect: `"art": "/show-images/image.jpg"`

To update existing shows data, run:
```bash
python update_art_paths.py
```

## Overview

The simplified workflow consists of:

1. **Local Components**: 
   - Python backend for scraping NTS shows and creating Spotify playlists
   - Local data management (shows.json)

2. **Website Component**:
   - Static website hosted on GitHub Pages
   - Updated manually when new shows/tracks are added

## One-Time Setup

### 1. Initial Setup for Local Components

1. Clone the TrackTracker repository:
   ```bash
   git clone https://github.com/yourusername/tracktracker.git
   cd tracktracker
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set up environment variables (create a `.env` file in the root directory):
   ```
   SPOTIFY_CLIENT_ID=your_spotify_client_id
   SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
   ```

### 2. Setting Up GitHub Pages Repository

1. Create a new GitHub repository for your static site (e.g., `radio-playlists`)

2. Enable GitHub Pages for this repository:
   - Go to repository settings
   - Navigate to the "Pages" section
   - Select the main branch as the source
   - Save the settings

3. Copy the GitHub Pages template to your new repository:
   ```bash
   # Clone your new repository
   git clone https://github.com/yourusername/radio-playlists.git
   
   # Copy template files
   cp -r tracktracker/github_pages_template/* radio-playlists/
   
   # Push to GitHub
   cd radio-playlists
   git add .
   git commit -m "Initial commit with template files"
   git push
   ```

## Regular Workflow

### 1. Updating an Existing Show

When a show has new episodes:

1. Run the local scraper to update the show's playlist:
   ```bash
   cd tracktracker
   python local_scraper.py update "https://www.nts.live/shows/showname"
   ```

2. Export the updated shows data for the website:
   ```bash
   python export_for_web.py -o ../radio-playlists/shows.js --copy-images
   ```

3. Push the changes to GitHub:
   ```bash
   cd ../radio-playlists
   git add shows.js show-images/
   git commit -m "Update shows data with latest episodes"
   git push
   ```

4. Your website will automatically update with the latest data!

### 2. Adding a New Show

When you want to add a completely new show:

1. First, create a Spotify playlist for the show (or use an existing one)

2. Add the show to your local data:
   ```bash
   cd tracktracker
   python local_scraper.py add "https://www.nts.live/shows/newshow" "https://open.spotify.com/playlist/yourplaylistid"
   ```
   - You'll be prompted to enter a short title, show artwork path, and Apple Music URL (if available)

3. Export the updated shows data for the website:
   ```bash
   python export_for_web.py -o ../radio-playlists/shows.js --copy-images
   ```

4. Push the changes to GitHub:
   ```bash
   cd ../radio-playlists
   git add shows.js show-images/
   git commit -m "Add new show: Show Name"
   git push
   ```

## Customizing the Website

You can customize the look and feel of your GitHub Pages site:

1. Edit `index.html` to change the page structure and layout
2. Modify `styles.css` to update colors, fonts, spacing, etc.
3. Update `app.js` if you want to change how shows are displayed or add new features

After making changes, commit and push them to see the updates live.

## Troubleshooting

### Authentication Issues

If you encounter Spotify authentication issues:

1. Verify your credentials in the `.env` file
2. Try resetting the authentication:
   ```bash
   python reset_spotify_auth.py
   ```

### Missing Show Images

If show images aren't appearing:

1. Make sure the image files exist in `show-images/` directory
2. Check that the file paths in shows.json match the filenames
3. Verify that images were copied with the `--copy-images` flag during export

### API Rate Limits

If you hit API rate limits when processing many shows:

1. Add a delay between requests using the `--chunk-size` option
2. Try again after waiting for the rate limit to reset

## Benefits of This Approach

This simplified workflow offers several advantages:

- **Separation of Concerns**: Scraping and website display are completely separate
- **Enhanced Security**: No need for SSH keys or complex deployment setups
- **Manual Control**: You decide when to update the site
- **Simplified Hosting**: Static sites can be hosted anywhere (not just GitHub Pages)
- **Easier Maintenance**: Each component can be updated independently

## Advanced Usage

### Batch Processing Multiple Shows

To update multiple shows at once, you can create a simple shell script:

```bash
#!/bin/bash
# update_shows.sh

cd tracktracker

# Update each show
python local_scraper.py update "https://www.nts.live/shows/show1"
python local_scraper.py update "https://www.nts.live/shows/show2"
python local_scraper.py update "https://www.nts.live/shows/show3"

# Export for web
python export_for_web.py -o ../radio-playlists/shows.js --copy-images

# Push changes
cd ../radio-playlists
git add shows.js show-images/
git commit -m "Update shows data"
git push
```

Make it executable and run it:
```bash
chmod +x update_shows.sh
./update_shows.sh
```