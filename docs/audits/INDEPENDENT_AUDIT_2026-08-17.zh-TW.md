# Riftbound Chronicle 獨立審計報告（修復後複驗與定位重評）

**複驗日期：** 2026-08-18（Asia/Taipei）
**審計對象：** `riftbound-chronicle`
**目前版本：** `1751c7d`（`main`）
**基線版本：** `8e0b4dd`（2026-08-17 初始審計）
**審計性質：** 唯讀複驗、規則來源校對、資料與文件完整性審計
**報告語言：** 繁體中文

---

## 1. 結論先行

本次以目前 `main` 的 `1751c7d` 重新複驗，並把產品責任重新定義為：**組牌助手＋Gameplay 助手**。它需要足夠的基礎遊戲知識，才能提供構築方向、完成牌組的核心循環、起手與回合操作建議；它不負責取代裁判，也不承諾解答細節判定。

在這個定位下，基線指出的來源權威、Gameplay、errata 套用與合法性模型，已經完成關鍵修復；本次未再找到 Rek'Sai 卡文正文殘留，ARC／日期的主要矛盾也已消除。Tier 2 實戰驗證已跑完 46/46，但只有少數條目得到完整確認，這表示構築方向可以提供為「有證據層級的建議」，不能一律包裝成已驗證的最佳答案。

**重新定位後評分：8/10。**
**發布判定：可作組牌與 Gameplay 教學助手；不應自稱詳細規則裁定、賽事 Judge 或即時完整卡文資料庫。**

目前最重要的剩餘事項：

1. Gameplay 文件規則背景充足，但尚未以固定的「這副牌怎麼玩」輸出格式交付；缺少每副完成牌組都能套用的核心循環、前中後期、起手、保留牌與常見失誤模板。
2. `SKILL.md` 仍把細節互動／裁定問題列為主要觸發語句，與「不負責細節判定」的產品邊界不完全一致；需要明確改成背景說明＋不確定性標示＋官方轉介。
3. `README.md` 仍寫「3 of 46」及 `battle-tested`／`can't go stale` 等過時或過強承諾；`SKILL.md` 仍有「every card across every set」的覆蓋語氣。
4. raw harvester 尚未公開，clean clone 仍無法完整重建原始 snapshot；overlay 雖已通過 freshness 與語意殘留 gate，仍是 16 項 live-fetched、47 項 spot-checked。
5. Void Burrower 的卡文已修正，但 `reksai.md` 與 `errata_overlay.json` 仍有過時 annotation；這不再是助手核心能力的 P0，但會誤導後續內容維護。

其餘主要結果：

- `SKILL.md` 已明列 event addendum → Tournament Rules → Core Rules 的競賽優先級，並把 FAQ／Core／errata 分成不同問題軸。
- Gameplay 的 Burn Out、Open／Showdown 限制、chain 結算、priority shortcut、Showdown／combat、damage assignment、No Result、control 與 mulligan 程序，已逐項對到官方 PDF 條文。
- `errata_overlay.json` 已收錄四波共 63 項官方勘誤；目前有 16 項 live-fetched、47 項 spot-checked，且新增 freshness gate 與衍生 Markdown 的 63 項 `old_text` 殘留檢查，這兩項均通過。
- 路徑與基本資料管線已有 CI；但 raw harvester 仍不在公開 repository。Domain 統計目前可重跑為 `949`，舊 `965` 已在方法來源中標為退役 historical population，不應再拿來作現況數字。
- 合規文字已由「政策即許可」改為明確揭露註冊待審與非官方資料來源；這改善了文件誠實度，但不等於實際取得 Riot 註冊或資料來源核准。
- 46 個 Legend catalogue entries 已全部完成 Tier 2 檢查；目前只有 4 個完整確認，其餘是 partial／not confirmed／修正後仍需保留不確定性的條目。這符合助手定位，只要輸出時保留證據層級，不把它們混成「已證實攻略」。

---

## 2. 審計範圍與複驗方法

### 2.1 納入範圍

- 產品目標：組牌助手、Gameplay 助手、基礎遊戲知識；不以詳細規則裁定或 Judge replacement 作為驗收標準。
- 根目錄 `README.md`、授權與合規聲明。
- `skill/SKILL.md` 的路由、來源權威與 freshness 規則。
- `skill/references/gameplay/gameplay.md`。
- Deckbuilding、Legend catalogue、regional legality 與 verification log。
- `skill/data/riftcodex_cards_raw.json`、`skill/data/errata_overlay.json` 與資料說明。
- `skill/scripts/`、GitHub Actions CI、相對連結與不同 working directory 的可攜性。
- 2026-07-16 官方 Core Rules／Tournament Rules PDF，以及 Rules Hub、FAQ、四波官方 errata 與 ban-list 頁面。

### 2.2 複驗程序

