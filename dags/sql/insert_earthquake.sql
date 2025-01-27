CREATE TEMP TABLE temp_earthquake_staging (
  earthquake_id STRING,
  position GEOGRAPHY,
  depth FLOAT64,
  magnitude FLOAT64,
  time TIMESTAMP,
  alert STRING,
  significance INT64
);

INSERT INTO temp_earthquake_staging (earthquake_id, position, depth, magnitude, time, alert, significance)
VALUES 
  {% for feature in task_instance.xcom_pull(task_ids='transform_features', key='return_value') %}
    (
    '{{ feature.earthquake_id }}',
    ST_GEOGPOINT({{ feature.longitude }}, {{ feature.latitude }}),
    {{ feature.depth }},
    {{ feature.magnitude }},
    '{{ feature.time }}',
    {{ feature.alert }},
    {{ feature.significance }}
    ) {{ ", " if not loop.last else "" }}
  {% endfor %}
;

MERGE INTO earthquake.earthquake AS target
USING temp_earthquake_staging AS source
ON target.earthquake_id = source.earthquake_id
WHEN NOT MATCHED THEN
  INSERT (earthquake_id, position, depth, magnitude, time, alert, significance)
  VALUES (source.earthquake_id, source.position, source.depth, source.magnitude, source.time, source.alert, source.significance);
