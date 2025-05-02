# TrackTracker Static Site

This is a static website template for displaying radio show playlists created with the TrackTracker tool.

## Setup

1. Create a GitHub repository
2. Enable GitHub Pages for this repository
3. Copy all files from this template to your repository

## Updating Shows

1. Run the TrackTracker local scraper to update your shows data:
   ```
   python local_scraper.py update <show-url>
   ```

2. Export the updated shows data to a format suitable for this site:
   ```
   python local_scraper.py export -o shows_data.js
   ```

3. Edit the exported file to prepend `window.shows = ` to the JSON array and save it as `shows.js` in this repository.

4. Push the changes to GitHub:
   ```
   git add shows.js
   git commit -m "Update shows data"
   git push
   ```

## Adding Show Images

1. Create a `show-images` directory if it doesn't exist
2. Add your show artwork to this directory
3. Update the paths in your shows data to point to these images

## Customization

You can customize the look and feel of the site by editing:
- `index.html` - The main page structure
- `styles.css` - The site styling
- `app.js` - The JavaScript that renders the shows

## Deployment

The site is automatically published by GitHub Pages whenever you push changes to the repository.