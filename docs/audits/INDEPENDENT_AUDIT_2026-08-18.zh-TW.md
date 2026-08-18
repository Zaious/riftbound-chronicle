# Riftbound Chronicle 獨立審計報告（更新後重新複驗）

**複驗日期：** 2026-08-18（Asia/Taipei）  
**審計對象：** riftbound-chronicle  
**目前版本：** ea0c583（main）  
**前次審計基線：** 8e0b4dd（2026-08-17 初始審計）  
**前次重評版本：** 1751c7d  
**審計性質：** 唯讀複驗、規則來源校對、資料／CI／文件一致性審計  
**產品定位基準：** 組牌助手＋Gameplay 助手＋足以支撐建議的基礎遊戲知識；不負責 Judge 級細節裁定

---

## 1. 結論先行

這一波更新不是單純補文件，而是完成了三個核心產品修正：

1. Router 明確定位為策略助手，而不是規則裁判。
2. Gameplay 書新增固定的八段式 deck primer，能把一副完成牌組轉成可練習的操作指南。
3. Deckbuilding 書新增八種 functional roles，推薦卡不再只靠熱門度或卡名堆疊，而是回到它在核心循環中的工作。

因此，依照正確的產品定位，本 repository 的**產品能力評分為 8/10**：已能支撐組牌方向、牌組診斷、基礎 Gameplay 與完成牌組教學的輸出。

但是目前不能直接判定為「工程發布完成」，原因有一個新的 P1：

- 新版 extractor 正確保留額外 Champion print 後，輸出 48 個 Legend packets，其中 9 個不是恰好兩張 Champion；CI workflow 仍硬性要求所有 packet 恰好兩張，因此當前 smoke test 會失敗。

其他仍開放但不是產品定位阻擋項的風險：

- raw harvester 仍未公開，clean clone 不能重建相同 snapshot。
- 46 個 Legend 已全部完成 Tier 2 檢查，但目前真正維持「完全確認」的是 Ivern、Leona、Nasus 三個；Jayce 的初次確認已被 follow-up 重新打開。
- README、Legend index、verification log 對「完全確認數」仍有 3／4 的敘述矛盾。
- Riot 註冊仍待審，卡牌資料仍來自非官方 RiftCodex，而不是 Riot API。

**發布判定：Conditional。**  
產品內容已可作為組牌／Gameplay 助手；修正 CI irregular-packet assertion 與統計敘述後，才適合把 main 標成通過工程驗收。

---

## 2. 本次更新範圍

相較前次重評版本 1751c7d，本次 main 新增或修正：

| 提交 | 更新內容 | 審計影響 |
|---|---|---|
| 59bf1f5 | 明確揭露 raw snapshot 不可從 clean clone 重建，以及 takedown 政策 | 誠實度提升；可重現性仍部分開放 |
| 2d287d7 | 修正過強承諾、舊引用與 link checker | 文件風險下降 |
| 5ab7928 | 修正 extractor 以 Domain collapse 靜默丟失額外 Champion 的 bug | 資料正確性提升，但改變了 CI 預期形狀 |
| 11f0ef8 | 追驗 Draven、Jayce、Master Yi、Rengar、Vi | 八個受影響 Legend 的 follow-up 證據補齊 |
| c386fe7 | Gameplay 新增固定八段式 deck primer 與 Nasus 範例 | 完成牌組教學從方法變成固定交付物 |
| b851402 | Router 與 Gameplay 明定 strategy advisor、非 rules judge | 產品邊界大幅對齊 |
| ea0c583 | 新增八種卡牌 functional roles | 構築建議更可解釋、可做替代牌 |

本次納入檢查：

- README、SKILL router、deckbuilding、gameplay、regional legality、Legend index 與 verification log。
- raw card snapshot、errata overlay 與資料說明。
- scripts、GitHub Actions、Markdown 相對連結與 fragment anchors。
- 2026-07-16 官方 Core Rules／Tournament Rules、Rules Hub、FAQ／errata／ban-list。
- 其他遊戲的公開 AI Skill 對標：MTG、Pokémon TCG Pocket、ScryChat、MagicAI、Flesh and Blood 工具。

---

## 3. 複驗方法與限制

