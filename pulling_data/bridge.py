from flask import Flask, request, jsonify
from pull import bbox_from_coordinates
from flask_cors import CORS


app = Flask(__name__)
CORS(app)

# Mapping for crop types to numbers (if needed for your existing function)
crop_mapping = {
    "Cabbage": [0.7, 1.05, 0.95],
    "Carrot": [0.7, 1.05, 0.95],
    "Lettuce": [0.7, 1.00, 0.95],
    "Watermelon": [0.4, 1.00, 0.75],
    "Potato": [0.5, 1.15, 0.75],
    "Strawberries": [0.40, 0.85, 0.75],
    "Sunflower": [0.35, 1.15, 2.0],
    "Barley": [0.3, 1.15, 0.25],
    "Wheat": [0.3, 1.15, 0.35]
}


# NEW ENDPOINT: Send crop list to frontend
@app.route('/api/crops', methods=['GET'])
def get_crops():
    """Return the list of available crops for the dropdown"""
    crop_list = list(crop_mapping.keys())
    return jsonify({
        'status': 'success',
        'crops': crop_list
    })


@app.route('/api/calculate', methods=['POST'])
def calculate():
    data = request.get_json()
    coordinates = data.get('coordinates')
    crop_index = data.get('crop_index')  # Frontend sends index (0, 1, 2, etc.)

    # Get crop name from index
    crop_list = list(crop_mapping.keys())
    crop_string = crop_list[crop_index]


    # Get the values for this crop
    crop_values = crop_mapping[crop_string]

    # Rest of your calculation logic...
    results = return_data(coordinates, crop_values)

    return jsonify({
        'status': 'success',
        'crop': crop_string,
        'crop_index': crop_index,
        'crop_values': crop_values,
        'results': results
    })


if __name__ == '__main__':
    app.run(debug=True, port=5000)