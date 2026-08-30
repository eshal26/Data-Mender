select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
    



select ts
from "shp"."public"."stg_weather"
where ts is null



      
    ) dbt_internal_test