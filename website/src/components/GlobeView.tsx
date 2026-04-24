import { useEffect, useRef } from "react";
import Globe from "globe.gl";
import { Box } from "@chakra-ui/react";
import CountryDropdown from "./CountryDropdown";

function GlobeView() {
  const globeContainerRef = useRef<HTMLDivElement>(null);
  const globeInstanceRef = useRef<any>(null);

  useEffect(() => {
    if (!globeContainerRef.current) return;

    const globe = Globe()(globeContainerRef.current);

    globe
      .globeImageUrl(
        "//unpkg.com/three-globe/example/img/earth-blue-marble.jpg"
      )
      .backgroundImageUrl(
        "//unpkg.com/three-globe/example/img/night-sky.png"
      )
      .width(window.innerWidth)
      .height(window.innerHeight)
      .pointOfView({ lat: 20, lng: 10, altitude: 2.5 });

    globeInstanceRef.current = globe;

    return () => {
      if (globeContainerRef.current) {
        globeContainerRef.current.replaceChildren();
      }
    };
  }, []);

  const handleSelectCountry = (lat: number, lng: number) => {
    if (globeInstanceRef.current) {
      globeInstanceRef.current.pointOfView(
        { lat, lng, altitude: 0.8 },
        2000
      );
    }
  };

  return (
    <>
      <CountryDropdown onSelectCountry={handleSelectCountry} />
      <Box
        ref={globeContainerRef}
        width="100vw"
        height="100vh"
        overflow="hidden"
        bg="black"
        position="fixed"
        top={0}
        left={0}
      />
    </>
  );
}

export default GlobeView;