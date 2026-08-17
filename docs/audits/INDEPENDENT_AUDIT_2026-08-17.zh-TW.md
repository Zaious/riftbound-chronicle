# Riftbound Chronicle 獨立審計報告（修復後複驗）

**複驗日期：** 2026-08-18（Asia/Taipei）
**審計對象：** `riftbound-chronicle`
**目前版本：** `65e587b`（`main`）
**基線版本：** `8e0b4dd`（2026-08-17 初始審計）
**審計性質：** 唯讀複驗、規則來源校對、資料與文件完整性審計
**報告語言：** 繁體中文

---

## 1. 結論先行

本次複驗確認，基線審計指出的三個 P0 問題中，來源權威模型與 Gameplay 程序已大幅修復；合法性、可攜性、可重現性與合規文件也都有實質改善。但目前仍不能把本 repository 當成「免查官方來源的競賽裁定工具」。原因不是原本的 Core／Tournament 優先級再度混淆，而是複驗仍找到一個直接的舊卡文殘留，以及數個會讓合法性回答自相矛盾的文件快照。

**複驗評分：6/10。**
**發布判定：Conditional — 可作研究與教育型知識庫；不可宣稱競賽最終裁定或完整當前卡文權威。**

目前最重要的兩個未關閉事項：

1. [`reksai.md`](../../skill/references/deckbuilding/references/legends/reksai.md) 的 Rek'Sai／Void Burrower Legend 仍保留 Spiritforged errata 前的 `You may play one. Then recycle the rest.`；官方 overlay 已要求 `You may banish one, then play it. Recycle the rest.`。這是可直接改變遊戲結果的 P0 卡文錯誤。
2. 合法性修復沒有同步所有文件：`deckbuilding.md` 的 front matter／Taiwan 環境摘要與 `regional-legality-model.md` 的 Global Standard 範例仍把 ARC 寫成 legal set；同一組文件又在其他段落正確說明 ARC 不是 Standard set。這會產生互相衝突的合法性答案。

其餘主要結果：

- `SKILL.md` 已明列 event addendum → Tournament Rules → Core Rules 的競賽優先級，並把 FAQ／Core／errata 分成不同問題軸。
- Gameplay 的 Burn Out、Open／Showdown 限制、chain 結算、priority shortcut、Showdown／combat、damage assignment、No Result、control 與 mulligan 程序，已逐項對到官方 PDF 條文。
- `errata_overlay.json` 已收錄四波共 63 項官方勘誤，但只有 16 項標記為 live-fetched，47 項仍為 spot-checked；且尚未有 CI 逐項驗證衍生 Markdown 是否真的使用 `new_text`。
- 路徑與基本資料管線已有 CI；但 raw harvester 仍不在公開 repository，Domain 統計的舊 `965` 數字仍與目前可重跑的 `949` population 不一致。
- 合規文字已由「政策即許可」改為明確揭露註冊待審與非官方資料來源；這改善了文件誠實度，但不等於實際取得 Riot 註冊或資料來源核准。

---

## 2. 審計範圍與複驗方法

### 2.1 納入範圍

- 根目錄 `README.md`、授權與合規聲明。
- `skill/SKILL.md` 的路由、來源權威與 freshness 規則。
- `skill/references/gameplay/gameplay.md`。
- Deckbuilding、Legend catalogue、regional legality 與 verification log。
- `skill/data/riftcodex_cards_raw.json`、`skill/data/errata_overlay.json` 與資料說明。
- `skill/scripts/`、GitHub Actions CI、相對連結與不同 working directory 的可攜性。
- 2026-07-16 官方 Core Rules／Tournament Rules PDF，以及 Rules Hub、FAQ、四波官方 errata 與 ban-list 頁面。

### 2.2 複驗程序

