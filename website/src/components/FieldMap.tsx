import "leaflet/dist/leaflet.css";
import { MapContainer, TileLayer, Polygon, Polyline, Rectangle, CircleMarker, useMapEvents, useMap } from "react-leaflet";
import { useState, useEffect, useRef } from "react";

interface Props {
  lat: number;
  lng: number;
  onBack: () => void;
}

interface Field {
  name: string | null;
  points: any[];
  area: number;
  et: number;
  eto: number | null;
  grid: number[][] | null;
  visible: boolean;
}

const countries = [
  { name: "Austria", lat: 47.5162, lng: 14.5501 },
  { name: "Bulgaria", lat: 42.7339, lng: 25.4858 },
  { name: "Hungary", lat: 47.1625, lng: 19.5033 },
  { name: "Italy", lat: 41.8719, lng: 12.5674 },
  { name: "Netherlands", lat: 52.1326, lng: 5.2913 },
  { name: "North Macedonia", lat: 41.6086, lng: 21.7453 },
  { name: "Norway", lat: 60.4720, lng: 8.4689 },
  { name: "Poland", lat: 51.9194, lng: 19.1451 },
  { name: "Romania", lat: 45.9432, lng: 24.9668 },
  { name: "Spain", lat: 40.4637, lng: 3.7492 },
];

function getColor(value: number): string {
  if (value <= 3) {
    const t = value / 3;
    const g = Math.round(100 + t * 50);
    const b = Math.round(255 - t * 100);
    return `rgb(0,${g},${b})`;
  } else if (value <= 6) {
    const t = (value - 3) / 3;
    const r = Math.round(t * 50);
    const g = Math.round(200 - t * 50);
    return `rgb(${r},${g},0)`;
  } else if (value <= 9) {
    const t = (value - 6) / 3;
    const g = Math.round(255 - t * 100);
    return `rgb(255,${g},0)`;
  } else if (value <= 12) {
    const t = (value - 9) / 3;
    const g = Math.round(165 - t * 100);
    return `rgb(255,${g},0)`;
  } else {
    return `rgb(255,0,0)`;
  }
}

function calculateArea(points: any[]): number {
  const toRad = (deg: number) => deg * Math.PI / 180;
  const R = 6371000;
  let area = 0;
  const n = points.length;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    const lat1 = toRad(points[i].lat);
    const lat2 = toRad(points[j].lat);
    const lng1 = toRad(points[i].lng);
    const lng2 = toRad(points[j].lng);
    area += (lng2 - lng1) * (2 + Math.sin(lat1) + Math.sin(lat2));
  }
  return Math.round(Math.abs(area * R * R / 2));
}

function getLabel(value: number): string {
  if (value <= 3) return "No irrigation needed";
  if (value <= 6) return "Low irrigation needed";
  if (value <= 9) return "Moderate irrigation needed";
  if (value <= 12) return "High irrigation needed";
  return "Urgent irrigation needed";
}

function FlyToField({ points }: { points: any[] }) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 0) return;
    const lats = points.map((p: any) => p.lat);
    const lngs = points.map((p: any) => p.lng);
    const bounds: [[number, number], [number, number]] = [
      [Math.min(...lats), Math.min(...lngs)],
      [Math.max(...lats), Math.max(...lngs)],
    ];
    map.fitBounds(bounds, { padding: [60, 60] });
  }, [points]);
  return null;
}

function FlyToCountry({ center }: { center: [number, number] }) {
  const map = useMap();
  const isFirstRender = useRef(true);

  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    map.flyTo(center, 7, { duration: 1.5 });
  }, [center]);
  return null;
}

function DrawPolygon({ onComplete, onPointAdded }: { onComplete: (points: any[]) => void, onPointAdded: () => void }) {
  const [points, setPoints] = useState<any[]>([]);

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

function GridOverlay({ field }: { field: Field }) {
  if (!field.grid || field.grid.length === 0) return null;

  const lats = field.points.map((p: any) => p.lat);
  const lngs = field.points.map((p: any) => p.lng);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs);
  const maxLng = Math.max(...lngs);

  const rows = field.grid.length;
  const cols = field.grid[0].length;

  const cells: JSX.Element[] = [];

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const value = field.grid[r][c];
      const cellLat = maxLat - (r / rows) * (maxLat - minLat);
      const cellLng = minLng + (c / cols) * (maxLng - minLng);
      const nextLat = maxLat - ((r + 1) / rows) * (maxLat - minLat);
      const nextLng = minLng + ((c + 1) / cols) * (maxLng - minLng);

      cells.push(
        <Rectangle
          key={`${r}-${c}`}
          bounds={[[cellLat, cellLng], [nextLat, nextLng]]}
          pathOptions={{
            color: "transparent",
            fillColor: getColor(value),
            fillOpacity: 0.65,
            weight: 0,
          }}
        />
      );
    }
  }

  return <>{cells}</>;
}

