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
  const handleToggle = (e: React.MouseEvent) => {
    e.preventDefault();
    isOpen ? onClose() : onOpen();
  };
  
  return (
    <div className={`flex flex-col playlist-tile-outer${isOpen ? ' selected' : ''}`}>
      <div className="playlist-container">
        <button
          type="button"
          className="cursor-pointer playlist-tile-btn"
          onClick={handleToggle}
          aria-expanded={isOpen}
          aria-label={`Show info for ${show.longTitle}`}
          style={{ justifyContent: 'center', alignItems: 'center', display: 'flex' }}
        >
          <div className="playlist-tile-img-area">
            <img
              src={show.art}
              alt={show.longTitle}
              className="object-cover playlist-tile-image"
              draggable={false}
              style={{width: '220px', height: '220px'}}
            />
            <div className="heart-border-grid" style={{opacity: isOpen ? 1 : 0, width: '270px', height: '300px'}}>
              {/* Top row */}
              <span className="heart-cell">❤️</span>
              <span className="heart-cell">❤️</span>
              <span className="heart-cell">❤️</span>
              <span className="heart-cell">❤️</span>
              <span className="heart-cell">❤️</span>
              <span className="heart-cell">❤️</span>
              <span className="heart-cell">❤️</span>
              <span className="heart-cell">❤️</span>
              <span className="heart-cell">❤️</span>
              
              {/* Left side row 1 */}
              <span className="heart-cell">❤️</span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell">❤️</span>
              
              {/* Left side row 2 */}
              <span className="heart-cell">❤️</span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell">❤️</span>
              
              {/* Left side row 3 */}
              <span className="heart-cell">❤️</span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell">❤️</span>
              
              {/* Left side row 4 */}
              <span className="heart-cell">❤️</span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell">❤️</span>
              
              {/* Left side row 5 */}
              <span className="heart-cell">❤️</span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell">❤️</span>
              
              {/* Left side row 6 */}
              <span className="heart-cell">❤️</span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell">❤️</span>
              
              {/* Left side row 7 */}
              <span className="heart-cell">❤️</span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell">❤️</span>
              
              {/* Extra side row before bottom */}
              <span className="heart-cell">❤️</span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell" style={{visibility: "hidden"}}></span>
              <span className="heart-cell">❤️</span>
              
              {/* Bottom row */}
              <span className="heart-cell">❤️</span>
              <span className="heart-cell">❤️</span>
              <span className="heart-cell">❤️</span>
              <span className="heart-cell">❤️</span>
              <span className="heart-cell">❤️</span>
              <span className="heart-cell">❤️</span>
              <span className="heart-cell">❤️</span>
              <span className="heart-cell">❤️</span>
              <span className="heart-cell">❤️</span>
            </div>
          </div>
        </button>
        <div className="title-container">
          <h3 className="playlist-short-title">{show.shortTitle}</h3>
        </div>
      </div>
    </div>
  );
};

export default PlaylistTile;