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
  if (value === 0) return "rgba(255,255,255,0.3)";
  if (value <= 3) {
    const t = value / 3;
    return `rgb(0,${Math.round(100 + t * 50)},${Math.round(255 - t * 100)})`;
  } else if (value <= 6) {
    const t = (value - 3) / 3;
    return `rgb(${Math.round(t * 50)},${Math.round(200 - t * 50)},0)`;
  } else if (value <= 9) {
    const t = (value - 6) / 3;
    return `rgb(255,${Math.round(255 - t * 100)},0)`;
  } else if (value <= 12) {
    const t = (value - 9) / 3;
    return `rgb(255,${Math.round(165 - t * 100)},0)`;
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
    area += (toRad(points[j].lng) - toRad(points[i].lng)) *
      (2 + Math.sin(toRad(points[i].lat)) + Math.sin(toRad(points[j].lat)));
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

function calculateTotalWaterFromGrid(field: Field): number | null {
  if (!field.grid || field.grid.length === 0) return null;
  const rows = field.grid.length;
  const cols = field.grid[0].length;
  const cellArea = field.area / (rows * cols);
  let total = 0;
  let count = 0;
  for (const row of field.grid) {
    for (const val of row) {
      if (val !== null && val > 0) {
        total += val * cellArea;
        count++;
      }
    }
  }
  return count > 0 ? Math.round(total) : null;
}

function FlyToField({ points }: { points: any[] }) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 0) return;
    const lats = points.map((p: any) => p.lat);
    const lngs = points.map((p: any) => p.lng);
    map.fitBounds([[Math.min(...lats), Math.min(...lngs)], [Math.max(...lats), Math.max(...lngs)]], { padding: [60, 60] });
  }, [points]);
  return null;
}

function FlyToCountry({ center }: { center: [number, number] }) {
  const map = useMap();
  const isFirstRender = useRef(true);
  useEffect(() => {
    if (isFirstRender.current) { isFirstRender.current = false; return; }
    map.flyTo(center, 7, { duration: 1.5 });
  }, [center]);
  return null;
}

function DrawPolygon({ onComplete, onPointAdded }: { onComplete: (points: any[]) => void; onPointAdded: () => void }) {
  const [points, setPoints] = useState<any[]>([]);
  useMapEvents({
    click(e) {
      const newPoints = [...points, e.latlng];
      if (newPoints.length === 4) { onComplete(newPoints); setPoints([]); return; }
      setPoints(newPoints);
      onPointAdded();
    },
  });
  return (
    <>
      {points.map((point, i) => <CircleMarker key={i} center={point} radius={i === 0 ? 5 : 3} color="white" fillColor="white" fillOpacity={0.9} weight={1} />)}
      {points.length > 1 && <Polyline positions={points} color="white" weight={1.5} opacity={0.8} />}
      {points.length > 2 && <Polygon positions={points} color="white" fillOpacity={0.1} weight={1.5} />}
    </>
  );
}

