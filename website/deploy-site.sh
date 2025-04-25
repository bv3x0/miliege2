#!/bin/bash
# Simple and reliable deployment script for GitHub Pages

# Exit on error
set -e

# Build the website with correct base path
echo "Building the website..."
cd "$(dirname "$0")"
npm run build

# Create a local copy of the build
echo "Creating deployment directory..."
DEPLOY_DIR="$(pwd)/gh-pages-deploy"
rm -rf "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR"

# Copy the build files
echo "Copying build files..."
cp -R dist/* "$DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR/show-images"
cp -R public/show-images/* "$DEPLOY_DIR/show-images/" 2>/dev/null || true

# Create a .nojekyll file to disable Jekyll processing
touch "$DEPLOY_DIR/.nojekyll"

# Create README file
echo "# TrackTracker Radio Website

This repository hosts the build files for the TrackTracker radio website, deployed via GitHub Pages.
" > "$DEPLOY_DIR/README.md"

# Use SSH key for authentication
SSH_KEY="../keys/deploy_key"
if [ -f "$SSH_KEY" ]; then
  echo "Using SSH key for authentication..."
  # Set up SSH key
  eval $(ssh-agent -s)
  ssh-add "$SSH_KEY"
  
  # Clone the repository
  cd "$DEPLOY_DIR"
  git init
  git remote add origin git@github.com:bv3x0/radio-site.git
  git checkout -b main
  
  # Add all files
  git add .
  
  # Commit
  git config user.name "Deployment Script"
  git config user.email "noreply@example.com"
  git commit -m "Deploy website to GitHub Pages"
  
  # Push force to the main branch
  echo "Pushing to GitHub..."
  git push -f origin main
else
  echo "SSH key not found at $SSH_KEY"
  echo "Please make sure the SSH key is available or use GitHub Actions for deployment."
  exit 1
fi

# Clean up
cd ..
echo "Deployment completed!"
echo "Your site should be live at: https://bv3x0.github.io/radio-site/"
echo "NOTE: Make sure GitHub Pages is enabled in your repository settings:"
echo "Go to: https://github.com/bv3x0/radio-site/settings/pages"
echo "Source: Deploy from a branch"
echo "Branch: main, Folder: / (root)"