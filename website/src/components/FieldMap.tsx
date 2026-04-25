import "leaflet/dist/leaflet.css";
import { MapContainer, TileLayer, Polygon, Polyline, CircleMarker, useMapEvents, useMap } from "react-leaflet";
import { useState } from "react";

interface Props {
  lat: number;
  lng: number;
  onBack: () => void;
}

function getColor(value: number): string {
  if (value <= 3) {
    const t = value / 3;
    const r = Math.round(0 + t * 0);
    const g = Math.round(100 + t * 50);
    const b = Math.round(255 - t * 100);
    return `rgb(${r},${g},${b})`;
  } else if (value <= 6) {
    const t = (value - 3) / 3;
    const r = Math.round(0 + t * 50);
    const g = Math.round(200 - t * 50);
    const b = Math.round(0);
    return `rgb(${r},${g},${b})`;
  } else if (value <= 9) {
    const t = (value - 6) / 3;
    const r = Math.round(255);
    const g = Math.round(255 - t * 100);
    const b = Math.round(0);
    return `rgb(${r},${g},${b})`;
  } else if (value <= 12) {
    const t = (value - 9) / 3;
    const r = Math.round(255);
    const g = Math.round(165 - t * 100);
    const b = Math.round(0);
    return `rgb(${r},${g},${b})`;
  } else {
    const t = (value - 12) / 3;
    const r = Math.round(255);
    const g = Math.round(0);
    const b = Math.round(0);
    return `rgb(${r},${g},${b})`;
  }
}

function calculateArea(points: any[]): number {
  let area = 0;
  const n = points.length;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    area += points[i].lat * points[j].lng;
    area -= points[j].lat * points[i].lng;
  }
  area = Math.abs(area) / 2;
  return Math.round(area * 111320 * 111320);
}

function DrawPolygon({ onComplete, onPointAdded }: { onComplete: (points: any[]) => void, onPointAdded: () => void }) {
  const [points, setPoints] = useState<any[]>([]);
  const map = useMap();

  useMapEvents({
    click(e) {
      const newPoint = e.latlng;
      const newPoints = [...points, newPoint];

      if (newPoints.length === 4) {
        onComplete(newPoints);
        setPoints([]);
        return;
      }

      setPoints(newPoints);
      onPointAdded();
    },
  });

  return (
    <>
      {points.map((point, index) => (
        <CircleMarker
          key={index}
          center={point}
          radius={index === 0 ? 5 : 3}
          color="white"
          fillColor="white"
          fillOpacity={0.9}
          weight={1}
        />
      ))}
      {points.length > 1 && <Polyline positions={points} color="white" weight={1.5} opacity={0.8} />}
      {points.length > 2 && <Polygon positions={points} color="white" fillOpacity={0.1} weight={1.5} />}
    </>
  );
}

