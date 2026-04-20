# 任務鎖定

這個 repository 的用途是持續優化計算 65536 位數 pi 的速度。
一般 optimization wave 的演算法變更只能發生在
`algorithms/pi_algo_improve-by-agent.py`。

## 一般 wave 的允許修改範圍

- 在一般 optimization wave 中，只能修改 `algorithms/pi_algo_improve-by-agent.py`。
- 在一般 optimization wave 中，也可以更新 `log.md`，用來保存已驗證的 benchmark 結果。
- 控制面維護工作只在使用者明確要求時才能修改 `.codex/*`、`docs/*`、`README.md`、
  `tools/verify_pi_bin.py` 等控制層檔案。

## 優化目標

- 優化產生 65536 位數 pi 輸出的速度。
- 必須保持單核心執行模式。
- 任何速度提升都必須保留單核心限制。
- 保留 `algorithms/pi_algo_org.py` 作為原始比較基準。
- 所有一般 wave 的演算法優化都必須放在 `algorithms/pi_algo_improve-by-agent.py`。

## Campaign 控制面

- 多-wave campaign 由 `.codex/wave_request.json` 啟動。
- 建立或修改新的 request 之後，必須先執行 `python3 .codex/wave-control-init.py`
  來校正 `.codex/wave_state.json`，再開始 wave 1。
- 啟動新 campaign 時，必須在 `.codex/wave_request.json` 填入新的 `request_id`、
  `requested_waves`、`goal`、`continue_command`、`created_at`。
- `continue_command` 必須是 controller 用來繼續下一輪的固定命令。
- `.codex/wave_request.json` 在 active campaign 期間不可修改。
- `.codex/wave_state.json` 是 controller-owned runtime state，不可在 active campaign
  期間手動修改。
- `.codex/local/wave_events.jsonl` 是本地 append-only audit journal，不進 git。
- wave 1 必須由 initializer bootstrap；Stop hook 只負責驗證當前 wave 與自動續跑後續 wave。
- initializer 會把啟動當下的 worktree 記為 baseline；後續 wave 驗證只看相對於 baseline
  新增或變更的檔案，不要求 campaign start 時先把非控制面工作樹清空。

## 連續演化規則

- 每一輪 optimization wave 開始前，都必須先閱讀 `.codex/wave_request.json`、
  `docs/task.md`、`docs/init_prompt.md`、以及 `log.md`。
- `log.md` 中的目前最佳 trusted 結果是下一輪必須挑戰的 performance target。
- 每一輪都應以「超越 `log.md` 目前最佳 trusted 數據」為首要目標，而不只是做出一個可執行版本。
- 每一輪只允許一個範圍明確、可歸因的改動，讓性能變化可以被追蹤。
- Stop hook 會在每輪結束後決定是否繼續下一輪；agent 不可自行連跑多輪。

## 一般 optimization wave 中禁止修改的檔案

- `algorithms/pi_algo_org.py`
- `tools/run_verify_timed.py`
- `tools/verify_pi_bin.py`
- `reference/pi_65536.bin`
- `.codex/hooks.json`
- `.codex/wave_stop.py`
- `.codex/wave_request.json`
- `.codex/wave_state.json`
- `docs/task.md`
- `docs/init_prompt.md`
- `README.md`

## 記錄規則

- 開始新的一輪 optimization wave 前，必須先閱讀 `log.md`。
- 必須把 `log.md` 中的最佳結果視為需要超越的目標。
- 每個有效 wave 都必須出現在 `log.md` 的 Wave History。
- `log.md` 的 Current Best 只能由 trusted order-balanced benchmark 決定。
- `log.md` 至少要保留：
  - wave 識別碼
  - fixed benchmark 指令
  - trusted benchmark 指令
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
- controller 還會額外做 exact byte-for-byte 驗證；prefix-only 成功不算有效 wave。

## Benchmark 規則

- 必須比較 `algorithms/pi_algo_improve-by-agent.py` 與
  `algorithms/pi_algo_org.py`。
- 只有在兩個實作都各自獨立通過二進位驗證後，timing comparison 才算有效。
- 固定 benchmark 指令為：
  `python3 run_verify_timed.py 65536 --repeats 1`
- fixed benchmark 是 compatibility gate，不是 trusted best 判定依據。
- trusted best 判定由 controller 的 order-balanced confirmation benchmark 決定。
- 只有在 file-scope check、必要完整驗證指令、exact 驗證、以及固定 benchmark 指令都通過之後，才能消耗 controller-owned wave budget。

## 覆寫規則

- 只有在使用者明確要求修改其他檔案時，才能違反上述規則。
