import { Box } from "@chakra-ui/react";
import GlobeView from "./components/GlobeView";
import FieldMap from "./components/FieldMap";
import { useState } from "react";

function App() {
  const [selectedCountry, setSelectedCountry] = useState<{lat: number, lng: number} | null>(null);

  return (
    <Box bg="black" minH="100vh">
      {selectedCountry ? (
<FieldMap 
  lat={selectedCountry.lat} 
  lng={selectedCountry.lng} 
  onBack={() => setSelectedCountry(null)}
/>      ) : (
        <GlobeView onSelectCountry={(lat, lng) => setSelectedCountry({ lat, lng })} />
      )}
    </Box>
  );
}

export default App;