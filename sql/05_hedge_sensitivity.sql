CREATE OR REPLACE VIEW jet_fuel_gold.v_hedge_sensitivity AS
WITH latest AS (
 SELECT price_date, jet_fuel_gal AS base_price FROM jet_fuel_silver.fuel_prices
 QUALIFY row_number() OVER(ORDER BY price_date DESC)=1
), grid AS (
 SELECT h.scenario_id,h.hedge_ratio,p.price_change_pct,b.price_date AS as_of_date,b.base_price,
   b.base_price*(1+p.price_change_pct/100.0) AS scenario_price_gal,
   b.base_price*exp(0.04) AS locked_price_gal, 1.5e9 AS annual_gallons
 FROM jet_fuel_gold.dim_hedge_scenario h
 CROSS JOIN (SELECT explode(array(-30,-15,0,15,30,50)) AS price_change_pct) p CROSS JOIN latest b
)
SELECT *, scenario_price_gal*annual_gallons/1e9 AS unhedged_cost_b,
  (hedge_ratio*locked_price_gal+(1-hedge_ratio)*scenario_price_gal)*annual_gallons/1e9 AS hedged_cost_b,
  100.0*(scenario_price_gal-(hedge_ratio*locked_price_gal+(1-hedge_ratio)*scenario_price_gal))
    /scenario_price_gal AS cost_reduction_pct,
  'REFERENCE_CARRIER_1_5B_GALLONS' AS consumption_basis
FROM grid;