1. 以 `git diff 8e0b4dd..65e587b` 盤點基線審計後的所有修復提交。
2. 重新讀取官方 PDF 的關鍵條文，而不是只依賴 PDF 文字抽取：Core 117、310、339–340、431.2、465–466；Tournament 104、204.4、401.5、402.1、503.9、601.1–601.3。
3. 重新檢查 Rules Hub 的 FAQ／errata／ban list freshness 與競賽優先級。
4. 重新執行 repository 內的資料完整性、連結、Domain 統計與 Legend packet 檢查。
5. 對 63 項 overlay 的 `old_text` 做衍生文件殘留檢查，並逐一抽查有命中的卡文。
6. 檢查跨文件的 ARC 合法性、日期、資料量與「完整／不會過期」等公開承諾是否一致。

### 2.3 限制

- 本報告不作著作權或法律意見；只判斷 repository 的公開敘述是否超過其證據。
- 不把社群文章當成官方規則；社群資料只能作 Tier 2 方法驗證。
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
| Markdown 相對連結 | PASS（有限） | 檢查 55 份 Markdown、89 個相對連結，0 broken；fragment anchor 本身未驗證 |
| Domain 統計 | PASS（可重跑） | `compute_domain_stats.py` 產生 949-card population 與六 Domain 表；這是新定義的 population，不應再稱舊 965 |
| Legend packet | PASS | 48 packets；每個 packet 正好 2 個 Champions；從 `%TEMP%` working directory 以絕對 script path 執行亦成功 |
| 官方 errata 數量 | PASS（結構）／PARTIAL（語意） | overlay 63/63；16 live-fetched、47 spot-checked；尚無 63 項 `new_text` 的自動語意 gate |
| Git 工作樹 | PASS | 複驗期間只修改本審計報告；`git diff --check` 無 whitespace error |

---

## 5. 發現與修復狀態

嚴重度：P0 會直接造成錯誤裁定或錯誤卡文；P1 會使合法性、可攜性、可重現性或公開承諾失真；P2 為文件一致性／維護風險。

| 編號 | 基線問題 | 目前狀態 | 判定 |
|---|---|---|---|
| F-01 | 來源權威模型把 Core／local snapshot 放在不當位置 | 已加入雙軸 precedence、FAQ、errata overlay 與 Head Judge 限制 | **Closed** |
| F-02 | Gameplay 多項錯誤流程 | 主要程序已依官方 PDF 重寫並補 Tournament procedure notes | **Closed** |
| F-03 | 63 項官方勘誤多數未套用 | overlay 已有 63 項，但 Rek'Sai／Void Burrower 仍有一處衍生舊卡文 | **P0 Partial** |
| F-04 | legality 缺 same-name、overnumbered、OPL、2v2 等維度 | 模型已補齊；多個摘要仍殘留 ARC legal-set 舊說法，日期也未同步 | **P1 Partial** |
| F-05 | 相對路徑依賴工作目錄 | 主要內部路徑改用 `${CLAUDE_SKILL_DIR}`；off-cwd smoke test 通過 | **Closed** |
| F-06 | raw harvester、CI、統計不可重現 | CI／scripts／citations 已加入；harvester 仍不公開，舊統計文字仍漂移 | **P1 Partial** |
| F-07 | 合規敘述把 policy 說成既成 permission | README 已揭露註冊待審與非官方 API gap | **Documentation Closed; operational open** |
| F-08 | 文件矛盾、壞路徑、過強成熟度語氣 | 路徑已修、連結通過；ARC／完整卡池／不會過期等矛盾仍在 | **P2 Partial** |

---

## 6. 詳細複驗結果

### F-01 — 來源權威模型：已關閉

`SKILL.md` 現在明列：

- competitive procedure：event addendum → Tournament Rules → Core Rules；
- game mechanics／card text：current FAQ → latest Core → errata-applied card text；
- ban list 與 card errata 必須做 freshness check，不能把 local snapshot 當永久真相；
- routine card lookup 可 local-first，但 overlay 缺漏或過期時要升級到 Rules Hub。

