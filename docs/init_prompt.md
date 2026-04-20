# 連續優化初始化提示

在開始每一輪 optimization wave 之前：

- 如果這是新 campaign 的第一輪，先確認已執行
  `python3 .codex/wave-control-init.py`，讓 controller state 對齊新的 request。
- 先閱讀 `.codex/wave_request.json`，確認目前 active campaign 的 `request_id`、
  `requested_waves`、`goal`、`continue_command`。
- 先閱讀 `.codex/wave_state.json`，確認 controller state 已和目前 request 對齊；
  第一輪通常是 `queued`，後續 wave 可能是 `queued` 或 `running`，但不應殘留其他 request
  的 active campaign。
- 先閱讀 `docs/task.md`，並嚴格遵守其中所有規範。
- 再閱讀 `log.md`，確認目前 best known result，並將其視為本輪要挑戰的目標。
- 只執行一個 wave，完成後自然停止，讓 Stop hook 決定是否繼續下一輪。
