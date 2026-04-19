# 任務鎖定

這個 repository 的用途是持續優化計算 65536 位數 pi 的速度。
所有演算法優化工作都必須發生在
`algorithms/pi_algo_improve-by-agent.py`。

## 允許修改的目標

- 在一般 optimization wave 中，只能修改 `algorithms/pi_algo_improve-by-agent.py`。
- 在一般 optimization wave 中，也可以更新 `log.md`，用來保存目前最佳 benchmark 結果。

## 優化目標

- 優化產生 65536 位數 pi 輸出的速度。
- 必須保持單核心執行模式。
- 任何速度提升都必須保留單核心限制。
- 保留 `algorithms/pi_algo_org.py` 作為原始比較基準。
- 所有優化變更都必須放在 `algorithms/pi_algo_improve-by-agent.py`。

## 連續演化規則

- 每一輪 optimization wave 開始前，都必須先閱讀 `log.md`。
- `log.md` 中的目前最佳結果是下一輪必須挑戰的 performance target。
- 每一輪都應以「超越 `log.md` 目前最佳數據」為首要目標，而不只是做出一個可執行版本。
- 若本輪結果沒有超越目前最佳值，仍可視為一次有效嘗試，但必須清楚記錄這一輪沒有刷新紀錄，並說明未改善或退步的原因。
- 若本輪成功超越目前最佳值，必須同步更新 `log.md` 的 Current Best 與 Wave History。
- 每一輪只允許一個範圍明確、可歸因的改動，讓性能變化可以被追蹤。
- 下一輪必須以上一輪寫入 `log.md` 的最佳值作為新的目標，持續迭代。

## 一般 optimization wave 中禁止修改的檔案

- `algorithms/pi_algo_org.py`
- `tools/run_verify_timed.py`
- `tools/verify_pi_bin.py`
- `reference/pi_65536.bin`
- `.codex/hooks.json`
- `.codex/wave_stop.py`
- `docs/task.md`
- `docs/init_prompt.md`
- `README.md`

## 記錄規則

- 開始新的一輪 optimization wave 前，必須先閱讀 `log.md`。
- 必須把 `log.md` 中的最佳結果視為需要超越的目標。
- 成功完成一輪後，更新 `log.md`，至少包含：
  - wave 識別碼
  - benchmark 指令
  - `improve` 的 execution time
  - `org` 的 execution time
  - 相對於 `org` 的 ratio
  - 本輪是否創下新的最佳結果
  - 本輪修改的簡短說明

## 正確性規則

- 不得使用兩個演算法互相比對作為驗證方式。
- 正確性必須透過固定的二進位參考檔 `reference/pi_65536.bin` 驗證。
- Python 驗證器必須獨立於被測實作。
- 在驗證通過之前，任何優化結果都不能被視為有效。
- 驗證時使用 `tools/verify_pi_bin.py` 或 `tools/run_verify_timed.py`。
- 必要的完整驗證指令為：
  `python3 algorithms/pi_algo_improve-by-agent.py 65536 | python3 tools/verify_pi_bin.py`

## Benchmark 規則

- 必須比較 `algorithms/pi_algo_improve-by-agent.py` 與
  `algorithms/pi_algo_org.py`。
- 只有在兩個實作都各自獨立通過二進位驗證後，timing comparison 才算有效。
- 固定 benchmark 指令為：
  `python3 run_verify_timed.py 65536 --repeats 1`
- 只有在 file-scope check、必要完整驗證指令、以及固定 benchmark 指令都通過之後，才能消耗 `count.md` 預算。

## 覆寫規則

- 只有在使用者明確要求修改其他檔案時，才能違反上述規則。