function FieldMap({ lat, lng, onBack }: Props) {
  const [selectMode, setSelectMode] = useState(false);
  const [message, setMessage] = useState("");
  const [savedFields, setSavedFields] = useState<Field[]>([]);
  const [activeFieldIndex, setActiveFieldIndex] = useState<number | null>(null);
  const [showTools, setShowTools] = useState(false);
  const [mapCenter, setMapCenter] = useState<[number, number]>([lat, lng]);
  const [flyToPoints, setFlyToPoints] = useState<any[]>([]);
  const [isCalculating, setIsCalculating] = useState(false);
  const [plants] = useState<string[]>([
    "Wheat", "Corn", "Sunflower", "Barley",
    "Soybean", "Potato", "Tomato", "Grape",
  ]);
  const [selectedPlantIndex, setSelectedPlantIndex] = useState<number | null>(null);

  const activeField = activeFieldIndex !== null ? savedFields[activeFieldIndex] : null;

  const showMessage = (msg: string) => {
    setMessage(msg);
    setTimeout(() => setMessage(""), 3000);
  };

  const handleComplete = (points: any[]) => {
    const area = calculateArea(points);
    setFlyToPoints(points);
    setSelectMode(false);

    const newField: Field = {
      name: null,
      points,
      area,
      et: 0,
      eto: null,
      grid: null,
      visible: true,
    };

    const newFields = [...savedFields, newField];
    setSavedFields(newFields);
    setActiveFieldIndex(newFields.length - 1);
    showMessage("Field selected — choose a plant and click Calculate");
  };

  const handleCalculate = async () => {
    if (selectedPlantIndex === null) {
      showMessage("Please select a plant first");
      return;
    }
    if (activeFieldIndex === null || !activeField) return;

    setIsCalculating(true);
    showMessage("Calculating...");

    try {
      const response = await fetch("http://localhost:5000/api/calculate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          coordinates: activeField.points.map((p: any) => ({ lat: p.lat, lng: p.lng })),
          crop_index: selectedPlantIndex,
        }),
      });

      const data = await response.json();
      const { ETo, irrigation_avg, irrigation_grid } = data.results;

      const updated = [...savedFields];
      updated[activeFieldIndex] = {
        ...updated[activeFieldIndex],
        et: irrigation_avg,
        eto: ETo,
        grid: irrigation_grid,
      };
      setSavedFields(updated);
      showMessage("Calculation complete!");
    } catch (e) {
      showMessage("Error connecting to server");
    } finally {
      setIsCalculating(false);
    }
  };

  const handleNewSelection = () => {
    setActiveFieldIndex(null);
    setFlyToPoints([]);
    setSelectMode(true);
    setShowTools(false);
  };

  const handleRenameField = () => {
    if (activeFieldIndex === null) return;
    const name = prompt("Enter a name for this field:");
    if (name && name.trim() !== "") {
      const updated = [...savedFields];
      updated[activeFieldIndex].name = name.trim();
      setSavedFields(updated);
    }
  };

  const toggleVisibility = (index: number) => {
    const updated = [...savedFields];
    updated[index].visible = !updated[index].visible;
    setSavedFields(updated);
  };

  const handleLoadField = (index: number) => {
    setActiveFieldIndex(index);
    setFlyToPoints(savedFields[index].points);
    setShowTools(false);
  };

  const handleCountryChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const country = countries.find(c => c.name === e.target.value);
    if (country) {
      setMapCenter([country.lat, country.lng]);
      setFlyToPoints([]);
    }
  };

  const btnStyle: React.CSSProperties = {
    width: "100%",
    padding: "8px",
    borderRadius: "6px",
    border: "1px solid rgba(255,255,255,0.2)",
    background: "rgba(255,255,255,0.05)",
    color: "rgba(255,255,255,0.7)",
    fontSize: "12px",
    cursor: "pointer",
    marginBottom: 8,
  };

  return (
    <>
      <MapContainer
        center={mapCenter}
        zoom={7}
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
        <FlyToCountry center={mapCenter} />
        {flyToPoints.length > 0 && <FlyToField points={flyToPoints} />}
        {selectMode && (
          <DrawPolygon
            onComplete={handleComplete}
            onPointAdded={() => showMessage("Point added")}
          />
        )}

        {/* Field polygons */}
        {savedFields.map((field, index) =>
          field.visible ? (
            <Polygon
              key={index}
              positions={field.points}
              color={getColor(field.et)}
              fillColor={getColor(field.et)}
              fillOpacity={field.grid ? 0 : 0.4}
              weight={2}
              eventHandlers={{ click: () => handleLoadField(index) }}
            />
          ) : null
        )}

        {/* Grid overlays */}
        {savedFields.map((field, index) =>
          field.visible && field.grid ? (
            <GridOverlay key={`grid-${index}`} field={field} />
          ) : null
        )}
      </MapContainer>

      {/* Country selector */}
      <div style={{ position: "fixed", top: 12, left: "50%", transform: "translateX(-50%)", zIndex: 1000 }}>
        <select
          onChange={handleCountryChange}
          style={{
            background: "rgba(0,0,0,0.6)",
            color: "white",
            border: "1px solid rgba(255,255,255,0.2)",
            width: "200px",
            padding: "6px 12px",
            borderRadius: "6px",
            fontSize: "12px",
            cursor: "pointer",
          }}
        >
          <option value="">-- Go to country --</option>
          {countries.map((c) => (
            <option key={c.name} value={c.name} style={{ background: "#0d1420" }}>{c.name}</option>
          ))}
        </select>
      </div>

      {selectMode && (
        <div style={{
          position: "fixed", top: 50, left: "50%", transform: "translateX(-50%)",
          zIndex: 1000, background: "rgba(0,0,0,0.5)", color: "rgba(255,255,255,0.8)",
          padding: "6px 16px", borderRadius: "6px", fontSize: "12px",
        }}>
          Click 4 points to select your field
        </div>
      )}

      {message && (
        <div style={{
          position: "fixed", bottom: 40, left: 12, zIndex: 1000,
          background: "rgba(0,0,0,0.5)", color: "rgba(255,255,255,0.8)",
          padding: "5px 12px", borderRadius: "6px", fontSize: "11px",
        }}>
          {message}
        </div>
      )}

      {/* Tools dropdown - shifts left when details card is open */}
      <div style={{
        position: "fixed",
        top: 12,
        right: activeField ? "252px" : "12px",
        zIndex: 1000,
        transition: "right 0.2s ease",
      }}>
        <button
          style={{
            padding: "6px 14px", fontSize: "12px", fontWeight: 500,
            borderRadius: "6px", border: "1px solid rgba(255,255,255,0.2)",
            cursor: "pointer", background: "rgba(255,255,255,0.1)", color: "white",
          }}
          onClick={() => setShowTools(!showTools)}
        >
          Tools
        </button>

        {showTools && (
          <div style={{
            position: "absolute", top: 36, right: 0,
            background: "rgba(0,0,0,0.85)", backdropFilter: "blur(10px)",
            border: "1px solid rgba(255,255,255,0.15)", borderRadius: "8px",
            padding: "8px", minWidth: "180px",
          }}>
            <button
              onClick={handleNewSelection}
              style={{
                ...btnStyle,
                background: selectMode ? "rgba(220,50,50,0.4)" : "rgba(255,255,255,0.1)",
                color: "white",
              }}
            >
              {selectMode ? "Cancel Selection" : "Select Field"}
            </button>

            {savedFields.length > 0 && (
              <>
                <div style={{
                  borderTop: "1px solid rgba(255,255,255,0.1)",
                  paddingTop: 8, marginTop: 4,
                  color: "rgba(255,255,255,0.5)", fontSize: "11px",
                  marginBottom: 6,
                }}>
                  SAVED FIELDS
                </div>
                {savedFields.map((field, index) => (
                  <div
                    key={index}
                    style={{
                      display: "flex", alignItems: "center", gap: 8,
                      padding: "6px 8px", borderRadius: "4px",
                      background: activeFieldIndex === index ? "rgba(255,255,255,0.15)" : "transparent",
                      marginBottom: 2,
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={field.visible}
                      onChange={() => toggleVisibility(index)}
                      style={{ cursor: "pointer", accentColor: getColor(field.et) }}
                    />
                    <span
                      onClick={() => handleLoadField(index)}
                      style={{
                        color: "rgba(255,255,255,0.8)", fontSize: "12px",
                        flex: 1, cursor: "pointer",
                      }}
                    >
                      {field.name ?? `Field ${index + 1}`}
                    </span>
                    <div style={{
                      width: 8, height: 8, borderRadius: "50%",
                      background: field.et > 0 ? getColor(field.et) : "rgba(255,255,255,0.3)",
                      flexShrink: 0,
                    }} />
                  </div>
                ))}
              </>
            )}
          </div>
        )}
      </div>

      {/* Analysis Result Card */}
      {activeField && (
        <div style={{
          position: "fixed", top: "50%", right: 16,
          transform: "translateY(-50%)", zIndex: 999,
          background: "rgba(0,0,0,0.75)", backdropFilter: "blur(10px)",
          border: "1px solid rgba(255,255,255,0.15)", borderRadius: "12px",
          padding: "20px", width: "220px", color: "white", fontSize: "13px",
          maxHeight: "90vh", overflowY: "auto",
        }}>
          <p style={{ fontWeight: 600, fontSize: "14px", marginBottom: 4, letterSpacing: "0.05em" }}>
            {activeField.name ?? `Field ${activeFieldIndex! + 1}`}
          </p>
          <p style={{ opacity: 0.5, fontSize: "11px", marginBottom: 12 }}>Field Analysis</p>

          <div style={{ marginBottom: 8 }}>
            <span style={{ opacity: 0.6, fontSize: "11px" }}>TOTAL AREA</span>
            <p style={{ fontWeight: 500 }}>{activeField.area.toLocaleString()} m²</p>
          </div>

          <div style={{ marginBottom: 8 }}>
            <span style={{ opacity: 0.6, fontSize: "11px" }}>REFERENCE ET₀</span>
            <p style={{ fontWeight: 500 }}>
              {activeField.eto !== null ? `${activeField.eto} mm/day` : "—"}
            </p>
          </div>

          <div style={{ marginBottom: 8 }}>
            <span style={{ opacity: 0.6, fontSize: "11px" }}>IRRIGATION NEEDED</span>
            <p style={{ fontWeight: 500 }}>
              {activeField.et > 0 ? `${activeField.et} L/m²/day` : "—"}
            </p>
          </div>

          <div style={{ marginBottom: 16 }}>
            <span style={{ opacity: 0.6, fontSize: "11px" }}>TOTAL WATER NEEDED</span>
            <p style={{ fontWeight: 500 }}>
              {activeField.et > 0
                ? `${Math.round(activeField.et * activeField.area).toLocaleString()} L/day`
                : "—"}
            </p>
          </div>

          {activeField.et > 0 && (
            <div style={{
              padding: "8px 12px", borderRadius: "6px",
              background: getColor(activeField.et), color: "white",
              fontSize: "11px", fontWeight: 600, textAlign: "center", marginBottom: 16,
            }}>
              {getLabel(activeField.et)}
            </div>
          )}

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

          {/* Plant selector */}
          <div style={{ marginBottom: 16 }}>
            <span style={{ opacity: 0.6, fontSize: "11px" }}>PLANT TYPE</span>
            <select
              value={selectedPlantIndex ?? ""}
              onChange={(e) => setSelectedPlantIndex(Number(e.target.value))}
              style={{
                display: "block", width: "100%", marginTop: 4,
                padding: "6px 8px", borderRadius: "6px",
                border: "1px solid rgba(255,255,255,0.2)",
                background: "rgba(255,255,255,0.05)", color: "white",
                fontSize: "12px", cursor: "pointer",
              }}
            >
              <option value="">-- Select plant --</option>
              {plants.map((plant, index) => (
                <option key={index} value={index} style={{ background: "#0d1420" }}>
                  {plant}
                </option>
              ))}
            </select>
          </div>

          <button
            onClick={handleCalculate}
            disabled={isCalculating}
            style={{
              ...btnStyle,
              background: isCalculating ? "rgba(255,255,255,0.05)" : "rgba(80,160,80,0.3)",
              color: isCalculating ? "rgba(255,255,255,0.4)" : "white",
              border: "1px solid rgba(80,200,80,0.3)",
              cursor: isCalculating ? "not-allowed" : "pointer",
            }}
          >
            {isCalculating ? "Calculating..." : "Calculate"}
          </button>

          <button onClick={handleRenameField} style={btnStyle}>
            Name Field
          </button>

          <button onClick={() => setActiveFieldIndex(null)} style={btnStyle}>
            Close
          </button>
        </div>
      )}

      <button
        style={{
          position: "fixed", bottom: 24, right: 12, zIndex: 1000,
          padding: "6px 14px", fontSize: "12px", fontWeight: 500,
          borderRadius: "6px", border: "1px solid rgba(255,255,255,0.2)",
          cursor: "pointer", background: "rgba(255,255,255,0.1)",
          color: "rgba(255,255,255,0.8)",
        }}
        onClick={onBack}
      >
        Back
      </button>
    </>
  );
}

export default FieldMap;
