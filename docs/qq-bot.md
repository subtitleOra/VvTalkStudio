# QQ 群聊机器人

在配置的群里，`@机器人 今晚聊点什么` 会收到一条 AI 文字回复。`@机器人 /语音 用一句话打个招呼` 会把 AI 的中文短句交给 VvTalk 和 ACE Studio 合成，再作为群内可播放的语音回复。合成或上传失败时会改回文字。每个群至少间隔 5 秒处理一次回复，语音请求至少间隔 30 秒。

机器人单独在终端运行。关闭进程即停止接收群消息。只有被 @ 的文字和同群最近三轮机器人对话会传给配置的 AI 服务。对话上下文存在本次进程内存里，合成文件完成后会清理。

## 准备与运行

1. 在 QQ 开放平台创建机器人，将其加入有权限的测试群。准备 `AppID` 和 `AppSecret`，开启群 @ 机器人消息能力。如平台要求 IP 白名单，添加运行这台 Mac 的公网出口 IP。[QQ 官方接入说明](https://bot.q.qq.com/wiki/develop/api-v2/)
2. 在仓库目录安装可选依赖。以下命令假定已按原生版构建说明准备 Python 3.12 和 `.venv`。

   ```bash
   .venv/bin/python -m pip install -r requirements-qq.txt
   export VVTALK_QQ_APP_ID='在此填写 AppID'
   printf 'QQ AppSecret '
   read -r -s VVTALK_QQ_APP_SECRET
   export VVTALK_QQ_APP_SECRET
   printf '\n'
   .venv/bin/python qq_bot.py --discover-groups
   ```

3. 在目标群发一条 @ 机器人消息，复制终端显示的群 OpenID，然后按 `Ctrl+C` 退出发现模式。OpenID 是机器人接口标识，和 QQ 群号不同。
4. 设置允许的群和模型。模型需提供兼容的 `/chat/completions` 接口。填接口基址，例如 `https://你的服务地址/v1`，本地模型也可使用回环 HTTP 地址。如果模型需要 API Key，在同一终端输入。密钥只留在本机终端。

   ```bash
   export VVTALK_QQ_GROUPS='刚才取得的群 OpenID'
   export VVTALK_AI_BASE_URL='https://你的服务地址/v1'
   export VVTALK_AI_MODEL='该服务里的模型名'
   printf 'AI API Key '
   read -r -s VVTALK_AI_API_KEY
   export VVTALK_AI_API_KEY
   printf '\n'
   .venv/bin/python qq_bot.py
   ```

   可以用逗号列出多个群 OpenID。首次测试先用文字确认 QQ 和 AI 都已接通。

5. 如需语音，在 ACE Studio 开启 External Agent Access，保存一个专供机器人使用的空白 `.acep`，并在 ACE Studio 打开它。确认账号能使用 VvTalk 的默认中文声库。退出机器人后设置路径，再启动。

   ```bash
   export VVTALK_QQ_ACE_PROJECT='/绝对路径/QQ机器人待机.acep'
   .venv/bin/python qq_bot.py
   ```

   机器人只在 ACE 当前打开这个专用工程且无未保存修改时启动合成。任务结束后会尝试切回专用工程。合成时请等任务完成再切换或编辑 ACE 工程。

要指定中文声库，在 ACE 运行并启用 External Agent Access 时执行 `.venv/bin/python qq_bot.py --list-voices`。将列表左侧的标识写入 `export VVTALK_QQ_ACE_VOICE='模型:声库:种子'` 后再启动机器人。未指定时使用中文默认声库。

语音以 SILK 上传，通过原 @ 消息的 ID 回复。同一套接入支持群聊测试，实际发送能力由 QQ 开放平台授予的应用权限决定。[QQ 富媒体接口](https://github.com/tencent-connect/bot-docs/blob/main/docs/develop/api-v2/server-inter/message/send-receive/rich-media.md#用于群聊) · [QQ 官方 SDK 的本地媒体上传说明](https://github.com/tencent-connect/qqbot-nodejs/blob/main/USAGE.md#10-媒体上传与发送)
