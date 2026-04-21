# 自動優化工作流 Gap List

本文比對使用者原始期待的自動優化流程與目前 repository 內控制面的實作狀態，目標是明確列出已符合、部分符合、以及需要修正或泛化的差異。

## 原始設計摘要

使用者期待的流程如下：

1. 使用者手動修改 `.codex/wave_request.json`。
2. 執行 `.codex/wave_control_init.py` 校正 `.codex/` 下的控制面參數。
3. 使用者將 `docs/init_prompt.md` 的內容與 `docs/task.md` 一起餵給 Codex CLI。
4. Codex CLI 執行 `task.md` 任務，直到觸發 Codex Stop hook。
5. Stop hook 明確表示目前還剩下 `n-1` 個 wave，hook control 再把 `task.md` 餵給 Codex CLI，重複步驟 4，直到 `remaining_waves == 0`。
6. 當 `remaining_waves == 0` 時，Codex 被 Stop hook 觸發並結束整個優化流程。

補充期待：

- `algorithms/` 與 `run_verify_timed.py` 只是 demo 任務；控制面應該可被其他專案重用。
- 控制面要收斂到稀缺且泛用的狀態與規則，不應綁死 pi benchmark。
- 第 4 步開始後，希望持續保持在 Codex CLI 流程中，完整看到 wave 1 到 wave N 的輸出。

## 現況總覽

本 spec 的落地決策是採用 Hook-driven 架構：wave 1 由 foreground bootstrap 啟動，
後續 wave 由 Stop hook 透過 native Codex `decision: "block"` 指向下一輪
materialized prompt，讓同一個 Codex CLI session 繼續。

目前主要元件分工：

- `.codex/wave_request.json`：使用者修改的 campaign request。
- `.codex/wave_control_init.py`：初始化或切換 active campaign，建立 `.codex/wave_state.json`。
- `.codex/wave_project.json`：project policy，定義允許修改範圍、必要修改目標、prompt context、驗證命令。
- `.codex/wave_state.json`：controller-owned runtime state。
- `.codex/config.toml`：啟用 native Codex hooks，必須包含 `[features].codex_hooks = true`。
- `.codex/wave_start.py`：foreground bootstrap，啟動 wave 1。
- `.codex/wave_stop.py`：Stop hook，負責驗證目前 wave、消耗 wave budget、更新 state，並在還有剩餘 wave 時續跑下一輪。
- `.codex/wave_recover.py`：修復 runtime 已結束但 controller state 仍卡在 `running`/`validating` 的情況。
- `.codex/wave_loop_run.py`：舊 runner-driven 入口的 deprecated compatibility shim。
- `.codex/local/prompts/<request_id>/wave-<n>.md`：每輪實際餵給 Codex CLI 的合成 prompt。

## Gap List

### G1: Stop hook 沒有直接續跑下一個 wave

原始設計：

- Stop hook 在 wave 結束時看到 `remaining_waves > 0`。
- hook control 直接把 `task.md` 再餵給 Codex CLI。
- 流程由 hook 自己串接 wave 1 到 wave N。

落地後實作：

- Stop hook 驗證目前 wave 後，把 state 推進到下一輪 `running` 或最終 `completed`。
- Stop hook 在 `remaining_waves > 0` 時回傳 `decision: "block"`，`reason` 內引用下一輪 materialized prompt 檔。
- 同一個 Codex CLI session 讀取該 prompt 後繼續下一輪。

影響：

- 功能上符合 hook control 續跑 wave 的原始期待。
- 不需要 detached child process，因此保留 foreground 輸出與 session 連續性。

建議：

- 使用 native Codex Stop continuation contract：`decision: "block"` + `reason`。
- `reason` 只引用下一輪 prompt 檔，不內嵌完整 prompt。

結論：

- 已決策為 Hook-driven。

### G2: 不是同一個 Codex CLI process 持續跑完 wave 1 到 wave N

原始設計：

- 第 4 步開始後，希望一直保持在 Codex CLI 裡面。
- 使用者希望完整看到 wave 1 到 wave N 的輸出。

落地後實作：

- wave 1 由 `.codex/wave_start.py` 啟動 foreground `codex exec`。
- 後續 wave 由 Stop hook block 同一個 Codex CLI session 繼續。

