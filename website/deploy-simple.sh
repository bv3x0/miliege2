#!/bin/bash
# Simple deployment script for TrackTracker website

# Exit on error
set -e

# Create temporary deployment directory
TEMP_DIR=$(mktemp -d)
echo "Created temporary directory: $TEMP_DIR"

# Clone the repository
echo "Cloning repository..."
git clone https://github.com/bv3x0/radio.git $TEMP_DIR

# Remove existing files (keep .git directory)
echo "Cleaning repository..."
find "$TEMP_DIR" -mindepth 1 -maxdepth 1 -not -name ".git" -exec rm -rf {} \;

# Copy index file
echo "Copying index file..."
cp index-for-github.html "$TEMP_DIR/index.html"

# Create images directory
mkdir -p "$TEMP_DIR/show-images"

# Check if ImageMagick is installed
if ! command -v convert &> /dev/null; then
    echo "ImageMagick not found. Installing..."
    brew install imagemagick
fi

# Optimize and copy images
echo "Optimizing and copying images..."
for img in public/show-images/*.jpg public/show-images/*.jpeg; do
    if [ -f "$img" ]; then
        filename=$(basename "$img")
        echo "Optimizing $filename..."
        convert "$img" -resize 300x300 -quality 75 "$TEMP_DIR/show-images/$filename"
    fi
done

# Create README
echo "# TrackTracker Radio Website

This repository hosts the built version of the TrackTracker radio website." > "$TEMP_DIR/README.md"

# Commit and push
cd "$TEMP_DIR"
echo "Committing changes..."
git add .
git config user.name "Deployment Script"
git config user.email "noreply@example.com"
git commit -m "Deploy website - $(date)" || echo "No changes to commit"

echo "Pushing changes..."
git push

# Clean up
echo "Cleaning up..."
cd - > /dev/null
rm -rf "$TEMP_DIR"

echo "Deployment completed successfully!"
echo "Your website should be available at: https://bv3x0.github.io/radio/"