1. 以 `git diff 8e0b4dd..1751c7d` 盤點基線審計後的所有修復提交，包含最後一批 46/46 Legend Tier 2 verification。
2. 重新讀取官方 PDF 的關鍵條文，而不是只依賴 PDF 文字抽取：Core 117、310、339–340、431.2、465–466；Tournament 104、204.4、401.5、402.1、503.9、601.1–601.3。
3. 重新檢查 Rules Hub 的 FAQ／errata／ban list freshness 與競賽優先級。
4. 重新執行 repository 內的資料完整性、連結、Domain 統計與 Legend packet 檢查。
5. 對 63 項 overlay 的 `old_text` 做衍生文件殘留檢查，並確認 freshness gate 與結果。
6. 檢查跨文件的 ARC 合法性、日期、資料量、Tier 2 驗證狀態與「完整／不會過期」等公開承諾是否一致。

### 2.3 限制

- 本報告不作著作權或法律意見；只判斷 repository 的公開敘述是否超過其證據。
- 不要求本 repository 能回答每個細節互動或賽事爭議；這些只檢查是否有清楚的轉介與不確定性邊界。
- 不把社群文章當成官方規則；社群資料只能作 Tier 2 方法驗證。
- 同類 AI Skill 對標搜尋於 2026-08-18 完成，涵蓋 MTG、Pokémon TCG／Pocket、Flesh and Blood 與一般 Claude／MCP 公開 repository；結果不是完整市場普查。
- 外部網頁與產品註冊狀態會變動；本報告的官方來源基準日為 2026-08-18。

---

## 3. 官方規則權威模型（本次正式採用）

Core Rules 不是所有競賽問題的最高來源。兩條軸必須分開：

### 3.1 競賽程序軸

1. 適用於該賽事的官方 event addendum。
2. Tournament Rules。
3. Core Rules 中未被上述競賽文件修改的部分。
4. 實際 sanctioned event 的 Head Judge 裁定。

Tournament Rules 104.1 明定其與 Core Rules 衝突或補充時，以 Tournament Rules 為準；104.3 明定特定賽事 addendum 再優先；204.4 將 Head Judge 定為競賽規則與程序的最終權威。這是本次複驗的競賽基準。

### 3.2 遊戲機制與卡文軸

1. 在明示範圍內適用的最新官方 FAQ／clarification。
2. 最新 Core Rules。
3. 套用官方 errata 的卡文；卡文若與一般規則衝突，依 Golden Rule 以卡文為準。

2026-08-14 Vendetta FAQ 明示在下一版 Core Rules 發布前，FAQ 與當時 Core Rules 不同時以 FAQ 為準。因此「Core PDF 高於一切」不是可接受的路由規則；本 repository 目前的 `SKILL.md` 已正確拆開這兩條軸。

---

## 4. 可重現驗證結果

| 檢查 | 結果 | 複驗證據 |
|---|---|---|
| 資料完整性 | PASS | `1451 rows`、`1304 unique riftbound_id`、`147 duplicate-id groups`；overlay 4 documents／63 entries；script exit 0 |
| Markdown 相對連結 | PASS（有限） | 檢查 55 份 Markdown、58 個相對連結，0 broken；fragment anchor 本身未驗證 |
| Domain 統計 | PASS（可重跑） | `compute_domain_stats.py` 產生 949-card population 與六 Domain 表；這是新定義的 population，不應再稱舊 965 |
| Legend packet | PASS | 48 packets；每個 packet 正好 2 個 Champions；從 `%TEMP%` working directory 以絕對 script path 執行亦成功 |
| 官方 errata 數量 | PASS（正文）／PARTIAL（附註覆蓋） | overlay 63/63；16 live-fetched、47 spot-checked；正文 `old_text` residue 0 hit，但仍有一處 annotation 與最新正文不同步 |
| Git 工作樹 | PASS | 複驗期間只修改本審計報告；`git diff --check` 無 whitespace error |

---

## 5. 發現與修復狀態

嚴重度：P0 會直接造成錯誤裁定或錯誤卡文；P1 會使合法性、可攜性、可重現性或公開承諾失真；P2 為文件一致性／維護風險。

| 編號 | 基線問題 | 目前狀態 | 判定 |
|---|---|---|---|
| F-01 | 來源權威模型把 Core／local snapshot 放在不當位置 | 已加入雙軸 precedence、FAQ、errata overlay 與 Head Judge 限制 | **Closed** |
| F-02 | Gameplay 多項錯誤流程 | 主要程序已依官方 PDF 重寫並補 Tournament procedure notes | **Closed** |
| F-03 | 63 項官方勘誤多數未套用 | 卡文正文 63/63 overlay、freshness gate 通過、`old_text` residue 0 hit；附註仍有一處過時的機械影響描述 | **Closed with P2 annotation residual** |
| F-04 | legality 缺 same-name、overnumbered、OPL、2v2 等維度 | 模型、ARC same-name 說法與日期已同步；仍有一處教學句型把 ARC 帶進「outside」條件，需降歧義 | **P2 Partial** |
| F-05 | 相對路徑依賴工作目錄 | 主要內部路徑改用 `${CLAUDE_SKILL_DIR}`；off-cwd smoke test 通過 | **Closed** |
| F-06 | raw harvester、CI、統計不可重現 | CI／scripts／citations／freshness gate 已加入；harvester 仍不公開，README 的驗證進度仍漂移 | **P1 Partial** |
| F-07 | 合規敘述把 policy 說成既成 permission | README 已揭露註冊待審與非官方 API gap | **Documentation Closed; operational open** |
| F-08 | 文件矛盾、壞路徑、過強成熟度語氣 | 路徑、主要 ARC／日期矛盾已修；README／SKILL 尚有過時進度與覆蓋語氣 | **P2 Partial** |
| F-09 | Tier 1 Legend 推導與實戰結論的可信度界線 | 46/46 已 Tier 2 檢查，但只有 4 個完整確認；狀態已記錄，公開 README 尚未同步 | **P1 Partial** |
| F-10 | 產品邊界未完全對齊「組牌＋Gameplay 助手」 | 內容已具備構築方向與基礎 Gameplay 知識，但 router 仍把細節互動／裁定列為主要用途，且缺少固定的成品牌組教學輸出格式 | **P1 Partial** |

