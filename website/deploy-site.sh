#!/bin/bash
# Simple deployment script for GitHub Pages

# Exit on error
set -e

# Build the website
echo "Building the website..."
cd "$(dirname "$0")"
npm run build

# Prepare dist directory
echo "Preparing files..."
touch dist/.nojekyll
mkdir -p dist/show-images
find public/show-images -type f \( -name "*.jpg" -o -name "*.jpeg" -o -name "*.png" -o -name "*.gif" \) -exec cp {} dist/show-images/ \;

# Create README
echo "# TrackTracker Radio Website" > dist/README.md
echo "" >> dist/README.md
echo "This repository hosts the build files for the TrackTracker radio website." >> dist/README.md

echo ""
echo "Deployment instructions:"
echo ""
echo "1. Push your code to main branch for automatic deployment via GitHub Actions"
echo "   - GitHub Actions will build and deploy your site to bv3x0/radio-site"
echo ""
echo "2. Or manually deploy by:"
echo "   a. Clone the radio-site repository:"
echo "      git clone git@github.com:bv3x0/radio-site.git /tmp/radio-deploy"
echo "   b. Copy the dist directory contents:"
echo "      rm -rf /tmp/radio-deploy/* /tmp/radio-deploy/.[!.]*"
echo "      cp -R $(pwd)/dist/* /tmp/radio-deploy/"
echo "      cp -R $(pwd)/dist/.[!.]* /tmp/radio-deploy/ 2>/dev/null || true"
echo "   c. Commit and push:"
echo "      cd /tmp/radio-deploy && git add . && git commit -m \"Deploy website\" && git push"
echo ""
echo "Your site should be live at: https://bv3x0.github.io/radio-site/"
echo "Make sure GitHub Pages is enabled: https://github.com/bv3x0/radio-site/settings/pages"