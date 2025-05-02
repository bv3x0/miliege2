// Main application script for TrackTracker static site

document.addEventListener('DOMContentLoaded', () => {
  // Check if shows data exists
  if (!window.shows || !Array.isArray(window.shows)) {
    document.getElementById('showGrid').innerHTML = '<p>No shows available. Make sure shows.js is properly loaded.</p>';
    return;
  }

  // Format date helper function (matches your existing React implementation)
  function formatDate(d) {
    // d is YYYY-MM-DD
    if (!d) return '';
    const [y, m, day] = d.split("-");
    return `${m}/${day}/${y.slice(2)}`;
  }

  // Get templates and grid
  const showTileTemplate = document.getElementById('showTileTemplate');
  const showInfoTemplate = document.getElementById('showInfoTemplate');
  const heartGridTemplate = document.getElementById('heartGridTemplate');
  const showGrid = document.getElementById('showGrid');

  // Current selected show index
  let selectedShowIndex = null;
  
  // Sort shows alphabetically (matching your existing implementation)
  const sortedShows = [...window.shows].sort((a, b) => {
    return a.shortTitle.localeCompare(b.shortTitle);
  });

  // Calculate column count based on screen width
  function calculateColumnCount() {
    return window.innerWidth >= 900 ? 3 : 1;
  }

  // Initial column count
  let columnCount = calculateColumnCount();
  
  // Handle window resize
  window.addEventListener('resize', () => {
    const newColumnCount = calculateColumnCount();
    if (newColumnCount !== columnCount) {
      columnCount = newColumnCount;
      renderGrid();
    }
  });

  // Helper to chunk array into rows
  function chunk(arr, size) {
    const result = [];
    for (let i = 0; i < arr.length; i += size) {
      result.push(arr.slice(i, i + size));
    }
    return result;
  }

  // Function to render a show tile
  function createShowTile(show, index) {
    const tileElement = document.importNode(showTileTemplate.content, true);
    
    // Set image and title
    const imageElement = tileElement.querySelector('.playlist-tile-image');
    imageElement.src = show.art;
    imageElement.alt = show.shortTitle;
    
    tileElement.querySelector('.playlist-short-title').textContent = show.shortTitle;
    
    // Add heart grid (invisible by default)
    const heartGrid = document.importNode(heartGridTemplate.content, true);
    tileElement.querySelector('.playlist-tile-img-area').appendChild(heartGrid);
    
    // Set up click handler
    const button = tileElement.querySelector('.playlist-tile-btn');
    button.addEventListener('click', () => {
      toggleShowInfo(index);
    });

    return tileElement;
  }

  // Create show info section
  function createShowInfo(show) {
    const infoElement = document.importNode(showInfoTemplate.content, true);
    
    // Set title
    infoElement.querySelector('.show-info-long-title').textContent = show.longTitle;
    
    // Set description
    if (show.description) {
      const descEl = infoElement.querySelector('.show-description');
      const sourceName = show.source || 'NTS Radio';
      descEl.innerHTML = `<a href="${show.url}" target="_blank" rel="noopener noreferrer" class="source-link">${sourceName}</a>: "${show.description}"`;
    } else {
      infoElement.querySelector('.show-description').remove();
    }
    
    // Set date range
    infoElement.querySelector('.show-date-range').textContent = 
      `Playlists feature whatever is on streaming, from mixes ${formatDate(show.startDate)} - ${formatDate(show.endDate)}.`;
    
    // Set buttons
    if (show.spotify) {
      const spotifyBtn = infoElement.querySelector('.spotify-btn');
      spotifyBtn.href = show.spotify;
    } else {
      infoElement.querySelector('.spotify-btn').remove();
    }
    
    if (show.apple) {
      const appleBtn = infoElement.querySelector('.apple-btn');
      appleBtn.href = show.apple;
    } else {
      infoElement.querySelector('.apple-btn').remove();
    }
    
    if (show.url) {
      const sourceBtn = infoElement.querySelector('.nts-btn');
      sourceBtn.href = show.url;
      // Update button text to show the source name
      sourceBtn.textContent = show.source || 'NTS';
    } else {
      infoElement.querySelector('.nts-btn').remove();
    }
    
    // Set embeds
    if (show.spotifyEmbed) {
      infoElement.querySelector('.spotify-embed').innerHTML = show.spotifyEmbed;
    } else {
      infoElement.querySelector('.spotify-embed').remove();
    }
    
    if (show.appleEmbed) {
      infoElement.querySelector('.apple-embed').innerHTML = show.appleEmbed;
    } else {
      infoElement.querySelector('.apple-embed').remove();
    }
    
    // Set up close button
    const closeBtn = infoElement.querySelector('.close-btn');
    closeBtn.addEventListener('click', () => {
      closeShowInfo();
    });
    
    return infoElement;
  }

  // Toggle show info display
  function toggleShowInfo(index) {
    if (selectedShowIndex === index) {
      closeShowInfo();
    } else {
      openShowInfo(index);
    }
  }

  // Open show info
  function openShowInfo(index) {
    // Close any open show info first
    closeShowInfo();
    
    // Set selected show index
    selectedShowIndex = index;
    
    // Add selected class to the tile
    const tiles = document.querySelectorAll('.playlist-tile-outer');
    tiles[index].classList.add('selected');
    
    // Determine where to insert the show info
    const colCount = calculateColumnCount();
    const rowIndex = Math.floor(index / colCount);
    const insertAfterIndex = (rowIndex + 1) * colCount - 1;
    
    // Create the show info element
    const showInfo = createShowInfo(sortedShows[index]);
    const showInfoWrapper = document.createElement('div');
    showInfoWrapper.classList.add('show-info-wrapper');
    showInfoWrapper.style.gridColumn = '1 / -1';
    showInfoWrapper.appendChild(showInfo);
    
    // Insert at the right position
    const allGridItems = showGrid.children;
    
    if (insertAfterIndex < allGridItems.length - 1) {
      showGrid.insertBefore(showInfoWrapper, allGridItems[insertAfterIndex + 1]);
    } else {
      showGrid.appendChild(showInfoWrapper);
    }
    
    // Scroll to the selected tile if needed
    const tileRect = tiles[index].getBoundingClientRect();
    const tilePosition = tileRect.top + window.scrollY;
    
    // Only scroll if the tile is below threshold (500px)
    if (tilePosition > 500) {
      window.scrollTo({
        top: tilePosition - 50, // Position 50px from top
        behavior: 'smooth'
      });
    }
  }

  // Close show info
  function closeShowInfo() {
    if (selectedShowIndex === null) return;
    
    // Remove selected class from all tiles
    const tiles = document.querySelectorAll('.playlist-tile-outer');
    tiles.forEach(tile => tile.classList.remove('selected'));
    
    // Remove show info wrapper
    const infoWrapper = document.querySelector('.show-info-wrapper');
    if (infoWrapper) {
      infoWrapper.remove();
    }
    
    // Reset selected index
    selectedShowIndex = null;
  }

  // Render the grid with all shows
  function renderGrid() {
    // Clear existing grid
    showGrid.innerHTML = '';
    
    // Add all show tiles to the grid
    sortedShows.forEach((show, index) => {
      const tileElement = createShowTile(show, index);
      showGrid.appendChild(tileElement);
    });
    
    // Re-open selected show if any
    if (selectedShowIndex !== null) {
      const previousIndex = selectedShowIndex;
      selectedShowIndex = null; // Reset to avoid duplicate closing
      openShowInfo(previousIndex);
    }
  }

  // Initial render
  renderGrid();
});