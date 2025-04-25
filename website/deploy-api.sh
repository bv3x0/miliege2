#!/bin/bash
# Deploy the React application to GitHub Pages using GitHub API

# Exit on error
set -e

# Build the website
echo "Building the website..."
cd "$(dirname "$0")"
npm run build

# Repository information
REPO_OWNER="bv3x0"
REPO_NAME="radio"
BRANCH="main"

# Check for GitHub CLI
if ! command -v gh &> /dev/null; then
    echo "GitHub CLI not found. Installing..."
    brew install imagemagick
    echo "Please run 'gh auth login' to authenticate with GitHub"
    exit 1
fi

# Ensure authenticated with GitHub CLI
if ! gh auth status &> /dev/null; then
    echo "Please login to GitHub CLI:"
    gh auth login
    exit 1
fi

# Get the current commit SHA
echo "Getting current commit SHA..."
COMMIT_SHA=$(gh api repos/$REPO_OWNER/$REPO_NAME/git/refs/heads/$BRANCH | jq -r '.object.sha')
echo "Current commit SHA: $COMMIT_SHA"

# Upload JavaScript and CSS files
echo "Uploading assets..."
mkdir -p "dist/assets"  # Ensure directory exists
for file in dist/assets/*; do
    if [ -f "$file" ]; then
        filename=$(basename "$file")
        remotepath="assets/$filename"
        echo "Uploading $remotepath..."
        
        # Use GitHub CLI to update the file
        gh api repos/$REPO_OWNER/$REPO_NAME/contents/$remotepath \
            --method PUT \
            --field message="Update $remotepath" \
            --field content="$(base64 -i "$file")" \
            --field branch="$BRANCH"
    fi
done

# Upload index.html
echo "Uploading index.html..."
gh api repos/$REPO_OWNER/$REPO_NAME/contents/index.html \
    --method PUT \
    --field message="Update index.html" \
    --field content="$(base64 -i dist/index.html)" \
    --field branch="$BRANCH"

# Create show-images directory if it doesn't exist
echo "Creating show-images directory if needed..."
mkdir -p dist/show-images

# Copy images from public directory to ensure they're available
echo "Copying show images from public directory..."
cp -R public/show-images/* dist/show-images/ 2>/dev/null || true

# Upload each image file separately
echo "Uploading images..."
for img in dist/show-images/*; do
    if [ -f "$img" ]; then
        filename=$(basename "$img")
        remotepath="show-images/$filename"
        echo "Uploading $remotepath..."
        
        # Use GitHub CLI to update the file
        gh api repos/$REPO_OWNER/$REPO_NAME/contents/$remotepath \
            --method PUT \
            --field message="Update $remotepath" \
            --field content="$(base64 -i "$img")" \
            --field branch="$BRANCH"
    fi
done

# Add a README.md file
echo "Adding README.md..."
README_CONTENT="# TrackTracker Radio Website\n\nThis repository hosts the built version of the TrackTracker radio website."
gh api repos/$REPO_OWNER/$REPO_NAME/contents/README.md \
    --method PUT \
    --field message="Update README.md" \
    --field content="$(echo -e "$README_CONTENT" | base64)" \
    --field branch="$BRANCH"

echo "Deployment completed successfully!"
echo "Your website should be available at: https://bv3x0.github.io/radio/"