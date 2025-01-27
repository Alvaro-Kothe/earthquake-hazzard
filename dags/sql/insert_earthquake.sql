INSERT INTO earthquake.earthquake (earthquake_id, position, depth, magnitude, time, alert, significance) VALUES 
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
