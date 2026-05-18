---
name: duyi-night-read
description: 夜读章节推荐工作流模板。每天给使用者推荐一本书的一个章节：基于本机 Claude Code、Codex、Hermes、OpenClaw、QClaw、ClawX、Claw、WorkBuddy 等 agent 对话提炼隐性议题，调微信读书 API 搜书选章，输出经验证可打开的微信读书网页阅读链接、weread:// 章节直达原始链接和"为什么是这一章"的一句话理由。触发词：今晚读什么、夜读、夜读skill、夜晚读书、night-read、给我推章节、读什么。
---

# duyi-night-read

> 一天结束时，从使用者今天和 AI 的本机对话里，找出 TA **自己可能没意识到**的卡点。
> 再从微信读书里推荐一本书的一个章节作为"解药"。
> 二十分钟读完。

这是一个工作流 skill：本机对话抽取 → 隐性议题判断 → 微信读书搜书选章 → 输出能复制打开的网页阅读链接和章节直达原始链接。

定位：这是面向普通用户可迁移的夜读工作流模板。任何人都可以用同一套方法，把自己的 AI 对话变成当天最该读的一章。新机器使用前必须先跑依赖检查，因为每个人的 agent 安装路径、微信读书 skill、API Key、微信读书网页访问状态和 `weread://` 协议注册状态都可能不同。

## 触发场景

- 用户手动说：今晚读什么 / 夜读 / 夜读skill / 夜晚读书 / 给我推章节
- 未来 cron 定时触发

## 数据边界

只读本机 agent 记录，不读云端历史：
- Claude Code：`~/.claude/projects/**/*.jsonl`
- Codex：`~/.codex/state_5.sqlite` + `~/.codex/sessions/**/*.jsonl`
- Hermes：`~/.hermes/state.db`
- Claw 系（OpenClaw / QClaw / ClawX / Claw / WorkBuddy）：`~/.workbuddy/projects/**/*.jsonl`、`~/.openclaw/projects/**/*.jsonl`、`~/.qclaw/projects/**/*.jsonl`、`~/.clawx/projects/**/*.jsonl`、`~/.claw/projects/**/*.jsonl`

脚本也会尽量探测 Windows 常见位置：`%USERPROFILE%`、`%APPDATA%`、`%LOCALAPPDATA%` 下的 `.claude` / `Claude`、`.codex` / `Codex`、`.hermes` / `Hermes`，以及 `.workbuddy` / `WorkBuddy` / `.openclaw` / `OpenClaw` / `.qclaw` / `QClaw` / `.clawx` / `ClawX` / `.claw` / `Claw`。探测不到时，不报错，只表示该用户本机没有对应记录或路径不同。

默认只抽使用者主动发出的用户消息。不要把系统提醒、工具结果、命令回显、agent 长回答当成今日议题。

如果本机 agent 记录不在常见路径，优先让本机 agent 设置环境变量，不要直接改源码：

```bash
NIGHT_READ_CLAUDE_ROOT=/path/to/.claude
NIGHT_READ_CODEX_ROOT=/path/to/.codex
NIGHT_READ_HERMES_ROOT=/path/to/.hermes
NIGHT_READ_OPENCLAW_ROOT=/path/to/openclaw
NIGHT_READ_QCLAW_ROOT=/path/to/qclaw
NIGHT_READ_CLAWX_ROOT=/path/to/clawx
NIGHT_READ_CLAW_ROOT=/path/to/claw
NIGHT_READ_WORKBUDDY_ROOT=/path/to/.workbuddy
```

多个目录可用系统路径分隔符连接：macOS/Linux 用 `:`，Windows 用 `;`。也可使用复数变量：`NIGHT_READ_CODEX_ROOTS`、`NIGHT_READ_CLAUDE_ROOTS` 等。

## 两种读取模式

- **daily / 24h**：默认模式。看最近 24 小时，适合每天晚上问"今晚读什么"。
- **deep / 240h**：长周期模式。看最近 240 小时，适合问"这几天我反复卡在哪"或 24h 对话太少时兜底。

两种模式都衔接微信读书：先抽对话，再提炼隐性议题，再调用微信读书搜索书和章节目录，最终只推荐一本书的一章。

