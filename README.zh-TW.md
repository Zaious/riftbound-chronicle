# Riftbound Chronicle

一套以證據為核心的 Riftbound AI Skill，協助玩家組牌、理解牌組打法，以及用實體牌進行對練。

[English](README.md) · [한국어](README.ko.md)

## 為什麼要這樣做

不做這一整套，語言模型一樣「判斷」得出來——只是那是基於文字接龍的粗略判斷，不等於合法性。它會讀了反應牌的字面，就以為可以在法術對決的最後插進連鎖去加攻，因為讀起來很順；但那不是一個合法的動作。

所以機械的部分交給程式。什麼時候能打什麼、什麼能被回應、優先權怎麼傳，還有現在的分數、費用、戰力這些數字——這些都是規則化與算術的東西，交給模型發揮只會飄移。就算是最強的語言模型，沒有東西幫它檢查數字，還是會說 8.11 比 8.9 大。

模型接著只在程式已經框好的空間裡推理，外部拘束跟真實規則一樣。這就是整個設計的重點：**不是把規則翻譯成程式讓模型看懂，而是限制模型能得出什麼結論。**

目前程式擁有的是*時機與權限*這一層。完整合法性仍然由人確認（見下面的 P2-A 邊界），而且自動規則裁決在 Riot 政策下本來就還沒被核准。合法行動列舉是規劃中的版本，卡在 conformance 覆蓋率過關與否，而不是卡在要先蒐集多少對局紀錄。

## 體系

| 體系 | 用途 | 權限邊界 | 可執行產物 |
| --- | --- | --- | --- |
| `deck-coach` | 牌組分析、構築方向與八段式操作指南 | 只提供建議，不發布勝率或 Tier | profile、mask、primer、evaluation、A/B battle |
| `rule-consult` | 以日期與來源解釋規則和互動 | 非官方諮詢，不改變遊戲狀態，也不取代主審 | consultation record、evidence ledger |
| `player2-agent` | 實體雙牌對練時提出二號玩家策略建議 | 玩家掌握隱藏資訊、合法性、結算與狀態更新 | P2-A session ledger |

### 引擎接通狀態

一個體系只有在 checklist 的六個條件全部通過時才算接通：artifact 接受封裝、runner 能產出、validator 拒絕超額宣稱、UI 呈現各種結果、回歸測試涵蓋支援與棄權兩種案例、權威邊界在消費檢查後仍然成立。`skill/scripts/check_readme_connection_claims.py` 會從 artifact 推導這張表，表格與推導結果不一致時，多說少說都會失敗。

| 體系 | 狀態 | 條件 |
| --- | --- | ---: |
| `rule-consult` → `engine-check.v1` | `connected` | 6 / 6 |
| `player2-agent` → `engine-check.v1` | `connected` | 6 / 6 |
| `deck-coach` → `engine-check.v1` | `connected` | 6 / 6 |
| `match-analyst` → `engine-check.v1` | `planned` | 0 / 6 |

Deck Coach 只把這個封裝當規則一致性證據消費（ADR-0006）：附加檢查不改變診斷或入門指南，也不自行產生檢查；Match Analyst 已有規格與 fixture，尚未路由。

目前 Player 2 只有 **P2-A**：代理提出並解釋行動，玩家確認合法性並手動完成結算。P2-S 自動模擬器只有規劃文件，尚未實作。

四個體系共用一層由 **Chronicle 自主掌控的規則核心**，而它只宣稱 conformance 套件真的跑得過的東西：

- 時機與權限核心：四種回合狀態、Action／Reaction、Priority／Focus、HOT／FEPR —— 21 個可執行案例（`skill/data/rules_core_cases.json`）；
- 有界的 typed effect IR：19 種操作，加上序列、目標、連動效果、致死清理與觸發發射；遇到沒有建模的卡牌行為**直接 fail closed**，不猜；
- 兩者之間的原子橋接：時機判斷與它的 typed effect 要嘛一起提交，要嘛一起回滾。

