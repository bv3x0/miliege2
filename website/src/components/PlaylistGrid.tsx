import React, { useState, useRef, useLayoutEffect, useEffect } from "react";
import PlaylistTile from "./PlaylistTile";
import { Apple, ExternalLink } from "lucide-react";

export interface PlaylistShow {
  shortTitle: string;
  longTitle: string;
  art: string;
  nts: string;
  apple: string;
  spotify: string;
  appleEmbed: string;
  frequency: string;
  startDate: string; // ISO string
  endDate: string; // ISO string
}

// Move formatDate function here as a named export
export function formatDate(d: string) {
  // d is YYYY-MM-DD
  const [y, m, day] = d.split("-");
  return `${m}/${day}/${y.slice(2)}`;
}

const shows: PlaylistShow[] = [
  {
    shortTitle: "Malibu",
    longTitle: "United in Flames w/ Malibu",
    art: "/show-images/malibu.jpg",
    nts: "https://www.nts.live/shows/malibu",
    apple: "https://music.apple.com/us/playlist/malibu-nts-archive/pl.u-RmkoRhB1a4X",
    spotify: "https://open.spotify.com/playlist/5JhRr3EejhXhoYla1bzVzb?si=CVqSY6HWSeSXjTkREAgZCA",
    appleEmbed: `<iframe allow="autoplay *; encrypted-media *;" frameborder="0" height="450" style="width:567px;max-width:100%;overflow:hidden;background:transparent;" sandbox="allow-forms allow-popups allow-same-origin allow-scripts allow-storage-access-by-user-activation allow-top-navigation-by-user-activation" src="https://embed.music.apple.com/us/playlist/malibu-nts-archive/pl.u-RmkoRhB1a4X"></iframe>`,
    frequency: "Monthly",
    startDate: "2020-07-15",
    endDate: "2025-04-17",
  },
  {
    shortTitle: "Space Afrika",
    longTitle: "Space Afrika",
    art: "/show-images/africa.jpg",
    nts: "https://www.nts.live/shows/space-afrika",
    apple: "https://music.apple.com/us/playlist/space-afrika-nts-archive/pl.u-ljgGYse3D86",
    spotify: "https://open.spotify.com/playlist/5jA2VCCNFsFKbGPrg5bfXJ?si=490a9c3e56e54c89",
    appleEmbed: `<iframe allow="autoplay *; encrypted-media *;" frameborder="0" height="450" style="width:567px;max-width:100%;overflow:hidden;background:transparent;" sandbox="allow-forms allow-popups allow-same-origin allow-scripts allow-storage-access-by-user-activation allow-top-navigation-by-user-activation" src="https://embed.music.apple.com/us/playlist/space-afrika-nts-archive/pl.u-ljgGYse3D86"></iframe>`,
    frequency: "Monthly",
    startDate: "2021-04-10",
    endDate: "2025-04-10",
  },
  {
    shortTitle: "Yo La Tengo",
    longTitle: "James McNew (Yo La Tengo)",
    art: "/show-images/ylt.jpg",
    nts: "https://www.nts.live/shows/yo-la-tengo",
    apple: "https://music.apple.com/us/playlist/yo-la-tengo-nts-archive/pl.u-bJLBNFbv8aX",
    spotify: "https://open.spotify.com/playlist/44reWpjL1NYxoGKqkNxjTI",
    appleEmbed: `<iframe allow="autoplay *; encrypted-media *;" frameborder="0" height="450" style="width:567px;max-width:100%;overflow:hidden;background:transparent;" sandbox="allow-forms allow-popups allow-same-origin allow-scripts allow-storage-access-by-user-activation allow-top-navigation-by-user-activation" src="https://embed.music.apple.com/us/playlist/yo-la-tengo-nts-archive/pl.u-bJLBNFbv8aX"></iframe>`,
    frequency: "Monthly",
    startDate: "2022-01-01",
    endDate: "2025-03-01",
  },
  {
    shortTitle: "Malibu",
    longTitle: "United in Flames w/ Malibu",
    art: "/show-images/malibu.jpg",
    nts: "https://www.nts.live/shows/malibu",
    apple: "https://music.apple.com/us/playlist/malibu-nts-archive/pl.u-RmkoRhB1a4X",
    spotify: "https://open.spotify.com/playlist/5JhRr3EejhXhoYla1bzVzb?si=CVqSY6HWSeSXjTkREAgZCA",
    appleEmbed: `<iframe allow="autoplay *; encrypted-media *;" frameborder="0" height="450" style="width:567px;max-width:100%;overflow:hidden;background:transparent;" sandbox="allow-forms allow-popups allow-same-origin allow-scripts allow-storage-access-by-user-activation allow-top-navigation-by-user-activation" src="https://embed.music.apple.com/us/playlist/malibu-nts-archive/pl.u-RmkoRhB1a4X"></iframe>`,
    frequency: "Monthly",
    startDate: "2020-07-15",
    endDate: "2025-04-17",
  },
  {
    shortTitle: "Space Afrika",
    longTitle: "Space Afrika",
    art: "/show-images/africa.jpg",
    nts: "https://www.nts.live/shows/space-afrika",
    apple: "https://music.apple.com/us/playlist/space-afrika-nts-archive/pl.u-ljgGYse3D86",
    spotify: "https://open.spotify.com/playlist/5jA2VCCNFsFKbGPrg5bfXJ?si=490a9c3e56e54c89",
    appleEmbed: `<iframe allow="autoplay *; encrypted-media *;" frameborder="0" height="450" style="width:567px;max-width:100%;overflow:hidden;background:transparent;" sandbox="allow-forms allow-popups allow-same-origin allow-scripts allow-storage-access-by-user-activation allow-top-navigation-by-user-activation" src="https://embed.music.apple.com/us/playlist/space-afrika-nts-archive/pl.u-ljgGYse3D86"></iframe>`,
    frequency: "Monthly",
    startDate: "2021-04-10",
    endDate: "2025-04-10",
  },
  {
    shortTitle: "Yo La Tengo",
    longTitle: "James McNew (Yo La Tengo)",
    art: "/show-images/ylt.jpg",
    nts: "https://www.nts.live/shows/yo-la-tengo",
    apple: "https://music.apple.com/us/playlist/yo-la-tengo-nts-archive/pl.u-bJLBNFbv8aX",
    spotify: "https://open.spotify.com/playlist/44reWpjL1NYxoGKqkNxjTI",
    appleEmbed: `<iframe allow="autoplay *; encrypted-media *;" frameborder="0" height="450" style="width:567px;max-width:100%;overflow:hidden;background:transparent;" sandbox="allow-forms allow-popups allow-same-origin allow-scripts allow-storage-access-by-user-activation allow-top-navigation-by-user-activation" src="https://embed.music.apple.com/us/playlist/yo-la-tengo-nts-archive/pl.u-bJLBNFbv8aX"></iframe>`,
    frequency: "Monthly",
    startDate: "2022-01-01",
    endDate: "2025-03-01",
  },
  {
    shortTitle: "Malibu",
    longTitle: "United in Flames w/ Malibu",
    art: "/show-images/malibu.jpg",
    nts: "https://www.nts.live/shows/malibu",
    apple: "https://music.apple.com/us/playlist/malibu-nts-archive/pl.u-RmkoRhB1a4X",
    spotify: "https://open.spotify.com/playlist/5JhRr3EejhXhoYla1bzVzb?si=CVqSY6HWSeSXjTkREAgZCA",
    appleEmbed: `<iframe allow="autoplay *; encrypted-media *;" frameborder="0" height="450" style="width:567px;max-width:100%;overflow:hidden;background:transparent;" sandbox="allow-forms allow-popups allow-same-origin allow-scripts allow-storage-access-by-user-activation allow-top-navigation-by-user-activation" src="https://embed.music.apple.com/us/playlist/malibu-nts-archive/pl.u-RmkoRhB1a4X"></iframe>`,
    frequency: "Monthly",
    startDate: "2020-07-15",
    endDate: "2025-04-17",
  },
  {
    shortTitle: "Space Afrika",
    longTitle: "Space Afrika",
    art: "/show-images/africa.jpg",
    nts: "https://www.nts.live/shows/space-afrika",
    apple: "https://music.apple.com/us/playlist/space-afrika-nts-archive/pl.u-ljgGYse3D86",
    spotify: "https://open.spotify.com/playlist/5jA2VCCNFsFKbGPrg5bfXJ?si=490a9c3e56e54c89",
    appleEmbed: `<iframe allow="autoplay *; encrypted-media *;" frameborder="0" height="450" style="width:567px;max-width:100%;overflow:hidden;background:transparent;" sandbox="allow-forms allow-popups allow-same-origin allow-scripts allow-storage-access-by-user-activation allow-top-navigation-by-user-activation" src="https://embed.music.apple.com/us/playlist/space-afrika-nts-archive/pl.u-ljgGYse3D86"></iframe>`,
    frequency: "Monthly",
    startDate: "2021-04-10",
    endDate: "2025-04-10",
  },
  {
    shortTitle: "Yo La Tengo",
    longTitle: "James McNew (Yo La Tengo)",
    art: "/show-images/ylt.jpg",
    nts: "https://www.nts.live/shows/yo-la-tengo",
    apple: "https://music.apple.com/us/playlist/yo-la-tengo-nts-archive/pl.u-bJLBNFbv8aX",
    spotify: "https://open.spotify.com/playlist/44reWpjL1NYxoGKqkNxjTI",
    appleEmbed: `<iframe allow="autoplay *; encrypted-media *;" frameborder="0" height="450" style="width:567px;max-width:100%;overflow:hidden;background:transparent;" sandbox="allow-forms allow-popups allow-same-origin allow-scripts allow-storage-access-by-user-activation allow-top-navigation-by-user-activation" src="https://embed.music.apple.com/us/playlist/yo-la-tengo-nts-archive/pl.u-bJLBNFbv8aX"></iframe>`,
    frequency: "Monthly",
    startDate: "2022-01-01",
    endDate: "2025-03-01",
  },
  {
    shortTitle: "Malibu",
    longTitle: "United in Flames w/ Malibu",
    art: "/show-images/malibu.jpg",
    nts: "https://www.nts.live/shows/malibu",
    apple: "https://music.apple.com/us/playlist/malibu-nts-archive/pl.u-RmkoRhB1a4X",
    spotify: "https://open.spotify.com/playlist/5JhRr3EejhXhoYla1bzVzb?si=CVqSY6HWSeSXjTkREAgZCA",
    appleEmbed: `<iframe allow="autoplay *; encrypted-media *;" frameborder="0" height="450" style="width:567px;max-width:100%;overflow:hidden;background:transparent;" sandbox="allow-forms allow-popups allow-same-origin allow-scripts allow-storage-access-by-user-activation allow-top-navigation-by-user-activation" src="https://embed.music.apple.com/us/playlist/malibu-nts-archive/pl.u-RmkoRhB1a4X"></iframe>`,
    frequency: "Monthly",
    startDate: "2020-07-15",
    endDate: "2025-04-17",
  },
  {
    shortTitle: "Space Afrika",
    longTitle: "Space Afrika",
    art: "/show-images/africa.jpg",
    nts: "https://www.nts.live/shows/space-afrika",
    apple: "https://music.apple.com/us/playlist/space-afrika-nts-archive/pl.u-ljgGYse3D86",
    spotify: "https://open.spotify.com/playlist/5jA2VCCNFsFKbGPrg5bfXJ?si=490a9c3e56e54c89",
    appleEmbed: `<iframe allow="autoplay *; encrypted-media *;" frameborder="0" height="450" style="width:567px;max-width:100%;overflow:hidden;background:transparent;" sandbox="allow-forms allow-popups allow-same-origin allow-scripts allow-storage-access-by-user-activation allow-top-navigation-by-user-activation" src="https://embed.music.apple.com/us/playlist/space-afrika-nts-archive/pl.u-ljgGYse3D86"></iframe>`,
    frequency: "Monthly",
    startDate: "2021-04-10",
    endDate: "2025-04-10",
  },
  {
    shortTitle: "Yo La Tengo",
    longTitle: "James McNew (Yo La Tengo)",
    art: "/show-images/ylt.jpg",
    nts: "https://www.nts.live/shows/yo-la-tengo",
    apple: "https://music.apple.com/us/playlist/yo-la-tengo-nts-archive/pl.u-bJLBNFbv8aX",
    spotify: "https://open.spotify.com/playlist/44reWpjL1NYxoGKqkNxjTI",
    appleEmbed: `<iframe allow="autoplay *; encrypted-media *;" frameborder="0" height="450" style="width:567px;max-width:100%;overflow:hidden;background:transparent;" sandbox="allow-forms allow-popups allow-same-origin allow-scripts allow-storage-access-by-user-activation allow-top-navigation-by-user-activation" src="https://embed.music.apple.com/us/playlist/yo-la-tengo-nts-archive/pl.u-bJLBNFbv8aX"></iframe>`,
    frequency: "Monthly",
    startDate: "2022-01-01",
    endDate: "2025-03-01",
  },
];

