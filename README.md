# hook_loop_exp

這個 repository 是一個 Codex hook-driven 多輪自動優化工作流的 demo。

目前 demo 任務是優化 65536 位數 pi 的產生速度；`algorithms/` 和
`run_verify_timed.py` 都只是示範任務。真正要保留的是 `.codex/` 裡的稀缺控制面：
使用者只更新 request，controller 負責初始化、啟動 wave、Stop hook 驗證與續跑。

## 目錄結構

- `algorithms/`：pi baseline 與待優化實作。
- `tools/`：驗證與 benchmark 入口。
- `reference/`：固定二進位參考答案。
- `docs/`：任務規則與 wave 起始提示。
- `.codex/`：Codex hook 與 wave controller。
- `log.md`：已驗證 benchmark 與最佳結果紀錄。
- `AGENTS.md`：repo 層級的 Codex 操作規則。

## 重要檔案

- `algorithms/pi_algo_org.py`：原始 baseline。
- `algorithms/pi_algo_improve-by-agent.py`：一般 optimization wave 唯一可改的演算法檔。
- `tools/verify_pi_bin.py`：比對 `reference/pi_65536.bin` 的 byte-for-byte 驗證器。
- `tools/run_verify_timed.py`：包含 org/improve 的完整 compatibility benchmark。
- `docs/task.md`：任務範圍、驗證規則、benchmark 規則。
- `docs/init_prompt.md`：每個 wave 開始前的操作提示。
- `.codex/wave_request.json`：使用者唯一需要手動更新的 campaign request。
- `.codex/wave_project.json`：專案 policy，定義允許修改範圍、prompt context、驗證命令。
- `.codex/wave_state.json`：controller-owned runtime state，不要手動改。
- `.codex/config.toml`：啟用 Codex native hooks。
- `.codex/wave_control_init.py`：初始化或恢復 controller state，並可直接起跑。
- `.codex/wave_start.py`：wave 1 foreground bootstrap。
- `.codex/wave_stop.py`：Stop hook 驗證與續跑控制。
- `.codex/wave_recover.py`：修復 runtime 已結束但 state 卡在 `running` / `validating` 的情況。
- `.codex/local/wave_events.jsonl`：本地 append-only audit journal，不進 git。

## 一般使用方式

正常流程只有兩步：

1. 手動更新 `.codex/wave_request.json`。
2. 執行：

```bash
python3 .codex/wave_control_init.py --run
```

這個命令會：

- 讀取 `.codex/wave_request.json`。
- 讀取 `.codex/wave_project.json`。
- 校正 `.codex/wave_state.json`。
- materialize wave 1 prompt 到 `.codex/local/prompts/<request_id>/wave-1.md`。
- 啟動 wave 1 的 foreground `codex exec`。
- 後續 wave 由 Stop hook 用 native `decision: "block"` 接續同一個 Codex CLI session。

## Request 格式

`.codex/wave_request.json` 應填入：

```json
{
  "version": 2,
  "request_id": "new-request-id",
  "requested_waves": 4,
  "goal": "Describe the optimization goal.",
  "continue_command": "codex exec --dangerously-bypass-approvals-and-sandbox --cd \"${PROJECT_ROOT}\" - < \"${TASK_FILE}\"",
  "created_at": "2026-04-21T00:00:00Z"
}
```

`request_id` 應在每次新 campaign 時更新。`requested_waves` 是本次最多要跑的 wave 數。

## Hook-Driven 流程

```text
wave_control_init.py --run
  -> 建立或恢復 wave_state
  -> materialize wave prompt
  -> wave_start.py 啟動 wave 1 的 codex exec
  -> Codex 執行 exactly one wave
  -> Stop hook 觸發 wave_stop.py
  -> exact verification / file-scope check
  -> remaining_waves > 0 時回傳 decision:block 指向下一個 prompt
  -> 同一個 Codex CLI session 繼續下一個 wave
  -> remaining_waves == 0 時 state=completed
```

## Controller 規則

- `.codex/wave_request.json` 是 campaign source of truth。
- `.codex/wave_project.json` 是 project policy；active campaign 期間不可修改。
- `.codex/wave_state.json` 是 runtime state；不要手動修改。
- `.codex/config.toml` 必須啟用：

```toml
[features]
codex_hooks = true
```

- 如果同一 request 仍是 `queued`，重跑 `wave_control_init.py --run` 會 resume，不會 abort。
- 如果 state 是 `running` / `validating`，initializer 會先檢查是否還有 live runtime。
- 若 runtime 已結束但 state 卡住，會先走 `.codex/wave_recover.py`。
- 若 runtime 還活著，會拒絕重複啟動，避免 duplicate campaign。
- 如果 `codex exec` 結束但 Stop hook 沒有推進 state，`wave_start.py` 會 requeue 同一 wave 並 non-zero 結束。
- `.codex/wave_loop_run.py` 只保留為舊 runner-driven 模型的相容 shim。

## 驗證與 Benchmark

Stop hook 的續跑 gate 只要求 exact verification：

```bash
python3 algorithms/pi_algo_improve-by-agent.py 65536 | python3 tools/verify_pi_bin.py --exact
```

完整 compatibility benchmark 是：

```bash
python3 run_verify_timed.py 65536 --repeats 1
```

這個 benchmark 會跑很慢的 `algorithms/pi_algo_org.py`。因此 policy 是：

- wave 1 可以跑一次完整 benchmark 作為 campaign 參考。
- wave 2..N 不要預設重跑完整 org/improve benchmark。
- wave 2..N 優先使用 exact verification + improve-only targeted timing。
- 只有可能刷新 trusted best，或使用者明確要求完整證據時，才重跑完整 benchmark。

## 手動 Debug 指令

只初始化、不起跑：

```bash
python3 .codex/wave_control_init.py
```

手動啟動目前 queued wave：

```bash
python3 .codex/wave_start.py
```

修復 stale `running` / `validating` state：

```bash
python3 .codex/wave_recover.py
```

檢查目前 state：

```bash
cat .codex/wave_state.json
```

檢查 audit journal：

```bash
tail -n 20 .codex/local/wave_events.jsonl
```

## 測試

控制面測試使用 Python 標準庫 `unittest`：

```bash
python3 -m unittest discover -s tests
```

語法檢查：

```bash
python3 -m py_compile \
  .codex/wave_control_init.py \
  .codex/wave_start.py \
  .codex/wave_stop.py \
  .codex/wave_recover.py \
  tests/test_wave_control.py
```

diff whitespace 檢查：

```bash
git diff --check
```
