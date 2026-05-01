# Stochastic Robustness Report-Ready Notes

Test 9 uses stationary block bootstrap on the realized monthly return series from the quarterly-rebalanced strategy. The central annualized return is 12.51%, the central Sharpe is 0.788, and the 90% annualized-return interval is 3.27% to 22.31%.

Test 10 perturbs realized trading costs with epsilon ~ N(0, 0.3^2). The central Sharpe is 0.770, P(Sharpe > 0.50) is 100.0%, and the worst-5% Sharpe CVaR is 0.765.






Test 12 evaluates a rolling 24-period in-sample / 1-period out-of-sample chain. Out-of-sample annualized return is 16.62%, Sharpe is 1.100, and hit rate versus benchmark is 48.5%.

Test 13 simulates long-run paths from the empirical mean/covariance fit. The annualized-return percentiles are -0.37% / 6.97% / 12.37% / 18.18% / 26.63%, with central Sharpe 0.768.