---

## 6. 詳細複驗結果

### F-01 — 來源權威模型：已關閉

`SKILL.md` 現在明列：

- competitive procedure：event addendum → Tournament Rules → Core Rules；
- game mechanics／card text：current FAQ → latest Core → errata-applied card text；
- ban list 與 card errata 必須做 freshness check，不能把 local snapshot 當永久真相；
- routine card lookup 可 local-first，但 overlay 缺漏或過期時要升級到 Rules Hub。

這已直接修正基線審計最核心的錯誤：不能只讀 Core Rules PDF，也不能把 live official lookup 寫成罕見例外。此次複驗也確認 errata overlay 已有 90 天 freshness gate；因此治理邏輯已成形，剩餘風險主要是原始資料來源與人工 spot-check 覆蓋率。

### F-02 — Gameplay：已關閉

重新對照後，以下內容與官方條文一致：

- Core 431.2：Burn Out 先盡可能執行原動作，再 recycle trash、讓對手得 1 分，最後完成原動作；
- Core 310.1.a／308.1.a／806.1：Neutral Open 不等於只有 Action；Showdown 的 Action／Reaction 限制是另一層；
- Core 339.1、340.1：一輪全 pass 只結算最新 chain item，不會一次清空整條 chain；
- Tournament 503.9.b：放入 spell／ability 預設視為 pass，除非明示 retain priority；
- Core 344–348、464–466：Non-Combat Showdown、combat spell window、Might 計算、依序分配／同時造成 damage、No Result 與 cleanup 後 control；
- Core 117.1–117.3：set aside → draw replacement → recycle 的 mulligan 順序；
- Tournament 401.5：open decklist 是 Head Judge 的賽事政策，且只能在 match 開始／局間查看，不能 gameplay 中查看。

目前沒有在 Gameplay 主文中再找到基線列出的那批程序錯誤。這個結論代表基礎機制足以支撐 Gameplay 教學；不代表 repository 承諾逐張卡、逐個邊界互動都能提供 FAQ／Judge 級裁定。

### F-03 — 官方 errata：已關閉主要缺陷，保留覆蓋率限制

`skill/data/errata_overlay.json` 現在有四份官方文件、63 entries，結構檢查通過。原始 JSON 保持為未修改的 RiftCodex snapshot，overlay 作為修正層，這個設計是正確的。

本次複驗以 overlay 的 `old_text` 對 `skill/references/**/*.md` 做殘留搜尋，結果為 **0 hit**；`reksai.md` 已改用 `You may banish one, then play it. Recycle the rest.`。這關閉了基線中會直接改變遊戲結果的 P0 卡文錯誤。

但正文旁的註解仍寫「No mechanical change from the pre-errata text in either case」，這對 Void Burrower 並不精確：`play one` 與 `banish one, then play it` 的牌庫區域處理不同，不能當成純排版改寫。`errata_overlay.json` 的 Swarm Queen note 也仍說舊文逐字保留在 `reksai.md`，與目前 residue 0 的實際狀態不一致。兩者不再污染卡文正文，但會誤導後續研究者，應列為 P2 annotation cleanup。

`check_data_integrity.py` 目前同時通過兩道 gate：overlay 最後驗證日距今 1 天、在 90 天 freshness window 內；53 份 Markdown 對 63 個 `old_text` 的語意殘留檢查為 0 hit。剩餘限制是覆蓋率誠實標示為 16 項 live-fetched、47 項 spot-checked；這不等同於 63 項本次逐頁 live re-fetch，但已不再是衍生檔漏套用的結構性缺陷。

**後續建議：** 將 live／spot-checked／豁免狀態維持在機器可讀欄位，並在每波官方 errata 更新時重新跑 freshness 與 residue gate。

### F-04 — 合法性模型：核心已修，剩一處低嚴重度歧義

本次確認模型已補上 Tournament Rules 601.2–601.3 的主要維度：

- format（1v1／2v2 與不同 ban list）；
- region、event date、official launch date；
- same-name reprint（601.2.a）；
- overnumbered reprint（601.2.c）；
- ban list、OPL 與 low-OPL exact preconstructed exception（601.2.d.2）；
- sideboard 上限 10 張與 Main Deck + sideboard copy limit（601.1.c）；
- event addendum。

目前摘要與 worked example 已統一為：Taiwan legal pool 是 OGN + OGS；Global Standard 是 OGS、OGN、SFD、UNL、VEN；ARC 只透過 same-name reprint rule 取得可能的合法性，並非 Standard legal set。Taiwan／Global 的 last-verified 日期也已同步。