function FieldMap({ lat, lng, onBack }: Props) {
  const [selectMode, setSelectMode] = useState(false);
  const [completedPolygon, setCompletedPolygon] = useState<any[]>([]);
  const [message, setMessage] = useState("");
  const [analysisResult, setAnalysisResult] = useState<number | null>(null);
  const [fieldArea, setFieldArea] = useState<number>(0);

  // saved fields state
  const [savedFields, setSavedFields] = useState<{name: string, points: any[]}[]>([]);
  const [showSavedFields, setShowSavedFields] = useState(false);

  const showMessage = (msg: string) => {
    setMessage(msg);
    setTimeout(() => setMessage(""), 2000);
  };

  const handleComplete = (points: any[]) => {
    const area = calculateArea(points);
    setFieldArea(area);
    setCompletedPolygon(points);
    setSelectMode(false);
    const randomET = Math.round(Math.random() * 15 * 10) / 10;
    setAnalysisResult(randomET);
    showMessage("Field analyzed");
  };

  const handleSendData = () => {
    showMessage("Data sent to government");
  };

  const handleNewSelection = () => {
    setCompletedPolygon([]);
    setAnalysisResult(null);
    setSelectMode(true);
  };

  // save field with name prompt
  const handleSaveField = () => {
    const name = prompt("Enter a name for this field:");
    if (name && name.trim() !== "") {
      setSavedFields([...savedFields, { name: name.trim(), points: completedPolygon }]);
      showMessage("Field saved!");
    }
  };

  // load a saved field and rerun analysis
  const handleLoadField = (field: {name: string, points: any[]}) => {
    const area = calculateArea(field.points);
    setFieldArea(area);
    setCompletedPolygon(field.points);
    setSelectMode(false);
    setShowSavedFields(false);
    const randomET = Math.round(Math.random() * 15 * 10) / 10;
    setAnalysisResult(randomET);
    showMessage(`Loaded: ${field.name}`);
  };

  const polygonColor = analysisResult !== null ? getColor(analysisResult) : "white";

  const getLabel = (value: number): string => {
    if (value <= 3) return "No irrigation needed";
    if (value <= 6) return "Low irrigation needed";
    if (value <= 9) return "Moderate irrigation needed";
    if (value <= 12) return "High irrigation needed";
    return "Urgent irrigation needed";
  };

  const btnBase: React.CSSProperties = {
    position: "fixed",
    zIndex: 1000,
    padding: "6px 14px",
    fontSize: "12px",
    fontWeight: 500,
    borderRadius: "6px",
    border: "1px solid rgba(255,255,255,0.2)",
    cursor: "pointer",
    backdropFilter: "blur(6px)",
    letterSpacing: "0.05em",
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
            onPointAdded={() => showMessage("Point added")}
          />
        )}
        {completedPolygon.length > 0 && (
          <>
            <Polygon
              positions={completedPolygon}
              color={polygonColor}
              fillColor={polygonColor}
              fillOpacity={0.4}
              weight={2}
            />
            {completedPolygon.map((point, index) => (
              <CircleMarker
                key={index}
                center={point}
                radius={3}
                color="white"
                fillColor="white"
                fillOpacity={0.9}
                weight={1}
              />
            ))}
          </>
        )}
      </MapContainer>

      {selectMode && (
        <div style={{
          position: "fixed",
          top: 12,
          left: "50%",
          transform: "translateX(-50%)",
          zIndex: 1000,
          background: "rgba(0,0,0,0.5)",
          color: "rgba(255,255,255,0.8)",
          padding: "6px 16px",
          borderRadius: "6px",
          fontSize: "12px",
          backdropFilter: "blur(6px)",
          letterSpacing: "0.03em",
        }}>
          Click 4 points to select your field
        </div>
      )}

      {message && (
        <div style={{
          position: "fixed",
          bottom: 40,
          left: 12,
          zIndex: 1000,
          background: "rgba(0,0,0,0.5)",
          color: "rgba(255,255,255,0.8)",
          padding: "5px 12px",
          borderRadius: "6px",
          fontSize: "11px",
          backdropFilter: "blur(6px)",
        }}>
          {message}
        </div>
      )}

      {/* Analysis Result Card */}
      {analysisResult !== null && (
        <div style={{
          position: "fixed",
          top: "50%",
          right: 16,
          transform: "translateY(-50%)",
          zIndex: 1000,
          background: "rgba(0,0,0,0.75)",
          backdropFilter: "blur(10px)",
          border: "1px solid rgba(255,255,255,0.15)",
          borderRadius: "12px",
          padding: "20px",
          width: "220px",
          color: "white",
          fontSize: "13px",
        }}>
          <p style={{ fontWeight: 600, fontSize: "14px", marginBottom: 12, letterSpacing: "0.05em" }}>
            Field Analysis
          </p>

          <div style={{ marginBottom: 8 }}>
            <span style={{ opacity: 0.6, fontSize: "11px" }}>TOTAL AREA</span>
            <p style={{ fontWeight: 500 }}>{fieldArea.toLocaleString()} m²</p>
          </div>

          <div style={{ marginBottom: 8 }}>
            <span style={{ opacity: 0.6, fontSize: "11px" }}>EVAPOTRANSPIRATION</span>
            <p style={{ fontWeight: 500 }}>{analysisResult} L/m²/day</p>
          </div>

          <div style={{ marginBottom: 16 }}>
            <span style={{ opacity: 0.6, fontSize: "11px" }}>TOTAL WATER NEEDED</span>
            <p style={{ fontWeight: 500 }}>{Math.round(analysisResult * fieldArea).toLocaleString()} L/day</p>
          </div>

          <div style={{
            padding: "8px 12px",
            borderRadius: "6px",
            background: polygonColor,
            color: "white",
            fontSize: "11px",
            fontWeight: 600,
            textAlign: "center",
            marginBottom: 16,
          }}>
            {getLabel(analysisResult)}
          </div>

          {/* Legend */}
          <div style={{ borderTop: "1px solid rgba(255,255,255,0.1)", paddingTop: 12, marginBottom: 16 }}>
            <p style={{ opacity: 0.6, fontSize: "11px", marginBottom: 8 }}>LEGEND</p>
            {[
              { label: "0–3 L/m²", color: "rgb(0,150,255)" },
              { label: "3–6 L/m²", color: "rgb(50,150,0)" },
              { label: "6–9 L/m²", color: "rgb(255,200,0)" },
              { label: "9–12 L/m²", color: "rgb(255,80,0)" },
              { label: "12–15 L/m²", color: "rgb(255,0,0)" },
            ].map((item) => (
              <div key={item.label} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <div style={{ width: 12, height: 12, borderRadius: 2, background: item.color, flexShrink: 0 }} />
                <span style={{ fontSize: "11px", opacity: 0.8 }}>{item.label}</span>
              </div>
            ))}
          </div>

          {/* Buttons */}
          <button
            onClick={handleSendData}
            style={{
              width: "100%",
              padding: "8px",
              borderRadius: "6px",
              border: "1px solid rgba(255,255,255,0.2)",
              background: "rgba(255,255,255,0.1)",
              color: "white",
              fontSize: "12px",
              cursor: "pointer",
              marginBottom: 8,
            }}
          >
            Send Data
          </button>

          {/* NEW: Save Field button */}
          <button
            onClick={handleSaveField}
            style={{
              width: "100%",
              padding: "8px",
              borderRadius: "6px",
              border: "1px solid rgba(255,255,255,0.2)",
              background: "rgba(255,255,255,0.05)",
              color: "rgba(255,255,255,0.7)",
              fontSize: "12px",
              cursor: "pointer",
              marginBottom: 8,
            }}
          >
            Save Field
          </button>

          <button
            onClick={handleNewSelection}
            style={{
              width: "100%",
              padding: "8px",
              borderRadius: "6px",
              border: "1px solid rgba(255,255,255,0.2)",
              background: "rgba(255,255,255,0.05)",
              color: "rgba(255,255,255,0.7)",
              fontSize: "12px",
              cursor: "pointer",
            }}
          >
            ⬡ New Selection
          </button>
        </div>
      )}

      {/* Select Field button */}
      <button
        style={{
          ...btnBase,
          top: 90,
          left: 8,
          background: selectMode ? "rgba(220,50,50,0.4)" : "rgba(255,255,255,0.1)",
          color: "white",
          display: analysisResult !== null ? "none" : "block",
        }}
        onClick={() => setSelectMode(!selectMode)}
      >
        {selectMode ? "✕ Cancel" : "⬡ Select Field"}
      </button>

      {/* NEW: Saved Fields dropdown toggle */}
      {savedFields.length > 0 && analysisResult === null && (
        <div style={{
          position: "fixed",
          top: 122,
          left: 8,
          zIndex: 1000,
        }}>
          <button
            style={{
              ...btnBase,
              position: "relative",
              background: "rgba(255,255,255,0.1)",
              color: "white",
            }}
            onClick={() => setShowSavedFields(!showSavedFields)}
          >
            Saved Fields
          </button>

          {/* NEW: Saved fields list */}
          {showSavedFields && (
            <div style={{
              marginTop: 4,
              background: "rgba(0,0,0,0.75)",
              backdropFilter: "blur(10px)",
              border: "1px solid rgba(255,255,255,0.15)",
              borderRadius: "6px",
              overflow: "hidden",
              minWidth: "140px",
            }}>
              {savedFields.map((field, index) => (
                <button
                  key={index}
                  onClick={() => handleLoadField(field)}
                  style={{
                    display: "block",
                    width: "100%",
                    padding: "8px 12px",
                    background: "transparent",
                    border: "none",
                    borderBottom: index < savedFields.length - 1 ? "1px solid rgba(255,255,255,0.1)" : "none",
                    color: "rgba(255,255,255,0.8)",
                    fontSize: "12px",
                    cursor: "pointer",
                    textAlign: "left",
                  }}
                >
                  {field.name}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <button
        style={{
          ...btnBase,
          bottom: 24,
          right: 12,
          background: "rgba(255,255,255,0.1)",
          color: "rgba(255,255,255,0.8)",
          display: analysisResult !== null ? "none" : "block",
        }}
        onClick={onBack}
      >
        ← Back
      </button>
    </>
  );
}

export default FieldMap;