## 上下游 Skill

- 上游：本 skill 内置的 `scripts/extract_today.py`，负责从本机 Claude Code / Codex / Hermes / Claw 系 agent 抽取用户问题。
- 下游：`微信读书` skill。调用微信读书接口前，按该 skill 的 `SKILL.md` 和相关说明文件确认 `/store/search`、`/book/chapterinfo`、深度链接和 `skill_version` 规则。

链接验收目标：用户复制后，网页链接能打开到微信读书里的这本书；手机端链接能尝试唤起微信读书 App 的具体章节。

链接必须同时给两种，且都要以原始文本露出，不能只包在 Markdown 链接里：
- 网页阅读链接：`https://weread.qq.com/web/reader/{encodeId}?progressChapterUid={chapterUid}`。必须先验证 HTTP 200，并确认返回页面里能看到书名和章节标题。`encodeId` 不等于 `bookId`，不要用 `bookId` 拼 `/web/reader/` 或 `/web/bookDetail/`；`https://weread.qq.com/web/bookDetail/{bookId}` 对部分书会 404。
- App 章节直达链接：`weread://reading?bId={bookId}&chapterUid={chapterUid}`。这是微信读书 App 私有协议，桌面浏览器和聊天窗口可能不会自动变成可点击链接，但必须原样给出，方便复制到手机打开。
- 备用搜索页：`https://weread.qq.com/web/search/books?keyword={urlencoded_title}`。只有网页阅读链接无法验证时才输出，并明说"网页阅读链接未验证，只能先用搜索页 + App 章节直达"。

如果要从 `bookId` 找网页 reader 的 `encodeId`，优先用附带脚本：

```bash
python3 ~/.agents/skills/duyi-night-read/scripts/resolve_weread_link.py \
  --title "书名" \
  --book-id "<bookId>" \
  --chapter-uid "<chapterUid>" \
  --chapter-title "章节标题"
```

脚本只访问微信读书公开网页，不读取 `WEREAD_API_KEY`。如果脚本不可用，本机 agent 可手动抓取 `https://weread.qq.com/web/search/books?keyword={urlencoded_title}`，在 HTML 里找与目标 `bookId`、书名、作者相邻的 `/web/reader/{encodeId}`，再用 `https://weread.qq.com/web/reader/{encodeId}?progressChapterUid={chapterUid}` 验证。

如果在新机器上使用，先运行依赖检查：

```bash
python3 ~/.agents/skills/duyi-night-read/scripts/check_dependencies.py
```

该脚本只检查并提示，不自动安装第三方 skill。若缺少微信读书 skill，引导用户去：

https://weread.qq.com/r/weread-skills

如果用户不会用脚本，可以把这段提示词发给 AI 助手：

```text
请帮我安装并检查 duyi-night-read 夜读工作流：
1. 打开 https://weread.qq.com/r/weread-skills，按页面提示安装微信读书 skill。
2. 登录微信读书获取 API Key。
3. 根据我的系统配置 WEREAD_API_KEY。
4. 运行 duyi-night-read 的 scripts/check_dependencies.py。
5. 如果没有发现我的 agent 记录，请先检查本机常见目录；路径不同就设置 NIGHT_READ_CLAUDE_ROOT / NIGHT_READ_CODEX_ROOT / NIGHT_READ_HERMES_ROOT / NIGHT_READ_OPENCLAW_ROOT / NIGHT_READ_QCLAW_ROOT / NIGHT_READ_CLAWX_ROOT / NIGHT_READ_CLAW_ROOT / NIGHT_READ_WORKBUDDY_ROOT，不要直接改脚本。
6. 如果依赖齐全，运行 scripts/extract_today.py daily 40，确认能读到本机 agent 对话。
不要读取云端对话，不要泄露 API Key。
```

## 给其他 Agent 的适配协议

这个 skill 可以被别人的 Claude Code / Codex / Hermes / OpenClaw / QClaw / ClawX / Claw / WorkBuddy 使用。适配时遵守三层顺序：

