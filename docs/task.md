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
- 建立或修改新的 request 之後，必須先執行 `python3 .codex/wave_control_init.py`
  來校正 `.codex/wave_state.json`，再開始 wave 1。
- 一般開跑建議使用單一命令：`python3 .codex/wave_control_init.py --run`。
  使用者只需要手動更新 `.codex/wave_request.json`；initializer 會依目前 request
  重新 materialize prompt、校正 state，並立即啟動 wave 1。
- 啟動新 campaign 時，必須在 `.codex/wave_request.json` 填入新的 `request_id`、
  `requested_waves`、`goal`、`continue_command`、`created_at`。
- `continue_command` 是 `.codex/wave_start.py` 用來啟動 wave 1 foreground `codex exec`
  的固定命令；後續 wave 由 Stop hook 透過 native `decision: "block"` 在同一個 Codex
  CLI session 內續跑。
- `.codex/wave_project.json` 是必要的 project policy，定義允許修改範圍、必須修改的目標、
  prompt context files、log file、exact verification command、以及 diagnosis-only policy。
- `.codex/config.toml` 必須啟用 native Codex hooks：
  `[features].codex_hooks = true`。
- `.codex/wave_request.json` 在 active campaign 期間不可修改。
- `.codex/wave_project.json` 在 active campaign 期間不可修改；若要變更 policy，必須重新執行
  `python3 .codex/wave_control_init.py`。
- `.codex/wave_state.json` 是 controller-owned runtime state，不可在 active campaign
  期間手動修改。
- `.codex/local/wave_events.jsonl` 是本地 append-only audit journal，不進 git。
- wave 1 必須由 initializer bootstrap 後透過 `.codex/wave_start.py` 啟動。
- Stop hook 負責驗證剛完成的 wave、更新 controller state，並在 `remaining_waves > 0` 時
  回傳 native Codex `decision: "block"` 與下一輪 materialized prompt path，讓同一個
  Codex CLI session 繼續下一輪。
- 如果 Codex child process 結束但 Stop hook 沒有推進 controller state，`.codex/wave_start.py`
  必須把同一個 wave 設回 `queued` 並以 non-zero 結束，避免靜默卡在 `running`。
- 如果 runtime 已經結束但 state 仍卡在 `running` 或 `validating`，`.codex/wave_recover.py`
  會依相同 policy 驗證目前 wave；通過時消耗 wave budget 並 queue 下一輪，失敗時 requeue
  同一輪。
- initializer 會把啟動當下的 worktree 記為 baseline；後續 wave 驗證只看相對於 baseline
  新增或變更的檔案，不要求 campaign start 時先把非控制面工作樹清空。

## 連續演化規則

- 每一輪 optimization wave 開始前，都必須先閱讀 `.codex/wave_request.json`、
  `docs/task.md`、`docs/init_prompt.md`、以及 `log.md`。
- `log.md` 中的目前最佳 trusted 結果是下一輪必須挑戰的 performance target。
- 每一輪都應以「超越 `log.md` 目前最佳 trusted 數據」為首要目標，而不只是做出一個可執行版本。
- 每一輪只允許一個範圍明確、可歸因的改動，讓性能變化可以被追蹤。
- Stop hook 會在每輪結束後回報更新後的 state；若還有剩餘 wave，Stop hook 會直接 block
  目前停止並要求同一個 Codex session 讀取下一輪 prompt 繼續。
- agent 不可自行連跑多輪。

## 一般 optimization wave 中禁止修改的檔案

- `algorithms/pi_algo_org.py`
- `tools/run_verify_timed.py`
- `tools/verify_pi_bin.py`
- `reference/pi_65536.bin`
- `.codex/hooks.json`
- `.codex/wave_project.json`
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
  - 本輪使用的驗證或 benchmark 指令
  - `improve` 的 execution time，若本輪有量測
  - `org` 的 execution time，若本輪有跑完整 fixed benchmark；後續 wave 可以標記為 cached/skipped 並引用 `log.md`
    既有 org/current-best 資料
  - 相對於 `org` 的 ratio，若本輪有足夠資料
  - 本輪是否創下新的最佳結果
  - 本輪修改的簡短說明
- 如果本輪沒有對 `algorithms/pi_algo_improve-by-agent.py` 產生有效變更，但也沒有修改不允許的檔案，
  controller 會把這輪記為 diagnosis-only wave，將問題與下一步建議追加到 `log.md`。

## 正確性規則

- 不得使用兩個演算法互相比對作為驗證方式。
- 正確性必須透過固定的二進位參考檔 `reference/pi_65536.bin` 驗證。
- Python 驗證器必須獨立於被測實作。
- 在驗證通過之前，任何優化結果都不能被視為有效。
- 驗證時使用 `tools/verify_pi_bin.py` 或 `tools/run_verify_timed.py`。
- Stop hook 的 continuation gate 只要求 exact 驗證：
  `python3 algorithms/pi_algo_improve-by-agent.py 65536 | python3 tools/verify_pi_bin.py --exact`
- prefix-only 成功不算有效 wave。

## Benchmark 規則

- 完整 compatibility benchmark 必須比較 `algorithms/pi_algo_improve-by-agent.py` 與
  `algorithms/pi_algo_org.py`，但這個 benchmark 包含非常慢的 org baseline，不應每個 wave 預設執行。
- 只有在兩個實作都各自獨立通過二進位驗證後，timing comparison 才算有效。
- 固定 benchmark 指令為：
  `python3 run_verify_timed.py 65536 --repeats 1`
- 一般情況只在 wave 1 跑一次固定 benchmark；wave 2..N 預設不要重跑固定 benchmark。
- wave 2..N 應先跑 exact verification，必要時只做 improve-only targeted timing，並從 `log.md`
  讀取既有 org/current-best 資料作為比較背景。
- 只有當本輪 improve-only timing 顯示有機會刷新 trusted best，或使用者明確要求完整 benchmark 證據時，
  才在 wave 2..N 重跑固定 benchmark。
- fixed benchmark 不再是 Stop hook 的續跑 gate；重 benchmark 應由 wave 本身或 campaign 結束後執行。
- trusted best 判定仍由人工或後續 controller 流程的 order-balanced benchmark 決定，不在 Stop hook 內執行。
- 只有在 file-scope check 與 exact 驗證都通過之後，Stop hook 才能消耗 controller-owned wave budget 並把狀態推進到下一輪。
- 如果 file-scope check 顯示本輪沒有改到 `algorithms/pi_algo_improve-by-agent.py`，controller 可以把這輪當成
  diagnosis-only wave：不跑 benchmark，仍消耗一個 wave budget，並由 Stop hook 直接續跑下一輪。

## 覆寫規則

- 只有在使用者明確要求修改其他檔案時，才能違反上述規則。
