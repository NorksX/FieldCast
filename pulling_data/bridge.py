import asyncio
from quart import Quart, request, jsonify
from pull import return_data
from quart_cors import cors
import csv
import os
from datetime import datetime
import uuid

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
    "Peach": [0.45, 0.90, 0.65**16]
}

crop_list = list(crop_mapping.keys())
#-------------------------------------------------------------------
# CSV фајлови
MAIN_FIELD_LOG = 'main_field_log.csv'  # за целата нива
SUB_PARCELS_LOG = 'sub_parcels_log.csv'  # за парцелите


# Иницијализација на CSV фајловите
def init_csv_files():
    # Главен фајл за целата нива
    if not os.path.exists(MAIN_FIELD_LOG):
        with open(MAIN_FIELD_LOG, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow([
                'fieldID', 'datum', 'kolicina_voda_l', 'tip_rastenie'
            ])

    # Фајл за парцелите
    if not os.path.exists(SUB_PARCELS_LOG):
        with open(SUB_PARCELS_LOG, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow([
                'fieldID', 'coordinates', 'potrebna_voda_l'
            ])


@app.route('/api/getIsWatered', methods=['POST'])
async def getIsWatered():
    data = await request.get_json()

    # Од frontend добивам само:
    kolicina_voda_l = data.get('kolicina_voda_l')  # колку литри е наводнето
    tip_rastenie = data.get('tip_rastenie')  # тип на растение
    parcels = data.get('parcels', [])  # листа на парцели со longitude, latitude, potrebna_voda_l

    # Валидација на задолжителните полиња од frontend
    if kolicina_voda_l is None or not tip_rastenie:
        return jsonify({
            'status': 'error',
            'message': 'Недостасуваат податоци: kolicina_voda_l или tip_rastenie'
        }), 400

    # Генерирање на уникатен fieldID
    field_id = str(uuid.uuid4())

    # Генерирање на тековен датум и време
    datum = datetime.now().strftime('%d-%m-%Y %H:%M:%S')

    # Проверка на типот на растение (опционално)
    if tip_rastenie not in crop_mapping:
        return jsonify({
            'status': 'error',
            'message': f'Непознат тип на растение: {tip_rastenie}'
        }), 400

    # Иницијализација на CSV фајловите
    init_csv_files()

    # 1. ЗАПИШИ ВО ГЛАВНИОТ CSV (цела нива)
    with open(MAIN_FIELD_LOG, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow([
            field_id,
            datum,
            kolicina_voda_l,
            tip_rastenie
        ])

    # 2. ЗАПИШИ ВО CSV ЗА ПАРЦЕЛИТЕ
    parcel_results = []
    total_water_needed = 0

    for parcel in parcels:
        # longitude = parcel.get('longitude')
        # latitude = parcel.get('latitude')
        coordinates = parcel.get('coordinates')
        potrebna_voda_l_parcel = parcel.get('potrebna_voda_l')  # колку литри му треба на парцелата

        # Валидација на податоци за парцелата
        if None in [coordinates, potrebna_voda_l_parcel]:
            continue

        total_water_needed += potrebna_voda_l_parcel

        # Запис во CSV за парцелата
        with open(SUB_PARCELS_LOG, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow([
                field_id,
                coordinates,
                potrebna_voda_l_parcel,
                datetime.now().isoformat()
            ])

        parcel_results.append({
            'coordinates': coordinates,
            # 'longitude': longitude,
            # 'latitude': latitude,
            'potrebna_voda_l': potrebna_voda_l_parcel
        })

    # Проверка дали наводнетата вода е доволна за сите парцели
    # is_watered = kolicina_voda_l >= total_water_needed

    return jsonify({
        'status': 'success',
        'fieldID': field_id,
        'datum': datum,
        'main_field': {
            'fieldID': field_id,
            'datum': datum,
            'kolicina_voda_l': kolicina_voda_l,
            'tip_rastenie': tip_rastenie,
            'total_water_needed': round(total_water_needed, 2)
            # 'isWatered': is_watered
        },
        'parcels': parcel_results
    })


# Рута за читање на сите ниви (главен CSV)
@app.route('/api/getAllFields', methods=['GET'])
async def get_all_fields():
    if not os.path.exists(MAIN_FIELD_LOG):
        return jsonify({'status': 'success', 'fields': []})

    fields = []
    with open(MAIN_FIELD_LOG, mode='r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            fields.append(row)

    return jsonify({'status': 'success', 'fields': fields})


# Рута за читање на парцели за одредена нива
@app.route('/api/getParcelsByField/<field_id>', methods=['GET'])
async def get_parcels_by_field(field_id):
    if not os.path.exists(SUB_PARCELS_LOG):
        return jsonify({'status': 'success', 'parcels': []})

    parcels = []
    with open(SUB_PARCELS_LOG, mode='r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            if row['fieldID'] == field_id:
                parcels.append({
                    'coordinates': row['coordinates'],
                    # 'longitude': float(row['longitude']),
                    # 'latitude': float(row['latitude']),
                    'potrebna_voda_l': float(row['potrebna_voda_l']),
                    'timestamp': row['timestamp']
                })

    return jsonify({'status': 'success', 'fieldID': field_id, 'parcels': parcels})



#-----------------------------------------------------------------
@app.route('/api/crops', methods=['GET'])
async def get_crops():
    return jsonify({
        'status': 'success',
        'crops': list(crop_mapping.keys()),
    })


@app.route('/api/calculate', methods=['POST'])
async def calculate():
    data = await request.get_json()

    coordinates = data.get('coordinates')
    crop_index  = data.get('crop_index')

    crop_string = crop_list[crop_index]
    crop_values = crop_mapping[crop_string]

    results = await asyncio.to_thread(
        return_data,
        coordinates,
        crop_values,
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