#!/bin/bash
# Deploy script with image optimization for TrackTracker website

# Exit on error
set -e

# Build the website
echo "Building the website..."
cd "$(dirname "$0")"
npm run build

# Set repository URL
REPO_URL="https://github.com/bv3x0/radio.git"
REPO_NAME="radio"
BRANCH="main"

# Create a temporary directory
TEMP_DIR=$(mktemp -d)
echo "Created temporary directory: $TEMP_DIR"

# Check if GitHub CLI is installed
if ! command -v gh &> /dev/null; then
    echo "GitHub CLI not found. Installing..."
    brew install gh
    echo "Please run 'gh auth login' to authenticate with GitHub"
    exit 1
fi

# Check if logged in to GitHub CLI
if ! gh auth status &> /dev/null; then
    echo "Please login to GitHub CLI:"
    gh auth login
fi

# Clone the repository using GitHub CLI
echo "Cloning repository..."
gh repo clone $REPO_URL $TEMP_DIR

# Remove existing files (keep .git directory)
echo "Cleaning repository..."
find "$TEMP_DIR" -mindepth 1 -maxdepth 1 -not -name ".git" -exec rm -rf {} \;

# Copy non-image files
echo "Copying non-image files..."
mkdir -p "$TEMP_DIR/assets"
cp dist/*.html "$TEMP_DIR/"
cp dist/assets/*.css "$TEMP_DIR/assets/"
cp dist/assets/*.js "$TEMP_DIR/assets/"
cp dist/favicon.ico "$TEMP_DIR/" 2>/dev/null || true

# Set up image directory
mkdir -p "$TEMP_DIR/show-images"

# Optimize and copy images
if [ -d "dist/show-images" ]; then
    echo "Optimizing and copying images..."
    
    # Check if ImageMagick is installed
    if ! command -v convert &> /dev/null; then
        echo "ImageMagick not found. Installing..."
        brew install imagemagick
    fi
    
    # Process each image
    for img in dist/show-images/*.jpg dist/show-images/*.jpeg; do
        if [ -f "$img" ]; then
            filename=$(basename "$img")
            echo "Optimizing $filename..."
            convert "$img" -resize "400x400>" -quality 80 "$TEMP_DIR/show-images/$filename"
        fi
    done
    
    # Copy any image that might have been missed
    cp -R dist/show-images/* "$TEMP_DIR/show-images/"
fi

# Commit and push
cd "$TEMP_DIR"
echo "Committing changes..."
# Remove any .DS_Store files
find . -name ".DS_Store" -type f -delete

git add -A
git config user.name "Deployment Script"
git config user.email "noreply@example.com"
git commit -m "Update website with optimized images - $(date)" || echo "No changes to commit"

echo "Pushing changes..."
git push

# Clean up
echo "Cleaning up..."
cd - > /dev/null
rm -rf "$TEMP_DIR"

echo "Deployment completed successfully!"
echo "Your website should be available at: https://bv3x0.github.io/radio/"