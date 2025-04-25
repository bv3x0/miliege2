#!/bin/bash
# Deploy the React application to GitHub Pages

# Exit on error
set -e

# Build the website
echo "Building the website..."
cd "$(dirname "$0")"
npm run build

# Create a temporary directory for deployment
TEMP_DIR=$(mktemp -d)
echo "Created temporary directory: $TEMP_DIR"

# Clone the repository
echo "Cloning repository..."
git clone https://github.com/bv3x0/radio.git "$TEMP_DIR"

# Remove existing files (keep .git directory)
echo "Cleaning repository..."
find "$TEMP_DIR" -mindepth 1 -maxdepth 1 -not -name ".git" -exec rm -rf {} \;

# Copy the entire built website
echo "Copying built files..."
cp -R dist/* "$TEMP_DIR"
cp -R dist/.[^.]* "$TEMP_DIR" 2>/dev/null || true

# Make sure show-images directory exists
mkdir -p "$TEMP_DIR/show-images"

# Copy all show images (directly from public folder to ensure they're there)
echo "Copying show images..."
cp -R public/show-images/* "$TEMP_DIR/show-images/" 2>/dev/null || true

# Commit and push
cd "$TEMP_DIR"
echo "Committing changes..."
git add -A
git config user.name "Deployment Script"
git config user.email "noreply@example.com"
git commit -m "Deploy React website - $(date)" || echo "No changes to commit"

echo "Pushing changes..."
git push

# Clean up
echo "Cleaning up..."
cd - > /dev/null
rm -rf "$TEMP_DIR"

echo "Deployment completed successfully!"
echo "Your website should be available at: https://bv3x0.github.io/radio/"