
# CW1 Integration Notice / 对接通知 (Role 4 Integrator)

Audience / 适用对象: Roles 3, 5, 6, 7, 8  
Goal / 目标: Parallel development with low conflict and fast merge to team branch / 并行开发、低冲突、快速合流

## 1) Branch workflow / 分支流程（必须）
Run from repo root `ift_coursework_2025/`:

```bash
git checkout feature/coursework_one_Team_04_Pearson
git pull origin feature/coursework_one_Team_04_Pearson
git checkout -b feature/cw1-role6-source-a
```

Branch naming / 分支命名:
- `feature/cw1-role<id>-<module>`
- examples: `feature/cw1-role5-universe-db`, `feature/cw1-role8-normalize-quality`

After coding / 开发完成后:

```bash
git add <your files>
git commit -m "roleX: <change summary>"
git push -u origin <your branch>
```

Open PR to / 发 PR 到:
- `feature/coursework_one_Team_04_Pearson`

## 2) File ownership / 文件归属（只改自己的）
- Role 5: `modules/db/*`
- Role 6: `modules/input/extract_source_a.py`
- Role 7: `modules/input/extract_source_b.py`
- Role 8: `modules/output/normalize.py` and `modules/output/quality.py`
- Role 3: `modules/output/load.py`
- Role 4 (Integrator): `Main.py` and integration flow

Do not modify others' modules or `Main.py` without agreement.  
未经沟通，不要改别人模块和 `Main.py`。

## 3) Fixed interface contracts / 固定接口契约（函数名不可改）
1. `modules.db.get_company_universe(company_limit: int) -> list[str]`
2. `modules.input.extract_source_a(company_ids, run_date, backfill_years, frequency) -> list[dict]`
3. `modules.input.extract_source_b(company_ids, run_date, backfill_years, frequency) -> list[dict]`
4. `modules.output.normalize_records(records) -> list[dict]`
5. `modules.output.run_quality_checks(records) -> dict`
6. `modules.output.load_curated(records, dry_run: bool) -> int`

## 4) Minimum upstream schema / 上游最小字段要求（Role 6/7）
Each record returned by `extract_source_a/b` must include / 每条记录至少包含:
- `company_id`
- `observation_date`
- `factor_name`
- `factor_value`
- `source`
- `metric_frequency` (`daily|monthly|quarterly|annual`)

Recommended for staleness control / 为了时效性控制，强烈建议增加:
- `source_report_date`

## 4.1) Mixed-frequency policy / 混合频率处理规则（必须遵守）
- `--frequency` is pipeline run frequency, not the natural frequency of each metric.
- `--frequency` 是流水线运行频率，不等于每个因子的天然发布频率。
- Each row must carry its own `metric_frequency`.
- 每条记录必须标注自己的 `metric_frequency`。
- Low-frequency factors (quarterly/annual) must use step-forward fill with staleness limits; do not fake daily "new" fundamentals.
- 低频因子（季/年）在高频运行中必须使用前值延续并遵守过期阈值，不能伪造“每日新财报”。
- High-frequency factors (daily) may be aggregated to monthly for portfolio rebalance use.
- 高频因子（日报）可在组合调仓前聚合到月频使用。

Current data requirements reference / 当前需求对应频率示例:
- `News Sentiment`: daily
- `Dividend Yield`, `P/B`: monthly
- `Debt/Equity`: quarterly
- `EBITDA Margin`: quarterly/annual

## 5) Integrator flow / 总装流程（已接入）
- `get_company_universe`
- `extract_source_a` + `extract_source_b`
- `normalize_records`
- `run_quality_checks`
- `load_curated`
- run log

## 6) Local validation before PR / PR 前本地验收
Run in `team_Pearson/coursework_one/`:

```bash
poetry install
poetry run python Main.py --run-date 2026-02-14 --frequency daily --dry-run
poetry run pytest -q test/test_smoke.py
```

Pass criteria / 通过标准:
- Exit code is `0`
- Output contains `run_log_written_to`
- Smoke test passes

## 7) Commit scope / 提交边界
- Keep all changes inside `team_Pearson/coursework_one/` plus required team-level files.
- Do not commit unrelated folders/artifacts (DB folders, caches, temp files, etc.).

