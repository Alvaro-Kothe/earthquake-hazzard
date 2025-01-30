{{
    config(
    materialized='incremental',
    unique_key=['day_ts', 'country']
    )
}}

SELECT
    country,
    continent,
    TIMESTAMP_TRUNC(time, DAY) AS day_ts,
    COUNT(*) AS earthquakes_count,
    AVG(magnitude) AS avg_magnitude,
    AVG(depth) AS avg_depth,
    AVG(significance) AS avg_significance
FROM {{ source("earthquake", "earthquake") }}
WHERE country IS NOT NULL

{% if is_incremental() %}

AND time > (SELECT MAX(day_ts) FROM {{ this }})

{% endif %}

GROUP BY country, continent, day_ts
