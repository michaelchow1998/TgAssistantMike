# shared/python/bot_constants.py
# ============================================================
# 所有常數、列舉值、分類對照
# ============================================================

# ===== Entity Types =====
ENTITY_SCH = "SCH"
ENTITY_TODO = "TODO"
ENTITY_WORK = "WORK"
ENTITY_FIN = "FIN"
ENTITY_SUB = "SUB"
ENTITY_COUNTER = "COUNTER"
ENTITY_HEALTH = "HEALTH"
ENTITY_FIN_RECURRING = "FIN_RECURRING"

# ===== Schedule =====
SCH_STATUS_ACTIVE = "active"
SCH_STATUS_CANCELLED = "cancelled"

# Schedule types
SCH_TYPE_SINGLE = "single"
SCH_TYPE_PERIOD = "period"
SCH_TYPE_REPEAT = "repeat"

# Repeat patterns
SCH_REPEAT_DAILY = "daily"
SCH_REPEAT_WEEKLY = "weekly"
SCH_REPEAT_MONTHLY = "monthly"
SCH_REPEAT_CUSTOM = "custom"   # every N days

SCH_REPEAT_WEEKDAY_NAMES = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]

SCH_CATEGORIES = {
    "work":     {"display": "工作", "emoji": "💼"},
    "personal": {"display": "個人", "emoji": "👤"},
    "health":   {"display": "健康", "emoji": "🏥"},
    "social":   {"display": "社交", "emoji": "👥"},
    "other":    {"display": "其他", "emoji": "📦"},
}

# ===== Todo =====
TODO_STATUS_PENDING = "pending"
TODO_STATUS_COMPLETED = "completed"
TODO_STATUS_DELETED = "deleted"

TODO_CATEGORIES = SCH_CATEGORIES  # same set

TODO_PRIORITIES = {
    1: {"display": "高", "emoji": "🔴"},
    2: {"display": "中", "emoji": "🟡"},
    3: {"display": "低", "emoji": "🟢"},
}

# ===== Work =====
WORK_STATUS_IN_PROGRESS = "in_progress"
WORK_STATUS_COMPLETED = "completed"
WORK_STATUS_ON_HOLD = "on_hold"

WORK_CATEGORIES = {
    "development": {"display": "開發", "emoji": "💻"},
    "design":      {"display": "設計", "emoji": "🎨"},
    "marketing":   {"display": "行銷", "emoji": "📊"},
    "management":  {"display": "管理", "emoji": "📋"},
    "research":    {"display": "研究", "emoji": "🔬"},
    "other":       {"display": "其他", "emoji": "📦"},
}

# ===== Finance =====
FIN_TYPE_PAYMENT = "payment"
FIN_TYPE_INCOME = "income"
FIN_TYPE_EXPENSE = "expense"

FIN_STATUS_PENDING = "pending"
FIN_STATUS_PAID = "paid"
FIN_STATUS_CANCELLED = "cancelled"

FIN_RECURRING_STATUS_ACTIVE = "active"
FIN_RECURRING_STATUS_PAUSED = "paused"
FIN_RECURRING_STATUS_COMPLETED = "completed"

FIN_CATEGORIES = {
    "bills":         {"display": "帳單", "emoji": "🧾"},
    "salary":        {"display": "薪資", "emoji": "💵"},
    "food":          {"display": "餐飲", "emoji": "🍔"},
    "transport":     {"display": "交通", "emoji": "🚌"},
    "entertainment": {"display": "娛樂", "emoji": "🎮"},
    "shopping":      {"display": "購物", "emoji": "🛍️"},
    "health":        {"display": "醫療", "emoji": "💊"},
    "education":     {"display": "教育", "emoji": "📚"},
    "investment":    {"display": "投資", "emoji": "📈"},
    "other":         {"display": "其他", "emoji": "📦"},
}

# ===== Subscription =====
SUB_STATUS_ACTIVE = "active"
SUB_STATUS_PAUSED = "paused"
SUB_STATUS_CANCELLED = "cancelled"

