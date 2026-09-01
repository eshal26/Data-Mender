
    
    

select
    day as unique_field,
    count(*) as n_records

from "shp"."staging_verify"."daily_weather_summary"
where day is not null
group by day
having count(*) > 1


