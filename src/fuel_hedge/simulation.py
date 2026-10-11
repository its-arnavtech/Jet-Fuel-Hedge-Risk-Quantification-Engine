"""EWM calibration and deterministic GBM costs; no cloud dependencies."""

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SimulationConfig:
    s0: float
    mu: float
    sigma: float
    n_paths: int = 100_000
    horizon_years: float = 1.0
    annual_gallons: float = 1.5e9
    risk_free_rate: float = 0.04
    seed: int = 20261010
    hedge_ratios: tuple[float, ...] = (0.0, 0.2, 0.4, 0.6, 0.8)

    def __post_init__(self):
        values = [self.s0,self.mu,self.sigma,self.horizon_years,self.annual_gallons,self.risk_free_rate]
        if not all(math.isfinite(v) for v in values):
            raise ValueError('Simulation inputs must be finite')
        if self.s0<=0 or self.sigma<0 or self.annual_gallons<=0 or not 0<self.horizon_years<=5:
            raise ValueError('Invalid price, volatility, consumption, or horizon')
        if not isinstance(self.n_paths,int) or not 1<=self.n_paths<=1_000_000:
            raise ValueError('n_paths must be an integer between 1 and 1,000,000')
        if not isinstance(self.seed,int) or not 0<=self.seed<2**63:
            raise ValueError('seed must be a nonnegative integer below 2**63')
        if not math.isclose(self.horizon_years*52,round(self.horizon_years*52)):
            raise ValueError('Horizon must be a whole number of weekly periods')
        if (not self.hedge_ratios or 0.0 not in self.hedge_ratios
                or len(set(self.hedge_ratios))!=len(self.hedge_ratios)
                or not all(math.isfinite(r) and 0<=r<=1 for r in self.hedge_ratios)):
            raise ValueError('Unique hedge ratios in [0,1] including zero are required')

    @property
    def steps(self):
        return round(self.horizon_years*52)

    @property
    def forward_price(self):
        return self.s0*math.exp(self.risk_free_rate*self.horizon_years)


def calibrate(weekly: pd.DataFrame, *, decay: float = .94, lookback_days: int = 365) -> dict:
    if not 0<decay<1 or lookback_days<180:
        raise ValueError('Invalid decay or calibration window')
    frame=weekly.copy()
    frame['week_ending']=pd.to_datetime(frame.week_ending)
    frame=frame.sort_values('week_ending')
    if frame.empty or not frame.week_ending.is_unique:
        raise ValueError('Calibration requires unique weekly observations')
    end=frame.week_ending.max()
    frame=frame[frame.week_ending> end-pd.Timedelta(days=lookback_days)]
    if len(frame)<26 or frame.week_ending.diff().dropna().dt.days.ne(7).any():
        raise ValueError('Calibration requires at least 26 consecutive weekly observations')
    prices=frame.jet_fuel_gal.to_numpy(dtype=float)
    if not np.isfinite(prices).all() or (prices<=0).any():
        raise ValueError('Calibration prices must be finite and positive')
    returns=np.diff(np.log(prices))
    weights=decay**np.arange(len(returns)-1,-1,-1,dtype=float)
    weights/=weights.sum()
    weekly_mean=float(np.dot(weights,returns))
    weekly_variance=float(np.dot(weights,(returns-weekly_mean)**2)/(1-np.dot(weights,weights)))
    sigma=math.sqrt(max(weekly_variance,0)*52)
    return {'mu':weekly_mean*52+.5*sigma*sigma,'sigma':sigma,'decay':decay,
            'n_returns':len(returns),'calibration_start':str(frame.week_ending.min().date()),
            'calibration_end':str(end.date()),'weekly_log_mean':weekly_mean,
            'weekly_log_variance':weekly_variance}


def box_muller(rng, n: int) -> np.ndarray:
    uniform=rng.random(((n+1)//2,2))
    radius=np.sqrt(-2*np.log(np.maximum(uniform[:,0],np.finfo(float).tiny)))
    angle=2*np.pi*uniform[:,1]
    normals=np.column_stack((radius*np.cos(angle),radius*np.sin(angle))).reshape(-1)
    return normals[:n]


def price_paths(path_ids, config: SimulationConfig) -> np.ndarray:
    ids=np.asarray(path_ids)
    if ids.ndim!=1 or not np.issubdtype(ids.dtype,np.integer) or (ids<0).any():
        raise ValueError('Path IDs must be a one-dimensional array of nonnegative integers')
    dt=config.horizon_years/config.steps
    result=np.empty((len(ids),config.steps+1),dtype=float)
    result[:,0]=config.s0
    for i,path_id in enumerate(ids):
        rng=np.random.default_rng(np.random.SeedSequence([config.seed,int(path_id)]))
        shocks=box_muller(rng,config.steps)
        log_changes=(config.mu-.5*config.sigma**2)*dt+config.sigma*math.sqrt(dt)*shocks
        result[i,1:]=config.s0*np.exp(np.cumsum(log_changes))
    if not np.isfinite(result).all() or (result<=0).any():
        raise ValueError('Nonfinite or nonpositive simulated price; inspect calibration')
    return result


def cost_distribution(paths: np.ndarray, config: SimulationConfig) -> pd.DataFrame:
    if paths.ndim!=2 or paths.shape[1]!=config.steps+1 or not np.isfinite(paths).all():
        raise ValueError('Invalid price path matrix')
    average=paths[:,1:].mean(axis=1)  # Purchases in future periods; exclude initial spot.
    volume=config.annual_gallons*config.horizon_years/1e9
    return pd.DataFrame({ratio:volume*(ratio*config.forward_price+(1-ratio)*average)
                         for ratio in config.hedge_ratios})


def risk_summary(costs: pd.DataFrame) -> pd.DataFrame:
    if costs.empty or 0.0 not in costs.columns or not np.isfinite(costs.to_numpy()).all():
        raise ValueError('Finite costs including unhedged baseline required')
    result=[]
    for ratio in costs.columns:
        values=costs[ratio].to_numpy()
        p50,p95=np.quantile(values,[.5,.95],method='linear')
        mean=float(values.mean())
        result.append({'hedge_ratio':ratio,'mean_cost_b':mean,'p50_cost_b':p50,
                       'p95_cost_b':p95,'var_95_b':p95-mean,
                       'cvar_95_b':values[values>=p95].mean(),'n_paths':len(values)})
    frame=pd.DataFrame(result)
    baseline=float(frame.loc[frame.hedge_ratio==0,'var_95_b'].iloc[0])
    frame['var_reduction_pct']=100*(baseline-frame.var_95_b)/baseline if abs(baseline)>1e-12 else np.nan
    return frame
