import { Select, Box, Text } from "@chakra-ui/react";

const countries = [
  { name: "North Macedonia", lat: 41.6086, lng: 21.7453 },
  { name: "Serbia", lat: 44.0165, lng: 21.0059 },
  { name: "Greece", lat: 39.0742, lng: 21.8243 },
  { name: "Bulgaria", lat: 42.7339, lng: 25.4858 },
  { name: "Italy", lat: 41.8719, lng: 12.5674 },
  { name: "Spain", lat: 40.4637, lng: 3.7492 },
  { name: "France", lat: 46.2276, lng: 2.2137 },
  { name: "Germany", lat: 51.1657, lng: 10.4515 },
  { name: "Poland", lat: 51.9194, lng: 19.1451 },
  { name: "Romania", lat: 45.9432, lng: 24.9668 },
];

interface Props {
  onSelectCountry: (lat: number, lng: number) => void;
}

function CountryDropdown({ onSelectCountry }: Props) {
  return (
    <Box
      position="fixed"
      top={8}
      left="50%"
      transform="translateX(-50%)"
      zIndex={10}
      textAlign="center"
    >
      <Text
        color="white"
        fontSize="sm"
        mb={2}
        letterSpacing="widest"
        textTransform="uppercase"
        opacity={0.7}
      >
        Select your country
      </Text>
      <Select
        placeholder="-- Select country --"
        onChange={(e) => {
          const country = countries.find((c) => c.name === e.target.value);
          if (country) onSelectCountry(country.lat, country.lng);
        }}
        bg="whiteAlpha.100"
        color="white"
        border="1px solid"
        borderColor="whiteAlpha.300"
        width="280px"
        _hover={{ borderColor: "cyan.400" }}
        sx={{ option: { background: "#0d1420", color: "white" } }}
      >
        {countries.map((c) => (
          <option key={c.name} value={c.name}>
            {c.name}
          </option>
        ))}
      </Select>
    </Box>
  );
}

export default CountryDropdown;