# 廣東話 Reels Engine

用 AI 拍寫實嘅廣東話短劇 Reels。
Claude Code、Codex，或者任何 coding agent 都跑到。

AI 短劇通常睇落好假，原因係每個鏡頭都重新估過啲人同場景：個樣、件衫、架車，個個鏡頭都唔同。
呢套 engine 只得一個做法：**先鎖死，後開拍**。
人、衫、場景、道具、把聲，你逐樣審過、鎖死，之後每一格都要跟返。

## 成條流程

一個主 agent 做監製（Producer），同你傾、幫你落單、管錢。
另外有 4 個 subagent（分工嘅助手），各有各做：

| 角色 | 做咩 |
| --- | --- |
| 編劇 `screenwriter` | 故仔、廣東話對白 |
| 美術 `art` | 搵真實相、選角、鎖人樣、衫、場景、道具、把聲 |
| 導演 `director` | 分鏡、機位、每個鏡頭嘅定位畫面 |
| 場記 `qa` | 逐格對返鎖死咗嘅相，捉穿崩 |

```
① 故事關   同 agent 傾劇本 → 編劇寫對白            你批劇本 + 出圖預算
② 鎖定關   美術鎖人、衫、場景、道具、把聲          你逐樣批
③ 角度關   導演出每個鏡頭嘅定位畫面                你批角度 + 試片預算
   → 480p 試片，場記 QA 篩走穿崩嘅
④ 揀 take  你揀每段用邊個 take
⑤ 成片關   升 4K → 剪片、燒字幕 → 字卡、音效        你批成片
```

你未講 OK，下一關開唔到。
呢個係 code 強制嘅，唔係靠 agent 自律。

## 你要準備嘅嘢

1. **一個 coding agent**：Claude Code、Codex，或者其他都得。
2. **Python 3.12+**、**FFmpeg**（剪片工具）、**Node.js 18+**。
3. **Higgsfield Plus 或以上**：出相同出片全部喺度做（Seedance 2.5 出片、Seedream 出相）。
   👉 https://scalifylabs.ai/higgsfield
   - Free 用唔到 CLI，Starter 冇 Seedance 2.5，所以最少要 Plus。
   - Plus 每月 1,200 credits，大約夠拍一套 60 秒嘅片（見下面「錢」）。
4. **Kie AI 條 key**（只用嚟最後升 4K，可以唔用）：👉 https://scalifylabs.ai/kieai
5. **想用自己把聲做角色**（可以唔用）：喺 ElevenLabs 整好自己把聲（Voice Clone）。
   👉 https://scalifylabs.ai/elevenlabs
   - 喺 ElevenLabs 開一條 API key，要剔 Text to Speech 權限，放入 `.env` 嘅 `ELEVENLABS_API_KEY=`。
   - 同 agent 講你把聲嘅 voice id。agent 會經 API 用你把聲讀幾句對白，剪嚟做聲音樣本，之後每條片都跟住佢講。
   - 冇 ElevenLabs 都得：用手機喺靜嘅房錄 10–30 秒，放入集數 folder，同 agent 講個檔名。

> 上面幾條係推廣 link。經佢哋登記，價錢一樣，作者會收少少佣金。

## 安裝

```bash
# Windows
tools\setup.ps1

# macOS / Linux
sh tools/setup.sh
```

裝 Higgsfield 官方 CLI，然後登入一次：

```bash
npm install -g @higgsfield/cli
higgsfield auth login
```

登入會彈個 browser 出嚟，你撳批准就得。
唔使打 key，你嘅密碼 agent 都唔會見到。

最後喺 `.env` 填返要用嘅嘢（安裝時已經幫你由 `.env.example` 抄咗一份）：

- `KIE_API_KEY`：Kie 條 key，要升 4K 先填。
- `REELS_CONTACT`：一個你肯俾 Wikimedia 見到嘅網址或者 email。有咗呢行，engine 先可以自己搵真實場景相。

**唔好將任何 key 貼入 chat。** Key 只可以放喺 `.env`。

## 第一次用

喺你個 coding agent 開呢個 folder，然後講：

> 用 reels-start，幫我開始。

佢會做 3 樣嘢，全部唔使錢：

