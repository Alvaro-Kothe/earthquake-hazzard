# TODO: Call the api
# TODO: Store the geojson data into a data lake
# TODO: Manipulate the data from the geojson to extract:
#   0. id, in features[idx].id, This should have the unique constraint
#   1. The coordinates, in features[idx].geometry[0..1]
#   2. The depth, in features[idx].geometry[2]
#   3. The magnitude, in features[idx].properties.mag
#   4. The time, in features[idx].properties.time, this is in long int with offset from 1970-01-01T00:00:00.000Z, must convert from posix time to timestamp
#   5. alert, in features[idx].properties.alert, This is nullable
#   6. significance, in features[idx].properties.sig
# TODO: Get the country, using the coordinates, where the earthquake occurred. (store the encoding, ISO 3166-1 alpha-3 code; 3-digit country-code; country name) # check if 3-digit country code can be stored as i16
# TODO: Add a foreign key into the bigquery database, and the lookup table
