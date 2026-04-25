import GlobeView from "./components/GlobeView";
import FieldMap from "./components/FieldMap";
import { useState } from "react";

function App() {
  const [selectedCountry, setSelectedCountry] = useState<{lat: number, lng: number} | null>(null);

  return (
    <div style={{ background: "black", minHeight: "100vh" }}>
      {selectedCountry ? (
        <FieldMap 
          lat={selectedCountry.lat} 
          lng={selectedCountry.lng} 
          onBack={() => setSelectedCountry(null)}
        />
      ) : (
        <GlobeView onSelectCountry={(lat, lng) => setSelectedCountry({ lat, lng })} />
      )}
    </div>
  );
}

export default App;