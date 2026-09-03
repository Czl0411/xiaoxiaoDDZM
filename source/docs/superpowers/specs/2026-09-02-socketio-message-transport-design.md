# Socket.IO 消息传输改造设计

## 目标

将 DZMMBot 的底层消息读取、文字发送和图片发送从 DOM 操作与消息历史轮询切换为 `python-socketio.AsyncClient`。Socket.IO 协议、事件、消息结构、确认机制和恢复行为参考只读项目 `/Users/zhijian/Desktop/DDZM`，但实现必须适配 DZMMBot 当前的 asyncio 调度器。DDZM 的任何文件都不得修改。

## 范围

本次改造包括：

- 使用浏览器现有登录态获取 access token、Cookie 和机器人账号资料。
- 通过 Socket.IO 连接 `ws/matching`，监听实时消息并加入已配置群聊。
- 支持主群、悬赏群和图片群的实时读取与独立发送。
- 通过 `message:send` 发送文字和图片消息并校验 ACK。
- 通过 `chatroom.uploadImage` 上传本地图片，再发送标准 image content。
- 解析文字、图片和引用消息，使用平台消息 ID 和用户 ID。
- 处理断线、重新鉴权、重新连接、重新加入房间和关闭清理。
- 更新运行依赖、PyInstaller 收集项和自动化测试。

以下内容不在本次范围：

- 私聊房间和主动私聊功能。
- 消息撤回功能。
- 回读 Socket.IO 连接之前的历史消息。
- 修改现有规则、游戏、积分或 AI 业务逻辑。
- 修改 DDZM 参考项目。

## 现状

`DzmmAdapter` 当前通过 Playwright 扫描群聊 DOM，调用 tRPC 历史接口补充平台消息 ID，再按文本、头像和昵称进行身份对齐。文字发送通过填写输入框并按 Enter，图片发送通过文件输入框和发送按钮完成。该实现依赖网页结构，容易受到隐藏输入框、React 重建、重复文本和页面切换影响。

DZMMBot 已经使用 asyncio，调度器按群调用异步的 `read_recent_messages()`、`send_message()` 和 `send_image()`。因此采用 `socketio.AsyncClient`，避免同步 Socket.IO 客户端阻塞事件循环或引入额外工作线程。

## 架构

新增 `AikdaSocketGateway`，作为 Socket.IO 协议和连接状态的唯一负责人。`DzmmAdapter` 保留现有公开异步接口，但将读写委托给网关。`BrowserController` 继续负责持久化登录浏览器，并向网关提供 token、Cookie、用户资料和图片上传能力。

依赖关系如下：

1. `BrowserController` 提供已登录的 Playwright page/context。
2. `AikdaSocketGateway` 使用浏览器登录态建立 Socket.IO 连接并维护房间。
3. `DzmmAdapter` 将配置中的群键映射到 chatroom ID，并在现有消息字典与网关消息之间转换。
4. `BotScheduler` 保持现有调用方式，不感知传输实现变化。

浏览器仍用于登录、导航、状态检查、截图调试和 HTTP 图片上传；不再用于读取消息、填写文字输入框或点击图片发送按钮。

## 鉴权与连接

网关从群聊 URL 提取 origin 和 `c` 查询参数。所有已配置群聊必须属于同一 origin，群键到 chatroom ID 的映射为：

- `main`：`dzmm.group_url`
- `bounty`：`dzmm.bounty_group_url`
- `image`：`dzmm.image_group_url`

连接前通过当前登录页面执行与 DDZM 相同的请求：

- `user.getMe` 获取机器人平台用户 ID 和显示名。
- 获取当前 Supabase access token。
- 从浏览器 context 生成目标 origin 的 Cookie 请求头。

Socket.IO 连接参数为：

- URL：群聊 origin。
- `socketio_path`：`ws/matching`。
- `auth`：`{"token": access_token}`。
- `headers.Cookie`：浏览器目标 origin 的 Cookie。
- transport：优先 `websocket`，允许 `polling` 回退。
- Socket.IO 自带自动重连关闭，由网关在下一次维护时使用新 token 显式重连。

