import openeo

connection = openeo.connect("https://openeo.dataspace.copernicus.eu")
connection.authenticate_oidc()

bbox = {
    "west": 21.3,
    "south": 41.9,
    "east": 21.6,
    "north": 42.1
}

temporal_extent = ["2023-06-01", "2023-06-10"]

cube = connection.load_collection(
    "SENTINEL2_L2A",
    spatial_extent=bbox,
    temporal_extent=temporal_extent,
    bands=["B02", "B03", "B04", "B8A", "B11", "B12", "SCL"]
)

# само ако сакаш една слика:
cube = cube.reduce_dimension("t", "median")

job = cube.execute_batch("sentinel.tif")