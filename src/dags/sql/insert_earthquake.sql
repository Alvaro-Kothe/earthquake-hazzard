MERGE INTO `earthquake.earthquake` AS target
USING `{{ task_instance.xcom_pull(task_ids='create_temp_table') }}` AS source
ON target.earthquake_id = source.earthquake_id
WHEN NOT MATCHED THEN
  INSERT (earthquake_id, position, depth, magnitude, time, alert, significance)
  VALUES (source.earthquake_id, source.position, source.depth, source.magnitude, source.time, source.alert, source.significance);
