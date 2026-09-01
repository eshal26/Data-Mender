
  create view "shp"."staging_verify"."stg_weather__dbt_tmp"
    
    
  as (
    select
    ts,
    temperature_c::double precision as temperature_c,
    humidity_pct,
    precipitation_mm,
    loaded_at
from "shp"."public"."raw_weather"
where temperature_c ~ '^-?\d+(\.\d+)?$'
  );