### 3.1 執行的本地檢查

| 檢查 | 結果 |
|---|---|
| check_links.py | PASS：55 份 Markdown、58 個相對連結、2 個 fragment anchors，0 broken |
| check_data_integrity.py | PASS：1451 rows、1304 unique IDs、147 duplicate groups；4 documents／63 entries；0 old_text residue |
| errata freshness | PASS：last_verified 2026-08-17，距今 1 天，低於 90 天 gate |
| compute_domain_stats.py | PASS：可重跑 949-card deduplicated population |
| extract_legend_packets.py | 執行成功但輸出 9 個 irregular packets；CI 的「全部恰好兩張」assertion FAIL |
| Python compileall | PASS |
| git diff --check | 無 whitespace error；僅有 CRLF 轉換警告 |

### 3.2 限制

- 本報告不是法律意見，也不是 Riot 註冊或政策核准判定。
- 社群來源只能用作 Tier 2 實戰交叉驗證，不取代官方規則。
- 外部規則、ban list、產品註冊與資料來源政策會變動；報告基準日為 2026-08-18。
- Tier 2「已檢查」不等於「策略已被證明為最佳答案」；每條結論仍須保留 CONFIRMED、PARTIAL、NOT_CONFIRMED 或 Tier 3 狀態。

---

## 4. 規則權威與產品邊界

### 4.1 規則權威模型

目前 SKILL router 的兩條 authority axis 是正確的：

**競賽程序：**

1. 該賽事的 event addendum。
2. Tournament Rules。
3. Core Rules 中未被競賽文件修改的部分。
4. 實際賽事 Head Judge。

**遊戲機制與卡文：**

1. 最新且適用範圍明確的官方 FAQ／clarification。
2. 最新 Core Rules。
3. 套用官方 errata 後的卡文。

Rules Hub 目前把 Core Rules 與 Tournament Rules 都標為 2026-07-16 版本；Tournament Rules update 另明確處理 sideboard 10 張、trigger acknowledgement、resource tracking 與 Vendetta legal set。這支持「比賽版本高於 Core」的原則，不支持把 Core PDF 當成所有問題的唯一答案。

### 4.2 定位是否已對齊

目前已能直接回答：

- 這副牌的構築方向與核心循環。
- 卡牌在牌組中的功能角色與替代方向。
- 起手、前中後期、進攻／保留 Battlefield、資源保留。
- 一副完成牌組如何產出固定格式的 deck primer。
- 足以理解上述建議的 chain、priority、Showdown、combat、mulligan 基礎背景。

目前已明確降級為「背景＋最可能解讀＋轉介」：

- 某次已發生的爭議互動誰對誰錯。
- Tournament penalty、Head Judge procedure。
- 需要裁判作最終權威的細節判定。

這是本次最重要的產品修復。Gameplay 書仍保留 Tournament procedure notes，但已標明它們是背景與流程護欄，不是本 Skill 的裁定承諾。

---

## 5. 內容與研究品質

### 5.1 Deckbuilding

目前 deckbuilding 書已形成完整的構築方法：

- Legend-first，而不是先堆強牌。
- Domain、Legend、Champion、曲線、符文與合法池分開推理。
- 禁卡／未在該地區發售的卡使用「同一工作角色」替代，而非只找相同費用。
- 新增八種角色：Core engine、Battlefield presence、Mobility、Showdown interaction、Resource/economy、Protection、Closer、Flex/replacement。
- 明確禁止把其他遊戲的固定 quota 或 role score 搬成 Riftbound 的假精確數字。

這使構築建議能回答「這張牌在這副牌做什麼」，也讓未來的 ban substitution 與 collection-aware alternatives 有穩定接口。

剩餘缺口是：角色 taxonomy 目前是方法層文字，還沒有自動化的角色覆蓋診斷或每張推薦卡的機器可驗證 role 欄位。

### 5.2 Gameplay 與 deck primer

Gameplay 書目前的八段式輸出：

1. Identity
2. Core loop
3. Mulligan targets
4. Turn-by-turn priorities
5. When to fight, when to hold
6. 2–4 common lines
7. 3–5 common mistakes
8. Evidence ledger

