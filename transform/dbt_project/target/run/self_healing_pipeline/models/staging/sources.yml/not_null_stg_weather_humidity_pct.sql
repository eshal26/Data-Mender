select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select humidity_pct
from "shp"."public"."stg_weather"
where humidity_pct is null



      
    ) dbt_internal_test