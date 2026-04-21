# 連續優化初始化提示

在開始每一輪 optimization wave 之前：

- 如果這是新 campaign 的第一輪，先確認已執行
  `python3 .codex/wave_control_init.py`，讓 controller state 對齊新的 request。
- 先閱讀 `.codex/wave_request.json`，確認目前 active campaign 的 `request_id`、
  `requested_waves`、`goal`、`continue_command`。
- 先閱讀 `.codex/wave_project.json`，確認本專案的 allowed edit targets、required edit
  targets、prompt context files、verification command。
- 確認 `.codex/config.toml` 已啟用 native Codex hooks，否則 Stop hook continuation
  不會可靠運作。
- 先閱讀 `.codex/wave_state.json`，確認 controller state 已和目前 request 對齊；
  第一輪由 `.codex/wave_start.py` 從 `queued` 轉成 `running`，後續 wave 會由 Stop hook
  直接轉成 `running` 並要求同一個 Codex CLI session 繼續。
- 先閱讀 `docs/task.md`，並嚴格遵守其中所有規範。
- 再閱讀 `log.md`，確認目前 best known result，並將其視為本輪要挑戰的目標。
- 只執行一個 wave，完成後自然停止，讓 Stop hook 更新 state；若還有剩餘 wave，Stop hook
  會用 native Codex `decision: "block"` 指向下一輪 materialized prompt 並要求繼續。
- org 基準量測速度很慢；一般情況只在 wave 1 跑一次完整 `run_verify_timed.py` 作為 campaign
  參考。wave 2..N 不要預設重跑包含 org baseline 的 fixed benchmark，應先用 exact verification
  與 improve-only targeted timing 判斷方向，並引用 `log.md` 既有 org/current-best 資料。
- 如果本輪最後沒有對 `algorithms/pi_algo_improve-by-agent.py` 做出有效修改，Stop hook 會把這輪記成
  diagnosis-only wave：把問題與下一步方向追加到 `log.md`、消耗一個 wave budget，並在還有剩餘 wave 時直接續跑下一輪。
