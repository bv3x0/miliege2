#!/bin/bash
# Simple deployment script for GitHub Pages

# Exit on error
set -e

# Build the website
echo "Building the website..."
cd "$(dirname "$0")"
npm run build

# Prepare dist directory for local testing
echo "Preparing files..."
touch dist/.nojekyll
mkdir -p dist/show-images
find public/show-images -type f \( -name "*.jpg" -o -name "*.jpeg" -o -name "*.png" -o -name "*.gif" \) -exec cp {} dist/show-images/ \;

# Create README
echo "# TrackTracker Radio Website" > dist/README.md
echo "" >> dist/README.md
echo "This repository hosts the build files for the TrackTracker radio website." >> dist/README.md

# Start a local server for testing
echo ""
echo "Starting local preview server at http://localhost:8080"
echo "Press Ctrl+C to stop"
echo ""
cd dist && python3 -m http.server 8080