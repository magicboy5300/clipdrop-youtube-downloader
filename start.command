#!/bin/bash
cd "$(dirname "$0")"
python3 youtube_downloader.py
exit_code=$?
if [ "$exit_code" -ne 0 ]; then
  echo
  echo "启动失败。请确认已安装 Python 3，并且首次运行时可以连接网络下载依赖。"
  read -r -p "按回车关闭此窗口… " _
fi
