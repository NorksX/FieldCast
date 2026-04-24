import "leaflet/dist/leaflet.css";
import { MapContainer, TileLayer, Polygon, Polyline, CircleMarker, useMapEvents, useMap } from "react-leaflet";
import { Button, Text, Box } from "@chakra-ui/react";
import { useState } from "react";

interface Props {
  lat: number;
  lng: number;
  onBack: () => void;
}

function DrawPolygon({ onComplete, onPointAdded }: { onComplete: (points: any[]) => void, onPointAdded: () => void }) {
  const [points, setPoints] = useState<any[]>([]);
  const map = useMap();

  useMapEvents({
    click(e) {
      const newPoint = e.latlng;
      const zoom = map.getZoom();
      const threshold = 0.5 / Math.pow(2, zoom - 6);

      if (points.length >= 3) {
        const firstPoint = points[0];
        const distance = Math.sqrt(
          Math.pow(newPoint.lat - firstPoint.lat, 2) +
          Math.pow(newPoint.lng - firstPoint.lng, 2)
        );
        if (distance < threshold) {
          onComplete(points);
          setPoints([]);
          return;
        }
      }

      setPoints([...points, newPoint]);
      onPointAdded();
    },
  });

  return (
    <>
      {points.map((point, index) => (
        <CircleMarker
          key={index}
          center={point}
          radius={index === 0 ? 8 : 5}
          color={index === 0 ? "yellow" : "white"}
          fillColor={index === 0 ? "yellow" : "white"}
          fillOpacity={1}
        />
      ))}
      {points.length > 1 && <Polyline positions={points} color="cyan" />}
      {points.length > 2 && <Polygon positions={points} color="cyan" fillOpacity={0.2} />}
    </>
  );
}

function FieldMap({ lat, lng, onBack }: Props) {
  const [selectMode, setSelectMode] = useState(false);
  const [completedPolygon, setCompletedPolygon] = useState<any[]>([]);
  const [message, setMessage] = useState("");

  const showMessage = (msg: string) => {
    setMessage(msg);
    setTimeout(() => setMessage(""), 2000);
  };

  const handleComplete = (points: any[]) => {
    setCompletedPolygon(points);
    setSelectMode(false);
    console.log("Selected coordinates:", points);
    showMessage("✅ Shape created!");
  };

  return (
    <>
      <MapContainer
        center={[lat, lng]}
        zoom={6}
        style={{ width: "100vw", height: "100vh", position: "fixed", top: 0, left: 0 }}
      >
        <TileLayer
          url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
          attribution="Tiles © Esri"
        />
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="© OpenStreetMap contributors"
          opacity={0.4}
        />
        {selectMode && (
          <DrawPolygon
            onComplete={handleComplete}
            onPointAdded={() => showMessage("📍 Point added")}
          />
        )}
        {completedPolygon.length > 0 && (
          <>
            <Polygon positions={completedPolygon} color="cyan" fillOpacity={0.2} />
            {completedPolygon.map((point, index) => (
              <CircleMarker
                key={index}
                center={point}
                radius={5}
                color="white"
                fillColor="white"
                fillOpacity={1}
              />
            ))}
          </>
        )}
      </MapContainer>

      {selectMode && (
        <Box
          position="fixed"
          top={4}
          left="50%"
          transform="translateX(-50%)"
          zIndex={1000}
          bg="blackAlpha.700"
          color="white"
          px={4}
          py={2}
          borderRadius="md"
        >
          <Text fontSize="sm">Click to add points. Click the yellow point to close the shape.</Text>
        </Box>
      )}

      {message && (
        <Box
          position="fixed"
          bottom={8}
          left={4}
          zIndex={1000}
          bg="blackAlpha.700"
          color="white"
          px={4}
          py={2}
          borderRadius="md"
        >
          <Text fontSize="sm">{message}</Text>
        </Box>
      )}

      <Button
        position="fixed"
        top={20}
        left={4}
        zIndex={1000}
        colorScheme={selectMode ? "red" : "green"}
        onClick={() => setSelectMode(!selectMode)}
      >
        {selectMode ? "Cancel" : "Select Field"}
      </Button>

      <Button
        position="fixed"
        bottom={8}
        right={8}
        zIndex={1000}
        colorScheme="blue"
        onClick={onBack}
      >
        ← Back
      </Button>
    </>
  );
}

export default FieldMap;