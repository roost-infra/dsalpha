---
name: a-share-limit-up
description: "A-share limit-up tape: first-board, consecutive-board, strong and broken-board pools, the board ladder, and next-day follow-through. Triggers on 涨停复盘, 连板, 炸板率, 打板情绪, 涨停梯队, limit-up analysis."
---

# A-Share Limit-Up Tape

Read the A-share limit-up tape as participation data: how many boards, how high
the ladder, how many broke, and what happened to yesterday's boards today. The
output describes the tape; it does not tell anyone to chase a board.

Evidence rules: `.agents/skills/research-conventions/SKILL.md`.

## Data source

`aktools` MCP — `search_interfaces` → `describe_interface` → `get_data`.
Use `date=YYYYMMDD` for pool interfaces. Search "涨停 池", "连板", "炸板" when a
name below has moved.

| Need | Likely interface | Notes |
|---|---|---|
| 涨停池 | `stock_zt_pool_em` | columns include 连板数, 封板资金, 首次封板时间 |
| 昨日涨停今日表现 | `stock_zt_pool_previous_em` | follow-through, average %chg |
| 强势股池 | `stock_zt_pool_strong_em` | near-limit strength |
| 炸板池 | `stock_zt_pool_zbgc_em` | failed boards |
| 跌停池 | `stock_zt_pool_dtgc_em` | the other tail |
| 市场情绪 | `stock_market_activity_legu` | up/down count, 赚钱效应 |

If an interface returns an empty frame, that can mean "no rows" or "not
published yet" — check the time and say which.

## Workflow

1. **Pools.** Pull the four pools for the session.
2. **Counts and rates.** Limit-ups, limit-downs, broken boards; 炸板率 =
   broken / (limit-ups + broken). Do the arithmetic in code, not by eye.
3. **Ladder.** Group limit-ups by 连板数. Report the tallest board, how many
   stocks are at each height, and the first-board count. A ladder that thins at
   the top is a different tape from one that fills in.
4. **Follow-through.** `stock_zt_pool_previous_em` gives yesterday's boards'
   performance today. Report the average, the share that stayed green, and the
   share that hit limit-down. This is the honesty check on yesterday's tape.
5. **Seal quality.** When the columns are present, look at 封板资金 relative to
   turnover and at 首次封板时间; a late, thin seal is weaker than an early,
   heavy one. If the columns are missing, say so and skip the claim.
6. **Output.**

```
As of: <date> close (source)
Pool counts: limit-up / limit-down / broken / strong
炸板率: x% (formula shown)
Ladder: height -> count; tallest; first-board count
Follow-through: yesterday's boards avg %chg, green share, limit-down share
Read: 3 bullets on breadth, ladder quality, follow-through
Caveats: missing columns, late publication, 20cm/10cm board mix
```

## Rules

- Separate 主板 10%, 创业板/科创板 20%, and ST 5% when comparing counts; a raw
  total mixes three different games.
- A high 炸板率 with a tall ladder is a late-cycle tape, not a strong one.
- No "打板" instructions, no entry prices, no "next limit-up" lists. This skill
  describes what happened; `trade-pitch` owns any position discussion.
