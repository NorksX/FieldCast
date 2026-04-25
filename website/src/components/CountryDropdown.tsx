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

interface Props {
  onSelectCountry: (lat: number, lng: number) => void;
}

function CountryDropdown({ onSelectCountry }: Props) {
  return (
    <div style={{
      position: "fixed",
      top: 32,
      left: "50%",
      transform: "translateX(-50%)",
      zIndex: 10,
      textAlign: "center"
    }}>
      <p style={{
        color: "white",
        fontSize: "12px",
        marginBottom: 8,
        letterSpacing: "0.1em",
        textTransform: "uppercase",
        opacity: 0.7
      }}>
        Select your country
      </p>
      <select
        onChange={(e) => {
          const country = countries.find((c) => c.name === e.target.value);
          if (country) onSelectCountry(country.lat, country.lng);
        }}
        style={{
          background: "rgba(255,255,255,0.1)",
          color: "white",
          border: "1px solid rgba(255,255,255,0.3)",
          width: "280px",
          padding: "8px 12px",
          borderRadius: "6px",
          fontSize: "14px",
          cursor: "pointer"
        }}
      >
        <option value="">-- Select country --</option>
        {countries.map((c) => (
          <option key={c.name} value={c.name} style={{ background: "#0d1420" }}>
            {c.name}
          </option>
        ))}
      </select>
    </div>
  );
}

export default CountryDropdown;