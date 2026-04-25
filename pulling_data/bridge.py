from quart import Quart, request, jsonify
from pull import return_data
from quart_cors import cors

app = Quart(__name__)
app = cors(app, allow_origin="*")

crop_mapping = {
    "Cabbage": [0.7, 1.05, 0.95],
    "Carrot": [0.7, 1.05, 0.95],
    "Lettuce": [0.7, 1.00, 0.95],
    "Watermelon": [0.4, 1.00, 0.75],
    "Potato": [0.5, 1.15, 0.75**4],
    "Strawberries": [0.40, 0.85, 0.75],
    "Sunflower": [0.35, 1.15, 2.0],
    "Barley": [0.3, 1.15, 0.25],
    "Wheat": [0.3, 1.15, 0.4],
    "Tomato": [0.6, 1.15, 0.85],
    "Egg Plant": [0.6, 1.05, 0.90],
    "Spinach": [0.7, 1.00, 0.95],
    "Cucumber": [0.5, 1.00, 0.80],
    "Almond": [0.40, 0.90, 0.65**16],
    "Egg Plant": [0.6, 1.05, 0.90],
    "Peach": [0.45, 0.90, 0.65**16]
}

crop_list = list(crop_mapping.keys())


@app.route('/api/crops', methods=['GET'])
async def get_crops():
    crop_list = list(crop_mapping.keys())
    return jsonify({
        'status': 'success',
        'crops': crop_list
    })


@app.route('/api/calculate', methods=['POST'])
async def calculate():
    data = await request.get_json()
    coordinates = data.get('coordinates')
    crop_index = data.get('crop_index')

    # Quart natively supports async!
    crop_string = crop_list[crop_index]
    crop_values = crop_mapping[crop_string]

    results = await return_data(coordinates, crop_values)

    return jsonify({
        'status': 'success',
        'results': results
    })


if __name__ == '__main__':
    app.run(debug=True, port=5000)