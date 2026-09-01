select
    ts,
    temperature_c::double precision as temperature_c,
    humidity_pct,
    precipitation_mm,
    loaded_at
from {{ source('raw', 'raw_weather') }}
where temperature_c ~ '^-?\d+(\.\d+)?$'