function GridOverlay({ field, showGridLines, showCellColors }: {
  field: Field;
  showGridLines: boolean;
  showCellColors: boolean;
}) {
  const [hoveredCell, setHoveredCell] = useState<{ value: number; x: number; y: number } | null>(null);

  if (!field.grid || field.grid.length === 0) return null;

  const lats = field.points.map((p: any) => p.lat);
  const lngs = field.points.map((p: any) => p.lng);
  const minLat = Math.min(...lats), maxLat = Math.max(...lats);
  const minLng = Math.min(...lngs), maxLng = Math.max(...lngs);
  const rows = field.grid.length, cols = field.grid[0].length;

  function pointInPolygon(lat: number, lng: number, polygon: any[]): boolean {
    let inside = false;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      const xi = polygon[i].lng, yi = polygon[i].lat;
      const xj = polygon[j].lng, yj = polygon[j].lat;
      const intersect = ((yi > lat) !== (yj > lat)) &&
        (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi);
      if (intersect) inside = !inside;
    }
    return inside;
  }

  return (
    <>
      {field.grid.flatMap((row, r) =>
        row.map((value, c) => {
          const cellCenterLat = maxLat - ((r + 0.5) / rows) * (maxLat - minLat);
          const cellCenterLng = minLng + ((c + 0.5) / cols) * (maxLng - minLng);
          if (!pointInPolygon(cellCenterLat, cellCenterLng, field.points)) return null;

          return (
            <Rectangle
              key={`${r}-${c}`}
              bounds={[
                [maxLat - (r / rows) * (maxLat - minLat), minLng + (c / cols) * (maxLng - minLng)],
                [maxLat - ((r + 1) / rows) * (maxLat - minLat), minLng + ((c + 1) / cols) * (maxLng - minLng)],
              ]}
              pathOptions={{
                color: showGridLines ? "rgba(255,255,255,0.4)" : "transparent",
                weight: showGridLines ? 0.5 : 0,
                fillColor: showCellColors ? getColor(value) : "transparent",
                fillOpacity: showCellColors ? 0.65 : 0,
              }}
              eventHandlers={{
                mouseover: (e) => {
                  const { clientX, clientY } = e.originalEvent;
                  setHoveredCell({ value, x: clientX, y: clientY });
                },
                mousemove: (e) => {
                  const { clientX, clientY } = e.originalEvent;
                  setHoveredCell(prev => prev ? { ...prev, x: clientX, y: clientY } : null);
                },
                mouseout: () => setHoveredCell(null),
              }}
            />
          );
        })
      )}

      {hoveredCell && (
        <div style={{
          position: "fixed",
          left: hoveredCell.x + 12,
          top: hoveredCell.y - 28,
          zIndex: 2000,
          background: "rgba(0,0,0,0.75)",
          color: "white",
          padding: "4px 10px",
          borderRadius: "5px",
          fontSize: "11px",
          pointerEvents: "none",
          backdropFilter: "blur(6px)",
          border: "1px solid rgba(255,255,255,0.15)",
        }}>
          {hoveredCell.value.toFixed(2)} L/m²
        </div>
      )}
    </>
  );
}

function ZoomControlPortal() {
  const map = useMap();
  return (
    <div style={{ position: "absolute", top: 12, left: 12, zIndex: 1000 }}>
      {["+", "−"].map((sym, i) => (
        <button key={sym} onClick={() => i === 0 ? map.zoomIn() : map.zoomOut()} style={{
          display: "block", width: 36, height: 36,
          borderRadius: i === 0 ? "6px 6px 0 0" : "0 0 6px 6px",
          background: "rgba(0,0,0,0.65)", border: "1px solid rgba(255,255,255,0.2)",
          borderTop: i === 1 ? "none" : undefined,
          color: "white", fontSize: "20px", cursor: "pointer", lineHeight: "36px", textAlign: "center",
        }}>{sym}</button>
      ))}
    </div>
  );
}