Nasus 範例刻意把沒有 Tier 2 證據的區段標成 Tier 3，而不是臨場補出看似合理的細節。這是正確的研究紀律，也符合本產品要教玩家「怎麼操作」而不是假裝掌握每一副牌的最佳線。

目前仍有兩個品質限制：

- 只有一份完整 worked example，尚未有跨 Aggro、Control、Tempo、Combo 等多類型的 primer 回歸樣本。
- 沒有自動化 golden prompts，尚未能在 CI 檢查「只問怎麼玩時不偷偷改牌」或「問細節裁定時有清楚轉介」。

### 5.3 Legend Tier 2 研究

目前 46/46 Legend entries 都有 Tier 2 檢查。這代表覆蓋完成，不代表內容一致被證明：

- 目前完全 CONFIRMED：Ivern、Leona、Nasus。
- Jayce 初次通過，但因額外 Champion print Man of Progress 的 follow-up 而重新變成未定案。
- 其餘條目依各自 row 標示 PARTIALLY CONFIRMED、NOT CONFIRMED 或低信心。

新的 extractor 已修正「同 Domain 額外 Champion 被靜默丟失」的根本 bug。它目前保留 8 個真正額外 Champion print，並對 Kennen 的 Yordle tag mispair 發出警告。這是研究資料正確性的提升，但下游 CI 尚未接受新的資料形狀。

---

## 6. 發現與狀態

嚴重度定義：P0 會直接導致核心錯誤；P1 會阻擋可信發布或造成系統性誤導；P2 是文件、測試或長期維護風險。

| 編號 | 發現 | 目前判定 | 後續 |
|---|---|---|---|
| F-01 | Core／Tournament／FAQ／errata precedence | Closed | 保持 freshness routing |
| F-02 | Gameplay 基礎流程與官方條文不一致 | Closed | 不再擴張成 Judge engine |
| F-03 | 63 項 errata 套用與正文殘留 | Closed | 63/63 overlay、0 residue；持續逐波更新 |
| F-04 | Taiwan／Global／ARC／same-name／2v2 legality | Mostly closed | P2：保持日期與 live ban list 分離 |
| F-05 | 相對路徑與 off-cwd portability | Closed | 將 off-cwd smoke test 固定進 CI |
| F-06 | raw snapshot 無公開 harvester | P1 Partial | 接受 snapshot 限制，或公開可重建 pipeline |
| F-07 | Riot registration 與非官方資料來源 | Operational open | 不能宣稱已核准；需轉 Riot API 或取得政策處理 |
| F-08 | 3／4 完全確認數與方法文件矛盾 | P2 Partial | 統一為目前 3 個；另註 Jayce 初次確認已 reopened |
| F-09 | Tier 2 46/46 覆蓋 | Research complete, confidence provisional | 輸出必須保留 entry-level status |
| F-10 | 組牌＋Gameplay 助手定位 | Closed with P2 quality gate | 加 golden prompt／多 archetype primer 回歸 |
| F-11 | extractor 新資料形狀與 CI assertion 不一致 | P1 Open | 修正 CI：接受 48 packets、8 genuine extra prints 與 Kennen caveat，不能 assert all exactly 2 |

---

## 7. 新的主要 P1：CI smoke test 回歸

目前 extractor 的實際結果：

- 48 packets：包含 deckbuilding 書的 Kai'Sa、Annie canonical examples，以及 catalog 的 46 Legends。
- 39 packets 有恰好兩張 Champion。
- 8 個 Legend 保留真正的額外 Champion print。
- 1 個 Kennen/Yordle packet 仍有 7 張 tag-matched candidates，雖然 Domain filter 已發出警告，並非應直接當成合法 Champion pool。

但 .github/workflows/ci.yml 仍執行：

    irregular = [p for p in packets if len(p["champions"]) != 2]
    assert not irregular

因此，當前 main 的本地資料腳本可以成功產出結果，但 CI smoke test 會失敗。正確修法不是把額外 Champion 再刪掉，而是把 CI assertion 改成：

1. 至少有 48 packets，或明確以 roster manifest 驗證 48。
2. 允許已列入白名單的 8 個 genuine extra-print Legends。
3. Kennen/Yordle packet 必須維持 warning 或從生成 roster 中明確排除。
4. 對每個 catalog Legend 驗證其下游 markdown 是否已處理該 packet 的 irregular 狀態。

