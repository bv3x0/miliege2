import React from "react";
import { PlaylistShow, formatDate } from "./PlaylistGrid";
import { Apple, ExternalLink, ChevronDown } from "lucide-react";

interface PlaylistTileProps {
  show: PlaylistShow;
  isOpen: boolean;
  onOpen: () => void;
  onClose: () => void;
}

const PlaylistTile: React.FC<PlaylistTileProps> = ({
  show,
  isOpen,
  onOpen,
  onClose,
}) => {
  // Handle click: toggle open/close
  const handleToggle = () => (isOpen ? onClose() : onOpen());
  
  return (
    <div className={`flex flex-col playlist-tile-outer${isOpen ? ' selected' : ''}`}>
      <button
        type="button"
        className="group cursor-pointer playlist-tile-btn"
        onClick={handleToggle}
        aria-expanded={isOpen}
        aria-label={`Show info for ${show.longTitle}`}
      >
        <div className="playlist-tile-img-area">
          {isOpen ? (
            <div className="heart-border-grid">
              {/* Top row */}
              <span className="heart-cell">❤️</span>
              <span className="heart-cell">❤️</span>
              <span className="heart-cell">❤️</span>
              {/* Middle row */}
              <span className="heart-cell">❤️</span>
              <span className="heart-cell center-image">
                <img
                  src={show.art}
                  alt={show.longTitle}
                  className="object-cover playlist-tile-image"
                  draggable={false}
                />
              </span>
              <span className="heart-cell">❤️</span>
              {/* Bottom row */}
              <span className="heart-cell">❤️</span>
              <span className="heart-cell">❤️</span>
              <span className="heart-cell">❤️</span>
            </div>
          ) : (
            <img
              src={show.art}
              alt={show.longTitle}
              className="object-cover playlist-tile-image"
              draggable={false}
            />
          )}
        </div>
        <h3 className="font-serif text-xl mb-1 group-hover:text-gray-600 transition-colors flex items-center playlist-short-title">
          {show.shortTitle}
        </h3>

      </button>
      {/* Show info section, expands when isOpen is true */}
      {/* Removed ShowInfoSection to prevent duplicate/inline expanded info */}
    </div>
  );
};

// ShowInfoSection: handles scrolling into view when mounted
const ShowInfoSection: React.FC<{ show: PlaylistShow }> = ({ show }) => {
  const infoRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (infoRef.current) {
      infoRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, []);

  return (
    <div
      ref={infoRef}
      className="show-info-section-custom"
    >
      <div className="mb-2 text-sm text-gray-600">
        {formatDate(show.startDate)} - {formatDate(show.endDate)}
      </div>
      <div className="show-info-long-title">{show.longTitle}</div>
      <div className="flex flex-col gap-2 mt-2">
        {show.nts && (
          <a href={show.nts} target="_blank" rel="noopener noreferrer" className="flex items-center text-black hover:underline">
            <ExternalLink size={14} className="mr-1" /> NTS
          </a>
        )}
        {show.apple && (
          <a href={show.apple} target="_blank" rel="noopener noreferrer" className="flex items-center text-red-500 hover:underline">
            <Apple size={18} className="mr-1" /> Apple Music <ExternalLink size={14} className="ml-1" />
          </a>
        )}
        {show.spotify && (
          <a href={show.spotify} target="_blank" rel="noopener noreferrer" className="flex items-center text-green-500 hover:underline">
            Spotify <ExternalLink size={14} className="ml-1" />
          </a>
        )}
      </div>
    </div>
  );
};

export default PlaylistTile;