function FieldMap({ lat, lng, onBack }: Props) {
  const [selectMode, setSelectMode] = useState(false);
  const [message, setMessage] = useState("");
  const [savedFields, setSavedFields] = useState<Field[]>([]);
  const [activeFieldIndex, setActiveFieldIndex] = useState<number | null>(null);
  const [mapCenter, setMapCenter] = useState<[number, number]>([lat, lng]);
  const [flyToPoints, setFlyToPoints] = useState<any[]>([]);
  const [isCalculating, setIsCalculating] = useState(false);
  const [plants, setPlants] = useState<string[]>([]);
  const [selectedPlantIndex, setSelectedPlantIndex] = useState<number | null>(null);
  const [showPlantPicker, setShowPlantPicker] = useState(false);
  const [cropSearch, setCropSearch] = useState("");
  const [showGridLines, setShowGridLines] = useState(false);
  const [showCellColors, setShowCellColors] = useState(false);

  const activeField = activeFieldIndex !== null ? savedFields[activeFieldIndex] : null;
  const filteredPlants = plants.filter(p => p.toLowerCase().includes(cropSearch.toLowerCase()));

  useEffect(() => {
    fetch("http://localhost:5000/api/crops")
      .then(res => res.json())
      .then(data => setPlants(data.crops))
      .catch(() => setPlants(["Wheat", "Barley", "Sunflower", "Potato", "Cabbage", "Carrot", "Lettuce", "Watermelon", "Strawberries"]));
  }, []);

  const showMessage = (msg: string) => { setMessage(msg); setTimeout(() => setMessage(""), 3000); };

  const handleComplete = (points: any[]) => {
    const area = calculateArea(points);
    setFlyToPoints(points);
    setSelectMode(false);
    const newField: Field = { name: null, points, area, et: 0, eto: null, grid: null, visible: true };
    const newFields = [...savedFields, newField];
    setSavedFields(newFields);
    setActiveFieldIndex(newFields.length - 1);
    showMessage("Field selected — choose a plant and calculate");
  };

  const handleCalculate = async () => {
    if (selectedPlantIndex === null) { showMessage("Please select a plant first"); return; }
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
      updated[activeFieldIndex] = { ...updated[activeFieldIndex], et: irrigation_avg, eto: ETo, grid: irrigation_grid };
      setSavedFields(updated);
      showMessage("Calculation complete!");
    } catch {
      showMessage("Error connecting to server");
    } finally {
      setIsCalculating(false);
    }
  };

  const handleDeleteField = (index: number, e: React.MouseEvent) => {
    e.stopPropagation();
    const updated = savedFields.filter((_, i) => i !== index);
    setSavedFields(updated);
    if (activeFieldIndex === index) { setActiveFieldIndex(null); setFlyToPoints([]); }
    else if (activeFieldIndex !== null && activeFieldIndex > index) setActiveFieldIndex(activeFieldIndex - 1);
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

  const toggleVisibility = (index: number, e: React.MouseEvent) => {
    e.stopPropagation();
    const updated = [...savedFields];
    updated[index].visible = !updated[index].visible;
    setSavedFields(updated);
  };

  const handleLoadField = (index: number) => {
    setActiveFieldIndex(index);
    setFlyToPoints(savedFields[index].points);
  };

  const handleCountryChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const country = countries.find(c => c.name === e.target.value);
    if (country) { setMapCenter([country.lat, country.lng]); setFlyToPoints([]); }
  };

  const inputStyle: React.CSSProperties = {
    width: "100%", padding: "7px 10px", borderRadius: "6px", boxSizing: "border-box",
    border: "1px solid rgba(255,255,255,0.15)", background: "rgba(255,255,255,0.05)",
    color: "white", fontSize: "11px", outline: "none",
  };

  const smallBtn: React.CSSProperties = {
    padding: "7px 10px", borderRadius: "7px",
    border: "1px solid rgba(255,255,255,0.15)", background: "rgba(255,255,255,0.05)",
    color: "rgba(255,255,255,0.7)", fontSize: "11px", cursor: "pointer", width: "100%",
  };

  return (
    <div style={{ display: "flex", width: "100vw", height: "100vh", background: "#0d1420", overflow: "hidden" }}>

      {/* LEFT SIDEBAR */}
      <div style={{
        width: 160, minWidth: 160, height: "100vh",
        background: "rgba(0,0,0,0.8)", backdropFilter: "blur(12px)",
        borderRight: "1px solid rgba(255,255,255,0.08)",
        display: "flex", flexDirection: "column", padding: "12px 10px",
        gap: 8, zIndex: 1000, boxSizing: "border-box",
      }}>
        <select onChange={handleCountryChange} style={{ ...inputStyle }}>
          <option value="">— Country —</option>
          {countries.map(c => <option key={c.name} value={c.name} style={{ background: "#0d1420" }}>{c.name}</option>)}
        </select>

        <button
          onClick={() => { setSelectMode(!selectMode); if (!selectMode) { setActiveFieldIndex(null); setFlyToPoints([]); } }}
          style={{
            ...smallBtn, textAlign: "center", fontWeight: 500,
            background: selectMode ? "rgba(220,50,50,0.3)" : "rgba(255,255,255,0.07)",
            border: selectMode ? "1px solid rgba(220,80,80,0.4)" : "1px solid rgba(255,255,255,0.15)",
            color: "white",
          }}
        >
          {selectMode ? "Cancel" : "Select Field"}
        </button>

        {selectMode && (
          <p style={{ color: "rgba(255,255,255,0.3)", fontSize: "10px", textAlign: "center", margin: 0 }}>
            Click 4 points on the map
          </p>
        )}

        {savedFields.length > 0 && (
          <>
            <p style={{ color: "rgba(255,255,255,0.3)", fontSize: "10px", letterSpacing: "0.1em", margin: "4px 0 0" }}>
              SAVED FIELDS
            </p>
            <div style={{ flex: 1, overflowY: "auto" }}>
              {savedFields.map((field, index) => (
                <div
                  key={index}
                  onClick={() => handleLoadField(index)}
                  style={{
                    display: "flex", alignItems: "center", gap: 5,
                    padding: "5px 6px", borderRadius: "6px", marginBottom: 3,
                    background: activeFieldIndex === index ? "rgba(255,255,255,0.1)" : "transparent",
                    cursor: "pointer",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={field.visible}
                    onChange={() => {}}
                    onClick={e => toggleVisibility(index, e)}
                    style={{ cursor: "pointer", accentColor: getColor(field.et || 5), flexShrink: 0 }}
                  />
                  <span style={{ color: "rgba(255,255,255,0.8)", fontSize: "11px", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {field.name ?? `Field ${index + 1}`}
                  </span>
                  <div style={{ width: 7, height: 7, borderRadius: "50%", flexShrink: 0, background: field.et > 0 ? getColor(field.et) : "rgba(255,255,255,0.2)" }} />
                  <button
                    onClick={e => handleDeleteField(index, e)}
                    style={{ background: "none", border: "none", color: "rgba(255,80,80,0.6)", cursor: "pointer", fontSize: "13px", padding: "0 1px", lineHeight: 1, flexShrink: 0 }}
                  >×</button>
                </div>
              ))}
            </div>
          </>
        )}

        <button onClick={onBack} style={{ ...smallBtn, textAlign: "center", marginTop: "auto" }}>← Back</button>
      </div>

      {/* MAP */}
      <div style={{ flex: 1, position: "relative" }}>
        <MapContainer center={mapCenter} zoom={7} zoomControl={false} style={{ width: "100%", height: "100%" }}>
          <TileLayer url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}" attribution="Tiles © Esri" />
          <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="© OpenStreetMap contributors" opacity={0.4} />
          <FlyToCountry center={mapCenter} />
          {flyToPoints.length > 0 && <FlyToField points={flyToPoints} />}
          {selectMode && <DrawPolygon onComplete={handleComplete} onPointAdded={() => showMessage("Point added")} />}
          {savedFields.map((field, index) =>
            field.visible ? (
              <Polygon
                key={index}
                positions={field.points}
                color={activeFieldIndex === index ? "white" : getColor(field.et)}
                fillColor={activeFieldIndex === index ? "white" : getColor(field.et)}
                fillOpacity={field.grid && showCellColors ? 0 : 0.35}
                weight={2}
                eventHandlers={{ click: () => handleLoadField(index) }}
              />
            ) : null
          )}
          {savedFields.map((field, index) =>
            field.visible && field.grid && (showGridLines || showCellColors) ? (
              <GridOverlay
                key={`grid-${index}`}
                field={field}
                showGridLines={showGridLines}
                showCellColors={showCellColors}
              />
            ) : null
          )}
          <ZoomControlPortal />
        </MapContainer>

        {message && (
          <div style={{
            position: "absolute", bottom: 24, left: "50%", transform: "translateX(-50%)",
            zIndex: 1000, background: "rgba(0,0,0,0.65)", color: "rgba(255,255,255,0.9)",
            padding: "6px 18px", borderRadius: "6px", fontSize: "12px", pointerEvents: "none",
          }}>
            {message}
          </div>
        )}
      </div>

      {/* RIGHT PANEL */}
      {activeField && (
        <div style={{
          width: 255, minWidth: 255, height: "100vh",
          background: "rgba(0,0,0,0.8)", backdropFilter: "blur(12px)",
          borderLeft: "1px solid rgba(255,255,255,0.08)",
          display: "flex", flexDirection: "column",
          zIndex: 1000, boxSizing: "border-box", overflow: "hidden",
        }}>
          {showPlantPicker ? (
            <div style={{ display: "flex", flexDirection: "column", height: "100%", padding: "14px 14px" }}>
              <button onClick={() => { setShowPlantPicker(false); setCropSearch(""); }} style={{
                background: "none", border: "none", color: "rgba(255,255,255,0.4)",
                fontSize: "11px", cursor: "pointer", marginBottom: 10, padding: 0, textAlign: "left",
              }}>← Back</button>

              <p style={{ color: "rgba(255,255,255,0.3)", fontSize: "10px", letterSpacing: "0.1em", marginBottom: 8 }}>SELECT PLANT</p>

              <input
                type="text"
                placeholder="Search crops..."
                value={cropSearch}
                onChange={e => setCropSearch(e.target.value)}
                style={{ ...inputStyle, marginBottom: 8 }}
                autoFocus
              />

              <div style={{ flex: 1, overflowY: "auto" }}>
                {filteredPlants.length === 0 && (
                  <p style={{ color: "rgba(255,255,255,0.3)", fontSize: "12px", textAlign: "center", marginTop: 20 }}>No crops found</p>
                )}
                {filteredPlants.map((plant) => {
                  const originalIndex = plants.indexOf(plant);
                  return (
                    <button
                      key={plant}
                      onClick={() => { setSelectedPlantIndex(originalIndex); setShowPlantPicker(false); setCropSearch(""); }}
                      style={{
                        width: "100%", padding: "9px 12px", marginBottom: 5,
                        borderRadius: "7px", border: "1px solid rgba(255,255,255,0.12)",
                        background: selectedPlantIndex === originalIndex ? "rgba(80,160,80,0.25)" : "rgba(255,255,255,0.05)",
                        color: "white", fontSize: "12px", cursor: "pointer", textAlign: "left",
                      }}
                    >
                      {selectedPlantIndex === originalIndex ? "✓  " : ""}{plant}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", height: "100%", padding: "14px 14px", overflowY: "auto" }}>

              <p style={{ fontWeight: 600, fontSize: "14px", color: "white", marginBottom: 1 }}>
                {activeField.name ?? `Field ${activeFieldIndex! + 1}`}
              </p>
              <p style={{ color: "rgba(255,255,255,0.3)", fontSize: "10px", marginBottom: 12 }}>Field Analysis</p>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 10px", marginBottom: 10 }}>
                {[
                  { label: "AREA", value: `${activeField.area.toLocaleString()} m²` },
                  { label: "ET₀", value: activeField.eto !== null ? `${activeField.eto} mm/d` : "—" },
                  { label: "IRRIGATION", value: activeField.et > 0 ? `${activeField.et} L/m²` : "—" },
                  {
                    label: "TOTAL WATER",
                    value: (() => {
                      const gridTotal = calculateTotalWaterFromGrid(activeField);
                      if (gridTotal !== null) return `${gridTotal.toLocaleString()} L`;
                      if (activeField.et > 0) return `${Math.round(activeField.et * activeField.area).toLocaleString()} L`;
                      return "—";
                    })()
                  },
                ].map(item => (
                  <div key={item.label} style={{ background: "rgba(255,255,255,0.04)", borderRadius: 6, padding: "7px 9px" }}>
                    <p style={{ color: "rgba(255,255,255,0.3)", fontSize: "9px", letterSpacing: "0.08em", marginBottom: 2 }}>{item.label}</p>
                    <p style={{ color: "white", fontWeight: 500, fontSize: "12px" }}>{item.value}</p>
                  </div>
                ))}
              </div>

              {activeField.et > 0 && (
                <div style={{
                  padding: "6px 10px", borderRadius: "6px", marginBottom: 10,
                  background: getColor(activeField.et), color: "white",
                  fontSize: "10px", fontWeight: 600, textAlign: "center",
                }}>
                  {getLabel(activeField.et)}
                </div>
              )}

              <div style={{ marginBottom: 10 }}>
                <p style={{ color: "rgba(255,255,255,0.3)", fontSize: "9px", letterSpacing: "0.08em", marginBottom: 5 }}>LEGEND</p>
                <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                  {[
                    { label: "0–3", color: "rgb(0,150,255)" },
                    { label: "3–6", color: "rgb(50,150,0)" },
                    { label: "6–9", color: "rgb(255,200,0)" },
                    { label: "9–12", color: "rgb(255,80,0)" },
                    { label: "12+", color: "rgb(255,0,0)" },
                  ].map(item => (
                    <div key={item.label} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <div style={{ width: 10, height: 10, borderRadius: 2, background: item.color }} />
                      <span style={{ fontSize: "10px", color: "rgba(255,255,255,0.55)" }}>{item.label}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div style={{ borderTop: "1px solid rgba(255,255,255,0.07)", marginBottom: 10 }} />

              <div
                onClick={() => setShowPlantPicker(true)}
                style={{
                  padding: "9px 12px", borderRadius: "8px", marginBottom: 8,
                  border: "1px solid rgba(255,255,255,0.15)", background: "rgba(255,255,255,0.05)",
                  cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center",
                }}
              >
                <div>
                  <p style={{ color: "rgba(255,255,255,0.3)", fontSize: "9px", letterSpacing: "0.08em", marginBottom: 2 }}>PLANT TYPE</p>
                  <p style={{ color: "white", fontSize: "12px" }}>
                    {selectedPlantIndex !== null ? plants[selectedPlantIndex] : "Select a plant →"}
                  </p>
                </div>
                <span style={{ color: "rgba(255,255,255,0.3)", fontSize: "16px" }}>›</span>
              </div>

              <button onClick={handleCalculate} disabled={isCalculating} style={{
                width: "100%", padding: "9px", borderRadius: "7px", marginBottom: 6,
                border: "1px solid rgba(80,200,80,0.3)",
                background: isCalculating ? "rgba(255,255,255,0.04)" : "rgba(60,140,60,0.35)",
                color: isCalculating ? "rgba(255,255,255,0.3)" : "white",
                fontSize: "12px", fontWeight: 600, cursor: isCalculating ? "not-allowed" : "pointer",
              }}>
                {isCalculating ? "Calculating..." : "Calculate"}
              </button>

              <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
                <button onClick={handleRenameField} style={{ ...smallBtn, flex: 1 }}>Rename</button>
                <button
                  onClick={() => { if (activeFieldIndex !== null) handleDeleteField(activeFieldIndex, { stopPropagation: () => {} } as any); }}
                  style={{ ...smallBtn, flex: 1, color: "rgba(255,100,100,0.8)", border: "1px solid rgba(255,80,80,0.2)" }}
                >
                  Delete
                </button>
              </div>

              <button onClick={() => setActiveFieldIndex(null)} style={{ ...smallBtn, textAlign: "center" }}>Close</button>

              {/* Grid toggles — only show when grid data exists */}
              {activeField.grid && (
                <div style={{ marginTop: 10, borderTop: "1px solid rgba(255,255,255,0.07)", paddingTop: 10 }}>
                  <label style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={showGridLines}
                      onChange={() => setShowGridLines(!showGridLines)}
                      style={{ cursor: "pointer" }}
                    />
                    <span style={{ color: "rgba(255,255,255,0.6)", fontSize: "11px" }}>Show grid lines</span>
                  </label>
                  <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={showCellColors}
                      onChange={() => setShowCellColors(!showCellColors)}
                      style={{ cursor: "pointer" }}
                    />
                    <span style={{ color: "rgba(255,255,255,0.6)", fontSize: "11px" }}>Show cell colors</span>
                  </label>
                </div>
              )}

              <p style={{ color: "rgba(255,255,255,0.2)", fontSize: "9px", textAlign: "center", marginTop: "auto", paddingTop: 10 }}>
                Legend values in L/m²/day
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default FieldMap;