影響：

- 符合「同一個 terminal 看完整輸出」。
- 符合「同一個 Codex CLI session 由 Stop hook 續跑」。

建議：

- 將需求表述改成「同一個 foreground terminal session 看到完整 wave 1..N 輸出」。
- 如果必須維持同一個 Codex process，需要確認 Codex hook 的 `continue` 語義是否能安全地注入下一輪任務，而不是啟動新的 `codex exec`。

結論：

- 已符合。

### G3: `init_prompt.md` 與 `task.md` 不是直接各自餵給 CLI，而是合成 prompt

原始設計：

- 使用者把 `init_prompt.md` 的內容，也同時把 `task.md` 餵給 Codex CLI。

目前實作：

- controller 讀取 `.codex/wave_request.json`、`docs/init_prompt.md`、`docs/task.md`、`log.md`、`last_result`。
- controller 合成 `.codex/local/prompts/<request_id>/wave-<n>.md`。
- `continue_command` 實際讀取的是合成後的 prompt path。

影響：

- 語義上包含了 `init_prompt.md` 與 `task.md`。
- 實作上已從「餵兩份原始檔」變成「餵一份 controller 生成的完整 wave prompt」。
- 合成 prompt 對多 wave continuity 有幫助，因為可以帶入 `wave_number`、`remaining_waves`、`last_result`。

建議：

- 保留合成 prompt 設計，但在 spec 與 README 中明確定義「每輪餵給 Codex CLI 的輸入是 controller materialized prompt」。
- 避免文件再暗示直接手動把 `task.md` 餵給 CLI。

結論：

- 目前是「語義符合，實作不同」。

### G4: 控制面尚未泛用化，仍綁定 pi demo 專案

原始設計：

- `algorithms/` 只是 demo code。
- `run_verify_timed.py` 只是 demo benchmark。
- 未來任何專案只要能收斂到稀缺控制面，都可以套用此流程。

落地後實作：

- `.codex/wave_project.json` 保存 project-specific policy。
- `.codex/wave_stop.py` 從 policy 讀取 allowed targets、required targets、verification command、prompt context files、log file。

影響：

- 換專案時主要改 `.codex/wave_project.json`、`docs/task.md`、`docs/init_prompt.md`。
- controller 不再直接寫死 pi verification command 或 target path。

建議：

- 將 demo-specific 設定移出 `.codex/wave_stop.py`。
- 使用 `.codex/wave_project.json` 作為必要 project policy。
- 建議可配置項：
  - allowed edit targets
  - ignored paths
  - verification command
  - benchmark command
  - success gate
  - log file path
  - prompt context files
  - finalization command
  - diagnosis-only policy

結論：

- 已完成第一階段泛用化。

### G5: Stop hook 已成為續跑核心

原始設計：

- Stop hook 是流程循環的核心。
- Stop hook 不只驗證，也負責把下一輪交回 Codex CLI。

落地後實作：

- Stop hook 負責：
  - 檢查 request/state binding。
  - 檢查修改範圍。
  - 執行 exact correctness gate。
  - 消耗 wave budget。
  - 更新 `.codex/wave_state.json`。
  - 若還有剩餘 wave，materialize 下一輪 prompt。
  - 回傳 native Codex `decision: "block"`，要求同一個 Codex session 讀取下一輪 prompt 後繼續。
  - 寫入 `.codex/local/wave_events.jsonl`。

影響：

- 控制面符合原始 hook-driven mental model。
- 不需要 detached process 或舊 foreground runner loop。

建議：

- 保持 Stop hook 的續跑方式為 `decision: "block"`，不要在 hook 中啟動 detached child process。
- 保留 `.codex/wave_start.py` 只作為 wave 1 foreground bootstrap。

結論：

- 已決策並落地為 Hook-driven。

### G6: Active campaign conflict 的處理是新增行為，原始設計未明確定義

原始設計：

- 使用者修改 request 後執行 initializer。
- 未明確說明舊 campaign 仍為 `queued`、`running`、`validating` 時該如何處理。

目前實作：

