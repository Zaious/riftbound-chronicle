# Riftbound Chronicle 三體系可用化實作與複驗報告

**日期：** 2026-08-24
**基線版本：** `064d83b`
**範圍：** `deck-coach`、`rule-consult`、`player2-agent`、三套資料契約與三個展示流程

## 結論

Repository 已從「deckbuilding＋gameplay 策略助手」進化成三個責任分離的模式：

- `deck-coach`：沿用既有構築與 gameplay 研究，負責牌組診斷和教學。
- `rule-consult`：可分析細節互動，但必須交代來源、假設、信心與非官方身分。
- `player2-agent`：在實體、人類操作的對局中替 Player 2 提出策略選擇。

P2-A 已有可執行的 session ledger。它能建立對局、記錄人類確認的狀態、記錄 Agent 尚未驗證合法性的行動建議、記錄人類合法性確認，並要求人類在實體結算後另建一筆新狀態。

P2-S 只有規劃文件，沒有規則引擎、狀態引擎、自動結算、自我對弈或強化學習執行碼。

本次複驗後，`deck-coach` 與 `rule-consult` 都已從「方法文件」提升到可建立、驗證、匯出與展示的垂直版本；但「可用」指的是契約與流程可用，不代表已完成大規模專家語意評測，也不代表 UI 已串接模型 API。

## 本次交付

### 開發文件

- 產品範圍與三體系責任。
- 共用知識與模式邊界架構。
- P2-A 產品規格。
- P2-S 未實作提案與啟動閘門。
- Riot 政策責任矩陣及申請材料清單。
- 三模式分離的評估計畫。

### Skill

- `SKILL.md` 改為三模式薄路由。
- 新增 `deck-coach`、`rule-consult`、`player2-agent` 模式入口。
- 把跨模式的規則來源優先級整理成共享參考。
- Gameplay 書的細節互動問題改由 `rule-consult` 承接，而非只做模糊轉介。

### P2-A 程式

- `p2a_session.py`：不依賴外部套件的 session ledger CLI。
- `p2a-session.schema.json`：固定 P2-A 資料契約。
- `check_p2a_protocol.py`：自動驗證人類權威、隱藏資訊與狀態轉換邊界。
- CI 和 off-CWD portable check 已納入 P2-A regression。
- `prototype/p2a/`：不需建置、沒有規則引擎的可視化申請展示介面。

### Rule Consult 可用化

- `rules_source_registry.json`：2026-08-24 複查的來源登錄，包含 2026-07-16 Core Rules、2026-07-16 Tournament Rules、Vendetta patch notes／errata，以及僅作輔助的 RiftJudge。
- 明確保留兩條權威軸：競賽程序以 event addendum／Tournament Rules 高於未修改的 Core Rules；一般機制則依 scoped 官方澄清、最新 Core Rules 與現行 errata 判讀。
- `rule-consultation.schema.json`：固定 `official_status: unofficial`、`state_effect: none`。
- `rule_consult.py`：建立 facts、assumptions、來源定位、信心與 escalation 的可驗證產物。
- `rule_consult_cases.json`：9 個初始 mechanic／interaction／tournament-procedure cases。
- `prototype/rule-consult/`：來源階梯、證據 ledger、信心閘門與 JSON 匯出展示頁。
- P2-A 的 Rule Consult 入口只做獨立分頁導覽，沒有 session 讀寫能力。

### Deck Coach 深化

- `deck_coach_roles.json`：8 種質性角色。`not_observed` 只表示目前標記中未見，不等於缺陷、配額或分數。
- `deck-coach-session.schema.json`：固定 deck context、decklist、diagnosis、evidence 和八段式 primer。
- `deck_coach.py`：建立、加卡、finalize、validate 與 Markdown primer render。
- `deck_coach_pipeline.py`：把最小 deck input 轉成 structured profile、recommendation mask、八段 baseline primer 與 machine-readable evaluation report。
- `deck_coach_cases.json`：3 個完整可執行案例，涵蓋 Global Rengar、同牌表匯入台灣環境，以及 ban／collection／Domain／errata／sample-environment mask；每例都有玩家程度、必識 engine／弱點、禁止主張、可接受未知、八段專家參考答案與有效日期。
- `battle` runner：盲標 A／B 比較 Skill／模型／資料版本，將自動偏好與專家偏好分開留存。
- `prototype/deck-coach/`：牌表解析、角色覆蓋、診斷、八段 primer 與 JSON／Markdown 匯出展示頁。
- validator 明確拒絕 win rate、play rate、matchup win rate、tier rank 與 composite score 欄位。

