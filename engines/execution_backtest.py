import pandas as pd
import numpy as np

class RealisticBacktester:
    def __init__(self, spread=0.0001, commission=0.00005, slippage=0.00005, swap=0.00001):
        self.spread = spread
        self.commission = commission
        self.slippage = slippage
        self.swap = swap
        
    def simulate_trade(self, prices, signals, initial_capital=10000, leverage=10):
        capital = initial_capital
        position = 0
        equity_curve = [capital]
        
        for i in range(1, len(prices)):
            price = prices[i]
            prev_price = prices[i-1]
            signal = signals[i-1] # منع Look-Ahead Bias
            
            # تطبيق الانزلاق والعمولة
            exec_price = price + (self.slippage if signal==1 else -self.slippage)
            cost = abs(signal) * capital * leverage * (self.spread + self.commission)
            
            if signal != 0:
                position = signal * leverage
                capital -= cost
                
            # حساب العائد
            pnl = position * (price - prev_price) * capital / (prev_price * leverage)
            swap_cost = abs(position) * self.swap * capital
            capital += pnl - swap_cost
            equity_curve.append(capital)
            
        return np.array(equity_curve), capital / initial_capital - 1

    def calculate_metrics(self, equity_curve):
        returns = np.diff(equity_curve) / equity_curve[:-1]
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns)>0 else 0
        max_dd = np.min(np.maximum.accumulate(equity_curve) - equity_curve) / np.max(equity_curve)
        return {"sharpe": sharpe, "max_drawdown": max_dd, "final_return": equity_curve[-1]/equity_curve[0]-1}

