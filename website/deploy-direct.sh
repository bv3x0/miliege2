#!/bin/bash
# Direct deployment script using GitHub API

# Exit on error
set -e

# Build the website
echo "Building the website..."
cd "$(dirname "$0")"
npm run build

# GitHub repository information
REPO_OWNER="bv3x0"
REPO_NAME="radio"
BRANCH="main"

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

# Get current SHA of main branch
echo "Getting current commit SHA..."
MAIN_SHA=$(gh api repos/$REPO_OWNER/$REPO_NAME/git/refs/heads/$BRANCH | jq -r '.object.sha')
echo "Current commit SHA: $MAIN_SHA"

# Create a new commit with all files
echo "Uploading files to GitHub..."

# Process HTML and CSS files
echo "Processing HTML, CSS, and JS files..."
for file in dist/*.html dist/assets/*.css dist/assets/*.js; do
    if [ -f "$file" ]; then
        filename=$(basename "$file")
        path=${file#dist/}
        echo "Uploading $path..."
        
        # Create blob
        BLOB_SHA=$(gh api repos/$REPO_OWNER/$REPO_NAME/git/blobs \
            --method POST \
            --field content="$(base64 "$file")" \
            --field encoding="base64" | jq -r '.sha')
            
        echo "Created blob for $path: $BLOB_SHA"
    fi
done

# Process image files one by one
if [ -d "dist/show-images" ]; then
    echo "Processing image files..."
    for img in dist/show-images/*.jpg dist/show-images/*.jpeg dist/show-images/*.png; do
        if [ -f "$img" ]; then
            imgname=$(basename "$img")
            path=${img#dist/}
            echo "Uploading $path..."
            
            # Use gh api to create a blob and update the reference
            gh api repos/$REPO_OWNER/$REPO_NAME/contents/$path \
                --method PUT \
                --field message="Add $imgname" \
                --field content="$(base64 "$img")" \
                --field branch="$BRANCH"
        fi
    done
fi

echo "Deployment completed!"
echo "Your website should be available at: https://bv3x0.github.io/radio/"