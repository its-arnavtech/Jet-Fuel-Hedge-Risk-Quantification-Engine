CREATE OR REPLACE VIEW jet_fuel_gold.v_fleet_summary AS
WITH asof AS (SELECT max(price_date) AS price_date FROM jet_fuel_silver.fuel_prices),
fleet AS (
 SELECT r.aircraft_type, count(DISTINCT r.route_id) AS routes_operated,
   sum(r.daily_frequencies*365) AS annual_flights,
   sum(r.avg_fuel_burn_gal*r.daily_frequencies*365) AS annual_gallons
 FROM jet_fuel_silver.routes r CROSS JOIN asof p
 WHERE r.effective_dt<=p.price_date AND r.expiry_dt>p.price_date GROUP BY r.aircraft_type
)
SELECT *, 100.0*annual_gallons/sum(annual_gallons) OVER() AS fleet_share_pct,
 annual_gallons*(SELECT jet_fuel_gal FROM jet_fuel_silver.fuel_prices
   ORDER BY price_date DESC LIMIT 1)/1e9 AS annual_fuel_cost_b,
 'SYNTHETIC_SCHEDULE_ANNUALIZED_365_DAYS' AS consumption_basis,true AS is_synthetic
FROM fleet;
