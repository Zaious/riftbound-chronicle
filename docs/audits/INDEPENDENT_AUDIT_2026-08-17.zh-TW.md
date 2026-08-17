# Riftbound Chronicle 獨立審計報告

**審計日期：** 2026-08-17（Asia/Taipei）  
**審計對象：** `riftbound-chronicle`  
**審計版本：** `8e0b4dd`（`main`）  
**審計性質：** 唯讀、獨立技術與內容審計  
**報告語言：** 繁體中文

---

## 1. 執行摘要

`riftbound-chronicle` 的產品概念有明確價值：它不是把卡牌資料塞進一個大型提示詞，而是將牌組構築、實戰操作、區域合法性與個別 Legend 推導拆成可按需載入的知識庫。尤其「依比賽所在地的官方產品上市日判定區域卡池」這項洞察，已獲現行 Tournament Rules 601.2.b 直接支持，是本專案最具辨識度且應保留的核心。

然而，本次審計也確認三項會阻止它安全成為競賽規則／卡文權威來源的重大問題：

1. 規則權威層級沒有被完整實作，Gameplay 書仍包含多項會導致錯誤裁定的流程描述。
2. 隨附資料庫沒有套用大部分官方勘誤；63 項官方勘誤中，50 項仍呈現舊文字或舊語意，占 79.4%。
3. README 與 Skill 對「完整官方卡文」、「本地資料沒有準確度損失」、「政策即為使用許可」等敘述超過現有證據能支持的程度。

### 總體結論

**整體評分：5/10。**

本專案適合作為「有潛力的知識工程原型」與「可繼續發展的 Riftbound 助手骨架」，但目前不應標示為可供競賽裁定、完整官方卡文查詢或免查官方來源的成熟 Skill。在完成本報告 P0 修復前，建議在 README 與 `SKILL.md` 明確加入「規則與卡文仍在校正，不應作為賽事最終裁定」警語。

---

## 2. 審計範圍與限制

### 2.1 納入範圍

- 根目錄 README、授權與公開承諾。
- `skill/SKILL.md` 的路由、來源權威與本地資料策略。
- Deckbuilding 與 Gameplay 兩本知識書。
- 區域合法性模型、Legend catalogue 與 verification log。
- 隨附 `riftcodex_cards_raw.json` 的資料量、重複狀態與官方勘誤新鮮度。
- `extract_legend_packets.py` 的可執行性與輸出結構。
- 相對路徑、文件連結、自包含性與可重現性。
- Riot Riftbound Developer Policy 的公開合規敘述。

### 2.2 未納入範圍

- 不對 Riot、RiftCodex 或本專案做法律意見或著作權效力判決。
- 不逐一判定全部 46 份 Legend 策略文章的競技強度；本次審計評估其資料基礎、方法、證據與可重現性。
- 不以未公開的台灣代理商後台、銷售數據或私人營運資料證實上市與缺貨主張。
- 不評估網站部署、前端介面或非本 repository 內容。

### 2.3 方法

本次審計採取以下程序：

1. 盤點 repository 結構、分支、工作樹與最新提交。
2. 閱讀所有主要路由與方法文件，建立可驗證主張清單。
3. 依官方來源重新建立規則權威層級。
4. 將 Gameplay 與 Deckbuilding 主張逐條對照 Tournament Rules、Core Rules、最新 FAQ、Rules Hub 與官方勘誤。
5. 統計資料庫 rows、唯一 ID、重複 ID 群組、set 分布與空白文字狀態。
6. 將四波官方勘誤的新舊文字正規化後與本地基礎卡牌資料比對，並人工複核非精確命中項目。
7. 執行 Legend packet 抽取器並檢查 packet 數量與 Champion 配對數。
8. 檢查公開文件路徑、可攜性、來源可追溯性、重現管線與政策敘述。

---

## 3. 規則權威模型與審計更正

### 3.1 本報告採用的權威模型

Riftbound 不能只用一份 Core Rules 作為所有問題的最高來源。現行來源必須分成兩條軸處理。

#### 競賽程序軸

1. 特定賽事官方 addendum。
2. Tournament Rules。
3. Core Rules 中未被競賽文件修改的部分。

