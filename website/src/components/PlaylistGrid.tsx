import React, { useState, useRef, useLayoutEffect, useEffect } from "react";
import PlaylistTile from "./PlaylistTile";
import { Apple, ExternalLink } from "lucide-react";
import showsData from "../data/shows.json";

type SortMethod = "latest" | "alphabetical";

interface PlaylistGridProps {
  baseUrl?: string;
}

export interface PlaylistShow {
  shortTitle: string;
  longTitle: string;
  art: string;
  nts: string;
  apple: string;
  spotify: string;
  appleEmbed: string;
  spotifyEmbed: string;
  frequency: string;
  startDate: string; // ISO string
  endDate: string; // ISO string
  description?: string; // Optional description field
}

// Move formatDate function here as a named export
export function formatDate(d: string) {
  // d is YYYY-MM-DD
  const [y, m, day] = d.split("-");
  return `${m}/${day}/${y.slice(2)}`;
}

// Default shows data in case the imported file is empty
const defaultShows: PlaylistShow[] = [
  {
    shortTitle: "Malibu",
    longTitle: "United in Flames w/ Malibu",
    art: "/show-images/malibu.jpg",
    nts: "https://www.nts.live/shows/malibu",
    apple: "https://music.apple.com/us/playlist/malibu-nts-archive/pl.u-RmkoRhB1a4X",
    spotify: "https://open.spotify.com/playlist/5JhRr3EejhXhoYla1bzVzb?si=CVqSY6HWSeSXjTkREAgZCA",
    appleEmbed: `<iframe allow="autoplay *; encrypted-media *;" frameborder="0" height="450" style="width:567px;max-width:100%;overflow:hidden;background:transparent;" sandbox="allow-forms allow-popups allow-same-origin allow-scripts allow-storage-access-by-user-activation allow-top-navigation-by-user-activation" src="https://embed.music.apple.com/us/playlist/malibu-nts-archive/pl.u-RmkoRhB1a4X"></iframe>`,
    spotifyEmbed: `<iframe style="border-radius:12px" src="https://open.spotify.com/embed/playlist/5JhRr3EejhXhoYla1bzVzb?utm_source=generator" width="100%" height="352" frameBorder="0" allowfullscreen="" allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture; storage-access-by-user-activation" loading="lazy" sandbox="allow-forms allow-popups allow-same-origin allow-scripts allow-storage-access-by-user-activation"></iframe>`,
    frequency: "Monthly",
    startDate: "2020-07-15",
    endDate: "2025-04-17",
    description: "Malibu is a French electronic musician whose work sails between ambient and ethereal music. Forever inspired by soft reverbed vocals and melodious chord progressions, Malibu's music is an immersive nostalgic journey in a sea of synthetic strings and choirs.",
  },
  {
    shortTitle: "Space Afrika",
    longTitle: "Space Afrika",
    art: "/show-images/africa.jpg",
    nts: "https://www.nts.live/shows/space-afrika",
    apple: "https://music.apple.com/us/playlist/space-afrika-nts-archive/pl.u-ljgGYse3D86",
    spotify: "https://open.spotify.com/playlist/5jA2VCCNFsFKbGPrg5bfXJ?si=490a9c3e56e54c89",
    appleEmbed: `<iframe allow="autoplay *; encrypted-media *;" frameborder="0" height="450" style="width:567px;max-width:100%;overflow:hidden;background:transparent;" sandbox="allow-forms allow-popups allow-same-origin allow-scripts allow-storage-access-by-user-activation allow-top-navigation-by-user-activation" src="https://embed.music.apple.com/us/playlist/space-afrika-nts-archive/pl.u-ljgGYse3D86"></iframe>`,
    spotifyEmbed: `<iframe style="border-radius:12px" src="https://open.spotify.com/embed/playlist/5JhRr3EejhXhoYla1bzVzb?utm_source=generator" width="100%" height="352" frameBorder="0" allowfullscreen="" allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture; storage-access-by-user-activation" loading="lazy" sandbox="allow-forms allow-popups allow-same-origin allow-scripts allow-storage-access-by-user-activation"></iframe>`,
    frequency: "Monthly",
    startDate: "2021-04-10",
    endDate: "2025-04-10",
    description: "Experimental ambience, dub, techno, and other crazy left shxt from Joshua Reid & Joshua Inyang, a.k.a Space Afrika… Please, enjoy.",
  },
  {
    shortTitle: "Yo La Tengo",
    longTitle: "James McNew (Yo La Tengo)",
    art: "/show-images/ylt.jpg",
    nts: "https://www.nts.live/shows/yo-la-tengo",
    apple: "https://music.apple.com/us/playlist/yo-la-tengo-nts-archive/pl.u-bJLBNFbv8aX",
    spotify: "https://open.spotify.com/playlist/44reWpjL1NYxoGKqkNxjTI",
    appleEmbed: `<iframe allow="autoplay *; encrypted-media *;" frameborder="0" height="450" style="width:567px;max-width:100%;overflow:hidden;background:transparent;" sandbox="allow-forms allow-popups allow-same-origin allow-scripts allow-storage-access-by-user-activation allow-top-navigation-by-user-activation" src="https://embed.music.apple.com/us/playlist/yo-la-tengo-nts-archive/pl.u-bJLBNFbv8aX"></iframe>`,
    spotifyEmbed: `<iframe style="border-radius:12px" src="https://open.spotify.com/embed/playlist/5JhRr3EejhXhoYla1bzVzb?utm_source=generator" width="100%" height="352" frameBorder="0" allowfullscreen="" allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture; storage-access-by-user-activation" loading="lazy" sandbox="allow-forms allow-popups allow-same-origin allow-scripts allow-storage-access-by-user-activation"></iframe>`,
    frequency: "Monthly",
    startDate: "2022-01-01",
    endDate: "2025-03-01",
    description: "James McNew of Hoboken indie rock royalty Yo La Tengo shares an hour of picks from his collection each month.",
  },
];

