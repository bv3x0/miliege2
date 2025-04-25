#!/bin/bash
# Deploy script for GitHub Pages using incremental commits

# Exit on error
set -e

# Build the website
echo "Building the website..."
cd "$(dirname "$0")"
npm run build

# Clone or update the repository
if [ -d "fresh-deploy" ]; then
  echo "Updating existing repository..."
  cd fresh-deploy
  git pull
else
  echo "Cloning the repository..."
  git clone https://github.com/bv3x0/radio-site.git fresh-deploy
  cd fresh-deploy
fi

# Copy the build files
echo "Copying files..."
rm -rf assets show-images index.html
mkdir -p assets show-images
cp -R ../dist/*.html .
cp -R ../dist/assets/* assets/
cp -R ../public/show-images/* show-images/

# Remove .DS_Store files
find . -name ".DS_Store" -type f -delete

# Make sure we have a .nojekyll file
touch .nojekyll

# Stage all files except images
echo "Staging non-image files..."
git add index.html assets .nojekyll
git commit -m "Update website files - $(date)" || echo "No changes to commit"
git push

# Add each image separately
echo "Adding images one by one..."
for img in show-images/*; do
  if [ -f "$img" ]; then
    echo "Adding $img..."
    git add "$img"
    git commit -m "Add image: $img - $(date)" || echo "No changes to commit"
    git push || echo "Push failed for $img, continuing..."
  fi
done

echo "Deployment completed!"
echo "Your site should be available at: https://bv3x0.github.io/radio-site/"