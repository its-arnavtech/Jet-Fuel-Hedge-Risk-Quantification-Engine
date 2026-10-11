CREATE OR REPLACE VIEW jet_fuel_gold.v_price_correlation AS
SELECT price_date, wti_spot_bbl, jet_fuel_gal, crack_spread,
       rolling_vol_90d, rolling_corr_90d, return_gap_days, long_return_gap, source, is_synthetic
FROM jet_fuel_silver.fuel_prices;
