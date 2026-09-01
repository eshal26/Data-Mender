select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select reading_count
from "shp"."staging_verify"."daily_weather_summary"
where reading_count is null



      
    ) dbt_internal_test