const PlaylistGrid = () => {
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const tileRefs = useRef<(HTMLDivElement | null)[]>([]);
  const gridRef = useRef<HTMLDivElement | null>(null);
  const [colCount, setColCount] = useState(1);
  
  // Effect to handle scrolling when a show is selected
  useEffect(() => {
    if (openIndex !== null && tileRefs.current[openIndex]) {
      const selectedTile = tileRefs.current[openIndex];
      if (selectedTile) {
        // Scroll to position the selected tile 80px from the top of the viewport
        const yOffset = -58; 
        const y = selectedTile.getBoundingClientRect().top + window.pageYOffset + yOffset;
        
        window.scrollTo({
          top: y,
          behavior: 'smooth'
        });
      }
    }
  }, [openIndex]);

  useLayoutEffect(() => {
    if (gridRef.current) {
      const computedStyle = window.getComputedStyle(gridRef.current);
      const columns = computedStyle.gridTemplateColumns.split(" ").length;
      setColCount(columns);
    }
    const handleResize = () => {
      if (gridRef.current) {
        const computedStyle = window.getComputedStyle(gridRef.current);
        const columns = computedStyle.gridTemplateColumns.split(" ").length;
        setColCount(columns);
      }
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
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
  const numShows = shows.length;
  const rows = chunk(shows, colCount);
  let tileIdx = 0;
  for (let rowIdx = 0; rowIdx < rows.length; rowIdx++) {
    const row = rows[rowIdx];
    const rowTiles = row.map((show, colIdx) => {
      const idx = tileIdx + colIdx;
      return (
        <div 
          key={show.longTitle + idx} 
          ref={el => { tileRefs.current[idx] = el; }}
          style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', width: '100%' }}
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
          className="col-span-full w-full mt-2 mb-8 animate-fade-in"
          style={{ gridColumn: '1 / -1' }}
        >
          <div className="show-info-section-custom" style={{background:'#ffe600', borderRadius:'18px', border:'3px solid #000', margin:'2rem auto', width:'100%', maxWidth:'1200px', boxShadow:'0 2px 16px 0 rgba(0,0,0,0.10)', display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', boxSizing:'border-box', textAlign:'center'}}>
            <div className="show-info-long-title" style={{ marginBottom: '0.5rem' }}>{shows[openIndex].longTitle}</div>
            <div className="flex flex-col space-y-1 items-center">
              <p className="text-base text-gray-700 font-serif text-center">
                Full show archive: {formatDate(shows[openIndex].startDate)}-{formatDate(shows[openIndex].endDate)} (via{' '}
                <a
                  href={shows[openIndex].nts}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center text-base text-gray-700 hover:text-black transition font-serif underline"
                  style={{ display: 'inline-flex', alignItems: 'center' }}
                >
                  NTS
                </a>
                )
              </p>
              <div className="flex gap-6 items-center mt-1">
                <a
                  href={shows[openIndex].spotify}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="playlist-btn spotify-btn"
                  style={{ marginRight: '18px' }}
                >
                  SPOTIFY
                </a>
                <a
                  href={shows[openIndex].apple}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="playlist-btn apple-btn"
                >
                  APPLE MUSIC
                </a>
              </div>
            </div>
            <div className="w-full mt-8" style={{ margin: '2rem auto', background: 'none', padding: 0, textAlign: 'center', maxWidth: '1200px' }}>
              <br />
              <br />
              <div
                className="w-full"
                style={{background:"none", padding:0, margin:0, textAlign:'center', maxWidth:'567px'}}
                // eslint-disable-next-line react/no-danger
                dangerouslySetInnerHTML={{
                  __html: shows[openIndex].appleEmbed,
                }}
              />
            </div>
          </div>
        </div>
      );
    }
    tileIdx += row.length;
  }

  return (
    <div className="playlist-grid" ref={gridRef}>
      {tiles}
    </div>
  );
};

export default PlaylistGrid;
