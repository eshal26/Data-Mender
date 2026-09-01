select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select day
from "shp"."staging_verify"."daily_weather_summary"
where day is null



      
    ) dbt_internal_test