Tournament Rules 104.1 明定：當 Tournament Rules 與 Core Rules 衝突或補充 Core 未包含的資訊時，競賽以 Tournament Rules 為準。104.3 又明定特定賽事 addendum 可進一步優先於 Tournament Rules。

#### 遊戲規則與卡文軸

1. 現行官方 FAQ／clarification 在其明示優先範圍內。
2. 最新 Core Rules。
3. 套用官方 errata 後的卡文；依 Core Rules Golden Rule，卡文可覆寫一般規則。

2026-08-14 發布的 Vendetta Rules FAQ 明定：若該 FAQ 與當時 Core Rules 不同，FAQ 優先；下一版 Core Rules 發布後，新的 Core Rules 再優先於舊 FAQ。

實際賽事中，Tournament Rules 204.4 將 Head Judge 定義為競賽規則與程序的最終權威。

### 3.2 對先前審計的正式更正

先前以 Core Rules 103.2 的「Main Deck 至少 40 張」判定本專案「正好 40 張」錯誤，這個判定不成立。

Tournament Rules 402.1 與 601.1.b 均明定：**競賽 Constructed Main Deck 必須正好 40 張，且包含 Chosen Champion。** 因此：

- [`deckbuilding.md` 的正好 40 張敘述](../../skill/references/deckbuilding/deckbuilding.md#L43)正確。
- Chosen Champion 在遊戲設置時移到 Champion Zone，因此機率表使用 shuffled population `N=39` 的基礎正確。
- 原本針對「正好 40 張」的負面發現正式撤回。

這次更正不會使其餘 Gameplay 錯誤自動失效：Tournament Rules 只在衝突或補充的競賽事項上優先；沒有被其修改的遊戲引擎仍須依 Core Rules 與更新的官方 FAQ 判斷。

---

## 4. 評分

| 面向 | 分數 | 判定 |
|---|---:|---|
| 產品定位與知識架構 | 8/10 | 分書、薄路由與按需讀取方向良好 |
| 規則權威治理 | 4/10 | 已知道 Rules Hub，但沒有實作完整 precedence |
| Gameplay 規則正確性 | 3/10 | 多項核心流程會產生錯誤裁定 |
| 卡牌資料新鮮度 | 2/10 | 79.4% 已公布勘誤仍是舊文字／語意 |
| 區域與賽制合法性 | 6/10 | 核心洞察正確，但缺同名重印與低 OPL 例外 |
| Skill 可攜性 | 5/10 | 結構可攜，但資源路徑依賴目前工作目錄 |
| 可重現性與驗證 | 4/10 | 抽取器可用，但 raw harvester、測試與 CI 缺席 |
| 公開合規準備度 | 3/10 | 有權利意識，但政策與許可敘述過度 |
| **整體** | **5/10** | **有價值的原型，尚非可靠的競賽知識產品** |

---

## 5. 審計發現

嚴重度定義：

- **P0 — 阻斷：** 可能直接產生錯誤裁定、錯誤卡文或重大公開風險，發布前必須修正。
- **P1 — 重大：** 會使合法性、可攜性、可重現性或公開承諾失真。
- **P2 — 一般：** 文件矛盾、來源不足或維護成本問題。
- **P3 — 改善：** 不直接破壞結果，但可提升品質。

### F-01 — P0：來源權威策略不完整，且把官方查詢降級成「少見例外」

**位置：** [`skill/SKILL.md`](../../skill/SKILL.md#L19)

`SKILL.md` 有正確指出 Rules Hub 是現行來源，但第 27–29 行仍把基本規則視為穩定快照，並稱 live web fetch 是「rare escalation path」及本地資料已足以避免網路查詢。這與目前實際來源狀態不符：

- Tournament Rules 可覆寫 Core 的競賽規則。
- 2026-08-14 FAQ 比 2026-07-16 Core／Tournament PDF 更新，且明示可優先於 Core。
- 卡文勘誤沒有完整進入本地資料。

**影響：** Agent 會在最需要查官方來源的時候，反而被路由到已知過期的本地資料。

**建議：** 將來源選擇改為 freshness 與題型驅動，而非 local-first 絕對化：

- 競賽問題必讀 Tournament Rules／event addendum。
- 非平凡互動先檢查 Rules Hub 最新 FAQ 日期是否晚於本地 rules snapshot。
- 任何出現在官方 errata 索引中的卡，必須先套用 errata overlay。
- 本地資料只有在來源版本、抓取日期、官方勘誤版本與驗證狀態均可證明時才能作為快速路徑。

### F-02 — P0：Gameplay 書包含多項錯誤流程

**位置：** [`gameplay.md`](../../skill/references/gameplay/gameplay.md)

| 位置 | 現行敘述 | 正確規則與影響 |
|---|---|---|
| [第 20 行](../../skill/references/gameplay/gameplay.md#L20) | Main Deck 空時，對手得分「instead of drawing」 | Core 431.2：先盡可能完成動作、回收 Trash、指定對手得 1 分，再完成原動作；Draw Phase 範例最後仍抽 1 |
| [第 32 行](../../skill/references/gameplay/gameplay.md#L32) | Open State 只有 Action 卡可玩 | Core 310.1.a：Neutral Open 預設可出牌／啟動能力；Core 806.1 的 Action 是額外允許 Showdown 時機 |
| [第 36 行](../../skill/references/gameplay/gameplay.md#L36) | 雙方連續 pass 後整條 chain 關閉 | Core 339.1、340.1–340.3：全員 pass 後只結算最新 Finalized Chain Item；chain 尚有項目就繼續處理 |
| [第 38 行](../../skill/references/gameplay/gameplay.md#L38) | Holding priority 合法且常正確 | 策略可能成立，但 Tournament 503.9.b 預設出牌後視為 pass；必須明確宣告 retain priority |
| [第 46 行](../../skill/references/gameplay/gameplay.md#L46) | 移到無人控制戰場立即取得控制 | Core 345–348：開啟 Non-Combat Showdown；Showdown 關閉並完成清理後才建立控制 |
| [第 50–51 行](../../skill/references/gameplay/gameplay.md#L50) | 先加總 Might，再開 spell window | Core 464–465：Combat Showdown／互動先進行；Showdown 關閉後才進入 Combat Damage Step 並加總 Might |
| [第 52 行](../../skill/references/gameplay/gameplay.md#L52) | 雙方同時分配傷害 | Core 465.2.c：從 Attacker 開始依序分配；全部分配完成後才同時造成傷害 |
| [第 53 行](../../skill/references/gameplay/gameplay.md#L53) | Might 較高者勝，平手全部單位死亡 | Core 466.3：勝負依清理後是否只有一方仍有單位判定；防止、替代、回手等都可能改變結果，沒有通用的平手全滅規則 |
| [第 55 行](../../skill/references/gameplay/gameplay.md#L55) | 攻擊者只能靠「摧毀全部防守者」取得戰場 | 控制依最後剩餘單位建立，不限定摧毀；移動、Recall、替代效果與防守方反向征服都可能影響結果 |
| [第 63 行](../../skill/references/gameplay/gameplay.md#L63) | 先 bottom，再抽替代牌 | Core 117：先把最多兩張牌 set aside、抽同數量，最後才 Recycle 到牌庫底；數量正確但程序順序錯誤 |
| [第 71 行](../../skill/references/gameplay/gameplay.md#L71) | 看見對手 first plays 後再重評 mulligan | Mulligan 在遊戲開始前完成；能參考的是公開 Legend，以及 open-decklist 賽事在 match 開始提供的牌表，不可能參考已發生的第一手操作 |

**額外缺口：** 若 Gameplay 書定位包含 sanctioned play，還應涵蓋 Tournament 401.5 open decklist、503.9 shortcuts、506 triggered ability accountability／missed trigger，以及 Head Judge appeal 流程。

### F-03 — P0：隨附卡牌資料未套用多數官方勘誤

**位置：** [`riftcodex_cards_raw.json`](../../skill/data/riftcodex_cards_raw.json)、[`skill/data/README.md`](../../skill/data/README.md)、[`skill/SKILL.md`](../../skill/SKILL.md#L28)

本次將四波官方 errata 的 63 個條目與本地基礎卡牌紀錄比對。比對時正規化標點、空白、HTML 與 RiftCodex icon token，優先選擇非 alternate-art、非 overnumbered、非 promo 的基礎紀錄。

| 官方勘誤波次 | 條目 | 已是新文字 | 舊文字／舊語意 |
|---|---:|---:|---:|
| Origins | 31 | 9 | 22 |
| Spiritforged | 16 | 4 | 12 |
| Unleashed | 8 | 0 | 8 |
| Vendetta | 8 | 0 | 8 |
| **合計** | **63** | **13** | **50** |

其中 48 項精確命中官方舊文字；Rengar, Trophy Hunter 與 Resonating Strike 因 reminder text／符號格式不同未精確命中，但人工複核確認仍保留舊語意，故計入舊資料。

已確認受影響的衍生內容包括：

- [`deckbuilding.md` Annie 範例](../../skill/references/deckbuilding/deckbuilding.md#L80)仍是 `ready 2 runes`；官方已改成 `ready up to 2 runes`。
- [`teemo.md`](../../skill/references/deckbuilding/references/legends/teemo.md#L3)仍使用被實質修改的 Strategist 觸發條件。
- [`rengar.md`](../../skill/references/deckbuilding/references/legends/rengar.md#L3)仍使用舊版 Trophy Hunter Ambush 敘述。
- Draven, Vanquisher、Emperor's Dais、Stalking Wolf、Astral Heron、Gangplank, Naval、Guards!、Relentless Pursuit、Death from Below、Bone Skewer、Mirror Image 等仍命中官方舊文字。

**影響：** 「從主卡文做結構推導，因此不會過期」的前提不成立。推導方法可能穩定，但輸入文字已改變，所有以舊卡文生成的 Legend catalogue 與 worked example 都需要失效重建。

**建議：** 不應只重新抓一次 RiftCodex；應建立官方 errata overlay，保留來源 URL、發布日期、舊文、新文、套用狀態與最後驗證時間，並在 CI 中要求 63/63 全部命中新文字或有明確人工豁免。

### F-04 — P1：合法性模型抓到區域核心，但缺少正式例外

**位置：** [`deckbuilding.md`](../../skill/references/deckbuilding/deckbuilding.md#L15)、[`regional-legality-model.md`](../../skill/references/deckbuilding/references/regional-legality-model.md)

#### 已證實正確

- Tournament Rules 601.2.b 明定：在 set release parity 達成前，區域卡牌合法性依賽事所在地的官方產品上市日執行。
- 因此「台灣與 Global Standard 必須分開建模」的方向正確。
- 競賽主牌正好 40 張、1 Legend、12 Runes、3 張名稱各異的 Battlefields，方向正確。

#### 需要修正

1. [`deckbuilding.md` 第 37 行](../../skill/references/deckbuilding/deckbuilding.md#L37)將 ARC 列為 Global Standard legal set；Tournament Rules 601.3.c 的正式清單為 OGS、OGN、SFD、UNL、VEN，沒有 ARC。
2. Tournament Rules 601.2.a 允許與合法 set 卡牌同名的重印版本，因此 ARC 中的同名重印可能可用；正確理由是 same-name legality，而不是把 ARC 本身升格為 Standard set。
3. 601.2.c 規定超出正常編號範圍的 overnumbered reprint 不會自行取得該 set 的 format legality。
4. 601.2.d.2 規定：低 OPL 若使用官方預組的完全相同配置，可使用其中禁卡；修改任何內容或加入 sideboard 即失去豁免。
5. 1v1 Constructed 與 2v2 Constructed 有不同 ban list；Master Yi, Wuju Bladesman 目前只在 2v2 Constructed 被禁。
6. Tournament Rules 601.1.c 將 sideboard 上限更新為 10 張，且 copy limit 計算 Main Deck 與 sideboard 合計。

**建議資料模型：**

```text
legality = format
         + region
         + event_date
         + official_launch_date
         + same_name_reprint
         + overnumbered_rule
         + format_ban_list
         + OPL
         + exact_preconstructed_exception
         + event_addendum
```

### F-05 — P1：Skill 的資源路徑不是真正可攜

**位置：** [`skill/SKILL.md`](../../skill/SKILL.md#L14)

`SKILL.md` 指示執行 `ls references/` 並讀取 `references/<book>/<book>.md`、`data/...`。這些相對路徑會以 Claude Code 當前工作目錄解析，而不是自動以 `SKILL.md` 所在目錄解析。將 `skill/` 複製到任意專案的 `.claude/skills/riftbound/` 後，若從專案根目錄執行，`references/` 很可能不存在。

Claude Code 官方文件提供 `${CLAUDE_SKILL_DIR}`，用途正是從任意安裝層級可靠定位 Skill 自身的 script 與 supporting files。

**建議：** 所有內部資源路徑統一改成：

```text
${CLAUDE_SKILL_DIR}/references/
${CLAUDE_SKILL_DIR}/data/riftcodex_cards_raw.json
${CLAUDE_SKILL_DIR}/scripts/extract_legend_packets.py
```

並增加從不同 working directory 安裝與呼叫的 smoke test。

### F-06 — P1：資料與研究結論不可完整重現

**位置：** [`README.md`](../../README.md#L17)、[`skill/data/README.md`](../../skill/data/README.md#L18)、[`verification-log.md`](../../skill/references/deckbuilding/references/verification-log.md)

#### 已驗證的正面結果

- `extract_legend_packets.py` 可執行。
- 輸出 48 個 Legend packet。
- 每個 packet 均配對到正好兩個 Champion。
- 程式對 RiftCodex 重複列、alternate-art、overnumbered、signature 與 Kennen/Yordle 誤配做了具體防禦，這是良好的資料清理設計。

#### 不可重現部分

- 產生 `riftcodex_cards_raw.json` 的 raw harvester 不在公開 repository，而在維護者私人站點工具中。
- README 稱 `skill/` 自包含且 scripts included，但公開使用者無法用 repository 內容重建或更新 raw dataset。
- Domain personality 的「965 張卡統計」沒有提交可重跑程式、輸入 snapshot、輸出報表或 checksum。
- `verification-log.md` 的 Top 8、主流 Champion 選擇與社群共識等主張沒有來源 URL、文章標題、作者與存取日期。
- repository 沒有 test suite、CI、schema validation、link checker 或 freshness gate。

**資料統計補充：** `riftcodex_cards_raw.json` 有 1,451 rows、1,304 個唯一 `riftbound_id`，以及 147 組重複 ID。README 應使用「rows／records／printings」，而不是讓讀者理解成 1,451 張不同卡牌。

### F-07 — P1：公開合規聲明超過政策可支持範圍

**位置：** [`README.md`](../../README.md#L47)、[`skill/data/README.md`](../../skill/data/README.md#L3)

README 表示資料在 Riot Developer Portal policy 下重製，並稱該政策是「permission to use it」。但現行 Riftbound Developer Policy 同時規定：

- 面向玩家的產品即使不使用官方 API 也需要註冊。
- 卡牌與 Riftbound assets 應使用 Riot API 提供的版本，不得使用外部或非官方材料。
- App 必須顯示指定的 Legal Jibber Jabber 聲明。
- Deck builder／card library 是可接受 use case，但仍須遵守註冊、資料與品牌條件。

本 repository 明載資料來自非官方 `api.riftcodex.com`。這不等於本報告判定其一定侵權或違規，但足以說明「政策就是授權」不是目前證據能安全支持的公開陳述。

**建議：**

- 移除 `that's permission to use it`。
- 改成中性 provenance：資料權利屬 Riot、來源為非官方鏡像、使用者與部署者須自行確認 Riot 最新政策及產品註冊／核准狀態。
- 加入 Riot 指定的完整 Legal Jibber Jabber 聲明。
- 若已有 Developer Portal 產品核准，記錄可公開的核准範圍；不要從「approved use case」推導個別 repository 已獲核准。

### F-08 — P2：文件矛盾與壞路徑降低可信度

1. [`skill/data/README.md` 第 3 行](../../skill/data/README.md#L3)的 `../LICENSE` 解析為 `skill/LICENSE`，實際 LICENSE 位於 repository root，應為 `../../LICENSE`。
2. 同檔第 7 行的 `../skill/SKILL.md` 會解析為不存在的 `skill/skill/SKILL.md`；正確相對位置是 `../SKILL.md`。
3. 同檔第 20 行保留 `P:\MyOpenSource\...` 私人絕對路徑，與 [`README.md` 第 30 行](../../README.md#L30)的「zero private paths」承諾矛盾。
4. [`deckbuilding.md` 第 70 行](../../skill/references/deckbuilding/deckbuilding.md#L70)稱刻意不做每位 Legend 的靜態條目，第 93 行卻指向 46 份預寫條目；應改成「不把 Tier 2／meta 快照固化，但保留 Tier 1 結構假說」。
5. README 稱 46-entry index 是 full roster；實際架構是 index 46 份，加上 Annie 與 Kai'Sa 兩個 worked examples，合計覆蓋 48 位。應直接說明此分工，避免把 46 與 48 混成兩種 roster 數字。
6. README 的 `battle-tested`、`real established play` 與「不會過期」語氣，比 verification log 的 3/46 catalogue checks 更強，應降調到實際證據層級。

---

## 6. 值得保留的設計

### 6.1 薄路由、多本知識書

`SKILL.md` 不直接塞入全部知識，而是先判斷 Deckbuilding 或 Gameplay，再讀完整對應書。這比單一巨大 prompt 更容易維護，也減少不相關上下文。

### 6.2 區域上市與禁卡的雙軸思考

專案正確看見「實體產品是否在該地區上市」與「該卡是否被禁」是兩個獨立維度。Tournament Rules 601.2.b 證明此方向不是台灣社群自行創造的 house rule，而是官方競賽制度的一部分。

### 6.3 推導與驗證分層

將卡文結構推導標為 Tier 1，將實戰與社群／賽事驗證標為 Tier 2，是合理的 epistemic design。問題在於目前輸入卡文與 Tier 2 證據不夠可靠，不是分層概念本身錯誤。

### 6.4 資料抽取器的防禦性

抽取器明確處理重複 row、metadata 旗標與 Champion tag 誤配，顯示維護者確實分析過資料來源的具體失敗模式。這部分應保留並補測試，而不是重寫成黑箱生成流程。

### 6.5 避免 metagame-defining 數據

專案避免公開 win rate、play rate、matchup differential 與 Tier 排名，方向符合 Riot Developer Policy 對 metagame-defining data 的限制。

---

## 7. 修復路線圖

### Phase 0 — 立即停止錯誤擴散

1. README／SKILL 加入暫時警語：Gameplay 與 card text 正在校正，不供賽事最終裁定。
2. 將官方來源權威矩陣寫進 `SKILL.md`。
3. 修正 Gameplay 的 Burn Out、Open／Action、chain、Showdown、combat、mulligan 程序。
4. 建立官方 errata overlay，重新生成所有依賴卡文的 Legend 內容。

**完成標準：** 本報告 F-01、F-02、F-03 全部關閉；63/63 errata 均命中新文字或有書面人工豁免。

### Phase 1 — 合法性與競賽層

1. 將 legality 從 set allowlist 改成 format／region／date／same-name／ban／OPL 組合模型。
2. 加入 1v1、2v2、sideboard 及 exact preconstructed exception。
3. 修正 ARC 的說明：同名重印可合法，不等於 ARC 是 Standard set。
4. 將 Tournament shortcuts、open decklists、missed triggers 加入 Gameplay 競賽附錄。

**完成標準：** 為 Tournament 402.1、503.9、506、601.1–601.3 建立可執行 assertion tests。

### Phase 2 — 可攜性與可重現性

1. 所有 Skill 內部路徑改用 `${CLAUDE_SKILL_DIR}`。
2. 公開 raw harvester，或明確撤回「可自行重建／完整自包含」的承諾。
3. 提交 schema validator、duplicate report、link checker 與 CI。
4. 將 Domain 統計轉為可重跑 script 與固定輸入 snapshot。
5. verification log 每筆補來源 URL、標題、作者／平台、發布與存取日期、支持範圍。

**完成標準：** 從任意工作目錄安裝 Skill 都能通過 smoke test；乾淨 clone 可重建所有衍生資料；所有 Markdown 連結通過檢查。

### Phase 3 — 公開承諾與合規

1. 移除未有證據支持的 `permission`、`full official text`、`no accuracy gain` 等絕對語句。
2. 加入 Riot 指定聲明與產品註冊狀態說明。
3. 將第三方資料的 provenance、權利歸屬、更新責任與已知差距分開描述。
4. 釐清 public library 與 private companion 的實際邊界，移除所有私人絕對路徑。

---

## 8. 建議驗收清單

- [ ] `SKILL.md` 明列 event addendum、Tournament Rules、FAQ、Core、errata 的適用範圍與優先關係。
- [ ] 競賽 Constructed 測試確認 Main Deck 正好 40 張、Chosen Champion 包含在內。
- [ ] Gameplay 測試覆蓋 Burn Out、Neutral／Showdown Open、chain 單項結算與完整關閉。
- [ ] Combat 測試覆蓋依序分配、同時造成、prevention／replacement 與清理後勝負。
- [ ] Mulligan 文件使用 set aside → draw → recycle 的正確順序。
- [ ] Retain priority 明確提示 Tournament 503.9.b 宣告要求。
- [ ] 63 項官方 errata 全部命中新文字或有可審核豁免。
- [ ] Annie、Teemo、Rengar 與其他受勘誤影響的衍生內容已重新生成。
- [ ] Standard set 清單不再把 ARC 當成正式 Standard set。
- [ ] Legality tests 包含 same-name reprint、overnumbered、regional launch、2v2 ban 與低 OPL 預組例外。
- [ ] 所有 Skill 相對路徑改用 `${CLAUDE_SKILL_DIR}`。
- [ ] raw data 更新方式可公開重現，或文件不再宣稱可重建。
- [ ] verification log 的外部主張均有可追溯來源。
- [ ] README 不再將 Developer Policy 描述為個別資料集的既成授權。
- [ ] Riot 指定 Legal Jibber Jabber 聲明已加入。
- [ ] CI 包含 schema、duplicates、errata freshness、links 與 extractor tests。

---

## 9. 官方來源

審計以 2026-08-17 可取得的下列官方來源為準。官方網頁與 PDF 可能更新，後續驗收應先比較版本日期與文件內容。

1. [Riftbound Rules Hub](https://playriftbound.com/en-us/rules-hub/)
2. [Riftbound Tournament Rules — 2026-07-16 PDF](https://cmsassets.rgpub.io/sanity/files/dsfx7636/news_live/503da65669ced10598d62925a6f6bc15111af726.pdf)
3. [Riftbound Core Rules — 2026-07-16 PDF](https://cmsassets.rgpub.io/sanity/files/dsfx7636/news_live/e9ac8e3d33e0f78cef296f5945aba7bc1313b086.pdf)
4. [July 2026 Tournament Rules Update & Changelog](https://playriftbound.com/en-us/news/announcements/july-2026-tournament-rules-update-changelog/)
5. [Vendetta Rules FAQ and Clarifications — 2026-08-14](https://playriftbound.com/en-us/news/rules-and-releases/vendetta-rules-faq-and-clarifications/)
6. [Origins Card Errata](https://playriftbound.com/en-us/news/rules-and-releases/riftbound-origins-card-errata/)
7. [Spiritforged Errata](https://playriftbound.com/en-us/news/rules-and-releases/riftbound-spiritforged-errata/)
8. [Unleashed Errata Updates](https://playriftbound.com/en-us/news/rules-and-releases/unleashed-errata-updates/)
9. [Vendetta Errata Updates](https://playriftbound.com/en-us/news/announcements/vendetta-errata-updates/)
10. [July Ban List Updates](https://playriftbound.com/en-us/news/announcements/july-ban-list-updates/)
11. [Riot Riftbound Developer API Policy](https://developer.riotgames.com/policies/riftbound)
12. [Southeast Asia Enters the Rift](https://playriftbound.com/en-us/news/announcements/southeast-asia-enters-the-rift/)
13. [Korea Enters the Rift](https://playriftbound.com/en-us/news/announcements/korea-enters-the-rift/)
14. [Claude Code Skills documentation](https://code.claude.com/docs/en/slash-commands)

---

## 10. 最終意見

`riftbound-chronicle` 的主要問題不是「沒有想法」，而是它已經用成熟產品的語氣描述一套仍在驗證中的知識系統。區域合法性模型、分書架構、Tier 1／Tier 2 方法與資料抽取器都值得繼續投資；但規則型 AI 的可信度取決於最弱的來源治理環節，而目前這個環節正是過期卡文、錯誤 Gameplay 快照與不完整的競賽 precedence。

若先完成 P0 修復，再補齊合法性與可重現性，本專案有機會從 5/10 的研究原型提升為真正可公開依賴的 Riftbound 知識 Skill。在此之前，最誠實且最安全的定位是：**具潛力、方法清楚，但仍需官方來源覆核的社群知識庫。**

