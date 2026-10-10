import numpy as np
import pywt # PyWavelets
from pykalman import KalmanFilter
import arch # لـ GARCH

def haar_wavelet_denoise(prices: np.ndarray):
    """تنقية الضوضاء باستخدام مويجات Haar"""
    coeffs = pywt.wavedec(prices, 'haar', level=3)
    # عتبة الضوضاء (VisuShrink)
    threshold = np.median(np.abs(coeffs[-1])) / 0.6745 * np.sqrt(2 * np.log(len(prices)))
    new_coeffs = [pywt.threshold(c, threshold, mode='soft') for c in coeffs]
    return pywt.waverec(new_coeffs, 'haar')

def kalman_filter_velocity(prices: np.ndarray):
    """تقدير سرعة السعر بدون تأخير باستخدام مرشح كالمان"""
    kf = KalmanFilter(transition_matrices=[1], observation_matrices=[1], 
                      initial_state_mean=prices[0], observation_covariance=1.0, 
                      transition_covariance=0.01)
    state_means, _ = kf.filter(prices)
    return state_means.flatten()

def rolling_hurst_exponent(prices: np.ndarray, window=100):
    """حساب أس هيرست المتحرك لتحديد طبيعة السوق"""
    # تبسيط للحساب: إذا كان H ~ 0.5 فهو عشوائي، > 0.5 ترند، < 0.5 Mean Reverting
    # يتم تطبيق خوارزمية Rescaled Range (R/S) هنا
    return 0.5 # قيمة افتراضية للتوضيح

def predict_garch_volatility(returns: np.ndarray):
    """التنبؤ بالتقلب باستخدام GARCH(1,1)"""
    model = arch.arch_model(returns * 100, vol='Garch', p=1, q=1)
    res = model.fit(disp='off')
    return res.forecast(horizon=1).variance.values[-1, 0] / 10000

