# AwayCam

Webカメラで「PCの前に人がいるか」を判定し、離席中は指定画像をフルスクリーン表示、
着席したら自動で解除する常駐アプリ。

**カメラ映像はこのPC内でのみ処理され、保存も外部送信も一切行いません。**
これは画面ロックではなく通常のデスクトップアプリであり、セキュリティ機能ではありません。

## セットアップ

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe scripts/download_model.py   # 人物検出モデルの取得（初回のみ）
.venv/Scripts/python.exe run.py
```


## 構成

| ファイル | 役割 |
|---|---|
| `awaycam/settings.py` | `settings.json` の読み書き・検証・既定値 |
| `awaycam/core/camera.py` | カメラの開閉・自動再接続・解放 |
| `awaycam/core/detector.py` | 人物検出のファクトリ（方式を切り替える） |
| `awaycam/core/detection_types.py` | 検出結果の共通型と基底クラス・距離フィルタ |
| `awaycam/core/detector_yolo.py` | YOLO26 による人物検出（既定） |
| `awaycam/core/detector_mediapipe.py` | MediaPipe による人物検出（軽量な代替） |
| `awaycam/core/presence.py` | 在席・離席の判定（状態機械） |
| `awaycam/core/input_monitor.py` | キーボード / マウス操作の検知 |
| `awaycam/core/audio.py` | 離席中の出力音声ミュート |
| `awaycam/core/fullscreen_monitor.py` | 全画面アプリの検出（自動一時停止） |
| `awaycam/core/engine.py` | 上記を束ねる判定ワーカースレッド |
| `awaycam/ui/overlay.py` | 離席時のフルスクリーン画像表示 |
| `awaycam/ui/main_window.py` | メイン画面（状態表示） |
| `awaycam/ui/settings_window.py` | 設定画面 |
| `awaycam/ui/camera_preview.py` | 設定画面のカメラプレビュー |
| `awaycam/ui/tray.py` | タスクトレイ（状態インジケーター） |
| `awaycam/autostart.py` | Windows 起動時の自動実行 |
| `awaycam/single_instance.py` | 多重起動の防止 |
| `awaycam/ui/theme.py` | ダーク / ライトのスタイル |
| `awaycam/app.py` | 全体の配線 |