import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, leaves_list
from scipy.spatial.distance import squareform

def calculate_synthetic_dxy(prices: dict, weights: dict):
    # أوزان افتراضية لـ DXY
    # EUR: -0.576, JPY: 0.136, GBP: -0.119, CAD: 0.091, SEK: -0.042, CHF: 0.036
    log_prices = {k: np.log(v) for k,v in prices.items()}
    dxy = sum(weights[k] * log_prices[k] for k in weights)
    return np.exp(dxy)

def currency_strength_matrix(pairs_data):
    # حساب قوة كل عملة بناءً على أزواجها
    currencies = {'USD':0, 'EUR':0, 'GBP':0, 'JPY':0}
    for pair, ret in pairs_data.items():
        base, quote = pair[:3], pair[3:]
        currencies[base] += ret
        currencies[quote] -= ret
    return {k: v/3 for k,v in currencies.items()} # تطبيع

def hierarchical_risk_parity(cov_matrix):
    dist = squareform(1 - np.corrcoef(cov_matrix))
    link = linkage(dist, 'single')
    order = leaves_list(link)
    sorted_cov = cov_matrix[np.ix_(order, order)]
    
    weights = np.ones(len(cov_matrix)) / len(cov_matrix)
    # تبسيط لـ HRP
    return weights / np.sum(weights)

def detect_macro_shock(correlation_matrix, threshold=0.85):
    avg_corr = np.mean(np.abs(correlation_matrix - np.eye(len(correlation_matrix))))
    return avg_corr > threshold