仍有一處低嚴重度歧義：`skill/references/deckbuilding/deckbuilding.md` 的 deck-construction 步驟仍使用「set outside OGN+OGS+ARC entirely」這種句型。雖然上下文已說 ARC 不是 legal set，但這句容易讓讀者誤讀為 ARC 是台灣 pool 的第三個 set；應改成「outside the OGN+OGS legal pool, with ARC same-name reprints evaluated separately」。

### F-05 — 可攜性：已關閉，但應保留 smoke test

`SKILL.md` 的主要內部讀取路徑已改用 `${CLAUDE_SKILL_DIR}`。`extract_legend_packets.py` 從 repository 外的 temporary working directory 以絕對 script path 執行成功，證明目前 scripts 不依賴當前目錄。

仍建議把這個 off-cwd 測試固定進 CI，因為 `${CLAUDE_SKILL_DIR}` 是宿主工具提供的 substitution，並非一般 shell 的環境變數；文件應保持這個語意，不要把它改寫成要求使用者自行設定的 `$CLAUDE_SKILL_DIR`。

### F-06 — 可重現性：實質改善，但仍部分開放

已完成：

- data schema／errata 結構檢查；
- Markdown 相對連結檢查；
- Domain stats 可重跑 script；
- Legend packet extractor CI smoke test；
- verification log 補上 URL、標題、平台／作者與日期。

仍未完成：

- 產生 `riftcodex_cards_raw.json` 的 raw harvester 不在公開 repository；目前 README 只給手動 API 分頁說明，不能由 clean clone 產生相同 snapshot；
- `compute_domain_stats.py` 現在明確重算 949-card population，`deckbuilding.md` 也已把 965 標成退役 historical population；
- `README.md` 仍明載 3/46 checked，與目前 46/46 Tier 2 checked 的 verification log 不一致；
- CI 可以驗證 schema／可執行性、errata residue 與 freshness，但仍不替代逐項官方頁面 live re-fetch，也不驗證所有策略結論。

因此本項由基線 4/10 提升，但尚不能稱「完全自包含、可完整重建」。46/46 Tier 2 的完成是研究紀律上的重大改善，不等於 46/46 都已被官方或比賽結果完整證實。

### F-07 — 合規：文件修復完成，實際狀態仍開放

README 與 data README 已正確做到：

- 加入指定 Legal Jibber Jabber；
- 明確說明 product registration 仍 pending、pending 不等於 approval；
- 明確說明資料來自非官方 RiftCodex，而 Riot policy 要求 Riftbound assets 來自 Riot API；
- 不再把 approved use case 推導成此 repository 已獲個別核准；
- 不再使用「that's permission to use it」這類過度結論。

這是文件層面的關閉。但從政策條件來看，產品註冊尚未確認、card data source 仍不是 Riot API；所以公開產品仍不能宣稱已完成合規或已獲 Riot 授權。這不是 repository 內文案可自行解決的技術問題。

### F-08 — 文件一致性：部分關閉

`check_links.py` 已找到 58 個相對連結且 0 broken，先前的壞路徑問題已改善。但該檢查不解析 fragment anchors，也不做語意一致性。

以下成熟度／覆蓋語氣仍應降調：

- README 的 `battle-tested`；
- README／Legend index 的「derived from primary text, so it can't go stale」；
- `SKILL.md` 與 README 對「every card across every set」的語氣，與 data README 明列「不含 RAD、ARC、FND」不完全一致；
- README 的「3 of 46 checked」已經過時；
- `SKILL.md` 的「full official English rules text for every card across every set」超過 data README 已揭露的 Set 5/Radiance、ARC、FND 等資料缺口；
- `deckbuilding.md` 的 ARC「outside」句型仍應改成 same-name reprint 的明確說法（已列於 F-04）。

這些不是單純文風問題：在規則型 skill 中，讀者會把「不會過期／every card」理解成 freshness guarantee，與 raw snapshot、資料缺口及「只有 4/46 完整確認」的研究狀態不相稱。

### F-09 — Tier 2 實戰驗證：完成盤點，但不代表策略已被證實

目前 46/46 Legend catalogue entries 都已完成 Tier 2 check。這是方法透明度上的大幅進步，但結果本身也很重要：只有 4 個條目達到完整確認，其餘多為 partial、not confirmed 或在檢查後修正原先的 archetype／Champion split／supporting-card 假設。這說明 Tier 1 的卡文推導適合產生可檢驗假說，不適合直接標成「實戰最佳答案」。

目前 verification log 已保存每個條目的狀態，故研究層面可接受；但 README 仍寫 3/46，會讓讀者低估驗證進度，又會誤把未完整確認的內容當成同一種可信度。公開索引應同步顯示 `CONFIRMED`、`PARTIAL`、`NOT_CONFIRMED` 三類，而不要只用一個 checked／unchecked 二分法。

### F-10 — 產品邊界：適合助手，但輸出契約仍需收窄

以使用者重新指定的定位來看，這個 repository 的核心方向是合理的：deckbuilding 書負責「為什麼放這些牌、牌組想怎麼贏」，gameplay 書負責「拿到成品後如何安排回合、起手與資源」。這比「規則查詢引擎」更適合目前的資料與方法。