- initializer 預設將目前 `.codex/wave_request.json` 視為 source of truth。
- 若舊 request 仍 active，預設 abort 舊 campaign 並切換到新 request。
- 可用 `--no-abort-active` 改成拒絕初始化。

影響：

- 實務上解決 stale campaign 或切換 request 的問題。
- 但可能讓使用者誤以為舊 OS process 也被 kill；目前 abort 只是 controller state abort。

建議：

- 在 spec 中定義 active conflict policy：
  - default: abort old controller state and switch
  - strict: `--no-abort-active`
  - future: optionally detect and terminate old foreground bootstrap process

結論：

- 目前是「合理新增行為」，但需要明確文件化。

### G7: `wave_request.json` schema 太窄，無法承載泛用 workflow

原始設計：

- 透過 request 啟動泛用 workflow。
- 不同專案只要控制面一致就可套用。

落地後實作：

- request schema 只有：
  - `version`
  - `request_id`
  - `requested_waves`
  - `goal`
  - `continue_command`
  - `created_at`
- 專案政策與驗證行為不在 request 中，而是在 `.codex/wave_project.json`。

影響：

- request 只描述 campaign。
- project policy 由 `.codex/wave_project.json` 描述。

建議：

- 保持 `wave_request.json` 只描述 campaign。
- 使用 `.codex/wave_project.json` 作為必須存在的 project-level config。
- controller 啟動時同時讀 request 與 project config。

結論：

- 已完成第一階段拆分：campaign request 與 project policy 分離。

## 建議的目標架構

建議採用以下責任分層：

- Request layer：`.codex/wave_request.json`
- Project policy layer：`.codex/wave_project.json`
- Runtime state layer：`.codex/wave_state.json`
- Prompt materialization layer：產生 `.codex/local/prompts/<request_id>/wave-<n>.md`
- Wave 1 bootstrap layer：`.codex/wave_start.py`
- Stop continuation layer：`.codex/wave_stop.py`
- Audit layer：`.codex/local/wave_events.jsonl`

正式採用 Hook-driven，原因：

- 可以在同一 terminal 看到 wave 1 到 wave N 的完整輸出。
- 避免 Stop hook detached process 造成輸出不可見。
- 避免 Stop hook timeout 或 recursive launch 問題。
- Stop hook 透過 native `decision: "block"` 指令同一個 Codex session 繼續，不啟動子行程。

Hook-driven 實作約束：

- Stop hook 輸出 `decision: "block"` + `reason`。
- `reason` 引用下一輪 materialized prompt path，不內嵌完整 prompt。
- Stop hook 不使用 `subprocess.Popen` 啟動 detached Codex CLI。
- `wave_start.py` 必須在啟動前檢查 native hooks 已啟用，並在 child exit 後確認 state 有被 Stop hook 推進。
- 若 child exit 後 state 仍停在 active 狀態，`wave_start.py` requeue 同一 wave 並 non-zero 結束。
- `wave_control_init.py --run` 對 stale active state 先執行 recovery，再啟動 recovered queued wave。

## 優先級

### P0: 已決策

- 正式架構是 Hook-driven。
- 文件與術語改為「Stop hook 驗證並續跑下一輪」。

### P1: 已完成第一階段

- 抽出 pi-specific constants。
- 新增 project policy config。
- 讓驗證命令、允許修改範圍、prompt context files、log policy 可配置。

### P2: 已更新

- 明確說明 initializer conflict policy。
- 明確說明 abort 是 controller state abort，不一定終止 OS process。
- 明確說明每輪 Codex CLI 輸入是 materialized prompt。
- 明確說明同一 Codex CLI session 由 Stop hook block 續跑。

## 判定結果

目前控制面已採用 hook-driven 多 wave 優化架構。

整體判定：

- 多 wave execution：已達成。
- 使用者單 terminal 觀看完整 wave output：已達成。
- Stop hook 自行續跑下一輪：已達成，透過 native `decision: "block"`。
- `init_prompt.md` + `task.md` 同時餵入：透過合成 prompt 達成。
- 泛用 workflow engine：第一階段達成。
- pi demo 與控制面解耦：第一階段達成，project policy 已外部化。

後續若要更泛用，可繼續把 log formatting 與 benchmark evidence policy 做成更細的可插拔設定。
