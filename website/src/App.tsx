import React from "react";
import PlaylistGrid from "./components/PlaylistGrid";

const App = () => (
  <div className="min-h-screen w-full flex flex-col bg-white">
    <div className="main-content">
      <div className="main-content">
        <h1 className="site-title">TRACKTRACKER</h1>
        <div className="site-description">Bootleg playlists of radio show tracklists.</div>
        <PlaylistGrid />
      </div>
    </div>
  </div>
);

export default App;
