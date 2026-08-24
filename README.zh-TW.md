# Riftbound Chronicle

一套以證據為核心的 Riftbound AI Skill，協助玩家組牌、理解牌組打法，以及用實體牌進行對練。

[English](README.md) · [한국어](README.ko.md)

## 三個體系

| 體系 | 用途 | 權限邊界 | 可執行產物 |
| --- | --- | --- | --- |
| `deck-coach` | 牌組分析、構築方向與八段式操作指南 | 只提供建議，不發布勝率或 Tier | profile、mask、primer、evaluation、A/B battle |
| `rule-consult` | 以日期與來源解釋規則和互動 | 非官方諮詢，不改變遊戲狀態，也不取代主審 | consultation record、evidence ledger |
| `player2-agent` | 實體雙牌對練時提出二號玩家策略建議 | 玩家掌握隱藏資訊、合法性、結算與狀態更新 | P2-A session ledger |

目前 Player 2 只有 **P2-A**：代理提出並解釋行動，玩家確認合法性並手動完成結算。P2-S 自動模擬器只有規劃文件，尚未實作。

## 快速開始

需求：Git、Python 3.10 以上。展示頁不需要安裝套件或建置。

```powershell
git clone https://github.com/Zaious/riftbound-chronicle.git
cd riftbound-chronicle
python skill/scripts/deck_coach_pipeline.py run `
  --case-id DC-RNG-GLOBAL-001 `
  --output-dir deck-coach-output
```

直接用瀏覽器打開：

- [Deck Coach](prototype/deck-coach/index.html)
- [Rule Consult](prototype/rule-consult/index.html)
- [P2-A](prototype/p2a/index.html)

三頁共用 Ember & Aged Gold 視覺外殼，預設繁中，右上角 `EN` 可切換英文。頁面不呼叫模型、不保存瀏覽器資料，也不自動執行遊戲規則。

## Deck Coach 閉環

```text
decklist + environment + player level
  → structured deck profile
  → recommendation mask
  → eight-section primer
  → seven-dimension evaluation
  → optional blind A/B primer battle
```

profile 會記錄傳奇、賽制、地區牌池、Energy 曲線、Domain、Power、卡牌類型、八種職能、互動／抽牌／回收／移動密度、引擎候選、來源與信心水位。

mask 會排除未發售、禁用、不符合傳奇 Domain、玩家沒有、使用過時勘誤，以及環境不一致的候選牌。這是日期化快照，正式建議仍要重新查核官方合法性。

## Rift Atlas 牌組交接

repo 內有離線 bridge，可把使用者貼上的 Rift Atlas 牌表轉成 Deck Coach 的 input、profile、mask、八段式 primer scaffold 與 brief：

```powershell
python skill/scripts/riftatlas_bridge.py `
  --source-url https://riftatlas.com/decks/community/DECK_ID `
  --deck-file decklist.txt `
  --environment taiwan-set1-banned `
  --player-level new `
  --output-dir riftatlas-output
```

網址只作來源紀錄；bridge 不抓取 Rift Atlas、不呼叫私有 API，也不自動對戰。尚未被對方接受的合作提案與繁中化 sample 會留在本地，不放入公開 repo。

## Rule Consult 與規則書

Rule Consult 將玩家提供的事實、假設、規則依據、分析、信心與升級處理分開保存，並固定標示 `official_status: unofficial`、`state_effect: none`。

公開 repo 不放 Riot PDF。需要精確條文時執行：

```powershell
python skill/scripts/bootstrap_rules.py --yes
```

它會把 Core Rules 與 Tournament Rules 下載到 Git ignored 的 `skill/.local/rules/`，並寫入本機 SHA-256 lock。也可以使用 `RIFTBOUND_RULES_DIR` 或 `--rules-dir` 指定其他路徑。Skill 不會在回答問題時偷偷下載；檔案不存在就要求先 bootstrap 或提供目前官方來源。

競賽程序順序：

```text
event addendum > Tournament Rules > Core Rules 未被修改的部分 > 現場主審
```

## P2-A 邊界

```text
玩家確認可見狀態
  → 代理提出行動與理由
  → 玩家確認合法性
  → 玩家用實體牌結算並確認新狀態
```

P2-A 不會查看對手隱藏資訊、不會聲稱行動合法、不會推測結算後狀態，也不會洗牌、抽牌、推進階段、結算戰鬥、計分或判定勝者。

## 來源、資料與驗證

來源優先順序為：目前官方規則／賽事文件／勘誤／禁卡表、官方卡牌文字、可靠社群材料、明示推論，最後是未知。隨 repo 附帶的卡牌 snapshot 來自非官方 RiftCodex API，包含 1,451 rows、1,304 個 unique card IDs；請先閱讀 [資料來源與限制](skill/data/README.md)。

```powershell
python skill/scripts/check_data_integrity.py
python skill/scripts/check_links.py
python skill/scripts/check_deck_coach.py
python skill/scripts/check_deck_coach_prototype.py
python skill/scripts/check_rule_consult.py
python skill/scripts/check_rule_consult_prototype.py
python skill/scripts/check_p2a_protocol.py
python skill/scripts/check_p2a_prototype.py
python skill/scripts/check_prototype_ui.py
python skill/scripts/check_rules_bootstrap.py
```

## 合規與授權

本專案不發布或保存勝率、使用率、對局率或 Tier 排名，不聲稱官方主審權威，也不自動化 Riftbound 對局。Riot product registration 與官方 API 卡牌來源目前仍是開放問題。

原創程式碼與方法論採 [MIT](LICENSE)。卡名、規則文字與其他 Riot-owned material 不在此授權內。

> Riftbound Chronicle was created under Riot Games' “Legal Jibber Jabber” policy using assets owned by Riot Games. Riot Games does not endorse or sponsor this project.

Riftbound Chronicle 是非官方 fan project，與 Riot Games 無隸屬關係。
