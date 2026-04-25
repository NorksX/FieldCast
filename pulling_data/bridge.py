import asyncio
from quart import Quart, request, jsonify
from pull import return_data
from quart_cors import cors

app = Quart(__name__)
app = cors(app, allow_origin="*")

crop_mapping = {
    "Cabbage":      [0.7,  1.05, 0.95],
    "Carrot":       [0.7,  1.05, 0.95],
    "Lettuce":      [0.7,  1.00, 0.95],
    "Watermelon":   [0.4,  1.00, 0.75],
    "Potato":       [0.5,  1.15, 0.75],
    "Strawberries": [0.40, 0.85, 0.75],
    "Sunflower":    [0.35, 1.15, 2.0],
    "Barley":       [0.3,  1.15, 0.25],
    "Wheat":        [0.3,  1.15, 0.35],
}


@app.route('/api/crops', methods=['GET'])
def get_crops():
    return jsonify({
        'status': 'success',
        'crops': list(crop_mapping.keys()),
    })


@app.route('/api/calculate', methods=['POST'])
async def calculate():
    data = await request.get_json()

    coordinates = data.get('coordinates')
    crop_index  = data.get('crop_index')

    crop_list   = list(crop_mapping.keys())
    crop_name   = crop_list[crop_index]
    crop_values = crop_mapping[crop_name]

    results = await asyncio.to_thread(
        return_data,
        coordinates,
        crop_values,
        crop_name,
    )

    warnings = results.get('data_quality', {}).get('warnings', [])

    # Print every warning to the Quart console as it happens
    for w in warnings:
        app.logger.warning('[irrigation] %s', w)

    return jsonify({
        'status':   'success',
        'warnings': warnings,          # top-level so the frontend sees them immediately
        'results':  results,           # full payload including data_quality still intact
    })


if __name__ == '__main__':
    app.run(debug=True, port=5000)