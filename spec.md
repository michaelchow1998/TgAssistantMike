# ============================================================
# 產品規格書：私人秘書 Telegram Bot（Serverless 版）
# 文件名稱：spec.md
# 文件版本：2.0
# 最後更新：2026-03-02
# 架構方案：Lambda + API Gateway + DynamoDB + EventBridge
# ============================================================

---

## 目錄

1. [專案概述](#1-專案概述)
2. [系統架構](#2-系統架構)
3. [技術棧](#3-技術棧)
4. [資料庫設計](#4-資料庫設計)
5. [功能模組規格](#5-功能模組規格)
6. [指令總覽](#6-指令總覽)
7. [模組一：行程管理](#7-模組一行程管理)
8. [模組二：待辦事項](#8-模組二待辦事項)
9. [模組三：工作進度追蹤](#9-模組三工作進度追蹤)
10. [模組四：財務管理](#10-模組四財務管理)
11. [模組五：訂閱管理](#11-模組五訂閱管理)
12. [模組六：綜合查詢](#12-模組六綜合查詢)
13. [模組七：定時提醒](#13-模組七定時提醒)
14. [對話流程設計](#14-對話流程設計)
15. [Telegram API 互動規格](#15-telegram-api-互動規格)
16. [安全設計](#16-安全設計)
17. [錯誤處理規格](#17-錯誤處理規格)
18. [Lambda 函數規格](#18-lambda-函數規格)
19. [API Gateway 規格](#19-api-gateway-規格)
20. [EventBridge Scheduler 規格](#20-eventbridge-scheduler-規格)
21. [IAM 權限規格](#21-iam-權限規格)
22. [監控與告警規格](#22-監控與告警規格)
23. [部署規格](#23-部署規格)
24. [檔案結構](#24-檔案結構)
25. [非功能性需求](#25-非功能性需求)
26. [限制與已知約束](#26-限制與已知約束)
27. [附錄](#附錄)

---

## 1. 專案概述

### 1.1 產品定義

一個基於 Telegram Bot 的私人秘書系統，採用 AWS Serverless 架構，
提供行程管理、待辦事項、工作進度追蹤、財務管理、訂閱管理等功能。
系統透過 Webhook 接收使用者訊息，由 Lambda 函數即時處理並回覆；
定時提醒由 EventBridge Scheduler 觸發獨立的 Lambda 函數執行。

### 1.2 目標使用者

單一使用者（Bot 擁有者）。系統透過 Telegram User ID 進行存取控制，
僅允許預設的 OWNER_ID 操作所有功能。

### 1.3 設計原則

**事件驅動**：所有處理皆由事件觸發（Webhook 請求或排程事件），
無長駐進程，閒置時零資源消耗。

**無狀態處理**：每次 Lambda 呼叫為獨立請求，對話狀態持久化至
DynamoDB，不依賴進程記憶體。

**最小權限**：每個 Lambda 函數僅擁有完成其任務所需的最低 IAM
權限。

**成本優先**：所有服務採用按需計費（On-Demand），在個人使用場景
下維持極低成本（預估月費 < $0.50 USD）。

**免運維**：不使用 EC2、ECS 等需要管理作業系統的服務。所有基礎
設施由 AWS 全託管。

### 1.4 與 v1.0 的主要差異

| 項目           | v1.0（原始設計）                | v2.0（本版 Serverless 設計）        |
|---------------|--------------------------------|------------------------------------|
| 訊息接收       | Polling（Bot 主動拉取）          | Webhook（Telegram 推送至 API GW）   |
| 運行環境       | EC2 / VPS 上的 Python 進程       | AWS Lambda（事件觸發，按需執行）     |
| 框架           | python-telegram-bot v20.x       | 自行解析 Webhook + httpx 呼叫 API   |
| 資料庫         | SQLite3（單一檔案）              | DynamoDB（全託管 NoSQL）            |
| 排程引擎       | APScheduler / JobQueue           | EventBridge Scheduler              |
| 對話狀態       | ConversationHandler（記憶體）    | DynamoDB + TTL 自動過期             |
| 部署方式       | systemd + 手動部署               | AWS SAM（IaC）                     |
| 日誌           | 本地檔案 + journald              | CloudWatch Logs（自動）            |
| 成本           | VPS 月租 ~$5-10                  | ~$0.00-0.50/月                     |
| ID 系統        | INTEGER AUTOINCREMENT            | ULID + 短 ID（原子計數器）          |

---

## 2. 系統架構

### 2.1 架構總覽

系統由兩條主要處理路徑組成：

**路徑一：使用者互動（同步）**

使用者在 Telegram 發送訊息或點擊按鈕 → Telegram Bot API 透過
Webhook 將 Update POST 至 API Gateway → API Gateway 觸發
bot-webhook-handler Lambda → Lambda 解析請求、驗證身分、
讀寫 DynamoDB、呼叫 Telegram API 回覆使用者 → 回傳 200 OK
給 API Gateway。

**路徑二：定時提醒（非同步）**

EventBridge Scheduler 按預設 cron 表達式觸發 bot-reminder-handler
Lambda → Lambda 從 DynamoDB 查詢相關資料 → 組合提醒訊息 →
呼叫 Telegram API 發送至擁有者。

### 2.2 AWS 服務組成

| 服務                        | 角色                                    |
|----------------------------|-----------------------------------------|
| API Gateway (HTTP API v2)   | HTTPS 端點，接收 Telegram Webhook        |
| Lambda (Python 3.12, ARM64) | 業務邏輯執行                              |
| DynamoDB (On-Demand)        | 資料持久化儲存                            |
| EventBridge Scheduler       | 定時排程觸發                              |
| SSM Parameter Store         | 敏感設定（Token、Secret）                 |
| CloudWatch Logs             | 執行日誌                                  |
| CloudWatch Alarms           | 錯誤率告警                                |
| SNS                         | 告警通知                                  |
| S3                          | SAM 部署暫存（自動管理）                   |
| IAM                         | 權限控制                                  |

### 2.3 Region 選擇

ap-east-1（Hong Kong）。選擇依據：使用者位於香港，最低延遲。

---

## 3. 技術棧

### 3.1 運行時

| 元件                   | 技術選擇                        | 版本        |
|------------------------|--------------------------------|-------------|
| Lambda Runtime          | Python                          | 3.12        |
| Lambda Architecture     | ARM64 (Graviton2)               | —           |
| IaC 工具                | AWS SAM                         | Latest      |

### 3.2 Python 依賴

| 套件            | 版本      | 用途                                    | 部署位置           |
|----------------|-----------|----------------------------------------|--------------------|
| httpx           | 0.27.0    | 呼叫 Telegram Bot API（同步 HTTP）       | Lambda Layer       |
| pytz            | 2024.1    | 時區處理（Asia/Hong_Kong）               | Lambda Layer       |
| python-ulid     | 2.7.0     | 生成 ULID（時間有序唯一 ID）              | Lambda Layer       |
| boto3           | (內建)    | AWS SDK（DynamoDB、SSM）                 | Lambda Runtime 內建 |

### 3.3 移除的依賴

| 套件                     | 原用途                           | 替代方案                        |
|-------------------------|----------------------------------|---------------------------------|
| python-telegram-bot      | Telegram Bot 框架                 | 自行解析 JSON + httpx 呼叫 API  |
| apscheduler              | 進程內排程器                      | EventBridge Scheduler           |
| sqlite3                  | 本地資料庫                        | DynamoDB                        |

### 3.4 不使用 python-telegram-bot 框架的理由

python-telegram-bot v20.x 的核心設計基於長駐進程：Application 物件
管理事件迴圈、Dispatcher 路由 Update、ConversationHandler 在記憶體
中管理對話狀態、JobQueue 排程任務。這些在 Lambda 環境中均無法正常
運作（每次呼叫是獨立的、無共享記憶體、無事件迴圈）。

雖然可以部分使用框架（如僅用 Update 物件的反序列化），但框架依賴
較重（~15 MB），會增加冷啟動時間。Telegram Bot API 的 JSON 結構
簡單且穩定，自行解析的開發成本低於框架適配的成本。

---

## 4. 資料庫設計

### 4.1 DynamoDB 表總覽

| 表名稱                | 用途                              | 計費模式       | TTL   |
|----------------------|-----------------------------------|---------------|-------|
| BotMainTable          | 所有業務資料（行程/待辦/工作/財務/訂閱） | On-Demand     | 無    |
| BotConversationTable  | 進行中的對話狀態                    | On-Demand     | 啟用  |

### 4.2 BotMainTable — 主鍵

| 屬性  | 鍵類型         | 型別 | 格式                        |
|------|---------------|------|----------------------------|
| PK   | Partition Key | S    | `{ENTITY_TYPE}#{ulid}`     |
| SK   | Sort Key      | S    | `{ENTITY_TYPE}#META`       |

ENTITY_TYPE 對照：

| 實體     | ENTITY_TYPE | PK 範例               |
|----------|-------------|----------------------|
| 行程     | SCH         | `SCH#01HXK5P2ABCDEF`  |
| 待辦     | TODO        | `TODO#01HXK5R3GHIJK`  |
| 工作進度 | WORK        | `WORK#01HXK5T4LMNOP`  |
| 財務     | FIN         | `FIN#01HXK5V5QRSTU`   |
| 訂閱     | SUB         | `SUB#01HXK5W6VWXYZ`   |
| 計數器   | COUNTER     | `COUNTER`              |

### 4.3 BotMainTable — GSI 設計

**GSI-1：GSI_Type_Date（按狀態 + 日期查詢）**

| 屬性     | 鍵類型         | 型別 | 格式                                |
|---------|---------------|------|-------------------------------------|
| GSI1PK  | Partition Key | S    | `{ENTITY_TYPE}#{status}`            |
| GSI1SK  | Sort Key      | S    | `{date_field}#{time}#{ulid}`        |

Projection: ALL

覆蓋的存取模式：查詢指定日期行程、查詢 pending 待辦、查詢
進行中工作、查詢待付款項、查詢有效訂閱、依日期範圍篩選。

**GSI-2：GSI_Category（按分類查詢）**

| 屬性     | 鍵類型         | 型別 | 格式                                      |
|---------|---------------|------|-------------------------------------------|
| GSI2PK  | Partition Key | S    | `{ENTITY_TYPE}#{category}`                |
| GSI2SK  | Sort Key      | S    | `{status}#{date_field}#{time}#{ulid}`     |

Projection: ALL

覆蓋的存取模式：按分類查詢各類實體、按分類 + 狀態篩選。

**GSI-3：GSI_ShortID（短 ID 查詢）**

| 屬性     | 鍵類型         | 型別 | 格式                         |
|---------|---------------|------|------------------------------|
| GSI3PK  | Partition Key | S    | `{ENTITY_TYPE}`              |
| GSI3SK  | Sort Key      | S    | `{short_id 五位零填充}`       |

Projection: ALL

覆蓋的存取模式：使用者以短 ID 操作（如 `/done 3`）。

### 4.4 BotMainTable — 項目屬性定義

#### 4.4.1 行程（Schedule）

| 屬性          | 型別    | 必填 | 說明                         | 範例                          |
|--------------|---------|------|------------------------------|-------------------------------|
| PK           | S       | ✅   | 主分區鍵                      | `SCH#01HXK5P2ABCDEF`         |
| SK           | S       | ✅   | 主排序鍵                      | `SCH#META`                    |
| entity_type  | S       | ✅   | 實體類型標記                   | `SCH`                         |
| short_id     | N       | ✅   | 使用者操作用短 ID              | `1`                           |
| title        | S       | ✅   | 行程標題                      | `週一開會`                     |
| description  | S       | ❌   | 詳細說明                      | `討論 Q2 計畫`                |
| category     | S       | ✅   | 分類                          | `work`                        |
| event_date   | S       | ✅   | 日期 (YYYY-MM-DD)             | `2026-03-05`                  |
| event_time   | S       | ❌   | 時間 (HH:MM)                  | `14:00`                       |
| location     | S       | ❌   | 地點                          | `會議室 A`                     |
| status       | S       | ✅   | 狀態                          | `active` / `cancelled`         |
| created_at   | S       | ✅   | 建立時間 (ISO 8601)           | `2026-03-02T10:30:00+08:00`   |
| GSI1PK       | S       | ✅   | GSI-1 分區鍵                  | `SCH#active`                  |
| GSI1SK       | S       | ✅   | GSI-1 排序鍵                  | `2026-03-05#14:00#01HXK...`   |
| GSI2PK       | S       | ✅   | GSI-2 分區鍵                  | `SCH#work`                    |
| GSI2SK       | S       | ✅   | GSI-2 排序鍵                  | `active#2026-03-05#14:00#...` |
| GSI3PK       | S       | ✅   | GSI-3 分區鍵                  | `SCH`                         |
| GSI3SK       | S       | ✅   | GSI-3 排序鍵                  | `00001`                       |

行程狀態值：`active`（有效）、`cancelled`（已取消）。

行程分類值：`work`（工作）、`personal`（個人）、`health`（健康）、
`social`（社交）、`other`（其他）。

#### 4.4.2 待辦（Todo）

| 屬性          | 型別    | 必填 | 說明                         | 範例                          |
|--------------|---------|------|------------------------------|-------------------------------|
| PK           | S       | ✅   | 主分區鍵                      | `TODO#01HXK5R3GHIJK`         |
| SK           | S       | ✅   | 主排序鍵                      | `TODO#META`                   |
| entity_type  | S       | ✅   | 實體類型標記                   | `TODO`                        |
| short_id     | N       | ✅   | 短 ID                         | `1`                           |
| title        | S       | ✅   | 待辦標題                      | `準備報告`                     |
| description  | S       | ❌   | 詳細說明                      | `包含 Q1 數據`                |
| category     | S       | ✅   | 分類                          | `work`                        |
| priority     | N       | ✅   | 優先級 (1=高, 2=中, 3=低)     | `1`                           |
| due_date     | S       | ❌   | 截止日期 (YYYY-MM-DD)         | `2026-03-10`                  |
| status       | S       | ✅   | 狀態                          | `pending`                     |
| created_at   | S       | ✅   | 建立時間                      | `2026-03-02T10:35:00+08:00`   |
| completed_at | S       | ❌   | 完成時間                      | `null`                        |
| GSI1PK       | S       | ✅   | GSI-1 分區鍵                  | `TODO#pending`                |
| GSI1SK       | S       | ✅   | GSI-1 排序鍵                  | `2026-03-10#01HXK5R3...`     |
| GSI2PK       | S       | ✅   | GSI-2 分區鍵                  | `TODO#work`                   |
| GSI2SK       | S       | ✅   | GSI-2 排序鍵                  | `pending#2026-03-10#01HX...` |
| GSI3PK       | S       | ✅   | GSI-3 分區鍵                  | `TODO`                        |
| GSI3SK       | S       | ✅   | GSI-3 排序鍵                  | `00001`                       |

待辦狀態值：`pending`（待完成）、`completed`（已完成）、`deleted`（已刪除）。

待辦分類值：與行程相同。

待辦優先級值：`1`（🔴 高）、`2`（🟡 中）、`3`（🟢 低）。

無截止日期的待辦，GSI1SK 使用 `9999-12-31#{ulid}` 確保排在最後。

#### 4.4.3 工作進度（Work Project）

| 屬性           | 型別    | 必填 | 說明                         | 範例                          |
|---------------|---------|------|------------------------------|-------------------------------|
| PK            | S       | ✅   | 主分區鍵                      | `WORK#01HXK5T4LMNOP`        |
| SK            | S       | ✅   | 主排序鍵                      | `WORK#META`                  |
| entity_type   | S       | ✅   | 實體類型標記                   | `WORK`                       |
| short_id      | N       | ✅   | 短 ID                         | `1`                          |
| project_name  | S       | ✅   | 專案名稱                      | `網站改版`                    |
| task_name     | S       | ✅   | 任務名稱                      | `前端開發`                    |
| description   | S       | ❌   | 詳細說明                      | `使用 React`                 |
| category      | S       | ✅   | 分類                          | `development`                |
| progress      | N       | ✅   | 進度百分比 (0-100)             | `45`                         |
| deadline      | S       | ❌   | 截止日期 (YYYY-MM-DD)         | `2026-03-20`                 |
| status        | S       | ✅   | 狀態                          | `in_progress`                |
| created_at    | S       | ✅   | 建立時間                      | `2026-03-01T09:00:00+08:00`  |
| updated_at    | S       | ✅   | 最後更新時間                   | `2026-03-02T15:00:00+08:00`  |
| GSI1PK        | S       | ✅   | GSI-1 分區鍵                  | `WORK#in_progress`           |
| GSI1SK        | S       | ✅   | GSI-1 排序鍵                  | `2026-03-20#01HXK5T4...`    |
| GSI2PK        | S       | ✅   | GSI-2 分區鍵                  | `WORK#development`           |
| GSI2SK        | S       | ✅   | GSI-2 排序鍵                  | `in_progress#2026-03-20#...` |
| GSI3PK        | S       | ✅   | GSI-3 分區鍵                  | `WORK`                       |
| GSI3SK        | S       | ✅   | GSI-3 排序鍵                  | `00001`                      |

工作狀態值：`in_progress`（進行中）、`completed`（已完成）、
`on_hold`（暫停）。

工作分類值：`development`（開發）、`design`（設計）、`marketing`
（行銷）、`management`（管理）、`research`（研究）、`other`（其他）。

無截止日期的工作，GSI1SK 使用 `9999-12-31#{ulid}`。

#### 4.4.4 財務（Finance）

| 屬性           | 型別    | 必填 | 說明                         | 範例                          |
|---------------|---------|------|------------------------------|-------------------------------|
| PK            | S       | ✅   | 主分區鍵                      | `FIN#01HXK5V5QRSTU`         |
| SK            | S       | ✅   | 主排序鍵                      | `FIN#META`                   |
| entity_type   | S       | ✅   | 實體類型標記                   | `FIN`                        |
| short_id      | N       | ✅   | 短 ID                         | `1`                          |
| type          | S       | ✅   | 類型                          | `payment`                    |
| title         | S       | ✅   | 名稱                          | `信用卡還款`                  |
| amount        | N       | ✅   | 金額（Decimal）               | `5000.00`                    |
| currency      | S       | ✅   | 幣別                          | `HKD`                        |
| due_date      | S       | ❌   | 到期日 (YYYY-MM-DD)           | `2026-03-15`                 |
| is_recurring  | N       | ✅   | 是否週期性 (1/0)              | `1`                          |
| recurring_day | N       | ❌   | 每月固定日                    | `15`                         |
| category      | S       | ✅   | 分類                          | `bills`                      |
| status        | S       | ✅   | 狀態                          | `pending`                    |
| notes         | S       | ❌   | 備註                          | `恆生信用卡`                  |
| created_at    | S       | ✅   | 建立時間                      | `2026-03-01T09:00:00+08:00`  |
| paid_at       | S       | ❌   | 付款時間                      | `null`                       |
| GSI1PK        | S       | ✅   | GSI-1 分區鍵                  | `FIN#pending`                |
| GSI1SK        | S       | ✅   | GSI-1 排序鍵                  | `2026-03-15#01HXK5V5...`    |
| GSI2PK        | S       | ✅   | GSI-2 分區鍵                  | `FIN#bills`                  |
| GSI2SK        | S       | ✅   | GSI-2 排序鍵                  | `pending#2026-03-15#01HX...` |
| GSI3PK        | S       | ✅   | GSI-3 分區鍵                  | `FIN`                        |
| GSI3SK        | S       | ✅   | GSI-3 排序鍵                  | `00001`                      |

財務類型值：`payment`（應付款項）、`income`（收入）、`expense`（支出）。

財務狀態值：`pending`（待付）、`paid`（已付）、`cancelled`（已取消）。

財務分類值：`bills`（帳單）、`salary`（薪資）、`food`（餐飲）、
`transport`（交通）、`entertainment`（娛樂）、`shopping`（購物）、
`health`（醫療）、`education`（教育）、`investment`（投資）、
`other`（其他）。

#### 4.4.5 訂閱（Subscription）

| 屬性            | 型別    | 必填 | 說明                         | 範例                          |
|----------------|---------|------|------------------------------|-------------------------------|
| PK             | S       | ✅   | 主分區鍵                      | `SUB#01HXK5W6VWXYZ`         |
| SK             | S       | ✅   | 主排序鍵                      | `SUB#META`                   |
| entity_type    | S       | ✅   | 實體類型標記                   | `SUB`                        |
| short_id       | N       | ✅   | 短 ID                         | `1`                          |
| name           | S       | ✅   | 訂閱名稱                      | `Apple Music`                |
| amount         | N       | ✅   | 費用（Decimal）               | `78.00`                      |
| currency       | S       | ✅   | 幣別                          | `HKD`                        |
| billing_cycle  | S       | ✅   | 計費週期                      | `monthly`                    |
| billing_day    | N       | ✅   | 計費日                        | `15`                         |
| next_due_date  | S       | ✅   | 下次到期日 (YYYY-MM-DD)       | `2026-04-15`                 |
| category       | S       | ✅   | 分類                          | `entertainment`              |
| auto_renew     | N       | ✅   | 自動續訂 (1/0)                | `1`                          |
| notes          | S       | ❌   | 備註                          | `家庭方案`                    |
| status         | S       | ✅   | 狀態                          | `active`                     |
| created_at     | S       | ✅   | 建立時間                      | `2026-03-01T09:00:00+08:00`  |
| last_renewed_at| S       | ❌   | 最後續訂時間                   | `2026-03-15T08:00:00+08:00`  |
| GSI1PK         | S       | ✅   | GSI-1 分區鍵                  | `SUB#active`                 |
| GSI1SK         | S       | ✅   | GSI-1 排序鍵                  | `2026-04-15#01HXK5W6...`    |
| GSI2PK         | S       | ✅   | GSI-2 分區鍵                  | `SUB#entertainment`          |
| GSI2SK         | S       | ✅   | GSI-2 排序鍵                  | `active#2026-04-15#01HX...`  |
| GSI3PK         | S       | ✅   | GSI-3 分區鍵                  | `SUB`                        |
| GSI3SK         | S       | ✅   | GSI-3 排序鍵                  | `00001`                      |

訂閱狀態值：`active`（有效）、`paused`（暫停）、`cancelled`（已取消）。

計費週期值：`monthly`（每月）、`quarterly`（每季）、`yearly`（每年）。

訂閱分類值：`streaming`（串流）、`software`（軟體）、`cloud`（雲端）、
`entertainment`（娛樂）、`news`（新聞）、`health`（健康）、
`education`（教育）、`other`（其他）。

#### 4.4.6 計數器（Counter）

| 屬性          | 型別    | 說明                         | 範例           |
|--------------|---------|------------------------------|----------------|
| PK           | S       | 固定值                        | `COUNTER`      |
| SK           | S       | 實體類型                      | `SCH`          |
| current_value| N       | 當前最大值                    | `5`            |

每種實體類型一筆計數器記錄。新增項目時使用 `UpdateExpression`
的 `ADD current_value :inc`（`:inc` = 1）進行原子遞增，
`ReturnValues` 設為 `UPDATED_NEW` 取得遞增後的值作為新項目的
short_id。此操作是原子性的，併發安全。

### 4.5 BotConversationTable — 結構

| 屬性        | 型別    | 鍵類型         | 說明                         | 範例                          |
|------------|---------|---------------|------------------------------|-------------------------------|
| PK         | S       | Partition Key | 使用者 ID                     | `USER#123456789`             |
| SK         | S       | Sort Key      | 固定值                        | `CONV#active`                |
| module     | S       | —             | 對話所屬模組                   | `schedule`                   |
| step       | S       | —             | 當前對話步驟                   | `SCH_DATE`                   |
| data       | M       | —             | 已收集的對話資料               | `{"sch_title": "週一開會"}`  |
| started_at | S       | —             | 對話開始時間                   | `2026-03-02T10:30:00+08:00`  |
| expire_at  | N       | —             | TTL 過期時間 (Unix timestamp)  | `1740900600`                 |

TTL 設定：`expire_at` 屬性已在表級別啟用 TTL。每次更新對話狀態
時，將 `expire_at` 設定為當前時間 + 30 分鐘。DynamoDB TTL 會
在過期後自動刪除項目（實際刪除可能延遲至 48 小時，因此查詢時
必須同時以程式碼檢查 `expire_at > 當前時間`）。

每個使用者同一時間只會有一筆 `CONV#active` 記錄。開始新對話時
直接以 `PutItem` 覆寫舊記錄。

### 4.6 完整存取模式清單

| 編號 | 存取模式                              | 表/索引            | Key 條件                                                  | 排序方向 |
|------|--------------------------------------|--------------------|----------------------------------------------------------|---------|
| AP01 | 以 ULID 取得單一項目                  | Main PK+SK         | PK = `{TYPE}#{ulid}`, SK = `{TYPE}#META`                 | —       |
| AP02 | 以短 ID 取得項目                      | GSI-3              | GSI3PK = `{TYPE}`, GSI3SK = `{short_id}`                 | —       |
| AP03 | 今日行程                              | GSI-1              | GSI1PK = `SCH#active`, GSI1SK begins_with `{today}`      | ASC     |
| AP04 | 日期範圍行程                          | GSI-1              | GSI1PK = `SCH#active`, GSI1SK between `{start}#` ~ `{end}#~` | ASC |
| AP05 | pending 待辦（按截止日排序）           | GSI-1              | GSI1PK = `TODO#pending`                                   | ASC     |
| AP06 | 過期未完成待辦                        | GSI-1 + Filter     | GSI1PK = `TODO#pending`, GSI1SK < `{today}#`             | ASC     |
| AP07 | 按分類查詢待辦                        | GSI-2              | GSI2PK = `TODO#{category}`                                | ASC     |
| AP08 | 進行中工作                            | GSI-1              | GSI1PK = `WORK#in_progress`                               | ASC     |
| AP09 | 即將到期工作（N 天內）                 | GSI-1              | GSI1PK = `WORK#in_progress`, GSI1SK between range         | ASC     |
| AP10 | 待付款項（按到期日排序）               | GSI-1              | GSI1PK = `FIN#pending`                                    | ASC     |
| AP11 | 即將到期付款（N 天內）                 | GSI-1              | GSI1PK = `FIN#pending`, GSI1SK between range              | ASC     |
| AP12 | 週期性付款                            | GSI-1 + Filter     | GSI1PK = `FIN#pending`, Filter: is_recurring = 1          | ASC     |
| AP13 | 月度收支統計（已付）                   | GSI-1              | GSI1PK = `FIN#paid`, GSI1SK between month range           | ASC     |
| AP14 | 有效訂閱                              | GSI-1              | GSI1PK = `SUB#active`                                     | ASC     |
| AP15 | 即將到期訂閱（N 天內）                 | GSI-1              | GSI1PK = `SUB#active`, GSI1SK between range               | ASC     |
| AP16 | 按分類查詢訂閱                        | GSI-2              | GSI2PK = `SUB#{category}`                                 | ASC     |
| AP17 | 暫停中訂閱                            | GSI-1              | GSI1PK = `SUB#paused`                                     | ASC     |
| AP18 | 取得對話狀態                          | Conv PK+SK         | PK = `USER#{id}`, SK = `CONV#active`                     | —       |
| AP19 | 關鍵字搜尋                            | GSI-1 + Filter     | 各 TYPE 分別 Query, Filter: contains(title, kw)           | ASC     |
| AP20 | 月度財務報表（所有類型）               | GSI-1              | 分別查 FIN#paid, FIN#pending, month range                 | ASC     |
| AP21 | 訂閱月度費用統計                       | GSI-1 + Aggregate  | GSI1PK = `SUB#active`, 客戶端加總 amount                  | —       |

---

## 5. 功能模組規格

### 5.1 模組清單

| 模組     | 功能                                          | 指令數量 |
|----------|----------------------------------------------|---------|
| 行程管理 | 新增/查詢/取消行程                              | 4       |
| 待辦事項 | 新增/查詢/完成/刪除待辦                         | 4       |
| 工作進度 | 新增/查詢/更新進度/查看截止日                    | 4       |
| 財務管理 | 新增付款/收入/支出、查詢、標記已付、月度統計      | 6       |
| 訂閱管理 | 新增/查詢/續訂/暫停/恢復/取消/編輯/到期/費用統計  | 9       |
| 綜合查詢 | 每日摘要/搜尋/月度報表                          | 3       |
| 定時提醒 | 早晨/晚間提醒、付款/訂閱到期警告                 | 4 排程   |
| 系統     | 開始/幫助/取消                                  | 3       |

---

## 6. 指令總覽

### 6.1 完整指令表

| 指令                | 模組     | 觸發對話 | 說明                     | 引數                |
|--------------------|----------|---------|--------------------------|---------------------|
| `/start`           | 系統     | 否       | 歡迎訊息                  | —                   |
| `/help`            | 系統     | 否       | 顯示所有可用指令           | —                   |
| `/cancel`          | 系統     | 否       | 取消進行中的對話           | —                   |
| `/add_schedule`    | 行程     | ✅       | 新增行程（進入對話流程）    | —                   |
| `/today`           | 行程     | 否       | 查看今日行程               | —                   |
| `/week`            | 行程     | 否       | 查看未來 7 天行程          | —                   |
| `/cancel_schedule` | 行程     | 否       | 取消指定行程               | `{短ID}`            |
| `/add_todo`        | 待辦     | ✅       | 新增待辦（進入對話流程）    | —                   |
| `/todos`           | 待辦     | 否       | 查看所有待辦               | —                   |
| `/done`            | 待辦     | 否       | 標記待辦完成               | `{短ID}`            |
| `/del_todo`        | 待辦     | 否       | 刪除待辦                  | `{短ID}`            |
| `/add_work`        | 工作     | ✅       | 新增工作項目（進入對話流程） | —                   |
| `/work`            | 工作     | 否       | 查看所有進行中工作         | —                   |
| `/update_progress` | 工作     | 否       | 更新工作進度               | `{短ID} {百分比}`   |
| `/deadlines`       | 工作     | 否       | 查看即將到期工作           | —                   |
| `/add_payment`     | 財務     | ✅       | 新增應付款項（進入對話流程） | —                   |
| `/add_income`      | 財務     | ✅       | 新增收入（進入對話流程）    | —                   |
| `/add_expense`     | 財務     | ✅       | 新增支出（進入對話流程）    | —                   |
| `/payments`        | 財務     | 否       | 查看待付款項               | —                   |
| `/paid`            | 財務     | 否       | 標記已付款                 | `{短ID}`            |
| `/finance_summary` | 財務     | 否       | 月度財務統計               | —                   |
| `/add_sub`         | 訂閱     | ✅       | 新增訂閱（進入對話流程）    | —                   |
| `/subs`            | 訂閱     | 否       | 查看所有訂閱               | —                   |
| `/sub_due`         | 訂閱     | 否       | 查看即將到期訂閱           | —                   |
| `/renew_sub`       | 訂閱     | 否       | 手動續訂                  | `{短ID}`            |
| `/pause_sub`       | 訂閱     | 否       | 暫停訂閱                  | `{短ID}`            |
| `/resume_sub`      | 訂閱     | ✅       | 恢復訂閱（需輸入新到期日）  | `{短ID}`            |
| `/cancel_sub`      | 訂閱     | 否       | 取消訂閱（需確認）         | `{短ID}`            |
| `/edit_sub`        | 訂閱     | ✅       | 編輯訂閱（進入對話流程）    | `{短ID}`            |
| `/sub_cost`        | 訂閱     | 否       | 訂閱費用統計               | —                   |
| `/summary`         | 綜合查詢 | 否       | 每日綜合摘要               | —                   |
| `/search`          | 綜合查詢 | 否       | 關鍵字搜尋                 | `{關鍵字}`          |
| `/monthly_report`  | 綜合查詢 | 否       | 月度綜合報表               | `{YYYY-MM}` (可選)  |

### 6.2 帶引數指令的解析規格

帶引數的指令格式為 `/command arg1 arg2`，以空格分隔。

| 指令                | 引數格式            | 範例                       | 無引數時行為         |
|--------------------|--------------------|-----------------------------|---------------------|
| `/cancel_schedule` | `{整數}`            | `/cancel_schedule 3`        | 回覆提示需要 ID     |
| `/done`            | `{整數}`            | `/done 5`                   | 回覆提示需要 ID     |
| `/del_todo`        | `{整數}`            | `/del_todo 2`               | 回覆提示需要 ID     |
| `/update_progress` | `{整數} {0-100}`    | `/update_progress 1 75`     | 回覆提示格式        |
| `/paid`            | `{整數}`            | `/paid 4`                   | 回覆提示需要 ID     |
| `/renew_sub`       | `{整數}`            | `/renew_sub 1`              | 回覆提示需要 ID     |
| `/pause_sub`       | `{整數}`            | `/pause_sub 2`              | 回覆提示需要 ID     |
| `/resume_sub`      | `{整數}`            | `/resume_sub 2`             | 回覆提示需要 ID     |
| `/cancel_sub`      | `{整數}`            | `/cancel_sub 3`             | 回覆提示需要 ID     |
| `/edit_sub`        | `{整數}`            | `/edit_sub 1`               | 回覆提示需要 ID     |
| `/search`          | `{字串}`            | `/search 開會`              | 回覆提示需要關鍵字   |
| `/monthly_report`  | `{YYYY-MM}` (可選)  | `/monthly_report 2026-03`   | 預設為當前月份       |

---

## 7. 模組一：行程管理

### 7.1 新增行程 (`/add_schedule`)

**對話流程：**


步驟 1 — 標題 (SCH_TITLE)
Bot：「📅 新增行程\n\n請輸入行程標題：」
使用者：輸入文字（1-100 字元）
驗證：不可為空、不可超過 100 字元

步驟 2 — 日期 (SCH_DATE)
Bot：「請輸入日期：\n支援格式：YYYY-MM-DD、MM-DD、明天、後天、下週一」
使用者：輸入日期
驗證：可解析為有效日期、不可為過去日期
支援的中文輸入：今天、明天、後天、大後天、
下週一~下週日、下個月{N}號

步驟 3 — 時間 (SCH_TIME)
Bot：「請輸入時間（HH:MM）：\n或點擊『跳過』」
InlineKeyboard：[[{text: "⏭ 跳過", callback_data: "sch_skip_time"}]]
使用者：輸入時間或點擊跳過
驗證：HH:MM 格式、00:00-23:59 範圍

步驟 4 — 地點 (SCH_LOCATION)
Bot：「請輸入地點：\n或點擊『跳過』」
InlineKeyboard：[[{text: "⏭ 跳過", callback_data: "sch_skip_location"}]]
使用者：輸入地點或點擊跳過
驗證：0-200 字元

步驟 5 — 分類 (SCH_CATEGORY)
Bot：「請選擇分類：」
InlineKeyboard：
[[{text: "💼 工作", callback_data: "schcat_work"}],
[{text: "👤 個人", callback_data: "schcat_personal"}],
[{text: "🏥 健康", callback_data: "schcat_health"}],
[{text: "👥 社交", callback_data: "schcat_social"}],
[{text: "📦 其他", callback_data: "schcat_other"}]]

步驟 6 — 確認 (SCH_CONFIRM)
Bot：
「📅 確認新增行程：\n\n
標題：{title}\n
日期：{date}\n
時間：{time or '未設定'}\n
地點：{location or '未設定'}\n
分類：{category_emoji} {category}\n\n
確定新增嗎？」
InlineKeyboard：
[[{text: "✅ 確認", callback_data: "sch_confirm_yes"},
{text: "❌ 取消", callback_data: "sch_confirm_no"}]]

scheme

**DynamoDB 操作：**

確認後執行：

1. `_get_next_short_id("SCH")` → 取得 short_id
2. `_generate_id()` → 生成 ULID
3. `main_table.put_item()` → 寫入行程記錄（含所有 GSI 屬性）
4. `conv_table.delete_item()` → 清除對話狀態

**回覆訊息：**


✅ 行程已建立！

📅 #{short_id} {title}
📆 {date} {time}
📍 {location}
🏷️ {category}

scheme

### 7.2 查看今日行程 (`/today`)

**DynamoDB 查詢（AP03）：**

```python
GSI_Type_Date.query(
    GSI1PK = "SCH#active",
    GSI1SK begins_with "{today}"  # e.g., "2026-03-02"
)

回覆訊息（有行程）：

📅 今日行程 (2026-03-02, 週一)

1️⃣ #1 週一開會
   🕐 14:00 | 📍 會議室 A | 💼 工作

2️⃣ #3 牙醫覆診
   🕐 18:30 | 📍 XX 診所 | 🏥 健康

共 2 項行程

回覆訊息（無行程）：

📅 今日行程 (2026-03-02, 週一)

今日暫無行程安排 🎉

7.3 查看本週行程 (/week)
DynamoDB 查詢（AP04）：

python
GSI_Type_Date.query(
    GSI1PK = "SCH#active",
    GSI1SK between "{today}#" and "{today+6}#~"
)

執行

回覆訊息：

按日期分組顯示，每天為一個區塊。無行程的日期不顯示。

apache
📅 未來 7 天行程 (03/02 - 03/08)

📆 03/02 (週一)
  #1 週一開會 🕐 14:00 | 💼

📆 03/05 (週四)
  #2 客戶提案 🕐 10:00 | 💼
  #3 牙醫覆診 🕐 18:30 | 🏥

📆 03/07 (週六)
  #5 朋友聚餐 🕐 19:00 | 👥

共 4 項行程

7.4 取消行程 (/cancel_schedule {ID})
DynamoDB 操作（AP02 → UpdateItem）：

GSI-3 查詢取得項目
更新 status → cancelled
更新 GSI1PK → SCH#cancelled
更新 GSI2SK → 替換 status 前綴
回覆訊息：

✅ 已取消行程 #3：牙醫覆診 (2026-03-05)

錯誤回覆：

❌ 找不到 ID 為 99 的行程。

8. 模組二：待辦事項
8.1 新增待辦 (/add_todo)
對話流程：

json
步驟 1 — 標題 (TODO_TITLE)
  Bot：「📝 新增待辦\n\n請輸入待辦事項：」
  驗證：1-200 字元

步驟 2 — 截止日 (TODO_DUE)
  Bot：「請輸入截止日期：\n支援格式：YYYY-MM-DD、MM-DD、明天、後天\n或點擊『無截止日』」
  InlineKeyboard：[[{text: "⏭ 無截止日", callback_data: "todo_skip_due"}]]
  驗證：有效日期

步驟 3 — 分類 (TODO_CATEGORY)
  Bot：「請選擇分類：」
  InlineKeyboard：同行程分類

步驟 4 — 優先級 (TODO_PRIORITY)
  Bot：「請選擇優先級：」
  InlineKeyboard：
    [[{text: "🔴 高", callback_data: "todopri_1"}],
     [{text: "🟡 中", callback_data: "todopri_2"}],
     [{text: "🟢 低", callback_data: "todopri_3"}]]

步驟 5 — 確認 (TODO_CONFIRM)
  Bot：確認摘要
  InlineKeyboard：確認/取消

8.2 查看待辦 (/todos)
DynamoDB 查詢（AP05）：

python
GSI_Type_Date.query(
    GSI1PK = "TODO#pending"
)

執行

回覆訊息：

按優先級分組排序（GSI1SK 已含日期排序，客戶端再按 priority 分組）。

📝 待辦事項

🔴 高優先級
  #1 準備報告 | 📆 03/10 | 💼
  #4 回覆客戶信件 | 📆 03/05 | 💼

🟡 中優先級
  #2 購買日用品 | 無截止日 | 👤

🟢 低優先級
  #3 整理書架 | 無截止日 | 👤

共 4 項待辦（1 項已過期 ⚠️）

8.3 完成待辦 (/done {ID})
DynamoDB 操作：

GSI-3 查詢取得項目
驗證 status == pending
更新 status → completed
設定 completed_at → 當前時間
更新 GSI1PK → TODO#completed
回覆訊息：

✅ 已完成待辦 #1：準備報告

太棒了！繼續加油 💪

8.4 刪除待辦 (/del_todo {ID})
DynamoDB 操作：

同完成待辦，但 status → deleted，GSI1PK → TODO#deleted。

回覆訊息：

🗑 已刪除待辦 #2：購買日用品

9. 模組三：工作進度追蹤
9.1 新增工作 (/add_work)
對話流程：

json
步驟 1 — 專案名稱 (WORK_PROJECT)
  Bot：「🔨 新增工作項目\n\n請輸入專案名稱：」
  驗證：1-100 字元

步驟 2 — 任務名稱 (WORK_TASK)
  Bot：「請輸入任務名稱：」
  驗證：1-100 字元

步驟 3 — 截止日 (WORK_DEADLINE)
  Bot：「請輸入截止日期：\n或點擊『無截止日』」
  InlineKeyboard：[[{text: "⏭ 無截止日", callback_data: "work_skip_deadline"}]]

步驟 4 — 分類 (WORK_CATEGORY)
  Bot：「請選擇分類：」
  InlineKeyboard：
    [[{text: "💻 開發", callback_data: "workcat_development"}],
     [{text: "🎨 設計", callback_data: "workcat_design"}],
     [{text: "📊 行銷", callback_data: "workcat_marketing"}],
     [{text: "📋 管理", callback_data: "workcat_management"}],
     [{text: "🔬 研究", callback_data: "workcat_research"}],
     [{text: "📦 其他", callback_data: "workcat_other"}]]

步驟 5 — 確認 (WORK_CONFIRM)
  Bot：確認摘要（初始進度 0%）
  InlineKeyboard：確認/取消

9.2 查看工作 (/work)
DynamoDB 查詢（AP08）：

python
GSI_Type_Date.query(
    GSI1PK = "WORK#in_progress"
)

執行

回覆訊息：

🔨 進行中的工作

#1 網站改版 — 前端開發
   ████████░░░░░░░░░░░░ 45%
   📆 截止：03/20 (剩 18 天) | 💻 開發

#2 App 設計 — UI 原型
   ████████████░░░░░░░░ 60%
   📆 截止：03/15 (剩 13 天) | 🎨 設計

#3 市場調研 — 競品分析
   ████░░░░░░░░░░░░░░░░ 20%
   📆 無截止日 | 🔬 研究

共 3 項進行中

進度條使用 Unicode 方塊字元：█（已完成）和 ░（未完成），
20 格寬度，每格代表 5%。

9.3 更新進度 (/update_progress {ID} {百分比})
引數解析：

/update_progress 1 75
→ short_id = 1, new_progress = 75

DynamoDB 操作：

GSI-3 查詢取得項目
驗證 status == in_progress
更新 progress → 新值
更新 updated_at → 當前時間
若 progress == 100，自動更新 status → completed，
GSI1PK → WORK#completed
回覆訊息（進度更新）：

📊 已更新 #1 網站改版 — 前端開發

████████████████░░░░ 75% (↑30%)
📆 截止：03/20 (剩 18 天)

回覆訊息（完成 100%）：

🎉 恭喜完成！#1 網站改版 — 前端開發

████████████████████ 100%
完成時間：2026-03-02 15:30

9.4 查看截止日 (/deadlines)
DynamoDB 查詢（AP09）：

python
GSI_Type_Date.query(
    GSI1PK = "WORK#in_progress",
    GSI1SK between "{today}#" and "{today+7}#~"
)

執行

回覆訊息：

⏰ 未來 7 天截止的工作

🔴 已過期
  #5 報告撰寫 — 初稿 | 截止：03/01 (逾期 1 天) | 20%

🟡 3 天內
  #2 App 設計 — UI 原型 | 截止：03/05 (剩 3 天) | 60%

🟢 3-7 天
  #1 網站改版 — 前端開發 | 截止：03/08 (剩 6 天) | 75%

10. 模組四：財務管理
10.1 新增應付款項 (/add_payment)
對話流程：

json
步驟 1 — 名稱 (FIN_TITLE)
  Bot：「💰 新增應付款項\n\n請輸入名稱：」
  驗證：1-100 字元

步驟 2 — 金額 (FIN_AMOUNT)
  Bot：「請輸入金額（數字）：」
  驗證：正數、最多兩位小數

步驟 3 — 到期日 (FIN_DUE)
  Bot：「請輸入到期日期：\n或點擊『無到期日』」
  InlineKeyboard：[[{text: "⏭ 無到期日", callback_data: "fin_skip_due"}]]

步驟 4 — 是否週期性 (FIN_RECURRING)
  Bot：「是否為週期性付款？」
  InlineKeyboard：
    [[{text: "🔄 是（每月固定）", callback_data: "finrec_yes"}],
     [{text: "1️⃣ 否（一次性）", callback_data: "finrec_no"}]]

步驟 4a（若週期性）— 每月幾號 (FIN_RECURRING_DAY)
  Bot：「每月幾號付款？（輸入 1-31）」
  驗證：1-31 整數

步驟 5 — 分類 (FIN_CATEGORY)
  Bot：「請選擇分類：」
  InlineKeyboard：分類按鈕（帳單/薪資/餐飲 等）

步驟 6 — 確認 (FIN_CONFIRM)
  Bot：確認摘要（幣別預設 HKD）
  InlineKeyboard：確認/取消

10.2 新增收入 (/add_income)
對話流程與 /add_payment 類似，但 type 固定為 income，
status 固定為 paid，不需要到期日和週期性選項。

10.3 新增支出 (/add_expense)
對話流程與 /add_income 類似，type 固定為 expense，
status 固定為 paid。

10.4 查看待付款項 (/payments)
DynamoDB 查詢（AP10）：

python
GSI_Type_Date.query(
    GSI1PK = "FIN#pending"
)

執行

回覆訊息：

💰 待付款項

⚠️ 已逾期
  #2 水電費 | $800.00 HKD | 📆 03/01 | 🔄 每月

📅 7 天內到期
  #1 信用卡還款 | $5,000.00 HKD | 📆 03/05 | 🔄 每月

📅 之後
  #3 保險費 | $2,400.00 HKD | 📆 03/20 | 1️⃣ 一次性

待付總額：$8,200.00 HKD

10.5 標記已付 (/paid {ID})
DynamoDB 操作：

查詢項目
更新 status → paid，設定 paid_at
更新 GSI1PK → FIN#paid
若 is_recurring == 1，自動建立下個月的新付款項目：
新 ULID、新 short_id
due_date = 下個月的 recurring_day
status = pending
回覆訊息（週期性）：

✅ 已標記付款 #1：信用卡還款 ($5,000.00 HKD)

🔄 已自動建立下期付款：
   #6 信用卡還款 | $5,000.00 HKD | 📆 04/05

回覆訊息（一次性）：

✅ 已標記付款 #3：保險費 ($2,400.00 HKD)

10.6 月度財務統計 (/finance_summary)
DynamoDB 查詢（AP13 + AP20）：

分別查詢當月的 FIN#paid 項目，按 type 分類加總。

回覆訊息：

apache
📊 2026年3月 財務統計

💵 收入
  薪資：$30,000.00
  其他：$500.00
  小計：$30,500.00

💸 支出
  帳單：$5,800.00
  餐飲：$3,200.00
  交通：$1,500.00
  娛樂：$800.00
  小計：$11,300.00

📈 結餘：+$19,200.00 HKD

⏳ 待付款項：$2,400.00 (1 筆)

11. 模組五：訂閱管理
11.1 新增訂閱 (/add_sub)
對話流程：

json
步驟 1 — 名稱 (SUB_NAME)
  Bot：「📦 新增訂閱\n\n請輸入訂閱名稱：」
  驗證：1-100 字元

步驟 2 — 金額 (SUB_AMOUNT)
  Bot：「請輸入費用金額（數字）：」
  驗證：正數、最多兩位小數

步驟 3 — 計費週期 (SUB_CYCLE)
  Bot：「請選擇計費週期：」
  InlineKeyboard：
    [[{text: "📅 每月", callback_data: "subcycle_monthly"}],
     [{text: "📅 每季", callback_data: "subcycle_quarterly"}],
     [{text: "📅 每年", callback_data: "subcycle_yearly"}]]

步驟 4 — 下次到期日 (SUB_DUE)
  Bot：「請輸入下次到期日 (YYYY-MM-DD)：」
  驗證：有效日期

步驟 5 — 分類 (SUB_CATEGORY)
  Bot：「請選擇分類：」
  InlineKeyboard：
    [[{text: "🎬 串流", callback_data: "subcat_streaming"}],
     [{text: "💻 軟體", callback_data: "subcat_software"}],
     [{text: "☁️ 雲端", callback_data: "subcat_cloud"}],
     [{text: "🎮 娛樂", callback_data: "subcat_entertainment"}],
     [{text: "📰 新聞", callback_data: "subcat_news"}],
     [{text: "🏥 健康", callback_data: "subcat_health"}],
     [{text: "📚 教育", callback_data: "subcat_education"}],
     [{text: "📦 其他", callback_data: "subcat_other"}]]

步驟 6 — 自動續訂 (SUB_AUTO_RENEW)
  Bot：「是否自動續訂？」
  InlineKeyboard：
    [[{text: "✅ 是", callback_data: "subauto_yes"}],
     [{text: "❌ 否", callback_data: "subauto_no"}]]

步驟 7 — 備註 (SUB_NOTES)
  Bot：「請輸入備註（可選）：\n或點擊『跳過』」
  InlineKeyboard：[[{text: "⏭ 跳過", callback_data: "sub_skip_notes"}]]

步驟 8 — 確認 (SUB_CONFIRM)
  Bot：確認摘要
  InlineKeyboard：確認/取消

11.2 查看訂閱 (/subs)
DynamoDB 查詢（AP14 + AP17）：

分別查詢 SUB#active 和 SUB#paused。

回覆訊息：

coq
📦 訂閱管理

✅ 有效訂閱
  #1 Apple Music | $78/月 | 📆 下次：04/15 | 🎬 串流 | 🔄 自動
  #2 ChatGPT Plus | $160/月 | 📆 下次：04/01 | 💻 軟體 | 🔄 自動
  #3 iCloud+ | $78/月 | 📆 下次：04/20 | ☁️ 雲端 | 🔄 自動
  #5 Netflix | $98/月 | 📆 下次：04/10 | 🎬 串流 | 手動

⏸ 暫停中
  #4 Spotify | $58/月 | 🎬 串流

📊 每月總支出：$414.00 HKD (4 個有效)
📊 每年總支出：$4,968.00 HKD

11.3 即將到期訂閱 (/sub_due)
DynamoDB 查詢（AP15）：

python
GSI_Type_Date.query(
    GSI1PK = "SUB#active",
    GSI1SK between "{today}#" and "{today+7}#~"
)

執行

回覆訊息：

⏰ 未來 7 天到期的訂閱

📅 03/05
  #2 ChatGPT Plus | $160/月 | 💻 軟體 | 🔄 自動

📅 03/07
  #5 Netflix | $98/月 | 🎬 串流 | ⚠️ 手動續訂

共 2 項即將到期

11.4 手動續訂 (/renew_sub {ID})
邏輯：

查詢項目，驗證 status == active
根據 billing_cycle 計算新的 next_due_date：
monthly → 當前 next_due_date + 1 個月
quarterly → + 3 個月
yearly → + 1 年
更新 next_due_date、last_renewed_at
更新 GSI1SK（新日期）
回覆訊息：

🔄 已續訂 #5 Netflix

新的到期日：2026-05-10
下次帳單：$98.00 HKD

11.5 暫停訂閱 (/pause_sub {ID})
DynamoDB 操作：

更新 status → paused，GSI1PK → SUB#paused。

回覆訊息：

⏸ 已暫停訂閱 #4：Spotify

恢復請使用：/resume_sub 4

11.6 恢復訂閱 (/resume_sub {ID})
觸發對話（需輸入新到期日）：

步驟 1 — 新到期日 (RESUME_DUE)
  Bot：「📦 恢復訂閱 #4：Spotify\n\n請輸入新的到期日 (YYYY-MM-DD)：」
  驗證：有效日期、不可為過去

DynamoDB 操作：

更新 status → active、next_due_date → 新日期、
GSI1PK → SUB#active。

回覆訊息：

▶️ 已恢復訂閱 #4：Spotify

到期日：2026-04-15
費用：$58.00/月

11.7 取消訂閱 (/cancel_sub {ID})
需確認（InlineKeyboard）：

json
Bot：「⚠️ 確定要取消訂閱 #3 iCloud+ 嗎？\n\n此操作不可恢復。」
InlineKeyboard：
  [[{text: "✅ 確定取消", callback_data: "cancelsub_confirm_3"}],
   [{text: "❌ 保留", callback_data: "cancelsub_keep_3"}]]

DynamoDB 操作（確認後）：

更新 status → cancelled，GSI1PK → SUB#cancelled。

回覆訊息：

🚫 已取消訂閱 #3：iCloud+

11.8 編輯訂閱 (/edit_sub {ID})
觸發對話：

Bot 先顯示當前訂閱資訊，然後讓使用者選擇要編輯的欄位。

json
Bot：「📝 編輯訂閱 #1：Apple Music\n\n
       當前資訊：
       費用：$78.00/月
       分類：🎬 串流
       下次到期：04/15
       自動續訂：是\n\n
       請選擇要編輯的項目：」
InlineKeyboard：
  [[{text: "💰 修改費用", callback_data: "edit_sub_amount_1"}],
   [{text: "📅 修改到期日", callback_data: "edit_sub_due_1"}],
   [{text: "🔄 修改自動續訂", callback_data: "edit_sub_auto_1"}],
   [{text: "🏷️ 修改分類", callback_data: "edit_sub_cat_1"}],
   [{text: "📝 修改備註", callback_data: "edit_sub_notes_1"}],
   [{text: "✅ 完成編輯", callback_data: "edit_sub_done_1"}]]

選擇欄位後進入對應的輸入步驟，更新後返回編輯選單。

11.9 訂閱費用統計 (/sub_cost)
DynamoDB 查詢（AP21）：

查詢所有 SUB#active 項目，客戶端計算統計。

回覆訊息：

apache
💰 訂閱費用統計

📊 按週期
  每月訂閱：4 項 → $414.00/月
  每年訂閱：1 項 → $888.00/年 ($74.00/月)

📊 月均總支出：$488.00 HKD
📊 年度總支出：$5,856.00 HKD

📊 按分類
  🎬 串流：$176.00/月 (36.1%)
  💻 軟體：$160.00/月 (32.8%)
  ☁️ 雲端：$78.00/月 (16.0%)
  📚 教育：$74.00/月 (15.2%)

12. 模組六：綜合查詢
12.1 每日摘要 (/summary)
DynamoDB 查詢：

組合查詢今日行程（AP03）、pending 待辦（AP05）、進行中工作（AP08）、
待付款項（AP10）、即將到期訂閱（AP15，7 天內）。

回覆訊息：

gcode
📋 每日摘要 — 2026/03/02 (週一)

📅 今日行程 (2)
  #1 週一開會 🕐 14:00
  #3 牙醫覆診 🕐 18:30

📝 待辦事項 (4 待完成, 1 已過期 ⚠️)
  🔴 #1 準備報告 | 📆 03/10
  🔴 #4 回覆客戶信件 | 📆 03/05

🔨 進行中工作 (3)
  #1 網站改版 — 前端開發 | 75%
  #2 App 設計 — UI 原型 | 60%

💰 待付款項 (2, 共 $5,800.00)
  ⚠️ #2 水電費 | $800 | 已逾期

📦 訂閱提醒 (1 項 7 天內到期)
  #2 ChatGPT Plus | 03/05

12.2 關鍵字搜尋 (/search {關鍵字})
DynamoDB 查詢（AP19）：

對每種 entity type 的 active/pending/in_progress 狀態分別查詢，
使用 FilterExpression contains(title, :kw) 或
contains(#name, :kw)。

由於 DynamoDB 不支援全文搜尋，FilterExpression 是在伺服器端
讀取所有匹配 Key 條件的項目後再過濾，因此效率不如 SQL LIKE。
但在單一使用者的少量資料（預估每種類型 < 100 筆）場景下，
效能完全可接受。

回覆訊息：

🔍 搜尋結果：「開會」

📅 行程
  #1 週一開會 | 03/02 14:00

📝 待辦
  #7 整理開會記錄 | 📆 03/08

共找到 2 筆結果

無結果時：

🔍 搜尋「xyz」：無相關結果

12.3 月度報表 (/monthly_report {YYYY-MM})
DynamoDB 查詢：

組合查詢指定月份的行程數量、待辦完成率、工作完成率、財務統計。

回覆訊息：

apache
📊 2026年3月 月度報表

📅 行程
  總計：12 場
  已完成：8 | 已取消：2 | 未來：2

📝 待辦
  總計：15 項
  已完成：10 (66.7%) | 待完成：5

🔨 工作
  總計：5 項
  已完成：2 | 進行中：3
  平均進度：58%

💰 財務
  收入：$30,500.00
  支出：$11,300.00
  結餘：+$19,200.00

📦 訂閱
  有效：4 項
  月度支出：$414.00

13. 模組七：定時提醒
13.1 早晨提醒
觸發時間：每日 HKT 08:00（EventBridge cron）

觸發 Event：{"reminder_type": "morning"}

查詢內容：

今日行程（AP03）
已過期待辦（AP06）
3 天內到期工作（AP09，3 天範圍）
訊息格式：

🌅 早安！今天是 2026/03/02 (週一)

📅 今日行程
  🕐 14:00 週一開會 | 📍 會議室 A
  🕐 18:30 牙醫覆診 | 📍 XX 診所

⚠️ 過期待辦 (1)
  🔴 #4 回覆客戶信件 | 原截止：03/01

⏰ 近期工作截止
  #2 App 設計 — UI 原型 | 03/05 (剩 3 天) | 60%

祝你有美好的一天！😊

13.2 訂閱到期警告
觸發時間：每日 HKT 10:00

觸發 Event：{"reminder_type": "subscription_alert"}

查詢內容： 3 天內到期的訂閱（AP15，3 天範圍）

訊息格式（有到期訂閱時才發送）：

📦 訂閱到期提醒

以下訂閱即將到期：

  #5 Netflix | $98/月 | 📆 03/04 (明天) | ⚠️ 手動續訂
  #2 ChatGPT Plus | $160/月 | 📆 03/05 (後天) | 🔄 自動

手動續訂指令：/renew_sub {ID}

無到期訂閱時不發送任何訊息。

13.3 付款到期警告
觸發時間：每日 HKT 12:00

觸發 Event：{"reminder_type": "payment_alert"}

查詢內容： 已逾期 + 3 天內到期的付款（AP11）

訊息格式（有到期付款時才發送）：

💰 付款提醒

⚠️ 已逾期
  #2 水電費 | $800 | 原到期：03/01

📅 3 天內到期
  #1 信用卡還款 | $5,000 | 📆 03/05

付款確認指令：/paid {ID}

13.4 晚間提醒
觸發時間：每日 HKT 21:00

觸發 Event：{"reminder_type": "evening"}

查詢內容：

明日行程（AP03，明日日期）
未完成的高優先級待辦
當日是否有新增/完成的項目（客戶端統計）
訊息格式：

🌙 晚安！今日回顧

📊 今日成果
  ✅ 完成 2 項待辦
  ✅ 更新 1 項工作進度

📅 明日行程
  🕐 10:00 客戶提案 | 📍 辦公室

📝 尚有高優先級待辦
  🔴 #1 準備報告 | 📆 03/10

晚安，好好休息 🌟

14. 對話流程設計
14.1 對話狀態管理機制
由於 Lambda 是無狀態的，每次呼叫為獨立進程，無法像
python-telegram-bot 的 ConversationHandler 那樣在記憶體中
維護對話狀態。本系統將對話狀態持久化到 DynamoDB
BotConversationTable。

對話狀態生命週期：

指令觸發 → 建立狀態記錄（module, step=首步, data=空, TTL=30min）
    │
    ▼
使用者輸入 → Lambda 讀取狀態 → 驗證輸入 → 更新 data 和 step → 回覆下一步提示
    │                                          │
    ▼                                          ▼
  ... 重複 ...                           更新 TTL（每次操作重設 30min）
    │
    ▼
最終確認 → 寫入業務資料到 BotMainTable → 刪除對話狀態記錄
    │
    ▼
結束

異常情況處理：

使用者 30 分鐘不操作 → TTL 自動過期，下次輸入視為非對話中
使用者在對話中發送 /cancel → 刪除對話狀態，回覆「已取消」
使用者在對話中發送其他指令 → 回覆「你正在進行 {module} 操作，請先完成或 /cancel 取消」
使用者在對話中發送新的 add_* 指令 → 覆蓋舊對話狀態，開始新對話
14.2 對話模組與步驟定義
模組 (module)	步驟 (step)	輸入方式	下一步
schedule	SCH_TITLE	文字輸入	SCH_DATE
schedule	SCH_DATE	文字輸入	SCH_TIME
schedule	SCH_TIME	文字/Callback	SCH_LOCATION
schedule	SCH_LOCATION	文字/Callback	SCH_CATEGORY
schedule	SCH_CATEGORY	Callback	SCH_CONFIRM
schedule	SCH_CONFIRM	Callback	(結束)
todo	TODO_TITLE	文字輸入	TODO_DUE
todo	TODO_DUE	文字/Callback	TODO_CATEGORY
todo	TODO_CATEGORY	Callback	TODO_PRIORITY
todo	TODO_PRIORITY	Callback	TODO_CONFIRM
todo	TODO_CONFIRM	Callback	(結束)
work	WORK_PROJECT	文字輸入	WORK_TASK
work	WORK_TASK	文字輸入	WORK_DEADLINE
work	WORK_DEADLINE	文字/Callback	WORK_CATEGORY
work	WORK_CATEGORY	Callback	WORK_CONFIRM
work	WORK_CONFIRM	Callback	(結束)
finance	FIN_TITLE	文字輸入	FIN_AMOUNT
finance	FIN_AMOUNT	文字輸入	FIN_DUE
finance	FIN_DUE	文字/Callback	FIN_RECURRING
finance	FIN_RECURRING	Callback	FIN_RECURRING_DAY 或 FIN_CATEGORY
finance	FIN_RECURRING_DAY	文字輸入	FIN_CATEGORY
finance	FIN_CATEGORY	Callback	FIN_CONFIRM
finance	FIN_CONFIRM	Callback	(結束)
subscription	SUB_NAME	文字輸入	SUB_AMOUNT
subscription	SUB_AMOUNT	文字輸入	SUB_CYCLE
subscription	SUB_CYCLE	Callback	SUB_DUE
subscription	SUB_DUE	文字輸入	SUB_CATEGORY
subscription	SUB_CATEGORY	Callback	SUB_AUTO_RENEW
subscription	SUB_AUTO_RENEW	Callback	SUB_NOTES
subscription	SUB_NOTES	文字/Callback	SUB_CONFIRM
subscription	SUB_CONFIRM	Callback	(結束)
resume_sub	RESUME_DUE	文字輸入	(結束 → 直接更新)
edit_sub	EDIT_SELECT	Callback	(對應欄位步驟)
edit_sub	EDIT_AMOUNT	文字輸入	EDIT_SELECT
edit_sub	EDIT_DUE	文字輸入	EDIT_SELECT
edit_sub	EDIT_AUTO	Callback	EDIT_SELECT
edit_sub	EDIT_CAT	Callback	EDIT_SELECT
edit_sub	EDIT_NOTES	文字輸入	EDIT_SELECT
14.3 對話狀態 data 欄位
每個模組的對話過程中，收集到的資料暫存在 data Map 屬性中。

Schedule data：

json
{
  "sch_title": "週一開會",
  "sch_date": "2026-03-05",
  "sch_time": "14:00",
  "sch_location": "會議室 A",
  "sch_category": "work"
}

Todo data：

json
{
  "todo_title": "準備報告",
  "todo_due": "2026-03-10",
  "todo_category": "work",
  "todo_priority": 1
}

Work data：

json
{
  "work_project": "網站改版",
  "work_task": "前端開發",
  "work_deadline": "2026-03-20",
  "work_category": "development"
}

Finance data：

json
{
  "fin_type": "payment",
  "fin_title": "信用卡還款",
  "fin_amount": 5000.00,
  "fin_due": "2026-03-15",
  "fin_recurring": true,
  "fin_recurring_day": 15,
  "fin_category": "bills"
}

Subscription data：

json
{
  "sub_name": "Apple Music",
  "sub_amount": 78.00,
  "sub_cycle": "monthly",
  "sub_due": "2026-04-15",
  "sub_category": "streaming",
  "sub_auto_renew": true,
  "sub_notes": "家庭方案"
}

15. Telegram API 互動規格
15.1 Webhook 接收格式
API Gateway 接收到的 event 物件結構（HTTP API v2 payload format）：

json
{
  "version": "2.0",
  "routeKey": "POST /webhook/{proxy+}",
  "rawPath": "/prod/webhook/abc123secret",
  "headers": {
    "content-type": "application/json",
    "x-telegram-bot-api-secret-token": "your_webhook_secret"
  },
  "body": "{\"update_id\":12345, ...}",
  "isBase64Encoded": false
}

15.2 Telegram Update 物件結構
文字訊息：

json
{
  "update_id": 12345,
  "message": {
    "message_id": 100,
    "from": {
      "id": 123456789,
      "is_bot": false,
      "first_name": "使用者"
    },
    "chat": {
      "id": 123456789,
      "type": "private"
    },
    "date": 1709366400,
    "text": "/start"
  }
}

Callback Query（InlineKeyboard 按鈕點擊）：

json
{
  "update_id": 12346,
  "callback_query": {
    "id": "callback_123",
    "from": {
      "id": 123456789,
      "is_bot": false,
      "first_name": "使用者"
    },
    "message": {
      "message_id": 101,
      "chat": {
        "id": 123456789,
        "type": "private"
      }
    },
    "data": "schcat_work"
  }
}

15.3 使用的 Telegram Bot API 方法
方法	用途	頻率
sendMessage	發送文字訊息（含 InlineKeyboard）	每次互動
answerCallbackQuery	回應按鈕點擊（消除載入動畫）	每次按鈕
editMessageText	更新已發送的訊息（確認後更新摘要）	偶爾
setWebhook	設定 Webhook URL（部署時一次性）	一次
getWebhookInfo	驗證 Webhook 設定（除錯用）	按需
deleteWebhook	移除 Webhook（除錯用）	按需
15.4 Telegram API 呼叫規範
所有 Telegram API 呼叫使用 httpx 同步客戶端（Lambda 中不需要
非同步，同步更簡單可靠）。

python
BASE_URL = f"https://api.telegram.org/bot{token}"

執行

Timeout 設定為 10 秒。若 Telegram API 回傳非 200，記錄日誌但
不重試（避免 Lambda 超時）。回覆訊息使用 Markdown parse_mode
進行格式化。

15.5 訊息格式化規範
所有回覆訊息使用 Telegram Markdown V1 格式（較簡單且相容性好）。

*粗體* → 用於標題、重要數值
_斜體_ → 用於備註
`等寬` → 用於 ID、金額

特殊字元需要跳脫：_、*、`、[。在動態生成的使用者
輸入中，需要呼叫跳脫函數處理。

16. 安全設計
16.1 多層防護架構
第一層：URL Secret Path
  API Gateway URL 中包含隨機路徑段 /{secret_path}
  不知道路徑的請求會得到 404

第二層：Telegram Secret Token
  Telegram 在 Webhook 請求的 Header 中附帶 secret_token
  Lambda 驗證 X-Telegram-Bot-Api-Secret-Token header

第三層：User ID 驗證
  Lambda 檢查 from.id == OWNER_ID
  非擁有者的請求被拒絕

16.2 敏感資訊管理
資訊	儲存位置	存取方式
Bot Token	SSM Parameter Store (SecureString)	Lambda 啟動時讀取並快取
Owner ID	SSM Parameter Store (String)	Lambda 啟動時讀取並快取
Webhook Secret	SSM Parameter Store (SecureString)	Lambda 啟動時讀取並快取
Webhook Path	SSM Parameter Store (SecureString)	部署時讀取
DynamoDB 表名	Lambda 環境變數 (非敏感)	直接讀取
16.3 IAM 最小權限
每個 Lambda 函數僅擁有完成其任務所需的最低權限。
Webhook Handler 需要 DynamoDB CRUD 和 SSM 讀取。
Reminder Handler 僅需 DynamoDB 讀取和 SSM 讀取
（不需要 DynamoDB 寫入權限）。

16.4 DynamoDB 安全
主表啟用 Point-in-Time Recovery (PITR)，可在 35 天內恢復
到任意時間點的資料。靜態加密使用 AWS owned key（預設啟用，
免費）。DeletionPolicy 設為 Retain，防止 CloudFormation 堆疊
刪除時意外刪除資料表。

17. 錯誤處理規格
17.1 錯誤處理原則
Lambda 必須始終回傳 HTTP 200 給 API Gateway。如果回傳非 2xx，
Telegram 會認為 Webhook 傳送失敗並重試，可能造成重複處理。
所有錯誤處理在 Lambda 內部完成，透過 try-except 捕獲。

17.2 錯誤分類與處理
錯誤類型	處理方式
Webhook 驗證失敗	回傳 403，不做其他處理
非擁有者請求	發送拒絕訊息，回傳 200
指令格式錯誤	發送格式提示訊息給使用者
輸入驗證失敗（對話中）	發送錯誤提示，保持當前步驟，不推進
短 ID 不存在	發送「找不到 ID 為 X 的 {entity}」
狀態不允許操作	發送「{entity} #{id} 目前狀態為 {status}，無法 {action}」
DynamoDB 讀寫錯誤	記錄日誌，發送通用錯誤訊息給使用者
Telegram API 呼叫失敗	記錄日誌，不重試（避免超時）
Lambda 未預期例外	外層 try-except 捕獲，記錄日誌，發送通用錯誤訊息
17.3 使用者端錯誤訊息格式
❌ {具體錯誤描述}

# 範例
❌ 找不到 ID 為 99 的待辦事項。
❌ 日期格式不正確，請輸入 YYYY-MM-DD 格式。
❌ 金額必須為正數。
❌ 進度必須為 0-100 之間的整數。
❌ 該訂閱目前為暫停狀態，無法續訂。請先使用 /resume_sub 恢復。

17.4 輸入驗證規格
欄位類型	驗證規則
標題/名稱	不可為空、長度 1-100（或 200）字元
日期	可解析為有效日期、支援多種格式、不可為過去日期（行程/訂閱）
時間	HH:MM 格式、00:00-23:59
金額	正數、最多兩位小數、最大 9,999,999.99
百分比	0-100 整數
短 ID	正整數
日期（每月幾號）	1-31 整數
17.5 日期輸入解析規格
支援以下格式（不分大小寫）：

輸入格式	解析結果	範例
YYYY-MM-DD	直接解析	2026-03-05
YYYY/MM/DD	轉換分隔符	2026/03/05
MM-DD	預設為當年（若已過則下年）	03-05
MM/DD	同上	03/05
M/D	同上（支援不補零）	3/5
今天	今日日期	—
明天	今日 +1	—
後天	今日 +2	—
大後天	今日 +3	—
下週一 ~ 下週日	計算下週對應星期幾	—
下個月{N}號	下月第 N 天	下個月15號
所有日期解析後轉換為 YYYY-MM-DD 格式儲存。時區固定為
Asia/Hong_Kong (UTC+8)。

18. Lambda 函數規格
18.1 bot-webhook-handler
屬性	值
函數名稱	bot-webhook-handler
Runtime	Python 3.12
Architecture	ARM64 (Graviton2)
Memory	256 MB
Timeout	30 秒
觸發來源	API Gateway HTTP API (POST)
Layers	bot-dependencies, bot-shared-code
環境變數	MAIN_TABLE_NAME, CONV_TABLE_NAME, TIMEZONE, LOG_LEVEL
處理流程：

從 headers 取得 x-telegram-bot-api-secret-token
從全域快取（或 SSM）取得設定
比對 secret token，不符回傳 403
解析 body 為 Telegram Update JSON
提取 user_id，比對 OWNER_ID
若為 callback_query：路由至 callback handler → answerCallbackQuery
若為 message.text：
a. /cancel → 清除對話狀態
b. 檢查是否有進行中對話 → 路由至對話步驟處理器
c. 以 / 開頭 → 路由至指令處理器
d. 其他 → 回覆「請輸入指令」
回傳 {"statusCode": 200, "body": "OK"}
全域快取策略：

SSM 參數、DynamoDB resource、httpx client 在全域範圍初始化，
利用 Lambda 容器重用（Container Reuse）機制避免每次冷啟動
都重新建立連線。

18.2 bot-reminder-handler
屬性	值
函數名稱	bot-reminder-handler
Runtime	Python 3.12
Architecture	ARM64 (Graviton2)
Memory	256 MB
Timeout	60 秒
觸發來源	EventBridge Scheduler (4 個排程)
Layers	bot-dependencies, bot-shared-code
環境變數	MAIN_TABLE_NAME, TIMEZONE, LOG_LEVEL
處理流程：

從 event 取得 reminder_type
從全域快取（或 SSM）取得設定
根據 reminder_type 路由至對應處理函數
查詢 DynamoDB 取得相關資料
組合提醒訊息
若有內容需提醒，呼叫 Telegram sendMessage API
若無內容需提醒（如無到期訂閱），不發送任何訊息
回傳 {"statusCode": 200}
Timeout 設定為 60 秒 的理由：Reminder Handler 可能需要
執行多次 DynamoDB 查詢並多次呼叫 Telegram API（如早晨提醒
需查詢行程、待辦、工作三種資料並分別發送），需要比 Webhook
Handler 更長的執行時間。

19. API Gateway 規格
屬性	值
API 類型	HTTP API (v2)
名稱	secretary-bot-api
Stage	prod
路由	POST /webhook/{proxy+}
Integration	Lambda (bot-webhook-handler)
授權	None（驗證在 Lambda 內進行）
CORS	未啟用
限流	預設（10,000 req/sec）
路由中使用 {proxy+} 通配符，讓 secret_path 可以是任意長度的
隨機字串，不需要在 API Gateway 層硬編碼。Lambda 不需要檢查
URL 路徑（安全性由 Telegram secret_token header 保證），但
secret_path 作為額外的安全層，防止隨機掃描命中。

20. EventBridge Scheduler 規格
排程名稱	Cron (HKT 等效)	ScheduleExpression	Timezone	Event Payload
morning-reminder	每日 08:00	cron(0 8 * * ? *)	Asia/Hong_Kong	{"reminder_type": "morning"}
subscription-alert	每日 10:00	cron(0 10 * * ? *)	Asia/Hong_Kong	{"reminder_type": "subscription_alert"}
payment-alert	每日 12:00	cron(0 12 * * ? *)	Asia/Hong_Kong	{"reminder_type": "payment_alert"}
evening-reminder	每日 21:00	cron(0 21 * * ? *)	Asia/Hong_Kong	{"reminder_type": "evening"}
所有排程使用 EventBridge Scheduler（非 EventBridge Rules），
並設定 ScheduleExpressionTimezone: Asia/Hong_Kong，
直接使用 HKT 時間表達式，無需手動換算 UTC。

FlexibleTimeWindow 設為 OFF（精確時間觸發）。

21. IAM 權限規格
21.1 WebhookHandlerRole
yaml
Policies:
  - DynamoDBCrudPolicy:
      TableName: BotMainTable        # 含 GSI 讀寫
  - DynamoDBCrudPolicy:
      TableName: BotConversationTable # 含 TTL 項目讀寫
  - SSMParameterReadPolicy:
      ParameterName: "bot/*"          # 讀取 /bot/ 下所有參數
  # CloudWatch Logs 由 SAM 自動附加

21.2 ReminderHandlerRole
yaml
Policies:
  - DynamoDBReadPolicy:
      TableName: BotMainTable        # 僅讀取
  - SSMParameterReadPolicy:
      ParameterName: "bot/*"

21.3 EventBridgeSchedulerRole
yaml
Policies:
  - Statement:
      Effect: Allow
      Action: lambda:InvokeFunction
      Resource: !GetAtt ReminderHandlerFunction.Arn

22. 監控與告警規格
22.1 CloudWatch Logs
日誌群組	保留期限	來源
/aws/lambda/bot-webhook-handler	30 天	Webhook Lambda
/aws/lambda/bot-reminder-handler	30 天	Reminder Lambda
22.2 CloudWatch Alarms
告警名稱	指標	條件	期間	通知
bot-webhook-errors	Lambda Errors	> 3 次 / 5 分鐘	5 min	SNS → Email
bot-webhook-throttles	Lambda Throttles	> 0 / 5 分鐘	5 min	SNS → Email
bot-webhook-duration	Lambda Duration (P95)	> 10,000 ms	5 min	SNS → Email
bot-api-5xx	API Gateway 5xx Count	> 0 / 5 分鐘	5 min	SNS → Email
22.3 結構化日誌格式
所有 Lambda 日誌採用 JSON 格式，便於 CloudWatch Logs Insights 查詢。

json
{
  "timestamp": "2026-03-02T10:30:00+08:00",
  "level": "INFO",
  "event_type": "command_received",
  "command": "/add_schedule",
  "user_id": 123456789,
  "request_id": "abc-123"
}

日誌事件類型：command_received（收到指令）、callback_received
（收到按鈕點擊）、conversation_step（對話步驟處理）、db_read
（資料庫讀取）、db_write（資料庫寫入）、telegram_api_call
（呼叫 Telegram API）、reminder_sent（提醒已發送）、error
（錯誤）。

23. 部署規格
23.1 IaC 工具
AWS SAM（Serverless Application Model）。template.yaml 定義
所有 AWS 資源。samconfig.toml 定義部署參數。

23.2 CloudFormation Stack
屬性	值
Stack 名稱	secretary-bot
Region	ap-east-1
Capabilities	CAPABILITY_IAM
23.3 部署前置作業
安裝 AWS CLI + SAM CLI
設定 AWS 憑證（aws configure）
建立 SSM 參數（Bot Token、Owner ID、Webhook Secret、Webhook Path）
建置 Lambda Layer 依賴（pip install -t dependencies/python/）
23.4 部署指令
bash
sam build
sam deploy --guided   # 首次
sam deploy            # 後續

23.5 部署後作業
執行 setup_webhook.py 設定 Telegram Webhook
發送 /start 驗證
設定 CloudWatch Logs 保留期限
24. 檔案結構
mipsasm
secretary_bot_serverless/
│
├── template.yaml                    # SAM 範本
├── samconfig.toml                   # SAM 部署設定
├── requirements.txt                 # 開發用依賴
├── setup_webhook.py                 # Webhook 設定腳本
├── README.md                        # 專案說明
│
├── dependencies/                    # Lambda Layer: 第三方套件
│   └── python/
│       ├── httpx/
│       ├── pytz/
│       └── ulid/
│
├── shared/                          # Lambda Layer: 共用模組
│   └── python/
│       ├── bot_config.py            # 設定讀取 (SSM 快取)
│       ├── bot_db.py                # DynamoDB CRUD 封裝
│       ├── bot_telegram.py          # Telegram API 封裝
│       ├── bot_utils.py             # 工具函數 (日期解析等)
│       └── bot_constants.py         # 常數定義 (分類/狀態)
│
├── webhook_handler/                 # Lambda: bot-webhook-handler
│   ├── lambda_function.py           # 進入點
│   └── handlers/
│       ├── __init__.py
│       ├── router.py                # 指令/callback/對話 路由
│       ├── start.py                 # /start, /help
│       ├── schedule.py              # 行程管理
│       ├── todo.py                  # 待辦事項
│       ├── work.py                  # 工作進度
│       ├── finance.py               # 財務管理
│       ├── subscription.py          # 訂閱管理
│       └── query.py                 # 綜合查詢
│
├── reminder_handler/                # Lambda: bot-reminder-handler
│   ├── lambda_function.py           # 進入點
│   └── reminders/
│       ├── __init__.py
│       ├── morning.py               # 早晨提醒
│       ├── evening.py               # 晚間提醒
│       ├── payment_alert.py         # 付款到期
│       └── sub_alert.py             # 訂閱到期
│
└── tests/                           # 測試
    ├── conftest.py
    ├── test_db.py                   # DynamoDB 操作測試
    ├── test_router.py               # 路由測試
    ├── test_handlers.py             # Handler 測試
    ├── test_reminders.py            # 提醒測試
    ├── test_utils.py                # 工具函數測試
    └── events/                      # 測試用 event payload
        ├── webhook_message.json
        ├── webhook_callback.json
        └── reminder_morning.json

25. 非功能性需求
25.1 效能
指標	目標
Webhook 回應時間（冷啟動）	< 3 秒
Webhook 回應時間（暖啟動）	< 1 秒
Reminder 執行時間	< 10 秒
DynamoDB 單次查詢延遲	< 10 ms
25.2 可用性
指標	目標
Lambda 可用性	99.95%（AWS SLA）
DynamoDB 可用性	99.99%（AWS SLA）
API Gateway 可用性	99.95%（AWS SLA）
25.3 可維護性
所有基礎設施以程式碼定義（SAM template.yaml），可版本控制、
可重建。Lambda 程式碼模組化，每個功能模組獨立檔案。共用邏輯
抽離至 Lambda Layer。結構化日誌便於問題追蹤。

25.4 成本
指標	目標
月度成本（免費額度期間）	< $0.50 USD
月度成本（免費額度後）	< $1.00 USD
25.5 安全性
敏感資訊不出現在程式碼、環境變數或日誌中。IAM 權限遵循
最小權限原則。DynamoDB 啟用 PITR 備份。Webhook 雙重驗證
（URL path + secret token）。

26. 限制與已知約束
26.1 DynamoDB 限制
DynamoDB 不支援 SQL JOIN——本系統的各實體之間沒有關聯查詢
需求，不受此限制影響。

DynamoDB 不支援全文搜尋——/search 指令使用 FilterExpression
的 contains 函數，是伺服器端過濾（讀取所有匹配 Key 條件的
項目後再過濾），效率低於 SQL LIKE。在單一使用者的少量資料
場景下可接受。

DynamoDB 單一項目大小上限 400 KB——本系統所有項目遠小於此
限制。

DynamoDB Query 結果上限 1 MB——本系統的查詢結果通常只有
數十筆，遠小於此限制。若未來資料量增長，需要實作分頁
（LastEvaluatedKey）。

26.2 Lambda 限制
冷啟動延遲 0.5-2 秒——使用者首次操作（或閒置一段時間後）
會感受到稍慢的回應。Provisioned Concurrency 可解決但成本高。
替代方案：EventBridge 每 5 分鐘空觸發保暖。

Lambda 最大執行時間 15 分鐘——本系統所有操作預計在 60 秒內
完成，不受此限制影響。

Lambda 部署包上限 250 MB（解壓後）——本系統依賴精簡，
總大小預計 < 30 MB。

Lambda 併發上限 1,000（預設）——單一使用者場景不會達到
此限制。

26.3 Telegram 限制
Telegram Bot API 限流：每個 Bot 每秒最多 30 條訊息。
本系統為單一使用者，遠低於此限制。

Telegram 訊息長度上限 4,096 字元。若月度報表或查詢結果
過長，需要分割為多條訊息。

Telegram InlineKeyboard 每行最多 8 個按鈕、總共最多 100 個
按鈕。本系統的按鈕數量不會達到此限制。

26.4 ConversationHandler 限制
同一時間只能有一個進行中的對話。如果使用者同時需要新增行程
和新增待辦，必須完成或取消一個後再開始另一個。

對話超時時間固定為 30 分鐘。超時後需要重新開始整個對話流程，
無法從中斷處繼續。

26.5 時區限制
系統固定使用 Asia/Hong_Kong (UTC+8) 時區。不支援多時區或
動態切換。所有日期時間的顯示和解析均以 HKT 為準。

附錄
附錄 A：分類列舉值完整對照
行程分類 (Schedule Category)

值	顯示	Emoji
work	工作	💼
personal	個人	👤
health	健康	🏥
social	社交	👥
other	其他	📦
待辦分類 (Todo Category)

同行程分類。

工作分類 (Work Category)

值	顯示	Emoji
development	開發	💻
design	設計	🎨
marketing	行銷	📊
management	管理	📋
research	研究	🔬
other	其他	📦
財務分類 (Finance Category)

值	顯示	Emoji
bills	帳單	🧾
salary	薪資	💵
food	餐飲	🍔
transport	交通	🚌
entertainment	娛樂	🎮
shopping	購物	🛍️
health	醫療	💊
education	教育	📚
investment	投資	📈
other	其他	📦
訂閱分類 (Subscription Category)

值	顯示	Emoji
streaming	串流	🎬
software	軟體	💻
cloud	雲端	☁️
entertainment	娛樂	🎮
news	新聞	📰
health	健康	🏥
education	教育	📚
other	其他	📦
附錄 B：優先級列舉值
值	顯示	Emoji
1	高	🔴
2	中	🟡
3	低	🟢
附錄 C：狀態列舉值
行程狀態

值	顯示
active	有效
cancelled	已取消
待辦狀態

值	顯示
pending	待完成
completed	已完成
deleted	已刪除
工作狀態

值	顯示
in_progress	進行中
completed	已完成
on_hold	暫停
財務狀態

值	顯示
pending	待付
paid	已付
cancelled	已取消
訂閱狀態

值	顯示
active	有效
paused	暫停
cancelled	已取消
附錄 D：Callback Data 前綴對照
前綴	模組	用途
schcat_	行程	選擇分類
sch_skip_	行程	跳過可選欄位
sch_confirm_	行程	確認/取消新增
todocat_	待辦	選擇分類
todopri_	待辦	選擇優先級
todo_skip_	待辦	跳過可選欄位
todo_confirm_	待辦	確認/取消新增
workcat_	工作	選擇分類
work_skip_	工作	跳過可選欄位
work_confirm_	工作	確認/取消新增
finrec_	財務	是否週期性
fincat_	財務	選擇分類
fin_skip_	財務	跳過可選欄位
fin_confirm_	財務	確認/取消新增
subcycle_	訂閱	選擇計費週期
subcat_	訂閱	選擇分類
subauto_	訂閱	是否自動續訂
sub_skip_	訂閱	跳過可選欄位
sub_confirm_	訂閱	確認/取消新增
cancelsub_	訂閱	取消訂閱確認
edit_sub_	訂閱	編輯訂閱欄位選擇
附錄 E：進度條生成規格
smali
寬度：20 格
已完成字元：█ (U+2588)
未完成字元：░ (U+2591)

計算：
  filled = round(progress / 5)
  empty = 20 - filled
  bar = "█" * filled + "░" * empty
  display = f"{bar} {progress}%"

範例：
  0%  → ░░░░░░░░░░░░░░░░░░░░ 0%
  25% → █████░░░░░░░░░░░░░░░ 25%
  50% → ██████████░░░░░░░░░░ 50%
  75% → ███████████████░░░░░ 75%
  100%→ ████████████████████ 100%

附錄 F：貨幣格式化規格
格式：$X,XXX.XX {幣別}
千位分隔符：逗號
小數位數：2

範例：
  $5,000.00 HKD
  $78.00 HKD
  $1,234,567.89 HKD

附錄 G：SSM 參數完整列表
參數路徑	類型	說明
/bot/token	SecureString	Telegram Bot Token
/bot/owner_id	String	擁有者 Telegram User ID
/bot/webhook_secret	SecureString	Webhook 驗證 Secret Token
/bot/webhook_path	SecureString	URL 路徑中的隨機安全段
============================================================
文件結束
============================================================