但目前 `SKILL.md` 仍把「這個連鎖怎麼接」「這個互動怎麼 resolve」「play review」列為主要觸發例；gameplay 書也保留完整 Tournament procedure notes。這些內容可以作為助手的背景護欄，卻不應讓使用者誤以為輸出是 Judge-level ruling。建議固定以下邊界：

- 可以說明足以理解牌組運作的基礎規則與常見決策；
- 可以給 mulligan、回合節奏、資源保留、進攻／等待與牌組核心循環建議；
- 對細節互動只給「背景理解／可能方向」，明確標示不作裁定，必要時轉介官方來源或 Head Judge；
- 每份完成牌組教學固定輸出：身份／核心循環／勝法／起手／前中後期／常見線／常見錯誤／不確定性。

因此這不是「Gameplay 規則不夠多」，而是「Gameplay 知識尚未完全轉成助手交付物」的產品問題。

---

## 7. 修復後評分

| 面向 | 分數 | 複驗判定 |
|---|---:|---|
| 產品定位與知識架構 | 9/10 | deckbuilding／gameplay 分書與 Tier 分層很適合助手定位；router 邊界尚需收窄 |
| 規則權威治理 | 8/10 | precedence、FAQ／errata 分層與 freshness gate 已正確寫入 |
| 組牌方法與構築方向 | 8/10 | Legend-first、角色／曲線／合法池方法完整；Tier 2 顯示需保留 provisional 標籤 |
| Gameplay 基礎知識 | 8/10 | 足以支撐回合、Showdown、mulligan 與資源決策；不宜當細節裁定資料庫 |
| 成品牌組的 Gameplay 教學 | 6/10 | 有 Tier 1/2/3 piloting 方法，但尚缺固定的 deck primer 輸出格式 |
| 卡牌資料新鮮度 | 7/10 | 63 項 overlay、freshness／residue gate 通過；47 項仍為 spot-checked |
| 區域與賽制合法性 | 8/10 | dimensions、ARC same-name 與日期已同步；留一處低嚴重度句型歧義 |
| Skill 可攜性 | 8/10 | `${CLAUDE_SKILL_DIR}` 路徑與 off-cwd smoke test 通過 |
| 可重現性與驗證 | 7/10 | CI／scripts／freshness／residue gate 已存在；raw harvest 仍不公開 |
| Tier 2 研究可信度 | 7/10 | 46/46 已檢查且狀態透明，但僅 4 個完整確認；符合「方向建議」而非「最佳答案」 |
| 公開合規準備度 | 5/10 | 文件誠實，註冊與資料來源條件尚未解決 |
| **整體** | **8/10** | **組牌／Gameplay 助手可用；詳細裁定與即時完整卡文不在責任範圍** |

---

## 8. 必要修復順序

### P0 — 發布前必做

目前沒有會阻止「組牌＋Gameplay 助手」使用的 P0 程式或卡文正文錯誤。詳細裁定、競賽 procedure 與 Head Judge 轉介應被標成非目標，而不是繼續擴張成產品承諾。

### P1 — 讓助手輸出可直接使用

1. 新增固定的完成牌組 Gameplay primer：身份、核心循環、勝法、起手、前中後期、常見線、常見錯誤、證據層級。
2. 將 `SKILL.md` 的詳細 ruling 觸發語句改成「基礎背景說明」；細節判定一律標示不負責並轉介官方來源。
3. 將 `README.md` 的 3/46、`battle-tested`、`can't go stale` 與 `SKILL.md` 的 every-card 語氣同步到目前證據。
4. 把 `deckbuilding.md` 的 ARC「outside」句型改成 legal pool + same-name reprint 的明確分句。

### P2 — 讓資料與長期維護更可靠

1. 公開 raw harvester、輸入 snapshot checksum 與產出版本，或正式撤回「clean clone 可完整重建」的承諾。
2. 增加 Markdown fragment anchor checker。
3. 將 46 個 Legend 的狀態從 checked／unchecked 二分法改成 CONFIRMED／PARTIAL／NOT_CONFIRMED 的公開索引。
4. 清理 `reksai.md`／`errata_overlay.json` 的過時 errata annotation。
5. 將基礎 Combat 案例加入教學回歸測試，但不要把它擴張成自動裁定引擎。

---

## 9. 驗收清單

