CREATE OR REPLACE VIEW jet_fuel_gold.v_hedge_mtm AS
WITH latest AS (
  SELECT * FROM jet_fuel_silver.fuel_prices QUALIFY row_number() OVER(ORDER BY price_date DESC)=1
), marks AS (
  SELECT h.*, p.price_date AS as_of_date,
    CASE h.underlying WHEN 'JET_FUEL' THEN p.jet_fuel_gal
      WHEN 'WTI' THEN p.wti_spot_bbl / 42.0 WHEN 'HEATING_OIL' THEN p.heating_oil_gal END AS current_spot_gal,
    CASE WHEN h.instrument_type NOT IN ('futures','swap') THEN 'UNSUPPORTED_INSTRUMENT'
      WHEN h.underlying NOT IN ('JET_FUEL','WTI','HEATING_OIL') THEN 'UNSUPPORTED_UNDERLYING'
      WHEN h.contract_gallons <= 0 OR h.locked_price_gal IS NULL THEN 'INVALID_POSITION'
      ELSE 'LINEAR_SPOT_PROXY' END AS valuation_method
  FROM jet_fuel_silver.hedge_positions h CROSS JOIN latest p
  WHERE h.position_date <= p.price_date AND h.expiry_dt >= p.price_date
)
SELECT *, datediff(expiry_dt, as_of_date) AS days_to_expiry,
  CASE WHEN valuation_method='LINEAR_SPOT_PROXY' THEN
    (current_spot_gal - locked_price_gal)*contract_gallons END AS unrealized_pnl_usd,
  CASE WHEN valuation_method='LINEAR_SPOT_PROXY' THEN current_spot_gal - locked_price_gal END AS pnl_per_gallon,
  CASE WHEN valuation_method != 'LINEAR_SPOT_PROXY' THEN valuation_method
    WHEN current_spot_gal IS NULL THEN 'MISSING_MARK'
    WHEN current_spot_gal > locked_price_gal THEN 'IN_THE_MONEY'
    WHEN current_spot_gal < locked_price_gal THEN 'OUT_OF_MONEY' ELSE 'AT_THE_MONEY' END AS hedge_status
FROM marks;