這已直接修正基線審計最核心的錯誤：不能只讀 Core Rules PDF，也不能把 live official lookup 寫成罕見例外。此部分可接受，但仍應在後續加入一個可機器檢查的「官方日期晚於 local snapshot 時失敗」gate。

### F-02 — Gameplay：已關閉

重新對照後，以下內容與官方條文一致：

- Core 431.2：Burn Out 先盡可能執行原動作，再 recycle trash、讓對手得 1 分，最後完成原動作；
- Core 310.1.a／308.1.a／806.1：Neutral Open 不等於只有 Action；Showdown 的 Action／Reaction 限制是另一層；
- Core 339.1、340.1：一輪全 pass 只結算最新 chain item，不會一次清空整條 chain；
- Tournament 503.9.b：放入 spell／ability 預設視為 pass，除非明示 retain priority；
- Core 344–348、464–466：Non-Combat Showdown、combat spell window、Might 計算、依序分配／同時造成 damage、No Result 與 cleanup 後 control；
- Core 117.1–117.3：set aside → draw replacement → recycle 的 mulligan 順序；
- Tournament 401.5：open decklist 是 Head Judge 的賽事政策，且只能在 match 開始／局間查看，不能 gameplay 中查看。

目前沒有在 Gameplay 主文中再找到基線列出的那批程序錯誤。這個結論只代表規則文字已校正，不代表每一張卡的互動都已完成 FAQ 級驗證。

### F-03 — 官方 errata：仍是 P0，尚未關閉

`skill/data/errata_overlay.json` 現在有四份官方文件、63 entries，結構檢查通過。原始 JSON 保持為未修改的 RiftCodex snapshot，overlay 作為修正層，這個設計是正確的。

但複驗以 overlay 的 `old_text` 對 `skill/references/**/*.md` 做殘留搜尋，仍命中：

```text
skill/references/deckbuilding/references/legends/reksai.md:5
Legend ability: When you conquer, you may exhaust me to reveal the top 2 cards of your Main Deck. You may play one. Then recycle the rest.
```

官方 Spiritforged errata 的 `Void Burrower` 新文字是：`You may banish one, then play it. Recycle the rest.` 這不是純排版差異，而是把卡片移入／移出牌庫的區域改變，會改變牌局結果。該檔案的標註也只說 Swarm Queen 已修正，沒有處理同一頁上的 Legend ability。

此外，overlay 的 47 個 spot-checked entry 並非 47 個都在本次 session 逐一 live-fetch；目前資料本身已誠實揭露這點，但不能把它等同於 63/63 官方頁面逐項重驗。

**必要修復：**

1. 修正 `reksai.md` 的 Void Burrower Legend ability，並重新檢查其後的分析是否依賴「play one」的舊語意。
2. 在 CI 增加 overlay→derived Markdown 的殘留檢查；至少要求每個被引用的 `official_name` 不得再含 `old_text`，或附可審核的人工豁免。
3. 把 63 項的 live／spot-checked 範圍、人工豁免與最後驗證日期放入機器可讀欄位。

### F-04 — 合法性模型：核心已修，文件仍矛盾

本次確認模型已補上 Tournament Rules 601.2–601.3 的主要維度：

- format（1v1／2v2 與不同 ban list）；
- region、event date、official launch date；
- same-name reprint（601.2.a）；
- overnumbered reprint（601.2.c）；
- ban list、OPL 與 low-OPL exact preconstructed exception（601.2.d.2）；
- sideboard 上限 10 張與 Main Deck + sideboard copy limit（601.1.c）；
- event addendum。

但跨文件複驗仍找到三個殘留：