- [x] `reksai.md` 不再含 Void Burrower 的 errata 前文字。
- [x] 63/63 errata 有 `new_text`、來源頁、驗證狀態與最後驗證日期；衍生檔沒有未豁免的 `old_text`。
- [ ] errata annotation 不再把 `banish`／`play` 的區域變化描述成「無機械影響」，且 note 不再指向已不存在的舊文殘留。
- [x] `SKILL.md` 保留 event addendum → Tournament Rules → Core Rules 的競賽優先級。
- [x] Gameplay 的 Burn Out、chain、Showdown、combat、mulligan 與 Tournament notes 通過條文對照。
- [x] 所有合法性摘要只列 OGS、OGN、SFD、UNL、VEN 為現行 Standard set；ARC 僅以 same-name reprint 規則描述。
- [x] 1v1／2v2 ban list、regional launch、same-name、overnumbered、OPL 與 sideboard assertion tests 存在。
- [x] Taiwan／Global snapshot 日期與官方 release／ban／FAQ 日期一致。
- [ ] raw data 更新方式可由 clean clone 重建，或文件清楚標為不可重建 snapshot。
- [ ] 949 Domain population 與所有引用數字一致。
- [ ] CI 同時覆蓋 schema、links、anchors、extractor、errata semantic residue 與 freshness（目前 anchors 尚未覆蓋）。
- [ ] 完成牌組有固定 Gameplay primer：核心循環、勝法、起手、前中後期、常見線、常見錯誤與證據層級。
- [ ] `SKILL.md` 明確說明：提供基礎規則背景與策略建議，不承擔細節判定。
- [x] README 不宣稱已獲 Riot 個別授權或已完成產品註冊。

---