在此修復前，CI 狀態應標為 red，而不是「所有驗證通過」。

---

## 8. 重新評分

| 面向 | 分數 | 判定 |
|---|---:|---|
| 產品定位與 router | 9/10 | 已清楚分離組牌、Gameplay、基礎背景與裁定轉介 |
| 規則權威治理 | 8/10 | Tournament 高於 Core、FAQ／errata 分層正確 |
| 組牌方法與角色推理 | 9/10 | Legend-first＋八角色＋替代工作流完整；尚無自動 role evaluator |
| Gameplay 基礎知識 | 8/10 | 足以支撐策略建議；不應承諾細節裁定 |
| 完成牌組 Gameplay primer | 8/10 | 固定八段式已落地；目前只有一份完整示範 |
| 卡牌資料新鮮度 | 7/10 | 63 overlay、freshness／residue gate 通過；47 項仍是 spot-checked |
| 區域／賽制合法性 | 8/10 | 維度齊全；仍須 live ban／release date |
| Skill 可攜性 | 9/10 | skill folder 自包含、CLAUDE_SKILL_DIR 路徑與 script 可移植 |
| 可重現性與 CI | 6/10 | scripts 可跑，但 raw harvester 未公開且 CI assertion 現在失敗 |
| Tier 2 研究可信度 | 7/10 | 46/46 覆蓋透明；僅 3 個完全確認，不能包裝成最佳攻略 |
| 公開合規準備度 | 5/10 | 註冊未核准、資料來源非 Riot API |
| **整體產品評分** | **8/10** | **內容可用；工程發布需先修 CI 與統計文件** |

---

## 9. 對標 Skill 的更新後評價

### 9.1 已直接借鑒並落地

- **MTG deck-strat：** 固定完成牌組 strategy guide 的概念，已轉成 Riftbound 八段式 deck primer。
- **MTG deck-wizard → deck-strat：** 組牌方向與完成牌組駕駛指南分成兩個階段。
- **PTCGP Domain Skill：** legality／facts 與 advice／uncertainty 分離。
- **ScryChat：** functional-role-first 已轉成 Riftbound 八角色 taxonomy。
- **PokeClaude：** Router 已朝 deck build、deck review、card explanation、deck pilot 四個入口分化。

### 9.2 可以延後借鑒

- MTG skeleton／quota 改成 Riftbound role-coverage warning，但不搬固定數字。
- self-grill 改成 strategy critic，檢查 primer 是否前後矛盾。
- MagicAI 的 source gateway 與 safe uncertainty。
- PokeClaude 的 qualitative synergy／counter plan。
- 有玩家卡冊後才做 alternatives 與 deck-to-collection gap。

### 9.3 不應借鑒

- MTG rules-lawyer 或 Judge replacement。
- Tier、勝率、使用率、matchup differential。
- 自動對局模擬、勝負結算與保證式 keep／mulligan。
- 尚未有固定輸出契約前，先擴張完整 MCP／live scraper。

