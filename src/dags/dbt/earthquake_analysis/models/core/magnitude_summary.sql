{{ config(materialized='table') }}

SELECT
    country,
    continent,
    CASE
        WHEN magnitude < 4 THEN 'Minor'
        WHEN magnitude < 5 THEN 'Light'
        WHEN magnitude < 6 THEN 'Moderate'
        WHEN magnitude < 7 THEN 'Strong'
        WHEN magnitude < 8 THEN 'Major'
        ELSE 'Great'
    END AS magnitude_category,
    COUNT(*) AS earthquake_count
FROM {{ source("earthquake", "earthquake") }}
WHERE magnitude >= 3 AND country IS NOT NULL
GROUP BY country, continent, magnitude_category
