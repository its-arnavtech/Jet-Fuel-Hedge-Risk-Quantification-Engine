CREATE OR REPLACE VIEW jet_fuel_gold.v_route_burn AS
SELECT f.route_id, r.origin, r.destination, f.aircraft_type, f.cost_month,
       f.monthly_flights, f.monthly_gallons, f.spot_price_gal,
       f.unhedged_cost_usd AS monthly_fuel_cost_usd,
       f.price_observation_date, f.is_synthetic
FROM jet_fuel_gold.route_fuel_costs f JOIN jet_fuel_gold.dim_route r USING(route_id)
WHERE f.hedge_ratio=0.0;
