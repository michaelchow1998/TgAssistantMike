# ============================================================
# 部署指南：私人秘書 Telegram Bot — AWS Serverless 架構
# 文件名稱：guide.md
# 文件版本：1.0
# 最後更新：2026-03-02
# 架構方案：Lambda + API Gateway + DynamoDB + EventBridge
# ============================================================

---

## 目錄

1. [架構總覽](#1-架構總覽)
2. [AWS 服務清單與用途](#2-aws-服務清單與用途)
3. [架構圖](#3-架構圖)
4. [與原始設計的差異對照](#4-與原始設計的差異對照)
5. [DynamoDB 資料表設計](#5-dynamodb-資料表設計)
6. [Lambda 函數設計](#6-lambda-函數設計)
7. [API Gateway 設定](#7-api-gateway-設定)
8. [EventBridge Scheduler 排程設計](#8-eventbridge-scheduler-排程設計)
9. [Secrets 與環境變數管理](#9-secrets-與環境變數管理)
10. [IAM 權限設計](#10-iam-權限設計)
11. [程式碼重構指南](#11-程式碼重構指南)
12. [專案檔案結構（重構後）](#12-專案檔案結構重構後)
13. [部署方式：AWS SAM](#13-部署方式aws-sam)
14. [部署步驟（Step-by-Step）](#14-部署步驟step-by-step)
15. [Telegram Webhook 設定](#15-telegram-webhook-設定)
16. [測試與驗證](#16-測試與驗證)
17. [監控與日誌](#17-監控與日誌)
18. [成本估算](#18-成本估算)
19. [安全性檢查清單](#19-安全性檢查清單)
20. [故障排除](#20-故障排除)
21. [附錄](#附錄)

---

## 1. 架構總覽

### 1.1 設計理念

將原本基於 Polling 模式的長駐程式，轉換為事件驅動的無伺服器架構。
Bot 不再主動輪詢 Telegram API，而是由 Telegram 透過 Webhook 將訊息
推送至 AWS，觸發 Lambda 函數即時處理。排程提醒則由 EventBridge
Scheduler 定時觸發獨立的 Lambda 函數。

### 1.2 核心轉換

原始架構中有三個需要持續運行的元件，在無伺服器架構中分別被替代。

第一，Telegram 訊息接收：從 Polling（Bot 主動拉取）改為 Webhook
（Telegram 主動推送到 API Gateway，觸發 Lambda）。Bot 不再需要
持續運行的進程，每次收到訊息才啟動。

第二，資料庫：從 SQLite（單一檔案，依賴本地磁碟）改為 DynamoDB
（全託管 NoSQL 資料庫，按需計費，無需管理伺服器）。這是改動幅度
最大的部分，因為查詢模式從 SQL 轉為 Key-Value / GSI 查詢。

第三，定時排程：從 APScheduler（進程內排程器）改為 EventBridge
Scheduler（AWS 託管的 cron 排程服務），每個排程時間點觸發獨立的
Lambda 函數。

### 1.3 關鍵優勢

閒置時零成本——沒有訊息時不消耗任何計算資源。高可用性——Lambda
在多個可用區自動運行，無需擔心單點故障。免運維——不需要管理作業
系統、安全更新或進程監控。自動擴縮——雖然單一使用者場景不需要，
但架構本身可承受突發大量請求。

### 1.4 關鍵挑戰

冷啟動延遲：Lambda 首次呼叫（或閒置一段時間後）需要約 0.5-2 秒
初始化，使用者會感受到首次回應稍慢。DynamoDB 查詢模式與 SQL
差異大：需要預先規劃存取模式（Access Patterns），設計合適的分區鍵
（Partition Key）和排序鍵（Sort Key）。ConversationHandler 狀態管理：
原本存在進程記憶體中的對話狀態需要改為存放在 DynamoDB 中。

---

## 2. AWS 服務清單與用途

| AWS 服務                     | 用途                                 | 計費模式              |
|-----------------------------|--------------------------------------|----------------------|
| API Gateway (HTTP API)       | 接收 Telegram Webhook 請求            | 每百萬請求 $1.00      |
| Lambda                       | 執行 Bot 邏輯與排程提醒              | 每百萬請求 $0.20 + 運算時間 |
| DynamoDB (On-Demand)         | 資料儲存（行程、待辦、財務等）        | 按讀寫請求單位計費     |
| EventBridge Scheduler        | 定時觸發提醒 Lambda                   | 免費（含在 EventBridge 免費額度） |
| SSM Parameter Store          | 儲存 BOT_TOKEN 等敏感資訊            | 標準參數免費           |
| CloudWatch Logs              | Lambda 執行日誌                       | $0.50/GB 攝取         |
| CloudWatch Alarms            | 錯誤率告警                            | 前 10 個免費          |
| SNS                          | 告警通知推送                          | 前 1,000 則免費       |
| S3                           | SAM 部署用暫存                        | 極少量，可忽略         |
| IAM                          | 權限角色管理                          | 免費                  |

---

## 3. 架構圖

### 3.1 整體架構


┌──────────────────────────────────────────────────────────────────────────────┐
│ │
│ 使用者 (Telegram App) │
│ │ │
│ │ 發送訊息 / 指令 │
│ ▼ │
│ ┌─────────────────────┐ │
│ │ Telegram Bot API │ │
│ │ (api.telegram.org) │ │
│ └────────┬────────────┘ │
│ │ │
│ │ Webhook POST (HTTPS) │
│ │ │
│ ═══════════╪══════════════════════════════════════════════════════════════ │
│ AWS Cloud │ Region: ap-east-1 (Hong Kong) │
│ ═══════════╪══════════════════════════════════════════════════════════════ │
│ │ │
│ ▼ │
│ ┌─────────────────────┐ ┌──────────────────────┐ │
│ │ API Gateway │ │ SSM Parameter Store │ │
│ │ (HTTP API) │ │ ┌─────────────────┐ │ │
│ │ │ │ │ /bot/token │ │ │
│ │ POST /webhook │ │ │ /bot/owner_id │ │ │
│ │ POST /webhook/{t} │ │ │ /bot/webhook_sec │ │ │
│ └────────┬────────────┘ └──────────┬───────────┘ │
│ │ │ │
│ │ Invoke │ Read (啟動時快取) │
│ ▼ │ │
│ ┌────────────────────────────────┐ │ │
│ │ Lambda: bot-webhook-handler │◄─────────┘ │
│ │ │ │
│ │ Runtime: Python 3.12 │ │
│ │ Memory: 256 MB │ │
│ │ Timeout: 30 sec │ │
│ │ │ │
│ │ ┌──────────────────────────┐ │ │
│ │ │ 處理流程： │ │ │
│ │ │ 1. 驗證 Webhook 請求 │ │ │
│ │ │ 2. 解析 Update 物件 │ │ │
│ │ │ 3. 路由至對應 Handler │ │ │
│ │ │ 4. 讀寫 DynamoDB │ │ │
│ │ │ 5. 回覆 Telegram API │ │ │
│ │ └──────────────────────────┘ │ │
│ └────────┬───────────────────────┘ │
│ │ │
│ │ Read / Write │
│ ▼ │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ DynamoDB Tables (On-Demand Capacity) │ │
│ │ │ │
│ │ ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │ │
│ │ │ schedules │ │ todos │ │ work_projects │ │ │
│ │ └──────────────┘ └──────────────┘ └──────────────────────────┘ │ │
│ │ ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │ │
│ │ │ finances │ │subscriptions │ │ conversation_states │ │ │
│ │ └──────────────┘ └──────────────┘ └──────────────────────────┘ │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│ │
│ │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ EventBridge Scheduler (定時排程) │ │
│ │ │ │
│ │ ┌────────────────────────┐ ┌────────────────────────────────┐ │ │
│ │ │ ⏰ 08:00 每日 │ │ ⏰ 10:00 每日 │ │ │
│ │ │ morning-reminder │ │ subscription-alert │ │ │
│ │ └───────────┬────────────┘ └──────────────┬─────────────────┘ │ │
│ │ │ │ │ │
│ │ ┌───────────┴────────────┐ ┌──────────────┴─────────────────┐ │ │
│ │ │ ⏰ 12:00 每日 │ │ ⏰ 21:00 每日 │ │ │
│ │ │ payment-alert │ │ evening-reminder │ │ │
│ │ └───────────┬────────────┘ └──────────────┬─────────────────┘ │ │
│ │ │ │ │ │
│ └──────────────┼───────────────────────────────┼───────────────────┘ │
│ │ Invoke │ │
│ ▼ ▼ │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ Lambda: bot-reminder-handler │ │
│ │ │ │
│ │ Runtime: Python 3.12 │ │
│ │ Memory: 256 MB │ │
│ │ Timeout: 60 sec │ │
│ │ │ │
│ │ ┌──────────────────────────┐ │ │
│ │ │ 處理流程： │ │ │
│ │ │ 1. 判斷觸發來源（哪個排程）│ │ │
│ │ │ 2. 從 DynamoDB 查詢相關資料│ │ │
│ │ │ 3. 組合提醒訊息 │ │ │
│ │ │ 4. 呼叫 Telegram API 發送 │ │ │
│ │ └──────────────────────────┘ │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│ │
│ │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ CloudWatch │ │
│ │ ┌──────────────────┐ ┌──────────────────────────────────────┐ │ │
│ │ │ Logs │ │ Alarms │ │ │
│ │ │ /aws/lambda/bot-* │ │ - Lambda Error Rate > 5% │ │ │
│ │ │ │ │ - Lambda Throttles > 0 │ │ │
│ │ │ │ │ - API Gateway 5XX > 0 │ │ │
│ │ └──────────────────┘ └───────────────────┬──────────────────┘ │ │
│ └────────────────────────────────────────────┼─────────────────────┘ │
│ │ │
│ ▼ │
│ ┌────────────────┐ │
│ │ SNS Topic │ │
│ │ → Email 通知 │ │
│ └────────────────┘ │
│ │
└──────────────────────────────────────────────────────────────────────────────┘


### 3.2 請求處理流程圖


使用者發送訊息
│
▼
Telegram Bot API ──── Webhook POST ────▶ API Gateway
│
▼
┌─────────────────┐
│ Lambda 啟動 │
│ (冷啟動 ~1-2秒) │
└────────┬────────┘
│
▼
┌─────────────────┐
│ 驗證請求來源 │
│ (Secret Token) │
└────────┬────────┘
│
┌─────────┴─────────┐
│ │
驗證失敗 驗證成功
│ │
▼ ▼
回傳 403 ┌─────────────────┐
│ 解析 Update │
│ (Message/Callback)│
└────────┬────────┘
│
▼
┌─────────────────┐
│ 檢查使用者權限 │
│ (OWNER_ID) │
└────────┬────────┘
│
┌─────────┴─────────┐
│ │
非擁有者 是擁有者
│ │
▼ ▼
回傳 ⛔ ┌─────────────────┐
│ 檢查是否在對話中 │
│ (conversation_ │
│ states 表) │
└────────┬────────┘
│
┌─────────┴─────────┐
│ │
在對話中 非對話中
│ │
▼ ▼
路由至對話 路由至指令
步驟處理器 處理器
│ │
└─────────┬───────────┘
│
▼
┌─────────────────┐
│ 讀寫 DynamoDB │
└────────┬────────┘
│
▼
┌─────────────────┐
│ 呼叫 Telegram │
│ sendMessage API │
└────────┬────────┘
│
▼
回傳 200 OK
給 API Gateway


### 3.3 ConversationHandler 狀態流程（無伺服器版）


使用者輸入 /add_schedule
│
▼
Lambda 啟動 → 辨識為指令 → 路由至 schedule handler
│
▼
檢查 conversation_states 表 → 無記錄 → 這是新對話
│
▼
建立對話狀態記錄：
┌─────────────────────────────────────────┐
│ PK: USER#{owner_id} │
│ SK: CONV#active │
│ module: "schedule" │
│ step: "SCH_TITLE" (下一步) │
│ data: {} │
│ ttl: 當前時間 + 30 分鐘 │
└─────────────────────────────────────────┘
│
▼
回覆：「請輸入行程標題：」
│
─────────┼───── Lambda 結束，資源釋放 ─────
│
使用者輸入「週一開會」
│
▼
新的 Lambda 啟動 → 不是指令 → 檢查 conversation_states
│
▼
找到記錄：module=schedule, step=SCH_TITLE
│
▼
處理輸入 → 儲存 data.sch_title = "週一開會"
更新步驟 → step = "SCH_DATE"
更新 ttl → 當前時間 + 30 分鐘
│
▼
回覆：「請輸入日期：」
│
─────────┼───── Lambda 結束 ─────
│
... 後續步驟同理 ...
│
使用者點擊「✅ 確認」
│
▼
Lambda 啟動 → 讀取 conversation_states → step=SCH_CONFIRM
│
▼
從 data 取出所有欄位 → 寫入 schedules 表
刪除 conversation_states 記錄
│
▼
回覆：「✅ 行程已建立！ID: xxx」


### 3.4 EventBridge 排程流程


EventBridge Scheduler
│
│ ⏰ cron(0 0 * * ? *) ← UTC 00:00 = HKT 08:00
│
▼
┌─────────────────────────────────┐
│ Lambda: bot-reminder-handler │
│ │
│ Event Payload: │
│ { │
│ "reminder_type": "morning" │
│ } │
└────────────┬────────────────────┘
│
▼
┌─────────────────┐
│ 查詢 DynamoDB │
│ │
│ - 今日行程 │
│ - 過期待辦 │
│ - 到期工作 │
│ - 到期付款 │
│ - 到期訂閱 │
└────────┬────────┘
│
▼
┌─────────────────┐
│ 組合提醒訊息 │
└────────┬────────┘
│
▼
┌─────────────────┐
│ POST │
│ api.telegram.org │
│ /sendMessage │
└─────────────────┘

gherkin

---

## 4. 與原始設計的差異對照

### 4.1 技術棧變更

| 元件           | 原始設計                        | 無伺服器架構                      |
|---------------|--------------------------------|----------------------------------|
| 運行模式       | Polling（長駐進程）              | Webhook（事件觸發）               |
| 框架           | python-telegram-bot v20.x       | 自行解析 Webhook + httpx 回覆     |
| 資料庫         | SQLite3                         | DynamoDB                         |
| 排程引擎       | APScheduler / JobQueue           | EventBridge Scheduler            |
| 對話狀態       | context.user_data（記憶體）      | DynamoDB conversation_states 表  |
| 部署單位       | Python 進程 + systemd            | Lambda 函數 + API Gateway        |
| 敏感資訊       | config.py / SSM                  | SSM Parameter Store              |
| 日誌           | 檔案 + journald                  | CloudWatch Logs（自動）          |

### 4.2 python-telegram-bot 框架的取捨

原始設計深度使用 python-telegram-bot v20.x 的 ConversationHandler、
CallbackQueryHandler、JobQueue 等功能。在 Lambda 環境中，由於每次
請求是獨立的函數呼叫，框架的長駐進程特性無法使用。

有兩個選擇：

**選擇 A（推薦）：不使用框架，自行處理。** 直接解析 Telegram 的
Webhook JSON payload，使用 httpx 或 requests 呼叫 Telegram Bot API。
自行實作指令路由、對話狀態管理。程式碼更精簡，Lambda 套件更小，
冷啟動更快。

**選擇 B：使用框架的部分功能。** python-telegram-bot 支援將 Update
物件反序列化，可以用來解析 Webhook payload，但不使用 Application、
Dispatcher 等需要長駐運行的元件。這樣可以利用框架的型別定義，但
需要注意框架依賴較重，會增加 Lambda 部署包大小和冷啟動時間。

本指南採用選擇 A，最大化無伺服器架構的效益。

### 4.3 需要移除的依賴


原始 requirements.txt
python-telegram-bot==20.7 ← 移除（改為自行處理）
apscheduler==3.10.4 ← 移除（改為 EventBridge）
pytz==2024.1 ← 保留

新增
httpx==0.27.0 ← 非同步 HTTP 客戶端（呼叫 Telegram API）
boto3==1.34.0 ← AWS SDK（DynamoDB、SSM）

yaml

---

## 5. DynamoDB 資料表設計

### 5.1 設計原則

DynamoDB 是 NoSQL 資料庫，沒有 SQL 的 JOIN、複雜 WHERE 子句或
任意欄位排序。必須根據存取模式（Access Patterns）預先設計鍵結構。
本專案採用單表設計（Single-Table Design）與多表混合的策略——
將高頻存取且查詢模式簡單的資料放在同一張表，將查詢模式複雜的
模組獨立成表。

### 5.2 表結構總覽

本設計使用兩張 DynamoDB 表：

**表一：BotMainTable（主表）** — 存放所有業務資料（行程、待辦、工作、
財務、訂閱），使用單表設計模式。

**表二：BotConversationTable（對話狀態表）** — 獨立存放進行中的對話
狀態，設定 TTL 自動清理過期對話。

### 5.3 BotMainTable 設計


表名稱：BotMainTable
計費模式：On-Demand (PAY_PER_REQUEST)

gherkin

**主鍵設計：**

| 屬性名 | 鍵類型         | 格式                            | 說明                |
|--------|---------------|--------------------------------|---------------------|
| PK     | Partition Key | `{ENTITY_TYPE}#{id}`           | 實體類型 + 唯一 ID   |
| SK     | Sort Key      | `{ENTITY_TYPE}#META`           | 固定為 META（主記錄） |

**PK 格式對照：**

| 實體類型        | PK 格式                | 範例                  |
|----------------|------------------------|-----------------------|
| 行程            | `SCH#{ulid}`           | `SCH#01HXK5P2...`    |
| 待辦            | `TODO#{ulid}`          | `TODO#01HXK5R3...`   |
| 工作進度        | `WORK#{ulid}`          | `WORK#01HXK5T4...`   |
| 財務            | `FIN#{ulid}`           | `FIN#01HXK5V5...`    |
| 訂閱            | `SUB#{ulid}`           | `SUB#01HXK5W6...`    |

使用 ULID（Universally Unique Lexicographically Sortable Identifier）
替代原本的 INTEGER AUTOINCREMENT。ULID 的前半段包含時間戳，
天然有序，適合 DynamoDB 的排序需求。同時為了操作方便，額外維護
一個自增計數器（見 5.3.3 節），讓使用者仍可用短 ID（如 1, 2, 3）
操作。

#### 5.3.1 GSI（Global Secondary Index）設計

為了支援按日期查詢、按狀態查詢等存取模式，需要建立 GSI：

**GSI-1：GSI_Type_Date**

| 屬性名        | 鍵類型         | 格式                               |
|--------------|---------------|-------------------------------------|
| GSI1PK       | Partition Key | `{ENTITY_TYPE}#{status}`            |
| GSI1SK       | Sort Key      | `{date_field}#{ulid}`               |

用途與查詢範例：


查詢今日行程：
GSI1PK = "SCH#active"
GSI1SK BETWEEN "2026-03-02#" AND "2026-03-02#~"

查詢 pending 待辦（按截止日排序）：
GSI1PK = "TODO#pending"
GSI1SK BEGINS_WITH "2026-" (或完整範圍)

查詢進行中工作（按截止日排序）：
GSI1PK = "WORK#in_progress"

查詢待付款項（未來 N 天）：
GSI1PK = "FIN#pending"
GSI1SK BETWEEN "2026-03-02#" AND "2026-03-09#~"

查詢有效訂閱（按到期日排序）：
GSI1PK = "SUB#active"
GSI1SK BETWEEN "2026-03-02#" AND "2026-03-09#~"

gherkin

**GSI-2：GSI_Category**

| 屬性名        | 鍵類型         | 格式                               |
|--------------|---------------|-------------------------------------|
| GSI2PK       | Partition Key | `{ENTITY_TYPE}#{category}`          |
| GSI2SK       | Sort Key      | `{status}#{date_field}#{ulid}`      |

用途：按分類查詢（如「查看所有工作分類的待辦」）。

**GSI-3：GSI_ShortID**

| 屬性名        | 鍵類型         | 格式                               |
|--------------|---------------|-------------------------------------|
| GSI3PK       | Partition Key | `{ENTITY_TYPE}`                     |
| GSI3SK       | Sort Key      | `{short_id}`（數字，零填充）         |

用途：讓使用者透過短 ID 操作（如 `/done 3`、`/cancel_schedule 5`）。

#### 5.3.2 各實體屬性定義

**行程（Schedule）項目屬性：**

```json
{
  "PK": "SCH#01HXK5P2ABCDEF",
  "SK": "SCH#META",
  "entity_type": "SCH",
  "short_id": 1,
  "title": "週一開會",
  "description": "",
  "category": "work",
  "event_date": "2026-03-05",
  "event_time": "14:00",
  "location": "會議室 A",
  "status": "active",
  "created_at": "2026-03-02T10:30:00+08:00",

  "GSI1PK": "SCH#active",
  "GSI1SK": "2026-03-05#01HXK5P2ABCDEF",
  "GSI2PK": "SCH#work",
  "GSI2SK": "active#2026-03-05#01HXK5P2ABCDEF",
  "GSI3PK": "SCH",
  "GSI3SK": "00001"
}

待辦（Todo）項目屬性：

json
{
  "PK": "TODO#01HXK5R3GHIJKL",
  "SK": "TODO#META",
  "entity_type": "TODO",
  "short_id": 1,
  "title": "準備報告",
  "description": "",
  "category": "work",
  "priority": 1,
  "due_date": "2026-03-10",
  "status": "pending",
  "created_at": "2026-03-02T10:35:00+08:00",
  "completed_at": null,

  "GSI1PK": "TODO#pending",
  "GSI1SK": "2026-03-10#01HXK5R3GHIJKL",
  "GSI2PK": "TODO#work",
  "GSI2SK": "pending#2026-03-10#01HXK5R3GHIJKL",
  "GSI3PK": "TODO",
  "GSI3SK": "00001"
}

工作進度（Work Project）項目屬性：

json
{
  "PK": "WORK#01HXK5T4MNOPQR",
  "SK": "WORK#META",
  "entity_type": "WORK",
  "short_id": 1,
  "project_name": "網站改版",
  "task_name": "前端開發",
  "description": "",
  "category": "work",
  "progress": 45,
  "deadline": "2026-03-20",
  "status": "in_progress",
  "created_at": "2026-03-01T09:00:00+08:00",
  "updated_at": "2026-03-02T15:00:00+08:00",

  "GSI1PK": "WORK#in_progress",
  "GSI1SK": "2026-03-20#01HXK5T4MNOPQR",
  "GSI2PK": "WORK#work",
  "GSI2SK": "in_progress#2026-03-20#01HXK5T4MNOPQR",
  "GSI3PK": "WORK",
  "GSI3SK": "00001"
}

財務（Finance）項目屬性：

json
{
  "PK": "FIN#01HXK5V5STUVWX",
  "SK": "FIN#META",
  "entity_type": "FIN",
  "short_id": 1,
  "type": "payment",
  "title": "信用卡還款",
  "amount": 5000.00,
  "currency": "HKD",
  "due_date": "2026-03-15",
  "is_recurring": 1,
  "recurring_day": 15,
  "category": "finance",
  "status": "pending",
  "notes": "",
  "created_at": "2026-03-01T09:00:00+08:00",

  "GSI1PK": "FIN#pending",
  "GSI1SK": "2026-03-15#01HXK5V5STUVWX",
  "GSI2PK": "FIN#finance",
  "GSI2SK": "pending#2026-03-15#01HXK5V5STUVWX",
  "GSI3PK": "FIN",
  "GSI3SK": "00001"
}

訂閱（Subscription）項目屬性：

json
{
  "PK": "SUB#01HXK5W6YZ1234",
  "SK": "SUB#META",
  "entity_type": "SUB",
  "short_id": 1,
  "name": "Apple Music",
  "amount": 78.00,
  "currency": "HKD",
  "billing_cycle": "monthly",
  "billing_day": 15,
  "next_due_date": "2026-04-15",
  "category": "personal",
  "auto_renew": 1,
  "notes": "家庭方案",
  "status": "active",
  "created_at": "2026-03-01T09:00:00+08:00",
  "last_renewed_at": "2026-03-15T08:00:00+08:00",

  "GSI1PK": "SUB#active",
  "GSI1SK": "2026-04-15#01HXK5W6YZ1234",
  "GSI2PK": "SUB#personal",
  "GSI2SK": "active#2026-04-15#01HXK5W6YZ1234",
  "GSI3PK": "SUB",
  "GSI3SK": "00001"
}

5.3.3 短 ID 計數器
為了讓使用者繼續用 /done 3 這種短 ID 操作，使用 DynamoDB 的
原子計數器（Atomic Counter）為每種實體類型維護遞增 ID。

json
{
  "PK": "COUNTER",
  "SK": "SCH",
  "current_value": 5
}
{
  "PK": "COUNTER",
  "SK": "TODO",
  "current_value": 12
}

新增項目時，使用 UpdateExpression 的 ADD current_value :inc
取得遞增後的值作為 short_id。此操作是原子性的，不會重複。

5.4 BotConversationTable 設計
表名稱：BotConversationTable
計費模式：On-Demand (PAY_PER_REQUEST)
TTL 屬性：expire_at

主鍵設計：

屬性名	鍵類型	格式
PK	Partition Key	USER#{user_id}
SK	Sort Key	CONV#active
每個使用者同一時間只會有一個進行中的對話，因此 SK 固定為
CONV#active。當使用者開始新對話時，直接覆蓋舊記錄。

項目屬性：

json
{
  "PK": "USER#123456789",
  "SK": "CONV#active",
  "module": "schedule",
  "step": "SCH_DATE",
  "data": {
    "sch_title": "週一開會"
  },
  "started_at": "2026-03-02T10:30:00+08:00",
  "expire_at": 1740900600
}

expire_at 是 Unix 時間戳，設定為當前時間 + 30 分鐘。DynamoDB
的 TTL 功能會自動刪除過期項目（通常在過期後 48 小時內刪除，
但查詢時可用 FilterExpression 排除已過期項目）。這確保了使用者
如果中途放棄對話，狀態記錄不會永遠殘留。

5.5 完整存取模式對照表
編號	存取模式	表/索引	Key 條件
AP01	按 ID 取得單一項目	主表 PK+SK	PK = {TYPE}#{ulid}, SK = {TYPE}#META
AP02	按短 ID 取得項目	GSI-3	GSI3PK = {TYPE}, GSI3SK = {short_id}
AP03	取得指定日期的行程	GSI-1	GSI1PK = SCH#active, GSI1SK BETWEEN date range
AP04	取得日期範圍內的行程	GSI-1	同 AP03，擴大 SK 範圍
AP05	取得 pending 待辦（按截止日）	GSI-1	GSI1PK = TODO#pending
AP06	取得過期待辦	GSI-1	GSI1PK = TODO#pending, GSI1SK < today
AP07	按分類取得待辦	GSI-2	GSI2PK = TODO#{category}
AP08	取得進行中工作	GSI-1	GSI1PK = WORK#in_progress
AP09	取得即將到期工作	GSI-1	GSI1PK = WORK#in_progress, GSI1SK BETWEEN range
AP10	取得即將到期付款	GSI-1	GSI1PK = FIN#pending, GSI1SK BETWEEN range
AP11	取得週期性付款	GSI-1 + Filter	GSI1PK = FIN#pending, Filter: is_recurring = 1
AP12	取得 active 訂閱	GSI-1	GSI1PK = SUB#active
AP13	取得即將到期訂閱	GSI-1	GSI1PK = SUB#active, GSI1SK BETWEEN range
AP14	按分類取得訂閱	GSI-2	GSI2PK = SUB#{category}
AP15	取得對話狀態	對話表 PK+SK	PK = USER#{id}, SK = CONV#active
AP16	全域搜尋（關鍵字）	GSI-1 + Filter	各 entity type 分別查詢，Filter: contains(title, kw)
AP17	月度財務統計	GSI-1 + Filter	GSI1PK = FIN#paid, GSI1SK BETWEEN month range
注意 AP16（全域搜尋）是 DynamoDB 的弱項。由於 DynamoDB 不支援
全文搜尋，搜尋功能需要對每種實體類型分別查詢並使用 FilterExpression
做 contains 過濾。對於單一使用者的少量資料，這是可以接受的。
如果未來資料量增長到效能不佳，可以引入 OpenSearch Serverless。

6. Lambda 函數設計
6.1 函數清單
函數名稱	觸發方式	用途	記憶體	逾時
bot-webhook-handler	API Gateway POST	處理所有 Telegram 訊息	256 MB	30 sec
bot-reminder-handler	EventBridge	執行定時提醒	256 MB	60 sec
僅需兩個 Lambda 函數。webhook handler 處理所有使用者互動，
reminder handler 處理所有排程提醒（透過 event payload 區分類型）。

6.2 webhook handler 處理邏輯
python

查看全部
        return

    message = update["message"]
    text = message.get("text", "")

    # /cancel 在任何時候都能取消對話
    if text == "/cancel":
        if conv_state:
            clear_conversation_state(db, config["OWNER_ID"])
            send_message(config, chat_id, "已取消操作。")
        else:
            send_message(config, chat_id, "目前沒有進行中的操作。")
        return

    # 如果有進行中的對話，路由至對話處理器
    if conv_state:
        handle_conversation_step(config, db, chat_id, text, conv_state)
        return

    # 指令路由
    if text.startswith("/"):
        handle_command(config, db, chat_id, text)
    else:
        send_message(config, chat_id, "請輸入指令。使用 /help 查看可用指令。")

執行

6.3 reminder handler 處理邏輯
python

查看全部
# reminder_handler.py (bot-reminder-handler)

def lambda_handler(event, context):
    """由 EventBridge 觸發"""
    config = get_config()
    db = get_dynamodb()

    reminder_type = event.get("reminder_type", "unknown")

    if reminder_type == "morning":
        send_morning_reminder(config, db)
    elif reminder_type == "subscription_alert":
        send_subscription_alert(config, db)
    elif reminder_type == "payment_alert":
        send_payment_alert(config, db)
    elif reminder_type == "evening":
        send_evening_reminder(config, db)
    else:
        print(f"Unknown reminder type: {reminder_type}")

    return {"statusCode": 200}

執行

6.4 Lambda Layer 設計
將共用的依賴套件打包為 Lambda Layer，避免每個函數都包含
完整依賴，減少部署包大小。

mipsasm
Layer: bot-dependencies
  └── python/
      ├── httpx/
      ├── pytz/
      └── ulid/

Layer: bot-shared-code
  └── python/
      ├── bot_config.py      # 設定讀取
      ├── bot_db.py          # DynamoDB 操作封裝
      ├── bot_telegram.py    # Telegram API 呼叫封裝
      └── bot_utils.py       # 共用工具函數

7. API Gateway 設定
7.1 API 類型選擇
使用 HTTP API（v2），而非 REST API（v1）。HTTP API 成本更低
（每百萬請求 $1.00 vs $3.50）、延遲更低、設定更簡單。
對於 Telegram Webhook 的簡單 POST 請求，HTTP API 完全足夠。

7.2 路由設定
HTTP API: secretary-bot-api
│
├── POST /webhook/{secret_path}
│   └── Integration: Lambda bot-webhook-handler
│
└── (無其他路由)

{secret_path} 是 URL 路徑中的一段隨機字串，作為第一層
安全防護。即使有人知道 API Gateway 的 URL，如果不知道
這段隨機路徑，請求不會到達 Lambda。這與 Telegram 的
secret_token 驗證形成雙重保護。

7.3 API Gateway 設定參數
yaml
API 名稱: secretary-bot-api
協議: HTTPS（API Gateway 預設強制 HTTPS）
端點類型: Regional
CORS: 不需要（僅 Telegram 呼叫）
授權: 無（驗證在 Lambda 內進行）
限流: 預設（每秒 10,000 請求，遠超需求）

7.4 自訂域名（可選）
如果不想暴露 API Gateway 的預設 URL（含隨機 ID），可以使用
自訂域名。但需要：一個你擁有的域名、在 ACM 申請 SSL 憑證、
在 Route 53 或其他 DNS 設定 CNAME。對於個人 Bot，預設 URL
搭配 secret_path 已經足夠安全。

8. EventBridge Scheduler 排程設計
8.1 排程清單
所有時間使用 UTC，換算至 HKT（UTC+8）。

排程名稱	Cron 表達式 (UTC)	對應 HKT	Event Payload
morning-reminder	cron(0 0 * * ? *)	每日 08:00	{"reminder_type": "morning"}
subscription-alert	cron(0 2 * * ? *)	每日 10:00	{"reminder_type": "subscription_alert"}
payment-alert	cron(0 4 * * ? *)	每日 12:00	{"reminder_type": "payment_alert"}
evening-reminder	cron(0 13 * * ? *)	每日 21:00	{"reminder_type": "evening"}
8.2 EventBridge Scheduler vs EventBridge Rules
使用 EventBridge Scheduler（非 EventBridge Rules）。Scheduler 是較新
的服務，專為排程任務設計，支援一次性排程和重複排程，管理更方便，
並且有獨立的免費額度（每月 14,000,000 次呼叫免費）。

8.3 排程配置範例
json
{
  "Name": "morning-reminder",
  "ScheduleExpression": "cron(0 0 * * ? *)",
  "ScheduleExpressionTimezone": "Asia/Hong_Kong",
  "FlexibleTimeWindow": {
    "Mode": "OFF"
  },
  "Target": {
    "Arn": "arn:aws:lambda:ap-east-1:123456789:function:bot-reminder-handler",
    "Input": "{\"reminder_type\": \"morning\"}",
    "RoleArn": "arn:aws:iam::123456789:role/EventBridgeSchedulerRole"
  },
  "State": "ENABLED"
}

注意：EventBridge Scheduler 原生支援 ScheduleExpressionTimezone
參數，可以直接指定 Asia/Hong_Kong，不需要手動換算 UTC。
這比 EventBridge Rules 方便得多。

9. Secrets 與環境變數管理
9.1 SSM Parameter Store 參數
參數路徑	類型	說明
/bot/token	SecureString	Telegram Bot Token
/bot/owner_id	String	擁有者的 Telegram User ID
/bot/webhook_secret	SecureString	Webhook 驗證用的隨機字串
/bot/webhook_path	SecureString	URL 路徑中的隨機安全段
9.2 Lambda 環境變數
Lambda 函數的環境變數僅放不敏感的設定：

yaml
Environment:
  Variables:
    MAIN_TABLE_NAME: BotMainTable
    CONV_TABLE_NAME: BotConversationTable
    TIMEZONE: Asia/Hong_Kong
    LOG_LEVEL: INFO

敏感資訊（Token、Secret）一律從 SSM 讀取，在 Lambda 首次
執行時載入並快取在全域變數中（Lambda 容器重用時不需重複讀取）。

9.3 生成 Webhook Secret 與 Path
bash
# 生成 webhook secret（64 字元隨機字串）
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

# 生成 URL 安全路徑（32 字元）
python3 -c "import secrets; print(secrets.token_urlsafe(24))"

10. IAM 權限設計
10.1 Lambda 執行角色（Webhook Handler）
json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDBAccess",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:Query"
      ],
      "Resource": [
        "arn:aws:dynamodb:ap-east-1:*:table/BotMainTable",
        "arn:aws:dynamodb:ap-east-1:*:table/BotMainTable/index/*",
        "arn:aws:dynamodb:ap-east-1:*:table/BotConversationTable"
      ]
    },
    {
      "Sid": "SSMReadAccess",
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:GetParameters"
      ],
      "Resource": "arn:aws:ssm:ap-east-1:*:parameter/bot/*"
    },
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:ap-east-1:*:*"
    }
  ]
}

10.2 Lambda 執行角色（Reminder Handler）
與 Webhook Handler 相同權限。可共用同一個 IAM Role，或各自
獨立（如果想更細粒度控制，Reminder Handler 可以只給 DynamoDB
讀取權限，因為它不需要寫入）。

10.3 EventBridge Scheduler 執行角色
json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "arn:aws:lambda:ap-east-1:*:function:bot-reminder-handler"
    }
  ]
}

11. 程式碼重構指南
11.1 Telegram API 封裝模組
不使用 python-telegram-bot 框架，自行封裝 Telegram Bot API 呼叫。

python

查看全部
        }
        resp = self.client.post(f"{self.base_url}/setWebhook", json=payload)
        return resp.json()

    @staticmethod
    def build_inline_keyboard(buttons: list[list[dict]]) -> dict:
        """
        建構 InlineKeyboardMarkup

        buttons 格式：
        [
            [{"text": "按鈕1", "callback_data": "btn1"}],
            [{"text": "按鈕2", "callback_data": "btn2"}],
        ]
        """
        return {
            "inline_keyboard": [
                [
                    {"text": btn["text"], "callback_data": btn["callback_data"]}
                    for btn in row
                ]
                for row in buttons
            ]
        }

執行

11.2 DynamoDB 操作封裝模組
python

查看全部
        item = resp.get("Item")
        if item and item.get("expire_at", 0) > int(datetime.now().timestamp()):
            return item
        return None

    def set_conversation_state(self, user_id: int, module: str,
                                step: str, data: dict) -> None:
        """設定/更新對話狀態"""
        expire_at = int((datetime.now() + timedelta(minutes=30)).timestamp())
        self.conv_table.put_item(Item={
            "PK": f"USER#{user_id}",
            "SK": "CONV#active",
            "module": module,
            "step": step,
            "data": data,
            "started_at": datetime.now().isoformat(),
            "expire_at": expire_at,
        })

    def clear_conversation_state(self, user_id: int) -> None:
        """清除對話狀態"""
        self.conv_table.delete_item(
            Key={"PK": f"USER#{user_id}", "SK": "CONV#active"}
        )

執行

11.3 指令路由器
python

查看全部

    handler = COMMAND_ROUTES.get(command)
    if handler:
        handler(config, db, chat_id, args)
    else:
        send_message(config, chat_id, "未知指令。使用 /help 查看可用指令。")

def handle_callback(config, db, chat_id, callback_data, conv_state):
    """路由 callback 至對應處理器"""
    for prefix, handler in CALLBACK_ROUTES.items():
        if callback_data.startswith(prefix):
            handler(config, db, chat_id, callback_data, conv_state)
            return

def handle_conversation_step(config, db, chat_id, text, conv_state):
    """路由對話步驟至對應處理器"""
    module = conv_state["module"]
    step = conv_state["step"]
    module_routes = CONVERSATION_ROUTES.get(module, {})
    handler = module_routes.get(step)
    if handler:
        handler(config, db, chat_id, text, conv_state)
    else:
        send_message(config, chat_id, "對話狀態異常，請重新開始。/cancel")

執行

12. 專案檔案結構（重構後）
mipsasm
secretary_bot_serverless/
│
├── template.yaml              # AWS SAM 範本（基礎設施定義）
├── samconfig.toml             # SAM 部署設定
├── requirements.txt           # Python 依賴
├── setup_webhook.py           # 一次性腳本：設定 Telegram Webhook
│
├── shared/                    # Lambda Layer（共用程式碼）
│   └── python/
│       ├── bot_config.py      # 設定讀取（SSM）
│       ├── bot_db.py          # DynamoDB 操作封裝
│       ├── bot_telegram.py    # Telegram API 封裝
│       ├── bot_utils.py       # 工具函數（日期解析、格式化等）
│       └── bot_constants.py   # 常數定義（分類、狀態等）
│
├── webhook_handler/           # Lambda: bot-webhook-handler
│   ├── lambda_function.py     # 進入點
│   └── handlers/
│       ├── __init__.py
│       ├── start.py           # /start, /help
│       ├── schedule.py        # 行程管理指令 + 對話步驟
│       ├── todo.py            # 待辦事項指令 + 對話步驟
│       ├── work.py            # 工作進度指令 + 對話步驟
│       ├── finance.py         # 財務管理指令 + 對話步驟
│       ├── subscription.py    # 訂閱管理指令 + 對話步驟
│       ├── query.py           # 綜合查詢指令
│       └── router.py          # 指令/callback/對話 路由器
│
├── reminder_handler/          # Lambda: bot-reminder-handler
│   ├── lambda_function.py     # 進入點
│   └── reminders/
│       ├── __init__.py
│       ├── morning.py         # 早晨提醒
│       ├── evening.py         # 晚間提醒
│       ├── payment_alert.py   # 付款到期警告
│       └── sub_alert.py       # 訂閱到期警告
│
└── tests/                     # 單元測試
    ├── test_db.py
    ├── test_handlers.py
    ├── test_reminders.py
    └── events/                # 測試用 event payload
        ├── webhook_message.json
        ├── webhook_callback.json
        └── reminder_morning.json

13. 部署方式：AWS SAM
13.1 為什麼選擇 SAM
AWS SAM（Serverless Application Model）是 CloudFormation 的擴展，
專為無伺服器應用設計。相比純 CloudFormation，SAM 的語法更簡潔；
相比 Terraform 或 CDK，SAM 學習曲線最低、對 Lambda 開發體驗
最好（支援本地測試 sam local invoke）。

13.2 SAM Template（template.yaml）
yaml
AWSTemplateFormatVersion: "2010-09-09"
Transform: AWS::Serverless-2016-10-31
Description: >
  Private Secretary Telegram Bot — Serverless Architecture

Parameters:
  Environment:
    Type: String
    Default: prod
    AllowedValues: [prod, dev]

Globals:
  Function:
    Runtime: python3.12
    MemorySize: 256
    Architectures:
      - arm64
    Timeout: 30
    Environment:
      Variables:
        MAIN_TABLE_NAME: !Ref BotMainTable
        CONV_TABLE_NAME: !Ref BotConversationTable
        TIMEZONE: Asia/Hong_Kong
        LOG_LEVEL: INFO

Resources:

  # ═══════════════════════════════════════════
  # Lambda Layer — 共用依賴與程式碼
  # ═══════════════════════════════════════════

  BotDependenciesLayer:
    Type: AWS::Serverless::LayerVersion
    Properties:
      LayerName: bot-dependencies
      Description: Python dependencies (httpx, pytz, ulid)
      ContentUri: dependencies/
      CompatibleRuntimes:
        - python3.12
      CompatibleArchitectures:
        - arm64
    Metadata:
      BuildMethod: python3.12

  BotSharedCodeLayer:
    Type: AWS::Serverless::LayerVersion
    Properties:
      LayerName: bot-shared-code
      Description: Shared bot modules
      ContentUri: shared/
      CompatibleRuntimes:
        - python3.12
      CompatibleArchitectures:
        - arm64

  # ═══════════════════════════════════════════
  # Lambda Function — Webhook Handler
  # ═══════════════════════════════════════════

  WebhookHandlerFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: bot-webhook-handler
      CodeUri: webhook_handler/
      Handler: lambda_function.lambda_handler
      Timeout: 30
      Layers:
        - !Ref BotDependenciesLayer
        - !Ref BotSharedCodeLayer
      Policies:
        - DynamoDBCrudPolicy:
            TableName: !Ref BotMainTable
        - DynamoDBCrudPolicy:
            TableName: !Ref BotConversationTable
        - SSMParameterReadPolicy:
            ParameterName: "bot/*"
      Events:
        WebhookAPI:
          Type: HttpApi
          Properties:
            ApiId: !Ref BotHttpApi
            Path: /webhook/{proxy+}
            Method: POST

  # ═══════════════════════════════════════════
  # Lambda Function — Reminder Handler
  # ═══════════════════════════════════════════

  ReminderHandlerFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: bot-reminder-handler
      CodeUri: reminder_handler/
      Handler: lambda_function.lambda_handler
      Timeout: 60
      Layers:
        - !Ref BotDependenciesLayer
        - !Ref BotSharedCodeLayer
      Policies:
        - DynamoDBReadPolicy:
            TableName: !Ref BotMainTable
        - SSMParameterReadPolicy:
            ParameterName: "bot/*"
      Events:
        MorningReminder:
          Type: ScheduleV2
          Properties:
            ScheduleExpression: cron(0 0 * * ? *)
            ScheduleExpressionTimezone: Asia/Hong_Kong
            Input: '{"reminder_type": "morning"}'
        SubscriptionAlert:
          Type: ScheduleV2
          Properties:
            ScheduleExpression: cron(0 2 * * ? *)
            ScheduleExpressionTimezone: Asia/Hong_Kong
            Input: '{"reminder_type": "subscription_alert"}'
        PaymentAlert:
          Type: ScheduleV2
          Properties:
            ScheduleExpression: cron(0 4 * * ? *)
            ScheduleExpressionTimezone: Asia/Hong_Kong
            Input: '{"reminder_type": "payment_alert"}'
        EveningReminder:
          Type: ScheduleV2
          Properties:
            ScheduleExpression: cron(0 13 * * ? *)
            ScheduleExpressionTimezone: Asia/Hong_Kong
            Input: '{"reminder_type": "evening"}'

  # ═══════════════════════════════════════════
  # API Gateway — HTTP API
  # ═══════════════════════════════════════════

  BotHttpApi:
    Type: AWS::Serverless::HttpApi
    Properties:
      StageName: prod
      Description: Telegram Bot Webhook Endpoint

  # ═══════════════════════════════════════════
  # DynamoDB — Main Table
  # ═══════════════════════════════════════════

  BotMainTable:
    Type: AWS::DynamoDB::Table
    DeletionPolicy: Retain
    Properties:
      TableName: BotMainTable
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - AttributeName: PK
          AttributeType: S
        - AttributeName: SK
          AttributeType: S
        - AttributeName: GSI1PK
          AttributeType: S
        - AttributeName: GSI1SK
          AttributeType: S
        - AttributeName: GSI2PK
          AttributeType: S
        - AttributeName: GSI2SK
          AttributeType: S
        - AttributeName: GSI3PK
          AttributeType: S
        - AttributeName: GSI3SK
          AttributeType: S
      KeySchema:
        - AttributeName: PK
          KeyType: HASH
        - AttributeName: SK
          KeyType: RANGE
      GlobalSecondaryIndexes:
        - IndexName: GSI_Type_Date
          KeySchema:
            - AttributeName: GSI1PK
              KeyType: HASH
            - AttributeName: GSI1SK
              KeyType: RANGE
          Projection:
            ProjectionType: ALL
        - IndexName: GSI_Category
          KeySchema:
            - AttributeName: GSI2PK
              KeyType: HASH
            - AttributeName: GSI2SK
              KeyType: RANGE
          Projection:
            ProjectionType: ALL
        - IndexName: GSI_ShortID
          KeySchema:
            - AttributeName: GSI3PK
              KeyType: HASH
            - AttributeName: GSI3SK
              KeyType: RANGE
          Projection:
            ProjectionType: ALL
      PointInTimeRecoverySpecification:
        PointInTimeRecoveryEnabled: true
      Tags:
        - Key: Project
          Value: SecretaryBot

  # ═══════════════════════════════════════════
  # DynamoDB — Conversation State Table
  # ═══════════════════════════════════════════

  BotConversationTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: BotConversationTable
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - AttributeName: PK
          AttributeType: S
        - AttributeName: SK
          AttributeType: S
      KeySchema:
        - AttributeName: PK
          KeyType: HASH
        - AttributeName: SK
          KeyType: RANGE
      TimeToLiveSpecification:
        AttributeName: expire_at
        Enabled: true
      Tags:
        - Key: Project
          Value: SecretaryBot

  # ═══════════════════════════════════════════
  # CloudWatch Alarm — Lambda 錯誤率
  # ═══════════════════════════════════════════

  WebhookErrorAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: bot-webhook-errors
      AlarmDescription: Webhook Lambda error rate > 5%
      MetricName: Errors
      Namespace: AWS/Lambda
      Dimensions:
        - Name: FunctionName
          Value: !Ref WebhookHandlerFunction
      Statistic: Sum
      Period: 300
      EvaluationPeriods: 2
      Threshold: 3
      ComparisonOperator: GreaterThanThreshold
      AlarmActions:
        - !Ref AlertSNSTopic

  AlertSNSTopic:
    Type: AWS::SNS::Topic
    Properties:
      TopicName: bot-alerts
      Subscription:
        - Protocol: email
          Endpoint: your-email@example.com

# ═══════════════════════════════════════════
# Outputs
# ═══════════════════════════════════════════

Outputs:
  WebhookUrl:
    Description: API Gateway Webhook URL（需在後面附加 secret path）
    Value: !Sub "https://${BotHttpApi}.execute-api.${AWS::Region}.amazonaws.com/prod/webhook/"

  MainTableName:
    Description: DynamoDB Main Table
    Value: !Ref BotMainTable

  ConversationTableName:
    Description: DynamoDB Conversation Table
    Value: !Ref BotConversationTable

13.3 SAM 設定檔（samconfig.toml）
toml
version = 0.1

[default.deploy.parameters]
stack_name = "secretary-bot"
region = "ap-east-1"
confirm_changeset = true
capabilities = "CAPABILITY_IAM"
s3_prefix = "secretary-bot"
resolve_s3 = true

14. 部署步驟（Step-by-Step）
14.1 前置準備
步驟 1：安裝工具

bash
# 安裝 AWS CLI
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" \
    -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# 安裝 AWS SAM CLI
pip install aws-sam-cli

# 驗證安裝
aws --version
sam --version

步驟 2：設定 AWS 憑證

bash
aws configure
# AWS Access Key ID: <your-key>
# AWS Secret Access Key: <your-secret>
# Default region: ap-east-1
# Default output format: json

步驟 3：建立 Telegram Bot

在 Telegram 找 @BotFather，執行 /newbot，取得 Bot Token。
找 @userinfobot，取得你的 User ID。

步驟 4：儲存 Secrets 到 SSM

bash
# Bot Token
aws ssm put-parameter \
    --name "/bot/token" \
    --type "SecureString" \
    --value "YOUR_BOT_TOKEN_HERE" \
    --region ap-east-1

# Owner ID
aws ssm put-parameter \
    --name "/bot/owner_id" \
    --type "String" \
    --value "YOUR_TELEGRAM_USER_ID" \
    --region ap-east-1

# Webhook Secret（自動生成）
WEBHOOK_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
aws ssm put-parameter \
    --name "/bot/webhook_secret" \
    --type "SecureString" \
    --value "$WEBHOOK_SECRET" \
    --region ap-east-1

echo "Webhook Secret: $WEBHOOK_SECRET"

# Webhook Path（自動生成）
WEBHOOK_PATH=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
aws ssm put-parameter \
    --name "/bot/webhook_path" \
    --type "SecureString" \
    --value "$WEBHOOK_PATH" \
    --region ap-east-1

echo "Webhook Path: $WEBHOOK_PATH"

14.2 建置與部署
步驟 5：建置 Lambda Layer 依賴

bash
# 在專案根目錄
mkdir -p dependencies/python
pip install httpx pytz python-ulid \
    -t dependencies/python \
    --platform manylinux2014_aarch64 \
    --implementation cp \
    --python-version 3.12 \
    --only-binary=:all:

步驟 6：SAM Build

bash
sam build

步驟 7：SAM Deploy

bash
# 首次部署（互動式）
sam deploy --guided

# 後續部署
sam deploy

部署完成後，SAM 會輸出 API Gateway URL，記下來。

14.3 設定 Telegram Webhook
步驟 8：執行 Webhook 設定腳本

python

查看全部
    webhook_url = f"{api_url}{path}"

    # 設定 Webhook
    resp = httpx.post(
        f"https://api.telegram.org/bot{token}/setWebhook",
        json={
            "url": webhook_url,
            "secret_token": secret,
            "allowed_updates": ["message", "callback_query"],
            "max_connections": 10,
        },
    )

    print(f"Webhook URL: {webhook_url}")
    print(f"Response: {resp.json()}")

    # 驗證
    info = httpx.get(
        f"https://api.telegram.org/bot{token}/getWebhookInfo"
    ).json()
    print(f"Webhook Info: {json.dumps(info, indent=2)}")

if __name__ == "__main__":
    setup()

執行

bash
python setup_webhook.py

14.4 驗證部署
步驟 9：發送測試訊息

在 Telegram 找到你的 Bot，發送 /start。若一切正常，
應在 1-3 秒內收到歡迎訊息。

步驟 10：檢查 CloudWatch Logs

bash
# 查看 webhook handler 日誌
sam logs -n WebhookHandlerFunction --stack-name secretary-bot --tail

# 查看 reminder handler 日誌
sam logs -n ReminderHandlerFunction --stack-name secretary-bot --tail

15. Telegram Webhook 設定
15.1 Webhook 安全機制
Telegram 支援 secret_token 驗證。設定 Webhook 時傳入一個
secret_token，之後 Telegram 每次 POST 請求都會在 Header 中
附帶 X-Telegram-Bot-Api-Secret-Token，Lambda 需要驗證
此 header 值與預設的 secret 一致。

結合 URL 路徑中的 secret_path，形成雙重驗證：

完整 Webhook URL:
https://{api-id}.execute-api.ap-east-1.amazonaws.com/prod/webhook/{secret_path}

+ Header: X-Telegram-Bot-Api-Secret-Token: {webhook_secret}

15.2 Webhook vs Polling 行為差異
Polling 模式下，如果 Bot 離線，Telegram 會保留訊息，等 Bot
上線後一次性推送。Webhook 模式下，如果 Lambda 回傳非 2xx 或
逾時，Telegram 會重試（最多重試若干次，間隔遞增）。

Lambda 必須在處理完畢後回傳 200 OK，即使處理過程中發生錯誤。
否則 Telegram 會重複發送同一個 Update，造成重複處理。因此
錯誤處理必須在 Lambda 內部完成，不要讓例外冒泡到回傳層。

15.3 Webhook 限制
Telegram 的 Webhook 有以下限制：URL 必須為 HTTPS（API Gateway
預設滿足）、每個 Bot 只能設定一個 Webhook URL、Telegram 會
對 Webhook 進行連線測試（設定時）、若 Webhook 持續失敗，
Telegram 會自動停用並回退到 getUpdates 模式。

16. 測試與驗證
16.1 本地測試（SAM Local）
bash
# 測試 Webhook Handler
sam local invoke WebhookHandlerFunction \
    --event tests/events/webhook_message.json

# 測試 Reminder Handler
sam local invoke ReminderHandlerFunction \
    --event tests/events/reminder_morning.json

16.2 測試 Event Payload 範例
tests/events/webhook_message.json：

json
{
  "version": "2.0",
  "headers": {
    "x-telegram-bot-api-secret-token": "your-test-secret"
  },
  "body": "{\"update_id\":123456,\"message\":{\"message_id\":1,\"from\":{\"id\":YOUR_USER_ID,\"first_name\":\"Test\"},\"chat\":{\"id\":YOUR_USER_ID,\"type\":\"private\"},\"date\":1709366400,\"text\":\"/start\"}}"
}

tests/events/webhook_callback.json：

json
{
  "version": "2.0",
  "headers": {
    "x-telegram-bot-api-secret-token": "your-test-secret"
  },
  "body": "{\"update_id\":123457,\"callback_query\":{\"id\":\"123\",\"from\":{\"id\":YOUR_USER_ID,\"first_name\":\"Test\"},\"message\":{\"message_id\":2,\"chat\":{\"id\":YOUR_USER_ID,\"type\":\"private\"}},\"data\":\"schcat_work\"}}"
}

tests/events/reminder_morning.json：

json
{
  "reminder_type": "morning"
}

16.3 端對端測試檢查清單
測試項目	預期結果	狀態
/start	收到歡迎訊息	☐
/help	收到完整指令列表	☐
/add_schedule 完整對話	成功建立行程，收到確認訊息含 ID	☐
/today	顯示今日行程（或無行程提示）	☐
/add_todo 完整對話	成功建立待辦	☐
/done {ID}	標記完成，收到確認	☐
/add_sub 完整對話	成功建立訂閱	☐
/subs	顯示訂閱列表含統計	☐
對話中途 /cancel	對話終止，狀態清除	☐
非擁有者發送訊息	收到權限拒絕訊息	☐
等待早晨提醒時間	收到每日提醒	☐
30 分鐘不操作對話	對話狀態自動過期（TTL）	☐
Lambda 冷啟動	回應時間 < 3 秒	☐
17. 監控與日誌
17.1 CloudWatch Logs
Lambda 自動將 print() 和 logging 輸出寫入 CloudWatch Logs。
日誌群組名稱格式為 /aws/lambda/{function-name}。

建議設定日誌保留期限以控制成本：

bash
aws logs put-retention-policy \
    --log-group-name /aws/lambda/bot-webhook-handler \
    --retention-in-days 30

aws logs put-retention-policy \
    --log-group-name /aws/lambda/bot-reminder-handler \
    --retention-in-days 30

17.2 關鍵監控指標
指標	來源	告警閾值
Lambda Errors	CloudWatch	> 3 次 / 5 分鐘
Lambda Throttles	CloudWatch	> 0
Lambda Duration	CloudWatch	P95 > 10 秒
API Gateway 5XX	CloudWatch	> 0 / 5 分鐘
DynamoDB ThrottledRequests	CloudWatch	> 0
17.3 結構化日誌範例
python

查看全部
import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def log_event(event_type: str, **kwargs):
    """結構化日誌輸出"""
    log_entry = {
        "event_type": event_type,
        "timestamp": datetime.now().isoformat(),
        **kwargs,
    }
    logger.info(json.dumps(log_entry, ensure_ascii=False))

# 使用範例
log_event("command_received", command="/add_schedule", user_id=123456)
log_event("db_write", table="BotMainTable", entity="SCH", short_id=5)
log_event("telegram_api_call", method="sendMessage", status=200)

執行

18. 成本估算
18.1 使用量假設
指標	預估值
每日指令互動次數	~30 次（含對話步驟）
每月 Webhook 請求	~900 次
每月排程觸發	4 次/天 × 30 天 = 120 次
每次 Lambda 平均執行時間	Webhook: ~500ms, Reminder: ~2000ms
每月 DynamoDB 讀取	~3,000 RRU
每月 DynamoDB 寫入	~1,000 WRU
CloudWatch 日誌量	~50 MB/月
18.2 月度成本明細
服務	計算	費用 (USD)
Lambda 請求	(900 + 120) × $0.20/百萬 = ~$0.0002	$0.00
Lambda 運算	900×500ms×256MB + 120×2000ms×256MB ≈ 0.18 GB-sec	$0.00
API Gateway	900 × $1.00/百萬	$0.00
DynamoDB 讀取	3,000 × $0.283/百萬	$0.00
DynamoDB 寫入	1,000 × $1.414/百萬	$0.00
DynamoDB 儲存	< 1 GB × $0.28/GB	$0.28
EventBridge Scheduler	120 次（免費額度內）	$0.00
CloudWatch Logs	50 MB × $0.50/GB	$0.03
SSM Parameter Store	標準參數免費	$0.00
月度總計		~$0.31
Lambda 免費額度：每月 100 萬請求 + 400,000 GB-sec。
DynamoDB 免費額度：每月 25 GB 儲存 + 25 WCU + 25 RCU。
API Gateway 免費額度：首年每月 100 萬請求。

結論：在免費額度期間（首年）幾乎零成本。免費額度過後，
月成本預估在 $0.50 USD 以下。

19. 安全性檢查清單
項目	說明	狀態
S01	BOT_TOKEN 存放在 SSM SecureString，不在程式碼中	☐
S02	Webhook URL 包含 secret_path 隨機路徑	☐
S03	Lambda 驗證 X-Telegram-Bot-Api-Secret-Token header	☐
S04	Lambda 驗證 user_id == OWNER_ID	☐
S05	IAM Role 遵循最小權限原則	☐
S06	DynamoDB 主表啟用 PITR（時間點恢復）	☐
S07	DynamoDB 啟用靜態加密（預設 AWS owned key）	☐
S08	CloudWatch Logs 設定保留期限	☐
S09	API Gateway 無公開路由（僅 /webhook/{proxy+}）	☐
S10	Lambda 環境變數不含敏感資訊	☐
S11	Lambda 函數 URL 未啟用（僅透過 API Gateway 觸發）	☐
S12	SAM template 中 DeletionPolicy 為 Retain（防誤刪）	☐
20. 故障排除
20.1 Bot 沒有回應
排查順序：

第一步，確認 Webhook 是否正常：

bash
BOT_TOKEN="your_token"
curl "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo"

檢查回傳中的 url 是否正確、last_error_date 和
last_error_message 是否有錯誤。

第二步，查看 Lambda 日誌：

bash
sam logs -n WebhookHandlerFunction --stack-name secretary-bot --tail

第三步，檢查 API Gateway：在 AWS Console 進入 API Gateway →
選擇 API → 查看 Logs/Tracing。

20.2 冷啟動太慢
如果首次回應需要 3 秒以上，可以考慮：

方案一：使用 Provisioned Concurrency（為 Lambda 保留暖實例），
但會增加成本（約 $3-5/月 for 1 個保留實例）。對個人 Bot 通常
不值得。

方案二：減少部署包大小，精簡依賴。確保 Layer 不包含不必要的
套件。使用 ARM64 架構（已在 template 中設定）。

方案三：在全域範圍初始化 DynamoDB 和 httpx 客戶端（已在程式碼
中實作），利用 Lambda 容器重用。

20.3 DynamoDB 查詢效能不佳
如果某個查詢特別慢或消耗大量 RRU：

第一，確認是否使用了 Scan（全表掃描）而非 Query。Scan 會讀取
整張表的所有項目，成本高且速度慢。除了 /search 指令外，所有
操作都應使用 Query。

第二，確認 GSI 設計是否覆蓋了該查詢的存取模式。如果沒有合適
的 GSI，每次查詢可能需要全表 Scan + Filter。

第三，對於 /search 指令，接受它需要多次 Query（每種 entity
type 一次），並在每次 Query 中使用 FilterExpression。

20.4 提醒沒有發送
排查順序：

第一步，檢查 EventBridge Scheduler 狀態：

bash
aws scheduler list-schedules --region ap-east-1

確認所有排程的 State 為 ENABLED。

第二步，查看 Reminder Lambda 日誌：

bash
sam logs -n ReminderHandlerFunction --stack-name secretary-bot --tail

第三步，確認時區設定：EventBridge Scheduler 的
ScheduleExpressionTimezone 是否為 Asia/Hong_Kong。

20.5 對話狀態遺失
如果使用者在對話中途重新開始時狀態異常：

確認 ConversationTable 的 TTL 是否已啟用（TTL 是非同步刪除，
可能延遲最多 48 小時）。在查詢對話狀態時，程式碼中必須同時
檢查 expire_at > 當前時間，不能只依賴 DynamoDB TTL 自動刪除。

附錄
附錄 A：DynamoDB On-Demand 定價（ap-east-1）
操作類型	單價
寫入請求 (WRU)	$1.4135 / 百萬
讀取請求 (RRU)	$0.2827 / 百萬
儲存	$0.2827 / GB / 月
PITR 備份	$0.2260 / GB / 月
附錄 B：Lambda 定價（ap-east-1）
計費項目	單價
請求次數	$0.20 / 百萬
運算（ARM64）	$0.0000133334 / GB-sec
免費額度（每月）	100 萬請求 + 400,000 GB-sec
附錄 C：相依套件版本
apache
httpx==0.27.0
pytz==2024.1
python-ulid==2.7.0
boto3==1.34.0        # Lambda Runtime 已內建，可不打包

注意：Lambda Python 3.12 Runtime 已內建 boto3，不需要在
Layer 中打包。這可以大幅減小部署包大小。

附錄 D：後續優化方向
D.1 冷啟動優化： 若日後對回應速度要求更高，可以設定一個
EventBridge 排程每 5 分鐘觸發一次 Lambda（payload 為空或
特殊標記），讓 Lambda 保持暖狀態。這是一種低成本的
「自製 Provisioned Concurrency」方案。

D.2 DynamoDB Streams + Lambda： 未來如需即時觸發（如新增
待辦後立即推播），可以啟用 DynamoDB Streams，當表中有寫入
時觸發另一個 Lambda。

D.3 SAM Pipeline： 使用 sam pipeline init 建立 CI/CD
管線，支援 GitHub Actions 自動部署。

yaml
# .github/workflows/deploy.yml（SAM Pipeline 範例）
name: Deploy Bot
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: aws-actions/setup-sam@v2
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ap-east-1
      - run: sam build
      - run: sam deploy --no-confirm-changeset --no-fail-on-empty-changeset

============================================================
文件結束