网关监听 `message:joined`、`message:new` 和 `disconnect`。只有收到 `message:joined` 才认为连接可用。主群连接成功后仍显式维护完整房间集合；每个额外群通过 `message:join-room` 加入并要求 `success: true` 的 ACK。

## 实时消息读取

`message:new` 的 payload 必须包含 `chatroomId` 和 `message`。有效 message 至少包含：

- 字符串 `message_id`
- 字符串 `sent_by`
- ISO 格式字符串 `sent_at`
- 字典 `content`

机器人自己发送的消息直接丢弃。只接受当前已配置 chatroom ID 的事件。每条消息按 `(chatroomId, message_id)` 去重，并进入对应群键的内存队列。队列读取后清空；调度器按现有轮询节奏排空队列，不再请求历史消息。

支持的 content：

- `type=text`：要求 `text` 为字符串。
- `type=image`：要求 `url` 为绝对 HTTPS URL；可选 `alt`、`width`、`height` 必须类型合法。业务层文本使用 `[图片]`。

引用消息从 `content.reference` 读取，转换为现有的 `reply_to_message_id`、`reply_to_text` 和 `reply_to_sender` 字段。无法验证的引用字段被忽略，不丢弃主体消息。

平台 `sent_by` 是唯一身份来源。适配器将其同时写入 `user_id` 和 `platform_user_id`，并标记 `identity_source=platform`。若本地数据库已有该平台用户，则使用其昵称；否则使用稳定的 `用户-<平台ID前8位>` 占位名。身份绑定不依赖 DOM、头像、显示名或文本内容，因此改名、同名和重复文本不会串号。

适配器输出继续包含调度器当前依赖的字段，包括 `message_id`、身份字段、`sender`、`text`、`time`、`is_self`、引用字段、`source_index`、`source_stable`、`group_key` 和 `source_group`。图片元数据作为新增可选字段保留，不改变现有命令处理接口。

## 文字发送

文字发送继续执行当前的空文本、字符数和行数校验，并按群使用同一把异步发送锁。网关为每条消息生成 UUID，构造：

```json
{
  "message_id": "<uuid>",
  "sent_by": "<bot-platform-id>",
  "chatroom_id": "<chatroom-id>",
  "sent_at": "<UTC ISO timestamp>",
  "content": {"type": "text", "text": "<text>"}
}
```

发送前确认连接和目标房间已加入，然后调用 `message:send`，payload 为 `{"chatroomId": chatroom_id, "message": message}`。ACK 最长等待 3 秒。只有 ACK 为字典且 `success is true` 时返回成功。

ACK 超时、服务端拒绝、鉴权失败或传输异常均记录明确错误并返回失败。本层不自动重发已经提交的消息，以免在 ACK 丢失时产生重复回复。下一次独立发送可以触发重新连接。

## 图片发送

图片路径和扩展名继续使用当前校验规则。网关通过 Playwright context 的 API request 向目标 origin 的 `/api/trpc/chatroom.uploadImage` 提交 multipart：

- `file`：文件名、MIME 类型和文件内容。
- `chatroomId`：目标群 chatroom ID。

上传必须返回可用的 HTTPS 图片 URL；无 URL、非 HTTPS URL或 HTTP 请求失败均视为发送失败。成功后复用文字发送的连接、房间和 ACK 流程，content 为：

```json
{"type": "image", "url": "<uploaded-url>", "alt": "<filename>"}
```

文字与图片继续共享每群发送锁，保证同一群内的发送顺序。图片不再操作网页文件输入框、预览区或按钮。

## 配置变化与生命周期

启动时浏览器先启动，适配器随后根据当前配置建立网关并配置群房间。机器人处于暂停状态时可以保持连接，以便恢复时只处理恢复后的实时事件；恢复动作清空适配器当前待处理队列，避免暂停期间收到的消息在恢复后执行。

群 URL 保存或通过管理界面打开新群时，适配器重新计算群配置：