## 10. 官方與對標來源

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
12. [Magic: The Gathering Official Rules](https://magic.wizards.com/en/rules)
13. [Flesh and Blood Comprehensive Rules — Combat](https://rules.fabtcg.com/en/cr/07-combat/)
14. [Star Wars: Unlimited — First Look](https://starwarsunlimited.com/articles/star-wars-unlimited-first-look)
15. [Pokémon TCG Rules and Resources](https://www.pokemon.com/uk/pokemon-tcg/rules)
16. [MTG Skills — Claude Code skills for Magic: The Gathering](https://github.com/dan-blanchard/mtg-skills)
17. [MTG `deck-strat` Skill — fixed strategy-guide / pilot workflow](https://raw.githubusercontent.com/dan-blanchard/mtg-skills/main/deck-strat/SKILL.md)
18. [PTCGP Domain Skill — deck rules separated from advisory feedback](https://github.com/axross/ptcgp-deck-builder/blob/main/.claude/skills/ptcgp-domain/SKILL.md)
19. [PokeClaude — Pokémon TCG Pocket MCP plus deck-building and strategy skills](https://github.com/briansunter/pokeclaude)
20. [ScryChat — MTG functional-role deck-building assistant](https://github.com/cybermelons/scrychat)
21. [MagicAI — Judge / Tactician split architecture](https://github.com/Fartis/MagicAI)
22. [Goagain — Flesh and Blood card-data MCP, without an equivalent public pilot skill](https://api.goagain.dev/)

---

## 11. 定位校準與同類 Skill 對標

### 11.1 本產品應該被評價成什麼

本 repository 不是 Judge、Rules Engine 或牌局模擬器。正確的產品契約是：

1. **組牌助手**：從 Legend／Champion／Domain／卡牌角色推導構築方向，指出核心循環、曲線、資源與替代路線。
2. **Gameplay 助手**：拿到一副完成牌組後，告訴玩家它想怎麼贏、起手找什麼、前中後期做什麼、什麼資源要保留，以及常見失誤。
3. **基礎規則背景**：只提供足以理解上述建議的回合、Showdown、mulligan、chain／focus 概念。
4. **非裁定服務**：細節互動、爭議判定、賽事 procedure 不應成為承諾；需要時標示不確定並轉介官方來源。

以這個基準，現有兩本書的分工是對的，Tier 1／Tier 2／Tier 3 也適合表達「機械推導／實戰交叉驗證／尚無足夠證據」。真正的缺口不是規則少，而是缺少一個固定的成品交付物：**每副完成牌組都應能產出一份可直接照著練習的 Gameplay primer。**

建議 primer 固定包含：

- 一句話牌組身份與勝法；
- 核心循環與關鍵牌角色；
- 起手／mulligan 目標；
- 前期、中期、收尾的優先級；
- 何時主動進 Showdown、何時保留資源；
- 2–4 條常見操作線；
- 新手最常犯的 3–5 個錯誤；
- 每個結論的證據層級與不確定性。

### 11.2 找到的同類 AI Skill／Agent 架構

| 對標 | 類型 | 與本專案最有用的對照 |
|---|---|---|
| [MTG Skills](https://github.com/dan-blanchard/mtg-skills) | 最直接的 Skill 對標 | 把 `deck-wizard`（建牌／調牌）與 `deck-strat`（完成牌組的駕駛指南）分開；`deck-strat` 有固定 strategy-guide 骨架、起手、回合節奏、威脅評估、常見線與 cheat sheet。這是 Riftbound 最應學的產品形狀。 |
| [MTG `deck-strat`](https://raw.githubusercontent.com/dan-blanchard/mtg-skills/main/deck-strat/SKILL.md) | 完成牌組 Gameplay primer | 明確規定 read-only on deck，先分析再產生固定指南；Riftbound 目前已有 piloting 方法，但沒有同等明確的輸出契約。 |
| [PTCGP Domain Skill](https://github.com/axross/ptcgp-deck-builder/blob/main/.claude/skills/ptcgp-domain/SKILL.md) | 應用內 domain skill | 把硬性 legality validation 與非阻擋式 advice 分開；Riftbound 可借用這個界線，把「基礎規則背景」與「構築／操作建議」分開，不讓建議冒充裁定。 |
| [PokeClaude](https://github.com/briansunter/pokeclaude) | MCP＋多個遊戲 Skill | 以 deck builder、card analyst、meta analyst 分工，並提供 synergy／counter／deck analysis 工具；Riftbound 的兩本書已接近這種 modular routing，但目前工具面較薄。 |
| [ScryChat](https://github.com/cybermelons/scrychat) | 功能角色型組牌助手 | 以 functional roles、替代牌、quota、mana curve 與 eval tiers 支援構築，而非只靠熱門度；這和 Riftbound 的卡牌角色／Domain 方法最相近。 |
| [MagicAI](https://github.com/Fartis/MagicAI) | Judge／Tactician 分層 Agent | 把事實來源的 Judge 與策略分析的 Tactician 分離；Riftbound 不必複製 Judge，但應採用同一個輸出邊界：策略建議可以有推理，細節判定不假裝確定。 |

### 11.3 其他遊戲目前沒有找到的部分

在本次搜尋範圍內，沒有找到 Flesh and Blood 或 Star Wars: Unlimited 具有同等成熟、公開、直接可安裝的「組牌＋成品牌組 Gameplay 教學」Skill。找到的 Flesh and Blood 代表性工具是 [Goagain MCP](https://api.goagain.dev/)，偏向卡牌查詢、關鍵字與 legality API，而不是玩家教練。

因此對標結論不是「Riftbound 已經輸給其他遊戲」，而是：

- **MTG 已有最完整的 Skill 產品分層範例**，尤其是 deck-builder → finished-deck strategy guide；
- **Pokémon 已有最成熟的資料／MCP／deck advice 組合**；
- **Flesh and Blood 的公開 AI 能力偏資料 API，Gameplay coach 仍有空位**；
- Riftbound 的機會在於把自己的 Legend／Battlefield／Showdown 結構，做成同樣清楚的「牌組身份 → 操作教學」鏈。

### 11.4 Riftbound 應保留的差異化

Riftbound 不需要在規則裁定深度上追 MTG。它應把基礎規則壓縮成玩家做決策所需的四個問題：

```text
我這副牌想在哪裡得分？
現在應該爭哪個 Battlefield？
這次 Showdown 是要投入資源，還是逼對手先投入？
我下一個 Beginning phase 要保住什麼？
```

三個 Battlefield、Beginning phase 計分、Showdown focus／priority、以及戰鬥後 control 結果，是 Riftbound Gameplay primer 的核心，不必演變成逐條判定資料庫。

### 11.5 建議的下一版交付物

優先順序應改成：

1. 新增 `deck primer` 固定模板，能由每個 Legend／完成牌組套用。
2. 把目前 generic Gameplay 長文濃縮成「玩家需要知道的基礎規則」與「策略建議」兩層。
3. 將細節裁定與 Tournament procedure 移成明確的非主流程參考，並在輸出中標示不負責裁定。
4. 用 MTG `deck-strat`、PTCGP `advice vs legality`、ScryChat 的角色／quota／eval 概念設計 Riftbound 的 evaluator。
5. 不做自動化勝負結算、不做 Judge 替代品，也不把 Tier 2 研究寫成勝率或 Tier 排名。

### 11.6 借鑒分層：應直接借、可以借、不要借

以下不是「把別人的 Skill 複製過來」，而是拆出可以移植的工作契約。每一項都要先通過 Riftbound 的產品邊界與 Riot 合規限制。

#### A. 應直接借鑒：下一個版本就應採用

| 來源 Skill 的做法 | Riftbound 應借什麼 | 對應落地物 | 驗收方式 |
|---|---|---|---|
| MTG `deck-strat` 的固定 Strategy Guide 骨架 | 把「完成牌組怎麼玩」變成穩定 artifact，而不是臨場散文 | `deck-primer` 模板：身份、核心循環、勝法、起手、前中後期、常見線、常見錯誤、cheat sheet、證據層級 | 同一副牌重跑兩次，章節順序與必填欄位一致；每個策略結論標 Tier 1／2／3 |
| MTG `deck-wizard` → `deck-strat` 的兩階段分工 | 先取得／分析牌組，再產生駕駛指南；不要讓「調牌」與「教你操作」混成一篇 | `deckbuilding` 輸出構築方向；`gameplay` 只接收完成牌組與其核心循環 | 輸入只問「怎麼玩」時不重新改牌；輸入只問「怎麼組」時不硬寫對局線 |
| PTCGP Skill 的 legality 與 advice 分離 | 將硬事實、環境限制與策略建議分欄 | `Facts`／`Advice`／`Uncertainty` 三段式回答契約 | legality 不明時仍能給方向，但不得把建議寫成合法性保證 |
| ScryChat 的 functional-role-first | 先定義卡牌在這副牌的角色，再列候選，不以熱門卡名堆砌 | Riftbound role taxonomy：核心引擎、Battlefield presence、移動、Showdown interaction、資源、保護、收尾、替代件 | 每個推薦卡都必須有角色、服務的核心循環、替代方案與理由 |
| PokeClaude 的分工式路由與小工具 | 將 deck build、deck review、card explain、deck pilot 分成可預期入口 | `SKILL.md` router＋四個輸出模式；未來可接 `search_cards`／`find_synergies` 類工具 | 10 個代表性 prompt 各自路由正確，不把 card explain 變成 deck guide |

#### B. 可以借鑒：完成核心後再做

| 來源 Skill 的做法 | 可以怎麼改成 Riftbound 版本 | 為什麼不是第一優先 |
|---|---|---|
| MTG `deck-wizard` 的 skeleton／quota 檢查 | 做「角色覆蓋檢查」：Battlefield presence、interaction、resource、finisher、mobility 等，但只作 warning，不用固定 MTG 數字 | Riftbound 的 Domain／Legend 結構不是 MTG mana base，硬搬配額會製造假精確 |
| MTG 的 self-grill／rules audit | 做一個「策略 critic」：檢查核心循環、起手建議、前中後期是否互相矛盾；不做 Judge agent | 目前先需要穩定 primer schema，才有東西可評估 |
| MagicAI 的 Judge／Tactician source gateway | 保留「事實先查、策略後寫、證據不足就降級」的原則；不複製完整 Judge 層 | 使用者已明確把細節裁定排除在產品責任外 |
| PokeClaude 的 synergy／counter 工具 | 做 qualitative counter-plan：哪些常見策略會阻礙本牌、應保留什麼資源；不輸出勝率／使用率 | Riot 邊界禁止把產品推成 metagame 統計服務 |
| ScryChat 的 alternatives／collection-aware flow | 未來接玩家卡冊後，提供缺卡替代與 deck-to-collection gap | 目前 public catalog 仍適合 static JSON，尚未需要完整 MCP／多人資料層 |

#### C. 不應借鑒：看似強大但會把產品帶偏

- **MTG `rules-lawyer` 的逐條裁定承諾**：這會把 Riftbound 助手重新推回 Judge／Rules Engine，違反已確認的產品定位。
- **Pokémon／MTG 的競技分數、Tier、meta share 模式**：可引用定性來源，但不應在本 Skill 內生成勝率、使用率、matchup 或 Tier 排行。
- **直接搬用 MTG／Pokémon 的固定數字配額**：Riftbound 應用角色覆蓋與 Legend／Domain 互補性，不應把別的遊戲的曲線數字當成規則。
- **先做完整 MCP／live scraper 再補內容契約**：資料工具不能替代「玩家拿到牌組後要怎麼玩」的教學設計。
- **自動化對局模擬與勝負結算**：超出本專案的合規與產品範圍，也會讓基礎策略建議被誤讀成保證答案。

### 11.7 建議的 Riftbound Skill 目標架構

借鑒後，最小可行架構應是四層，而不是繼續增加規則段落：

```text
1. Router
   ├─ build direction
   ├─ deck review
   ├─ deck primer / how to pilot
   └─ card / basic-rule explanation

2. Evidence layer
   ├─ card text + errata overlay
   ├─ legality snapshot / provenance
   ├─ Tier 1 mechanical synthesis
   └─ Tier 2 sourced play evidence

3. Reasoning layer
   ├─ Legend / Champion / Domain identity
   ├─ functional roles + core loop
   ├─ resource / Battlefield priorities
   └─ uncertainty and boundary labels

4. Output layer
   ├─ deck direction
   ├─ deck diagnosis + changes
   ├─ finished-deck primer
   └─ basic-rule context with ruling deferral
```

這個架構的關鍵是把「資料證據」與「策略推理」分開，再把策略推理固定投影成玩家可讀的輸出。它比增加更多規則條文更能直接改善產品價值。

### 11.8 建議落地順序

1. **P1：建立 `deck-primer` 模板與一份完整示範**，先用一個 Tier 2 證據最完整的 Legend。
2. **P1：改寫 router 描述與輸出契約**，將細節裁定改成「背景＋轉介」，不再列為主要服務。
3. **P1：建立 Riftbound functional-role taxonomy**，並讓每個 Legend／推薦卡都能回指角色與核心循環。
4. **P2：加入 strategy critic／evaluator**，檢查 primer 是否漏掉起手、節奏、資源與不確定性。
5. **P2：有玩家卡冊需求後才加入 alternatives／collection gap 工具**。
6. **不排入近期：** Judge agent、勝率模型、完整對局模擬、競賽裁定引擎。

---

## 12. 最終意見

這次重新校準後，專案的價值不在「回答所有 Riftbound 規則問題」，而在「讓玩家知道一副牌為什麼這樣組、拿到後每回合想做什麼」。以這個定位看，repository 的結構與研究方法已達到可用水準：兩本書分工清楚、構築方向有 Tier 分層、Gameplay 基礎足以支撐操作建議、46/46 Legend 已完成 Tier 2 盤點。

目前最大的產品缺口，是沒有像 MTG `deck-strat` 那樣，把「完成牌組」穩定轉成一份固定格式的駕駛指南；其次是 router 與 README 還帶有細節裁定／完整性過強的語氣。這些是可透過輸出契約與文件收窄解決的 P1，不是架構失敗。

**最終定位：** **Riftbound 組牌與 Gameplay 助手**。它提供構築方向、牌組核心循環、起手與回合教學，以及足夠理解這些建議的基礎遊戲知識；遇到細節判定、賽事 procedure 或爭議互動時，清楚標示邊界並轉介官方來源，而不是假裝自己是 Judge。