1. `reels preflight`：檢查你有冇登入、plan 夠唔夠、剩幾多 credits，同埋 Higgsfield 收唔收 engine 每一種請求。
2. `reels demo`：用假相假片由頭行到尾一次，等你睇到每一關份 PDF 係咩樣。
3. 問你想拍咩故仔。

### 唔喺部機前面點登入？

如果 agent 喺另一部機度跑，你喺手機都登入到：

1. Agent 打 `higgsfield auth login`，會出一個 `sign-in.html` 檔，入面有條登入 link。
2. Agent 將條 link 俾你，你用手機開，然後登入。
3. 登入完，手機會跳去一版開唔到嘅頁，網址係 `http://localhost:8765/callback?code=...`。呢個係正常嘅。
4. 將成條網址貼返俾 agent，佢會喺部機度幫你完成登入。

條網址入面個 code 只可以用一次，而且一定要配合嗰部機先用得，所以就算俾人見到都冇用。

## 每一關你要做咩

| 關 | 你做嘅嘢 |
| --- | --- |
| ① 故事 | Agent 會一次問你一條問題，每條都附建議。答完佢寫劇本，你睇 PDF 再批。 |
| ② 鎖定 | 揀樣（例如「B」）、聽把聲、睇場景啱唔啱。 |
| ③ 角度 | 睇每個鏡頭嘅定位畫面，用編號講要改邊度（例如「s03 要近啲」）。 |
| ④ 揀 take | 睇試片，講每段用邊個 take。 |
| ⑤ 成片 | 睇成片，批。 |

每一關都會有一本 PDF 審閱冊，放喺 `episodes/<集名>/review/`。最後一頁有編號嘅問題，你用編號答就得。

**小貼士：** 劇本嗰關最緊要，因為一開始問啱問題，之後就少好多改動。
你可以另外裝開源嘅 grill-me skill，佢會一條一條咁追問到你諗清楚為止。

## 錢

每集批 3 次錢。每次 agent 都會先報數，你用自己說話講「批」先會出貨。

| 幾時 | 批咩 | 一套 60 秒片大約 |
| --- | --- | --- |
| 故事關 | 出相：選角、角色表、場景、定位畫面、試聲 | 150–250 credits |
| 角度關 | 480p 試片，已經包咗三成重拍額度 | 400–600 credits |
| 成片關（平嘅做法） | 揀中嘅 480p 直接用 Kie 升 4K | 大約 US$2 |
| 成片關（另一個做法） | Higgsfield 轉 1080p，之後可以再升 4K | 大約 1,000 credits |

- 平嘅做法，成套片大約 **700–850 credits 加 US$2**，Plus 一個月夠用。
- 喺批咗嘅預算入面，agent 唔會逐單再問。
- 重拍額度用完，engine 會自己停低，等你決定。
- 落單結果唔清楚嘅（可能已經扣咗錢），engine 唔會再落多次，會叫你上 Higgsfield 睇。

## 安全規矩

- Key 只放喺 `.env`。Agent 唔會印出嚟，亦唔會喺 chat 問你攞。
- 用真人個樣（包括你自己）之前，要先喺 `episodes/<集名>/consent/` 寫低同意紀錄。
- 你嘅集數（相、片、把聲、同意紀錄）全部留喺你部機，唔會上 Git。

## 檔案喺邊

| 邊度 | 係咩 |
| --- | --- |
| `AGENTS.md` | 俾 agent 嘅總指示（Claude Code 經 `CLAUDE.md` 讀） |
| `docs/DECISIONS.md` | Engine 嘅設計決定，同埋你自己長期要跟嘅決定 |
| `docs/craft/` | 編劇、美術、導演、場記各自嘅做嘢規矩 |
| `.agents/skills/` | 每一關嘅做法 |
| `.claude/agents/`、`.codex/agents/` | 4 個 subagent，Claude Code 同 Codex 各一份 |
| `examples/lock-test/` | 一套 15 秒試拍嘅故事、鎖定表、分鏡 |
| `episodes/<集名>/` | 每集一個 folder |

## 改 engine 之後

```bash
.venv/bin/python -m pytest -q      # Windows: .venv\Scripts\python.exe -m pytest -q
tools/reels demo                   # Windows: tools\reels.ps1 demo
```

兩樣都過先算改好。

## License

MIT