- 同 origin 的新增群加入房间。
- 已删除群停止接收和发送，并清空其待处理队列。
- origin 发生变化时关闭旧连接并按新 origin 重新建立网关。

断线事件清除认证和已加入房间状态。后续读取或发送调用执行恢复：重新调用 `user.getMe`、重新读取 access token 和 Cookie、重新连接、重新加入全部配置群。不回读断线期间的历史消息。

应用关闭顺序为：停止调度器、关闭网关、关闭浏览器、关闭数据库。浏览器 profile 重置前也必须先关闭网关，防止使用已失效的登录态。

## 错误处理与日志

错误分为三类：

- 鉴权错误：缺少用户资料或 token，提示需要登录，不进行快速重试。
- 传输错误：连接、加入房间、上传或 Socket.IO 通信失败，清理连接状态并等待后续周期恢复。
- 消息拒绝：`message:send` ACK 返回失败，记录服务端 code/error，不自动重发。

重复的连接错误使用现有调度周期自然限速，日志不得包含 token、完整 Cookie 或其他认证秘密。消息日志保留群键、消息 ID、字符数/行数和错误类别，避免记录图片二进制。

## 代码变更边界

预计新增或修改：

- 新增 `source/app/aikda_socket.py`：异步 Socket.IO 网关、消息解析和协议错误类型。
- 修改 `source/app/browser.py`：提供 token、tRPC、Cookie、图片上传能力，并管理网关关闭时机所需的浏览器接口。
- 修改 `source/app/dzmm_adapter.py`：配置房间、转换入站消息、委托文字和图片发送，移除被替代的 DOM 读写路径。
- 修改 `source/app/scheduler.py`：暂停/恢复时清空待处理实时消息，关闭时释放网关。
- 修改 `source/main.py`：启动和关闭生命周期接入。
- 修改 `source/requirements.txt`：加入兼容版本的 `python-socketio[asyncio_client]`。
- 修改 `source/DZMMBot.spec`：收集 Socket.IO、Engine.IO 及其运行依赖。
- 新增网关测试并更新受传输变化影响的适配器、调度器和打包测试。

删除仅限 `DzmmAdapter` 内已经没有调用者的 DOM 消息扫描、历史消息对齐、输入框文字发送和文件输入框图片发送代码及其专属状态。页面调试与选择器管理相关代码若仍被管理界面使用则保留。不得顺带重构业务代码。

## 测试策略

按照 TDD 逐项实现：

1. 使用假 AsyncClient 验证连接路径、auth、Cookie、事件注册和 `message:joined` 门槛。
2. 验证 main、bounty、image 房间配置、加入 ACK 和群键路由。
3. 验证文字、图片、引用消息解析，自发消息过滤、非法 payload 丢弃和消息 ID 去重。
4. 验证适配器输出兼容现有调度器字段，并以平台 ID 作为稳定身份。
5. 验证文字消息对象、每群串行、3 秒 ACK、成功与拒绝结果。
6. 验证图片 multipart 上传、URL 校验和 image content 发送。
7. 验证断线后使用新 token 重连并重新加入所有房间，不回读历史。
8. 验证暂停/恢复清队列和关闭顺序。
9. 运行现有消息身份、群路由、文字限制、图片生成和调度器测试，确保业务行为不回归。
10. 执行 PyInstaller 分析或等价的依赖收集检查，确认便携版包含 Socket.IO 运行依赖。

## 完成标准

- 实时入站消息全部来自 Socket.IO，不再扫描 DOM 或轮询消息历史。
- 文字和图片发送全部通过平台 Socket.IO 协议，且服务端 ACK 成功后才报告成功。
- main、bounty、image 配置群均可独立收发且顺序稳定。
- 断线后能使用新的浏览器登录凭据恢复连接和房间。
- 平台用户 ID 和消息 ID 稳定进入现有业务层，不因同名、改名或重复文本混淆。
- 自动化测试通过，便携版依赖检查通过。
- DDZM 参考项目没有任何文件变化。