## P2-A 強制不變量

- `automation_level` 只能是 `P2-A`。
- `p2s_enabled` 只能是 `false`。
- 狀態與合法性權威只能是 `user_confirmed`。
- Agent 建議建立時只能是 `unverified`。
- 每份建議綁定其依據的最新確認狀態。
- 人類接受行動後，系統不推算盤面；下一筆必須是人類確認的新狀態。
- 不允許 Player 1／對手隱藏手牌或牌序欄位。
- 不接受未知事件種類或可繞過流程的額外欄位。

## 驗證結果

以下檢查全部通過：

- Skill quick validation。
- P2-A protocol regression。
- P2-A CLI：`new → state → propose → confirm → state → validate`。
- P2-A 靜態介面契約：DOM IDs／欄位、Schema 常數、local-only runtime、responsive／reduced-motion。
- Rule Consult：6 個來源種類、9 個初始 cases、authority／confidence／escalation／no-state-effect regression。
- Rule Consult 靜態介面：來源 registry 鏡像、官方身分與狀態邊界、local-only runtime、responsive／reduced-motion。
- Deck Coach：8 種角色、3 個完整 closed-loop cases、7 項評分、6 種 recommendation-mask 排除理由、8 段 primer、evidence tiers、rate／score 欄位拒絕。
- Deck Coach 靜態介面：schema／role／primer 鏡像、local-only runtime、三體系導覽、responsive／reduced-motion。
- JSON Schema 2020-12 結構檢查與產生 fixture 驗證。
- Python compileall。
- off-CWD P2-A portability。
- card data integrity：1,451 rows／1,304 unique IDs。
- 63 筆 errata residue：0 hit。
- 48 Legend packet shape。
- 4 份八段式 deck primer。
- 56 筆 Tier 2 freshness report。
- tournament list store。
- Markdown links／anchors。
- `git diff --check`。

## 尚未完成與不可誇大的部分

- 已有 P2-A 流程介面，但尚未做卡桌／卡面 renderer；這是刻意避免被誤認為數位對戰客戶端。
- 尚未串接實際模型 API；目前 Agent 行為由 Skill 定義，UI 以 copy/paste bridge 接收建議，ledger 負責可驗證的流程與留痕。
- Rule Consult 只有 9 個初始 cases，尚不足以宣稱廣泛裁判準確率；下一步需要更多卡牌互動、版本漂移與互相衝突來源案例，並由熟悉規則者盲評實際 Agent 回答。
- Deck Coach 已有完整 artifact 與 deterministic proxy eval，但 3 個案例仍不足以代表廣泛構築品質；真正的下一步是更多熟練玩家盲評與不同模型／Skill 版本的 primer battle，而不是把 proxy 分數稱為專家準確率。
- 尚未建立 `player2-agent` 的專家情境評估集。
- Riot 註冊／API／RSO／資料來源問題仍待申請回覆。
- 現有 RiftCodex snapshot 仍是已揭露的非官方資料來源缺口。
- 自動化瀏覽器安全策略拒絕讀取工作區 `file:` 頁面；本輪完成 DOM、JavaScript、連結、schema mirror、responsive 與 reduced-motion 靜態驗證，但不能把它描述為瀏覽器點擊／視覺 QA 已通過。使用者目前可在一般桌面視窗開啟頁面，仍建議補一次人工走查。

## 下一個開發里程碑

下一階段應深化語意品質與審查材料，而不是開始 P2-S：

1. 對 9 個 Rule Consult cases 加上可盲評的完整標準答案與版本漂移測試。
2. 擴充 Deck Coach golden decks，請玩家對診斷、換牌理由與 primer 可操作性評分。
3. 建立 P2-A 人類已核對合法性的情境集，評估策略一致性、替代線與是否正確要求新 snapshot。
4. 人工走查三個展示頁，匯出 deck review、rule consultation 與 demo session 三份申請附件。
5. 提交 Riot 後，再依回覆調整公開產品邊界；P2-S 仍維持未實作。