它不依賴其他玩家模擬器，也不宣稱已能結算所有卡牌效果——`unsupported` 是第一級的結果，不是錯誤路徑。架構與吸收邊界見[主權規則層](docs/architecture/SOVEREIGN_RULES_LAYER.md)；兩份審計都建議不要做規則引擎、為何仍然做了，見 [ADR-0001](docs/decisions/ADR-0001-sovereign-rules-layer.md)。

第四個體系 `match-analyst`（賽後單一時間軸上的 Review 與 Commentary 兩種投影）規格已完整，但**刻意還沒接進 router**，要等 activation gate 全過——見[規格](docs/match-analyst/MATCH_ANALYST_PRODUCT_SPEC.md)。上面表格列的是 Skill router 今天真的提供的東西。

**四個體系都在備賽階段,沒有一個代替你打牌。**構築、規則、練習、檢討——遊戲本身是人在別的地方玩的。這也是為什麼一個權威規則引擎(包括官方線上版,如果哪天出了)會**增強**這四個體系而不是取代它們:那種引擎服務的是對局,這裡服務的是備賽。

本專案是協助玩家備賽的助理,基於研究與教育目的。**於賽事中使用違反相關規則**——條文見[合規邊界](docs/policy/RIOT_COMPLIANCE_BOUNDARY.md)。

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
python skill/scripts/bootstrap_rules.py --include-supplemental-en --yes
python skill/scripts/bootstrap_rules.py --include-zh-cn --yes
python skill/scripts/rules_index.py build
python skill/scripts/rules_index.py search "連鎖 結算"
```

預設下載英文 Core Rules 與 Tournament Rules；`--include-supplemental-en` 加入英文勘誤及已標為歷史資料的 Origins FAQ HTML 快照；`--include-zh-cn` 另裝簡中規則、禁限卡、FAQ、勘誤與分級標示的裁判資料。檔案、SHA-256 lock 與索引都留在 Git ignored 的 `skill/.local/rules/`。查詢結果不是自動裁定；翻譯衝突時英文優先，已被取代的來源預設不會出現在現行查詢。

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

改動規則層之前值得先讀的設計理據:[ADR-0001](docs/decisions/ADR-0001-sovereign-rules-layer.md)(為何在兩份審計建議不要做規則引擎之後仍然做了,以及它**不**主張什麼)、[RELATED_WORK](docs/architecture/RELATED_WORK.md)(與已發表工作的相對位置)、[ITERATION_INPUTS](docs/research/ITERATION_INPUTS.md)(該改變下一步做什麼的研究)。

來源優先順序為：目前官方規則／賽事文件／勘誤／禁卡表、官方卡牌文字、可靠社群材料、明示推論，最後是未知。隨 repo 附帶的卡牌 snapshot 來自非官方 RiftCodex API，包含 1,451 rows、1,304 個 unique card IDs；請先閱讀 [資料來源與限制](skill/data/README.md)。

跑完所有確定性關卡，跟 CI 一樣。這個迴圈直接掃描磁碟上的檢查腳本，所以不會像手抄清單那樣過期（先前的手抄版本就漏了四道，包含規則核心那幾道）：

```powershell
Get-ChildItem skill/scripts/check_*.py | ForEach-Object {
  python $_.FullName
  if ($LASTEXITCODE -ne 0) { Write-Error "FAILED: $($_.Name)" }
}
```

實際在 push 時跑哪些，以 `.github/workflows/ci.yml` 為準；CI 另外會從 repo 以外的目錄再跑一次，證明這些腳本不依賴當前工作目錄。

## 合規與授權

本專案不發布或保存勝率、使用率、對局率或 Tier 排名，不聲稱官方主審權威，也不自動化 Riftbound 對局。Riot product registration 與官方 API 卡牌來源目前仍是開放問題。

原創程式碼與方法論採 [MIT](LICENSE)。卡名、規則文字與其他 Riot-owned material 不在此授權內。

> Riftbound Chronicle was created under Riot Games' “Legal Jibber Jabber” policy using assets owned by Riot Games. Riot Games does not endorse or sponsor this project.

Riftbound Chronicle 是非官方 fan project，與 Riot Games 無隸屬關係。
