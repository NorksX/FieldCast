import { useEffect, useRef } from "react";
import Globe from "globe.gl";
import CountryDropdown from "./CountryDropdown";

interface Props {
  onSelectCountry: (lat: number, lng: number) => void;
}

function GlobeView({ onSelectCountry }: Props) {
  const globeContainerRef = useRef<HTMLDivElement>(null);
  const globeInstanceRef = useRef<any>(null);
  const onSelectCountryRef = useRef<(lat: number, lng: number) => void>(onSelectCountry);

  useEffect(() => {
    onSelectCountryRef.current = onSelectCountry;
  }, [onSelectCountry]);

  useEffect(() => {
    if (!globeContainerRef.current) return;

    const globe = Globe()(globeContainerRef.current);

    globe
      .globeImageUrl("//unpkg.com/three-globe/example/img/earth-blue-marble.jpg")
      .backgroundImageUrl("//unpkg.com/three-globe/example/img/night-sky.png")
      .width(globeContainerRef.current.offsetWidth)
      .height(globeContainerRef.current.offsetHeight)
      .pointOfView({ lat: 20, lng: 10, altitude: 2.5 });

    globeInstanceRef.current = globe;

    const handleKeyDown = (e: KeyboardEvent) => {
      const currentPov = globeInstanceRef.current.pointOfView();
      if (e.key === '+' || e.key === '=') {
        globeInstanceRef.current.pointOfView(
          { ...currentPov, altitude: currentPov.altitude - 0.2 },
          300
        );
      }
      if (e.key === '-') {
        globeInstanceRef.current.pointOfView(
          { ...currentPov, altitude: currentPov.altitude + 0.2 },
          300
        );
      }
    };

    const handleResize = () => {
      if (!globeContainerRef.current || !globeInstanceRef.current) return;

      globeInstanceRef.current
        .width(globeContainerRef.current.offsetWidth)
        .height(globeContainerRef.current.offsetHeight);
    };

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("resize", handleResize); // ✅ cleanup
      if (globeContainerRef.current) {
        globeContainerRef.current.replaceChildren();
      }
    };
  }, []);

  const handleSelectCountry = (lat: number, lng: number) => {
    if (globeInstanceRef.current) {
      globeInstanceRef.current.pointOfView({ lat, lng, altitude: 0.3 }, 2000);
      setTimeout(() => {
        onSelectCountryRef.current(lat, lng);
      }, 2000);
    }
  };

  return (
    <>
      <CountryDropdown onSelectCountry={handleSelectCountry} />
      <div
        ref={globeContainerRef}
        style={{
          width: "100vw",
          height: "100vh",
          overflow: "hidden",
          background: "black",
          position: "fixed",
          top: 0,
          left: 0,
        }}
      />
    </>
  );
}

export default GlobeView;