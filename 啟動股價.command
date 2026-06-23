#!/bin/bash
# 雙擊此檔即可開啟「明爸分類股價」（本機伺服器模式）。
# 用 http://localhost 開啟，瀏覽器才不會擋住抓股價；按「抓最新股價並更新K線檔」會【自動存檔】，免另存對話框。
# 使用中請保持這個黑色視窗開著；看完要關閉，按 Ctrl+C 或直接關掉視窗即可。

cd "$(dirname "$0")" || exit 1
PORT=8910
PAGE="1.html"
PAGE="2.html"

PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
  echo "找不到 Python。請先在終端機執行 xcode-select --install 安裝，再雙擊本檔。"
  read -r -p "按 Enter 關閉..."
  exit 1
fi

echo "====================================="
echo " 明爸分類股價 — 本機伺服器（含自動存檔）"
echo " 網址： http://localhost:$PORT/$PAGE"
echo " 視窗請保持開啟；要關閉按 Ctrl+C"
echo "====================================="

# 過 1 秒自動用預設瀏覽器打開頁面
( sleep 1; open "http://localhost:$PORT/$PAGE" ) &

# 啟動本機伺服器（會停在這裡執行，直到關閉）
"$PY" 股價伺服器.py