1. 先跑 `scripts/check_dependencies.py`，确认微信读书 skill、`WEREAD_API_KEY`、本机 agent 记录是否存在。
2. 路径不同时，优先用 `NIGHT_READ_*_ROOT` 或 `NIGHT_READ_*_ROOTS` 指向真实记录目录。
3. 只有环境变量无法解决时，才由本机 agent 提出脚本 patch；改前说明改哪个路径、为什么改、怎么验证。

无论谁使用，都不要读取云端历史，不要上传原始对话，不要打印 API Key。

不同 agent 可以按本机情况调整路径和验证方法，但不能放宽最终验收：最后交给用户的必须是具体书名、具体章节、网页阅读链接、App 章节直达链接。不能只给搜索结果页、书籍页或一句"去微信读书搜"。

## 密钥安全

`WEREAD_API_KEY` 只能从当前进程环境变量读取。不要为了找 key 去 `cat`、`rg`、`grep`、`source` 或打印这些文件：

- `~/.zshrc`
- `~/.bashrc`
- `~/.bash_profile`
- `~/.profile`
- `.env`
- 任何可能包含 token / key / secret / password 的配置文件

如果当前 shell 没有 `WEREAD_API_KEY`，只提示用户配置或重开终端，不要替用户从 profile 里找回 key。任何命令输出里一旦可能出现 key，必须停下，不要展示。

## 硬规则

1. **不推泛励志、成功学、效率类书**。这类内容容易变成自我催促，不适合做"解药"。优先推：心理学、哲学、社会学、传记、文学、思想史。
2. **只推一本一章**。不要给候选清单让用户选。决定就是决定。
3. **不要复述用户今天做了什么**。用户知道。只说 TA **没说出来但在做**的那件事。
4. **不要总结、不要收束、不要"希望对你有帮助"**。最后一句要有重量。
5. **章节理由限 80 字以内**。用户读完会自己想，不需要被引导。
6. **没有合适的就说没有**。绝不为了交差硬推一本不准的书。

## 执行流程

### Step 1: 抽取今日对话

```bash
python3 ~/.agents/skills/duyi-night-read/scripts/extract_today.py daily 40
```

如果用户明确要长周期，或 24h 提问数 < 5，再用：

```bash
python3 ~/.agents/skills/duyi-night-read/scripts/extract_today.py deep 40
```

输出会有"模式"、"覆盖来源"、"会话数"、"提问总数"和分来源计数。若 deep 模式提问数仍 < 5，说明最近没怎么对话，告诉用户"最近对话太少，没什么可读的"，停下。

### Step 2: 读完全部，提炼隐性议题

把所有用户提问读完。**不是读关键词，是读情绪走向**。

判断隐性议题的标准（满足 2 条以上才算）：
- 同一个困惑在不同会话里**反复回到**
- 用户**自己说出过迟疑、矛盾、撤退、害怕、失落**等情绪词
- 显性任务（写文章/做配图/调试）**背后**真正在解决的问题
- 用户**问出了问题但没拿到答案**就跳走了

把每个候选议题写一行：「用户今天反复在 X 这件事上停顿，因为 Y」。
最多 3 个候选，最少 1 个。

如果今天全是执行类任务（排版、调试、配图），没有情绪重量，直接告诉用户："今天都是手活，没什么可读的，去睡。" 停下。

### Step 3: 选 1 个最有 weight 的议题

从候选里挑**最有重量**的那一个。判断标准：
- 这个议题如果不处理，用户**明天还会再回到它**
- 它**不是商业问题**，是认知/关系/自我层面的问题
- 它有具体的处境（不是抽象的"焦虑"，而是"今天在 X 事件上失落"）

### Step 4: 生成查询词

针对选中的议题，生成 3-5 个**精准查询词**。
不是关键词列表，是**精准定位一本书的核心命题**的词。

例子：
- 议题"想拉群但害怕承接情绪" → 查询词：「课题分离」「他人课题」「助人者综合征」「情绪边界」
- 议题"亲密关系里的供需错位" → 查询词：「依恋错位」「亲密关系 供需」「Esther Perel」「爱与被需要」
- 议题"撤退与现金流的拉扯" → 查询词：「内在冲突」「分裂的自我」「Karen Horney 内心冲突」

