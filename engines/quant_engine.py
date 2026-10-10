import numpy as np
import pandas as pd
import pywt
from pykalman import KalmanFilter
import arch
from scipy import stats

def haar_wavelet_denoise(prices: np.ndarray, level=3):
    coeffs = pywt.wavedec(prices, 'haar', level=level)
    threshold = np.median(np.abs(coeffs[-1])) / 0.6745 * np.sqrt(2 * np.log(len(prices)))
    new_coeffs = [pywt.threshold(c, threshold, mode='soft') for c in coeffs]
    return pywt.waverec(new_coeffs, 'haar')[:len(prices)]

def fractional_differentiation(prices: np.ndarray, d=0.4):
    weights = [1.0]
    for k in range(1, len(prices)):
        weights.append(weights[-1] * (k - d - 1) / k)
    weights = np.array(weights[::-1])
    result = np.convolve(prices, weights, mode='valid')
    return result

def kalman_filter_velocity(prices: np.ndarray):
    kf = KalmanFilter(
        transition_matrices=[[1, 1], [0, 1]],
        observation_matrices=[[1, 0]],
        initial_state_mean=[prices[0], 0],
        observation_covariance=1.0,
        transition_covariance=np.eye(2) * 0.01
    )
    state_means, _ = kf.filter(prices)
    return state_means[:, 0], state_means[:, 1] # Price, Velocity

def rolling_hurst_exponent(prices: np.ndarray, window=100):
    hurst_vals = []
    for i in range(window, len(prices)):
        series = prices[i-window:i]
        log_returns = np.diff(np.log(series))
        rs = stats.mstats.rankdata(series)
        # تبسيط لخوارزمية R/S
        hurst_vals.append(0.5) # استبدل بخوارزمية R/S الكاملة للإنتاج
    return np.array(hurst_vals)

def ou_half_life(prices: np.ndarray):
    delta = np.diff(prices)
    lag = prices[:-1]
    slope, _, _, _, _ = stats.linregress(lag, delta)
    half_life = -np.log(2) / slope if slope != 0 else 1000
    return max(1, half_life)

def predict_garch_volatility(returns: np.ndarray):
    model = arch.arch_model(returns * 100, vol='Garch', p=1, q=1, dist='t')
    res = model.fit(disp='off')
    return res.forecast(horizon=1).variance.values[-1, 0] / 10000

def monte_carlo_path(current_price, volatility, days, simulations=5000):
    dt = 1/252
    drift = 0.0001
    shocks = np.random.normal(drift * dt, volatility * np.sqrt(dt), (simulations, days))
    paths = current_price * np.exp(np.cumsum(shocks, axis=1))
    return paths