這個方向與 [MTG Skills](https://github.com/dan-blanchard/mtg-skills)、[PTCGP Domain Skill](https://github.com/axross/ptcgp-deck-builder/blob/main/.claude/skills/ptcgp-domain/SKILL.md)、[PokeClaude](https://github.com/briansunter/pokeclaude)、[ScryChat](https://github.com/cybermelons/scrychat) 的公開架構對照一致；Flesh and Blood 目前找到的 [Goagain](https://api.goagain.dev/) 仍偏卡牌資料／legality API，而不是成熟的 Gameplay coach。

---

## 10. 修復優先順序

### P1：發布前

1. 修正 CI 的 irregular Champion packet assertion，建立白名單與 Kennen caveat 檢查。
2. 修正 Legend index 與 verification log 的「4 個完全確認」敘述，統一為目前 3 個，並說明 Jayce 已被 follow-up reopened。
3. 在 CI 加入至少一組 deck primer golden prompt，檢查輸出八段式、Tier 標籤與裁定轉介。

### P2：品質與維護

1. 增加 Aggro、Control、Tempo、Combo 各一份 deck primer worked example。
2. 把八角色轉成可機器檢查的 recommendation metadata，先做 warning，不做假精確分數。
3. 讓 off-cwd extractor test 與 949 Domain population test 成為正式 CI assertion。
4. 補每個 Legend 的 legal-set metadata，避免 Tier 2 supporting card 在 Taiwan pool 中無聲失效。
5. raw harvester 若不公開，持續明確標示「可攜但不可由零重建」。

### 不排入近期

- Judge agent。
- 細節規則引擎。
- 勝率／Tier／matchup 模型。
- 自動化對局模擬。

---

## 11. 驗收清單

- [x] Tournament Rules 高於 Core Rules 的競賽 precedence。
- [x] FAQ／Core／errata 分成不同問題軸。
- [x] Gameplay 基礎流程與官方條文重新校對。
- [x] 63/63 errata overlay，衍生 Markdown old_text residue 為 0。
- [x] 相對連結與 fragment anchor 檢查。
- [x] 949-card Domain population 可重跑。
- [x] 46/46 Legend 完成 Tier 2 檢查。
- [x] Router 明確為 strategy advisor、非 rules judge。
- [x] 固定八段式完成牌組 deck primer。
- [x] 八種功能角色已納入 deckbuilding 方法。
- [ ] CI 接受新版 48-packet／irregular Champion 資料形狀。
- [ ] 3／4 完全確認數在 README、Legend index、verification log 統一。
- [ ] raw card harvester 可公開重建，或維持不可重建 snapshot 的明確承諾。
- [ ] 多 archetype primer 與 golden prompt regression。
- [ ] Riot registration 與 Riot API card-source condition。

---

## 12. 來源

### 官方 Riftbound

1. [Riftbound Rules Hub](https://playriftbound.com/en-us/rules-hub/)
2. [Riftbound Tournament Rules — 2026-07-16](https://cmsassets.rgpub.io/sanity/files/dsfx7636/news_live/503da65669ced10598d62925a6f6bc15111af726.pdf)
3. [Riftbound Core Rules — 2026-07-16](https://cmsassets.rgpub.io/sanity/files/dsfx7636/news_live/e9ac8e3d33e0f78cef296f5945aba7bc1313b086.pdf)
4. [July 2026 Tournament Rules Update & Changelog](https://playriftbound.com/en-us/news/announcements/july-2026-tournament-rules-update-changelog/)
5. [Riot Riftbound Developer API Policy](https://developer.riotgames.com/policies/riftbound)

### 對標 Skill／Agent

1. [MTG Skills](https://github.com/dan-blanchard/mtg-skills)
2. [MTG deck-strat](https://raw.githubusercontent.com/dan-blanchard/mtg-skills/main/deck-strat/SKILL.md)
3. [PTCGP Domain Skill](https://github.com/axross/ptcgp-deck-builder/blob/main/.claude/skills/ptcgp-domain/SKILL.md)
4. [PokeClaude](https://github.com/briansunter/pokeclaude)
5. [ScryChat](https://github.com/cybermelons/scrychat)
6. [MagicAI](https://github.com/Fartis/MagicAI)
7. [Goagain](https://api.goagain.dev/)

---

## 13. 最終意見

更新後的 Riftbound Chronicle 已不再是「規則很多的卡牌資料夾」，而是具備清楚產品契約的組牌與 Gameplay 助手：

- 組牌書回答為什麼這樣組、每張牌在核心循環中做什麼。
- Gameplay 書回答拿到成品後怎麼起手、怎麼安排節奏、何時爭 Battlefield、何時保留資源。
- 基礎規則只服務於上述決策。
- 細節爭議保留不確定性，交給官方來源或 Head Judge。

這個方向已經成立，且本次更新把前次建議的主要產品形狀真正落地。現在最大的阻擋不是內容方向，而是工程治理：CI 必須接受真實的多 Champion 資料形狀，文件必須統一驗證統計，之後才是多 archetype primer 與 evaluator 的品質提升。

**最終判定：產品可用，工程發布 Conditional；修正 F-11 與 F-08 後，可進入下一輪內容品質迭代。**