### Step 5: 调微信读书搜书

对每个查询词调一次 `/store/search`，scope=10（电子书）：

```bash
curl -s -X POST "https://i.weread.qq.com/api/agent/gateway" \
  -H "Authorization: Bearer $WEREAD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"api_name":"/store/search","keyword":"课题分离","scope":10,"skill_version":"1.0.3"}' \
  | python3 -m json.tool
```

收集所有返回里的 `bookInfo`，按以下条件筛：
- 评分（newRating）≥ 80
- 评分人数（newRatingCount）≥ 500（冷门书容易判断失真）
- 排除：成功学、领导力、效率类、商业管理类、心灵鸡汤类
- 优先：经典心理学 / 哲学 / 思想家原著 / 社科 / 文学

如果搜索回包没有 `newRating` 或 `newRatingCount`，不要卡死在评分规则上。改用兜底判断：
- 读者规模 / 阅读人数更大的优先
- 作者和书本身更经典的优先
- 章节标题直接命中议题的优先
- 标题很贴但明显冷门、读者很少的书，不要优先

候选剩 3-5 本，进入下一步。

### Step 6: 调 chapterinfo 拿章节目录

对每本候选书：

```bash
curl -s -X POST "https://i.weread.qq.com/api/agent/gateway" \
  -H "Authorization: Bearer $WEREAD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"api_name":"/book/chapterinfo","bookId":"<bookId>","skill_version":"1.0.3"}'
```

看 chapters 数组的 title 字段。**章节标题往往就是命题本身**。

判断标准（挑唯一一章）：
- 标题里**直接命中议题核心词**的优先
- 不要选「前言」「序」「致谢」「附录」
- 不要选纯人物传记类的章节（除非传记本身就对路）
- 一本书里选**最直接对应的那一章**，不要为了凑数选相关章

### Step 7: 最终输出

输出 Markdown，写到文件，并在终端打印一遍。

```bash
mkdir -p "${NIGHT_READ_OUTPUT_DIR:-$HOME/night-read}"
```

文件名：`${NIGHT_READ_OUTPUT_DIR:-$HOME/night-read}/{YYYY-MM-DD}-{书名简写}.md`

如果用户已经有自己的知识库路径，可以沿用用户指定的位置，或提前设置 `NIGHT_READ_OUTPUT_DIR`。

输出格式：

```markdown
# 今晚读什么 · {YYYY-MM-DD}

## 我看到你今天卡在

{2-4 行白描。原话引用 1-2 句用户自己说过的话。不解释、不分析、不安慰。}

## 推荐章节

**《{书名}》**
{作者} · {章节标题}

网页阅读：{verifiedReaderUrl}

App 章节直达：weread://reading?bId={bookId}&chapterUid={chapterUid}

备用搜索：{只在网页阅读无法验证时输出 https://weread.qq.com/web/search/books?keyword={urlencoded_title}}

## 为什么是这一章

{80 字以内。说清楚这一章为什么对今天的卡点是解药。不教学、不展开、不剧透。}

---

## 今日对话索引

{按时间列出用户今天提的"有重量"的问题原文，每条一行。最多 8 条。让用户自己看到走向。}
```

写完后**在终端也打印一遍**，让用户立即看到。

## 错误处理

- API Key 没配：提示用户配置 `WEREAD_API_KEY` 或重开已配置的终端；不要搜索 shell profile、`.env` 或任何配置文件来找 key
- 搜书返回 0 本：换查询词再试一轮，最多 2 轮。仍 0 本，告诉用户"今晚没找到合适的书，建议回到自己最近写下的笔记或判断"
- chapterinfo 失败：换一本候选书
- 网页阅读链接无法验证：不要声称"可打开"；输出备用搜索页和 App 章节直达，并说明网页端只能确认到搜索页
- 整套跑下来没有满足硬规则的章节：直接说"今晚没有"，不硬凑

## 不做什么

- 不推第二本作为备选（避免把选择压力还给用户）
- 不写读后感引导
- 不复盘用户今天的产出
- 不评价用户的状态
- 不在对话索引里加评论标签
