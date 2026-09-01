select
    date_trunc('day', ts)              as day,
    avg(temperature_c)                 as avg_temp_c,
    min(temperature_c)                 as min_temp_c,
    max(temperature_c)                 as max_temp_c,
    avg(humidity_pct)                  as avg_humidity_pct,
    sum(precipitation_mm)              as total_precipitation_mm,
    count(*)                           as reading_count
from "shp"."staging_verify"."stg_weather"
group by 1