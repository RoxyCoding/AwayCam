# AwayCam のビルド（exe 化）

## 手順

```bash
python -m pip install pyinstaller
python -m PyInstaller AwayCam.spec --noconfirm
```

出力: `dist/AwayCam/AwayCam.exe`

## 構成の選び方

**どの Python でビルドするかで、同梱される torch が決まります。**
AwayCam 自体の設定ではなく、ビルド環境で決まる点に注意してください。

| ビルドに使う Python | 同梱される torch | 出力サイズ | 推論速度 |
|---|---|---|---|
| CUDA 版 torch が入った環境 | `torch+cu124`（4.35GB） | 約 5GB | 約 9ms（GPU） |
| CPU 版 torch が入った環境 | `torch+cpu`（0.46GB） | 約 1.3GB | 約 46ms |

GPU 版は NVIDIA GPU のある PC でのみ速度の利点があります。他の PC へ配布する
なら CPU 版でビルドしてください。

## フォルダ形式（onedir）にしている理由

- 常駐アプリなので起動の速さを優先する（onefile は毎回の展開で数十秒かかる）
- `settings.json` と `logs/` が exe の隣に置かれ、利用者が直接触れる
- `models/` のモデルを差し替えられる

## exe 実行時のファイルの置き場所

`awaycam/paths.py` が凍結状態を判定して切り替えます。

| | 通常実行 | exe 実行 |
|---|---|---|
| `settings.json` / `logs/` | リポジトリのルート | **exe と同じフォルダ** |
| モデル | `models/` | exe の隣の `models/` を優先し、無ければ同梱分 |

`__file__` 基準のままにすると、exe では一時展開先を指してしまい、
設定が保存できなかったり起動のたびに消えたりします。

## 自動起動について

exe 版では、レジストリに **exe のパスが直接**登録されます
（`"...\AwayCam.exe" --minimized`）。Python 版から exe 版へ乗り換えた場合は、
設定画面で自動起動を一度オフ→オンにするか、`autostart.sync_if_stale()` が
起動時に自動で登録し直します。

## 再ビルド時の注意

`--noconfirm` は `dist/AwayCam` を作り直すため、**exe の隣に置かれた
`settings.json` と `logs/` は消えます。** 調整済みの設定を引き継ぐなら、
ビルド前後で退避・復元してください。

```powershell
Copy-Item dist\AwayCam\settings.json $env:TEMP\awaycam_settings.json -Force
python -m PyInstaller AwayCam.spec --noconfirm
Copy-Item $env:TEMP\awaycam_settings.json dist\AwayCam\settings.json -Force
```

また、AwayCam が起動していると exe を上書きできません。ビルド前に
トレイから終了させてください。多重起動防止があるため、Python 版が
動いたままだと exe を起動しても即終了します。

## 注意点

- **UPX 圧縮は使っていません。** torch の DLL を壊すことがあるためです。
- `console=False` にしているので、実行してもコンソール窓は出ません。
  ビルドの問題を調べたいときは spec の `console` を一時的に `True` にしてください。
- ビルドには数分〜十数分かかります（CUDA 同梱時は特に長くなります）。
