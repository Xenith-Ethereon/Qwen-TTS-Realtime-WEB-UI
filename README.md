# Qwen TTS Realtime WEB UI

千问 TTS Realtime 的声音复刻和语音合成的简易 Web 面板。

上传一段录音就能复刻音色，然后用复刻的音色把文字转成语音。根据官网文档写了个demo，方便测试不同音频的复刻质量。

仅供个人学习使用。

## 用法

```bash
pip install -r requirements.txt
```

编辑 `.env`，填入你的 阿里云百炼 API Key：

```
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx
```

启动：

```bash
python app.py
```

浏览器打开 `http://localhost:5000`。

## 页面说明

左边是**声音复刻**面板：

- 上传一段 10~20 秒的清晰录音（WAV / MP3 / M4A）
- 填个音色名字，选模型，点创建
- 创建好的音色会出现在下方列表，可以一键填入右侧合成面板

右边是**语音合成**面板：

- 输入文字，选音色和模型，点合成
- 合成完直接在页面播放，音频同时保存在 `outputs/` 目录

## 支持的模型

| 模型 | 类型 | 说明 |
|---|---|---|
| `qwen3-tts-vc-realtime-2026-01-15` | 流式 | 最新版复刻模型 |
| `qwen3-tts-vc-realtime-2025-11-27` | 流式 | 旧版复刻模型 |
| `qwen3-tts-vc-2026-01-22` | 非流式 | 适合生成完整音频文件 |

> 创建音色时选的 `target_model` 要和合成时的模型一致，不然会报错。

## 项目结构

```
├── .env                 # API Key 配置
├── app.py               # 后端
├── requirements.txt     # 依赖
├── templates/
│   └── index.html       # 前端页面
└── outputs/             # 合成的音频文件
```

## 音频要求

用来复刻的录音需要：

- 时长 10~20 秒，最长 60 秒
- 采样率 ≥ 24kHz，单声道
- 文件 < 10MB
- 内容清晰，没有背景噪音

## API Key

去 [阿里云百炼](https://help.aliyun.com/zh/model-studio/get-api-key) 申请。
