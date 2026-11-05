You manage a portfolio in a simulated market, one step at a time. Each step reveals the next {time_gap} days of daily prices. A cycle is about {cycle_days} days ({steps_per_cycle} steps); at the start of every cycle your portfolio is reset to $100,000 in cash.

Tradable assets ({n_assets}): {assets}. Their names are disguised and their prices are rebased; some trade every day, others only on weekdays. Context series (not tradable): {context}.

Your strategy lives in strategy.py and must define weights(history). Before each trading day the backtest calls it with:
- history.open, .high, .low, .close, .volume: pandas DataFrames, one row per date, one column per asset;
- history.context: one row per date, one column per context series;
- history.assets: the asset names; history.today: the day about to be traded.
Every row in history is before history.today. Return a dict {{asset: weight}} (the share of the portfolio's value to hold; long only; weights sum to at most 1 and the rest stays in cash), or None to keep the current positions. Orders run at the day's open and the portfolio is valued at its close. An asset with no price that day is not traded. Every trade pays a fee of 0.1% of its value. If weights() raises or returns something invalid, that day is held in cash. weights() has {timeout} seconds in total for a whole step.

Score: your cycle return minus the return of an equal-weight buy-and-hold of all tradable assets (which pays no fees).

Data for your scripts (read-only, every day released so far): /data/prices.csv (date,asset,open,high,low,close,volume) and /data/context.csv (date,series,value). run_script sees them; they are never in your folder.

Keep market data out of your folder: between cycles, dates (YYYY-MM-DD, YYYY/MM/DD, YYYYMMDD) and price levels (numbers with 3 or more digits before the decimal point, or 2 digits and 2 or more decimals) are replaced by a [cleaned …] marker, and data files ({globs}) are deleted. Read /data from your scripts instead, and small settings like 0.5, 20 or 252.0 (a lone .0) are left as they are.

Asset names are erased too: between cycles every "Asset X" in your folder becomes a [cleaned …] marker, in code and notes alike. Never write an asset's name: read the names from history.assets and pick assets by what the data shows (for example their volatility or how they move together).

Tools: read_prices (released daily rows, paged), wayback_fetch (archived pages of a few news and statistics sites, dated no later than the released step), backtest_report (your strategy's last step, day by day, with any errors).

Be inventive: strategies that read structure in the series are welcome, for example spectral analysis over moving windows (Fourier or wavelet transforms) to find cycles and how they shift, links between assets read from shared frequencies or lead and lag, network or physics models of how moves spread. Plain rules like "if A is above B, do C" are a weak start, not a goal.

Check before you ship: after you change strategy.py, replay it on the days released so far, in the same step. Write a script in your folder holding `import runpy; runpy.run_path("/data/replay.py", run_name="__main__")` and run it with run_script (optional args: [number of days], default 120). It prints your strategy's return, the equal-weight return, the difference, fees, trades and errors. Fix errors before you finish, and write in notes.md what the replay showed.

How to hold: express your views as tilts away from equal weight. Stay fully invested by default (weights summing to about 1), and move part of the portfolio to cash only when an explicit risk signal says so; name that signal in interpretation.md. Cash is not neutral here: the score compares you with a fully invested equal-weight portfolio, so cash loses whenever prices rise.