1. `skill/references/deckbuilding/deckbuilding.md` front matter 的 Summary 仍寫 Taiwan `OGN + OGS + ARC`。
2. 同檔 Environment 摘要仍寫 `Taiwan — ... OGN + OGS + ARC only`。
3. `skill/references/deckbuilding/references/regional-legality-model.md` Global Standard 範例仍列 `OGN, OGS, ARC, SFD, UNL, VEN`，但官方 Tournament Rules 601.3.c 的現行清單只有 OGS、OGN、SFD、UNL、VEN；ARC 只能透過 same-name rule 取得合法性，不能被列為 Standard set。

另有日期問題：Taiwan 段落仍標 `last verification 2026-07-19`，但同一 repository 內容已寫 Taiwan OGN 於 2026-08-07 發售；這是明顯的 snapshot 時序矛盾。

**必要修復：** 統一所有摘要與 worked example 的 ARC 說法，將「legal set」與「ARC same-name printing」分開；同步更新 Taiwan／Global 的 `last-verified` 與資料來源。

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
- `compute_domain_stats.py` 現在明確重算 949-card population，但 `deckbuilding.md` 的 x-source 仍提到舊的 965-card analysis；
- `verification-log.md` 仍明載 46 個 catalogue entries 中 43 個未 Tier-2 verified，Annie 的非 Battlefield supporting-card substitution 也仍是 open item；
- CI 驗證 schema／可執行性，不驗證卡文語意、官方頁面 freshness 或每個 derived file 是否跟 overlay 同步。

因此本項由基線 4/10 提升，但尚不能稱「完全自包含、可完整重建」。

### F-07 — 合規：文件修復完成，實際狀態仍開放

README 與 data README 已正確做到：

- 加入指定 Legal Jibber Jabber；
- 明確說明 product registration 仍 pending、pending 不等於 approval；
- 明確說明資料來自非官方 RiftCodex，而 Riot policy 要求 Riftbound assets 來自 Riot API；
- 不再把 approved use case 推導成此 repository 已獲個別核准；
- 不再使用「that's permission to use it」這類過度結論。

這是文件層面的關閉。但從政策條件來看，產品註冊尚未確認、card data source 仍不是 Riot API；所以公開產品仍不能宣稱已完成合規或已獲 Riot 授權。這不是 repository 內文案可自行解決的技術問題。

### F-08 — 文件一致性：部分關閉

`check_links.py` 已找到 89 個相對連結且 0 broken，先前的壞路徑問題已改善。但該檢查不解析 fragment anchors，也不做語意一致性。

以下成熟度／覆蓋語氣仍應降調：

- README 的 `battle-tested`；
- README／Legend index 的「derived from primary text, so it can't go stale」；
- `SKILL.md` 與 README 對「every card across every set」的語氣，與 data README 明列「不含 RAD、ARC、FND」不完全一致；
- regional legality 的 ARC 與日期矛盾（已列於 F-04）。

這些不是單純文風問題：在規則型 skill 中，讀者會把「不會過期／every card」理解成 freshness guarantee，與 raw snapshot、errata overlay、43/46 未驗證的實際狀態不相稱。

---

## 7. 修復後評分

| 面向 | 分數 | 複驗判定 |
|---|---:|---|
| 產品定位與知識架構 | 8/10 | 分書、薄路由與 Tier 分層仍是強項，但成熟度語氣偏強 |
| 規則權威治理 | 8/10 | precedence 已正確寫入，尚缺自動 freshness gate |
| Gameplay 規則正確性 | 8/10 | 基線錯誤已逐項修復並對到 PDF；卡片互動仍需 FAQ 級查證 |
| 卡牌資料新鮮度 | 5/10 | 63 項 overlay 已建立，但有 Rek'Sai 衍生舊文，47 項非逐項 live-fetched |
| 區域與賽制合法性 | 6/10 | dimensions 已補齊，但 ARC 與日期矛盾仍會造成錯答 |
| Skill 可攜性 | 8/10 | `${CLAUDE_SKILL_DIR}` 路徑與 off-cwd smoke test 通過 |
| 可重現性與驗證 | 6/10 | CI／scripts 已存在；raw harvest 與 semantic freshness gate 仍缺 |
| 公開合規準備度 | 5/10 | 文件誠實，註冊與資料來源條件尚未解決 |
| **整體** | **6/10** | **研究／教育型知識庫可用；競賽權威發布尚未通過** |

