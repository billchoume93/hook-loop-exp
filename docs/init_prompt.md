# 連續優化初始化提示

在開始每一輪 optimization wave 之前：

- 先閱讀 `.codex/wave_request.json`，確認目前 active campaign 的 `request_id`、
  `requested_waves`、`goal` 與 `target_file`。
- 先閱讀 `docs/task.md`，並嚴格遵守其中所有規範。
- 再閱讀 `log.md`，確認目前 best known result，並將其視為本輪要挑戰的目標。
- 只執行一個 wave，完成後自然停止，讓 Stop hook 決定是否繼續下一輪。