SUB_CYCLES = {
    "monthly":   {"display": "每月", "emoji": "📅", "months": 1},
    "quarterly": {"display": "每季", "emoji": "📅", "months": 3},
    "yearly":    {"display": "每年", "emoji": "📅", "months": 12},
}

SUB_CATEGORIES = {
    "streaming":     {"display": "串流", "emoji": "🎬"},
    "software":      {"display": "軟體", "emoji": "💻"},
    "cloud":         {"display": "雲端", "emoji": "☁️"},
    "entertainment": {"display": "娛樂", "emoji": "🎮"},
    "news":          {"display": "新聞", "emoji": "📰"},
    "health":        {"display": "健康", "emoji": "🏥"},
    "education":     {"display": "教育", "emoji": "📚"},
    "other":         {"display": "其他", "emoji": "📦"},
}

# ===== Conversation Modules =====
CONV_MODULE_SCHEDULE = "schedule"
CONV_MODULE_TODO = "todo"
CONV_MODULE_WORK = "work"
CONV_MODULE_FINANCE = "finance"
CONV_MODULE_SUBSCRIPTION = "subscription"
CONV_MODULE_RESUME_SUB = "resume_sub"
CONV_MODULE_EDIT_SUB = "edit_sub"
CONV_MODULE_EDIT_FIN = "edit_fin"
CONV_MODULE_HEALTH = "health"          # add_meal flow
CONV_MODULE_SET_HEALTH = "set_health"  # set_health flow
CONV_MODULE_ADD_RECURRING = "add_recurring"
CONV_MODULE_EDIT_RECURRING = "edit_recurring"

# ===== Health =====
HEALTH_MEAL_BREAKFAST = "breakfast"
HEALTH_MEAL_LUNCH     = "lunch"
HEALTH_MEAL_DINNER    = "dinner"
HEALTH_MEAL_OTHER     = "other"

HEALTH_MEAL_DISPLAY = {
    "breakfast": {"label": "早餐", "emoji": "🌅"},
    "lunch":     {"label": "午餐", "emoji": "☀️"},
    "dinner":    {"label": "晚餐", "emoji": "🌙"},
    "other":     {"label": "其他", "emoji": "🍎"},
}

# ===== Conversation =====
CONV_TTL_SECONDS = 30 * 60  # 30 minutes

# ===== Display / Formatting =====
NO_DUE_DATE_SENTINEL = "9999-12-31"
SHORT_ID_PAD_WIDTH = 5
PROGRESS_BAR_WIDTH = 20
PROGRESS_BAR_FILLED = "█"
PROGRESS_BAR_EMPTY = "░"
DEFAULT_CURRENCY = "HKD"
DEFAULT_TIMEZONE = "Asia/Hong_Kong"

# ===== Module Display Names (for conversation warnings) =====
MODULE_DISPLAY_NAMES = {
    CONV_MODULE_SCHEDULE: "新增行程",
    CONV_MODULE_TODO: "新增待辦",
    CONV_MODULE_WORK: "新增工作",
    CONV_MODULE_FINANCE: "新增財務",
    CONV_MODULE_SUBSCRIPTION: "新增訂閱",
    CONV_MODULE_RESUME_SUB: "恢復訂閱",
    CONV_MODULE_EDIT_SUB: "編輯訂閱",
    CONV_MODULE_EDIT_FIN: "編輯財務",
    CONV_MODULE_HEALTH: "記錄餐點",
    CONV_MODULE_SET_HEALTH: "設定健康目標",
    CONV_MODULE_ADD_RECURRING: "新增週期記錄",
    CONV_MODULE_EDIT_RECURRING: "編輯週期記錄",
}

# ===== Commands that start conversations =====
CONVERSATION_STARTER_COMMANDS = {
    "/add_schedule", "/add_todo", "/add_work",
    "/add_payment", "/add_income", "/add_expense",
    "/add_sub", "/resume_sub", "/edit_sub", "/edit_fin",
    "/set_health", "/add_meal",
    "/add_recurring",
}