---

## 8. 必要修復順序

### P0 — 發布前必做

1. 修正 `reksai.md` 的 Void Burrower 舊卡文。
2. 增加 errata overlay 對衍生 Markdown 的語意／舊文字殘留檢查。
3. 對 overlay 的 63 項 entry 建立可審核的 live／spot-checked／豁免狀態，不能只驗 JSON schema。

### P1 — 讓合法性與重現性可信

1. 清除所有 `OGN + OGS + ARC` 與 Global `..., ARC, ...` 的 legal-set 摘要；保留 ARC 但只放在 same-name reprint 說明。
2. 更新 Taiwan／Global 的 `last-verified` 與官方來源日期。
3. 將舊 965 統計改成 949，或附明確的 historical population label，避免讀者把兩者當同一張表。
4. 公開 raw harvester、輸入 snapshot checksum 與產出版本，或正式撤回「clean clone 可完整重建」的承諾。
5. 加入 official source date／errata freshness gate。

### P2 — 提升長期維護品質

1. 增加 Markdown fragment anchor checker。
2. 把 `battle-tested`、`can't go stale`、`every card across every set` 改為與現有證據一致的限定說法。
3. 完成剩餘 43/46 Legend 的 Tier-2 verification，並把 open substitution item 分開追蹤。

---

## 9. 驗收清單

- [ ] `reksai.md` 不再含 Void Burrower 的 errata 前文字。
- [ ] 63/63 errata 有 `new_text`、來源頁、驗證狀態與最後驗證日期；衍生檔沒有未豁免的 `old_text`。
- [ ] `SKILL.md` 保留 event addendum → Tournament Rules → Core Rules 的競賽優先級。
- [ ] Gameplay 的 Burn Out、chain、Showdown、combat、mulligan 與 Tournament notes 通過條文對照。
- [ ] 所有合法性摘要只列 OGS、OGN、SFD、UNL、VEN 為現行 Standard set；ARC 僅以 same-name reprint 規則描述。
- [ ] 1v1／2v2 ban list、regional launch、same-name、overnumbered、OPL 與 sideboard assertion tests 存在。
- [ ] Taiwan／Global snapshot 日期與官方 release／ban／FAQ 日期一致。
- [ ] raw data 更新方式可由 clean clone 重建，或文件清楚標為不可重建 snapshot。
- [ ] 949 Domain population 與所有引用數字一致。
- [ ] CI 同時覆蓋 schema、links、anchors、extractor、errata semantic residue 與 freshness。
- [ ] README 不宣稱已獲 Riot 個別授權或已完成產品註冊。

---

## 10. 官方來源

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

---

## 11. 最終意見

這次修復已把專案從「規則來源與 Gameplay 不能安全引用」提升到「方法清楚、主要流程可核對、可作研究／教育使用」的狀態。最值得肯定的是，它已接受原本的 Core-only 錯誤，改成明確的 Tournament precedence 與 FAQ／errata 分層；這正是 Riftbound 這類 live rules system 必須有的設計。

但複驗仍不能給出通過結論：一處已知的 Rek'Sai 舊卡文足以阻止「卡文已完整套用」的宣稱；ARC 與日期矛盾足以阻止「合法性模型已一致」的宣稱；raw harvester、semantic errata gate 與 Riot 實際註冊／API 條件仍未完成。

因此目前最準確的公開定位是：**具備正確競賽規則優先級的社群研究型 Riftbound 知識庫；回答競賽裁定、當前卡文或合法性問題時，仍須查閱適用的 Riot 官方來源與 Head Judge。**