const PlaylistGrid: React.FC<PlaylistGridProps> = ({ baseUrl = '/' }) => {
  // Use imported shows data if available, otherwise use default shows data
  const shows: PlaylistShow[] = showsData.length > 0 ? (showsData as PlaylistShow[]) : defaultShows;
  
  // Fix image paths with baseUrl
  const fixedShows = shows.map(show => ({
    ...show,
    art: `${baseUrl}${show.art.startsWith('/') ? show.art.slice(1) : show.art}`
  }));
  
  // State for sorting method
  const [sortMethod, setSortMethod] = useState<SortMethod>("latest");
  
  // Sort shows based on current sort method
  const sortedShows = [...fixedShows].sort((a, b) => {
    if (sortMethod === "latest") {
      // Sort by most recent endDate
      return new Date(b.endDate).getTime() - new Date(a.endDate).getTime();
    } else { // alphabetical
      return a.shortTitle.localeCompare(b.shortTitle);
    }
  });
  
  // Initialize with the first show (index 0) already open
  const [openIndex, setOpenIndex] = useState<number | null>(0);
  const tileRefs = useRef<(HTMLDivElement | null)[]>([]);
  const gridRef = useRef<HTMLDivElement | null>(null);
  const [colCount, setColCount] = useState(1);
  // Add a state to track if grid has content expanded (true by default)
  const [hasExpandedContent, setHasExpandedContent] = useState(true);

  // Calculate column count based on screen width
  useLayoutEffect(() => {
    const calculateColumns = () => {
      const width = window.innerWidth;
      if (width >= 900) {
        setColCount(3);
      } else {
        setColCount(1);
      }
    };

    calculateColumns();
    window.addEventListener('resize', calculateColumns);
    return () => window.removeEventListener('resize', calculateColumns);
  }, []);

  function chunk<T>(arr: T[], size: number): T[][] {
    const res: T[][] = [];
    for (let i = 0; i < arr.length; i += size) {
      res.push(arr.slice(i, i + size));
    }
    return res;
  }

  // Chunk shows by row and render info panel after the row containing the openIndex
  const tiles: React.ReactNode[] = [];
  const numShows = sortedShows.length;
  const rows = chunk(sortedShows, colCount);
  let tileIdx = 0;
  for (let rowIdx = 0; rowIdx < rows.length; rowIdx++) {
    const row = rows[rowIdx];
    const rowTiles = row.map((show, colIdx) => {
      const idx = tileIdx + colIdx;
      return (
        <div
          key={show.longTitle + idx}
          ref={el => { tileRefs.current[idx] = el; }}
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            width: '100%',
            position: 'relative'
          }}
        >
          <PlaylistTile
            show={show}
            isOpen={openIndex === idx}
            onOpen={() => setOpenIndex(idx)}
            onClose={() => setOpenIndex(null)}
          />
        </div>
      );
    });
    tiles.push(...rowTiles);
    // If openIndex is in this row, render info panel after the row
    if (
      openIndex !== null &&
      openIndex >= tileIdx &&
      openIndex < tileIdx + row.length
    ) {
      tiles.push(
        <div
          key={"show-info-" + openIndex}
          className="col-span-full w-full mt-2 mb-8"
          style={{
            gridColumn: '1 / -1',
            position: 'relative',
            left: 0,
            right: 0,
            width: '100%',
            maxWidth: '960px',
            margin: '0 auto'
          }}
        >
          <div className="show-info-section-custom" style={{background:'#ffe600', borderRadius:'18px', border:'3px solid #000', margin:'2rem auto', width:'80%', maxWidth:'750px', boxShadow:'0 2px 16px 0 rgba(0,0,0,0.10)', display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', boxSizing:'border-box', textAlign:'center', padding:'2.5rem 2rem 2rem', position: 'relative'}}>
            <button
              onClick={() => setOpenIndex(null)}
              aria-label="Close"
              style={{
                position: 'absolute',
                top: '16px',
                right: '16px',
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                fontSize: '1.25rem',
                fontWeight: 'normal',
                color: '#000',
                padding: '4px 8px',
                lineHeight: 1
              }}
            >
              ×
            </button>
            <div className="show-info-long-title" style={{ marginBottom: '1.5rem', letterSpacing: '0.05em' }}>{sortedShows[openIndex].longTitle}</div>
            {sortedShows[openIndex].description && (
              <p className="text-base text-gray-800 font-serif text-center" style={{ maxWidth: '85%', margin: '0 auto 1.2rem', lineHeight: '1.2', fontSize: '1.05rem' }}>
                <a
                  href={sortedShows[openIndex].nts}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-bold nts-link"
                >
                  NTS Radio
                </a>: "{sortedShows[openIndex].description}"
              </p>
            )}
            <div className="flex flex-col items-center">
              <p className="font-serif text-center" style={{ fontStyle: 'italic', fontSize: '0.95rem', color: '#555', marginBottom: '1.5rem', letterSpacing: '0.02em' }}>
                Listen to the complete show archive ({formatDate(sortedShows[openIndex].startDate)} - {formatDate(sortedShows[openIndex].endDate)})
              </p>
              <div className="flex gap-8 items-center">
                <a
                  href={sortedShows[openIndex].spotify}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="playlist-btn spotify-btn"
                  style={{ letterSpacing: '0.08em' }}
                >
                  SPOTIFY
                </a>
                <a
                  href={sortedShows[openIndex].apple}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="playlist-btn apple-btn"
                  style={{ letterSpacing: '0.08em' }}
                >
                  APPLE MUSIC
                </a>
              </div>
            </div>
            <div className="w-full" style={{ margin: '3rem auto 0', background: 'none', padding: 0, textAlign: 'center', maxWidth: '1200px' }}>
              <div
                className="w-full"
                style={{background:"none", padding:0, margin:0, textAlign:'center', maxWidth:'567px', height:'352px', overflow:'hidden'}}
                // eslint-disable-next-line react/no-danger
                dangerouslySetInnerHTML={{
                  __html: sortedShows[openIndex].spotifyEmbed,
                }}
              />
              <br />
              <div
                className="w-full"
                style={{background:"none", padding:0, margin:0, textAlign:'center', maxWidth:'567px'}}
                // eslint-disable-next-line react/no-danger
                dangerouslySetInnerHTML={{
                  __html: sortedShows[openIndex].appleEmbed,
                }}
              />
            </div>
          </div>
        </div>
      );
    }
    tileIdx += row.length;
  }

  // Update hasExpandedContent when openIndex changes and scroll to position if needed
  useEffect(() => {
    setHasExpandedContent(openIndex !== null);

    // Scroll to position the selected tile 50px from the top of the viewport,
    // but only if the tile is more than 500px from the top of the page
    if (openIndex !== null && tileRefs.current[openIndex]) {
      const selectedTile = tileRefs.current[openIndex];
      if (selectedTile) {
        const tilePosition = selectedTile.getBoundingClientRect().top + window.scrollY;

        // Only scroll if the tile is below the threshold (500px)
        if (tilePosition > 500) {
          window.scrollTo({
            top: tilePosition - 50, // Position 50px from top
            behavior: 'smooth'
          });
        }
      }
    }
  }, [openIndex]);

  // Sorting links style - Times New Roman as requested
  const sortLinkStyle = {
    fontFamily: "'Times New Roman', serif",
    fontSize: "1rem",
    color: "#000",
    cursor: "pointer",
    textDecoration: sortMethod === "latest" ? "none" : "underline",
    marginRight: "1rem",
    fontWeight: "normal" as const
  };
  
  const sortLinkStyleAZ = {
    ...sortLinkStyle,
    textDecoration: sortMethod === "alphabetical" ? "none" : "underline"
  };

  return (
    <>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "1.5rem" }}>
        <span 
          onClick={() => setSortMethod("latest")}
          style={sortLinkStyle}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => e.key === 'Enter' && setSortMethod("latest")}
        >
          Latest
        </span>
        <span 
          onClick={() => setSortMethod("alphabetical")}
          style={sortLinkStyleAZ}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => e.key === 'Enter' && setSortMethod("alphabetical")}
        >
          A-Z
        </span>
      </div>
      <div
        className={`playlist-grid${hasExpandedContent ? ' has-expanded-content' : ''}`}
        ref={gridRef}
      >
        {tiles}
      </div>
    </>
  );
};

export default PlaylistGrid;