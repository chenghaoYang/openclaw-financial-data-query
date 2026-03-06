# LLM 路由分类法参考表 (Routing Taxonomy Reference)

> **用途**：本文件是 `domain_router.py` 中 `DEFAULT_ROUTER_RULES` 的结构化摘要，供 LLM 作为路由查找参考。
> **生成方式**：从 141 条 `RouterRule` 中提取，按 `(market, intent)` 分组、去重合并。
> **排序规则**：按市场分组，组内按最高优先级降序排列。
> **最后更新**：2026-03-05

---

## 1. A股 (priority 45 ~ 650)

| intent_category (意图分类) | 最高优先级 | 置信度 | yaml_scopes (YAML 路径范围) | typical_query_expansions (典型扩展词) | typical_triggers (典型触发词) |
|---|---|---|---|---|---|
| `technical_macd` -- MACD技术指标 | 645 | 0.95 | `股票/stock_astock_mkt_daily_trans.yaml`, `股票/stock_astock_latest_index.yaml` | MACD, DIF, DEA, 技术指标, 金叉, 死叉 | MACD, 异同移动平均, DIF, DEA, MACD柱 |
| `technical_kdj` -- KDJ随机指标 | 640 | 0.95 | `股票/stock_astock_mkt_daily_trans.yaml`, `股票/stock_astock_latest_index.yaml` | KDJ, 随机指标, 超买超卖 | KDJ, 随机指标, K值, D值, J值 |
| `technical_rsi` -- RSI相对强弱指标 | 635 | 0.95 | `股票/stock_astock_mkt_daily_trans.yaml`, `股票/stock_astock_latest_index.yaml` | RSI, 相对强弱 | RSI, 相对强弱指标, 相对强弱 |
| `technical_boll` -- 布林带指标 | 630 | 0.92 | `股票/stock_astock_mkt_daily_trans.yaml`, `股票/stock_astock_latest_index.yaml` | 布林带, BOLL, 上轨, 下轨 | BOLL, 布林, 布林带, 布林线, 上轨, 下轨, 中轨 |
| `technical_ma` -- 均线/MA金叉死叉 | 625 | 0.90 | `股票/stock_astock_mkt_daily_trans.yaml`, `股票/stock_astock_latest_index.yaml` | 均线, 移动平均, 金叉, 死叉 | 均线, 移动平均, MA线 + 金叉/死叉/交叉/突破/多头排列/空头排列/上穿/下穿 |
| `technical_volume` -- 量价分析 | 620 | 0.85 | `股票/stock_astock_mkt_daily_trans.yaml`, `股票/stock_astock_latest_index.yaml` | 成交量, 量价 | 放量, 缩量, 天量, 地量, 量价背离, 量价齐升, 量价齐跌, 量能 |
| `technical_kline_pattern` -- K线形态 | 615 | 0.85 | `股票/stock_astock_mkt_daily_trans.yaml`, `股票/stock_astock_latest_index.yaml` | K线形态, 技术形态 | 十字星, 锤子线, 吊颈线, 吞没, 乌云盖顶, 启明星, 射击之星, 大阳, 大阴, 长上影, 长下影, 红三兵, 三只乌鸦 |
| `technical_general` -- 通用技术分析(兜底) | 610 | 0.75 | `股票/stock_astock_mkt_daily_trans.yaml`, `股票/stock_astock_latest_index.yaml` | 技术指标, 技术分析 | 技术面, 技术分析, 技术指标, 超买, 超卖, 背离, 支撑, 压力, 阻力, 趋势线, 金叉, 死叉, 突破, 形态 |
| `stock_institution_holding` -- A股机构持股统计 | 236 | 0.88 | `股票/stock_astock_shareholding_insitutions.yaml`, `股票/stock_astock_institutional_stat.yaml` | 机构持仓, 基金持股, 社保基金持股 | 基金重仓股, 社保基金重仓, 基金/社保/保险/QFII持股+家数/数量/市值/占比/变动/统计 |
| `lhb_foreign_trade` -- 外资买卖(龙虎榜) | 100 | 0.90 | `股票/stock_astock_charts.yaml` | 龙虎榜, 境外游资, 营业部类型 | 外资+买入/卖出/买卖/净买入/净卖出/流入/流出/金额/资金 |
| `lhb_northbound_trade` -- 北向资金买卖(龙虎榜) | 95 | 0.85 | `股票/stock_astock_charts.yaml` | 龙虎榜, 境外游资 | 北向资金/陆股通/沪股通/深股通/港资+买入/卖出/净买入/净卖出/流入/流出/金额/资金流向 |
| `lhb_institution_trade` -- 机构买卖(龙虎榜) | 90 | 0.85 | `股票/stock_astock_charts.yaml` | 龙虎榜, 机构席位, 机构专用, 机构买入 | 机构+买入/卖出/净买入/席位/资金/流向 |
| `northbound_connect_holding` -- 北向/陆股通持股变动 | 86 | 0.88 | `股票/stock_astock_stock_connect.yaml` | 北向资金, 陆股通持股, 加仓, 减仓 | 北向资金/陆股通/沪股通/深股通+加仓/减仓/增持/减持/调仓/持股变动/持股 |
| `lhb_direct` -- 龙虎榜直接提及 | 85 | 0.95 | `股票/stock_astock_charts.yaml`, `股票/stock_astock_charts_stat.yaml` | (无) | 龙虎榜 |
| `northbound_ranking` -- 北向资金成交排行 | 84 | 0.88 | `股票/stock_astock_mkt_daily_trans.yaml`, `股票/stock_astock_basic_info.yaml` | 北向资金, 陆股通成交额, 沪股通, 深股通, 股票代码 | 北向资金/陆股通/沪股通/深股通+排行/排名/榜/成交/成交量/成交额/净买入/净流入 |
| `intraday_timesharing` -- 分时/分钟级行情 | 82 | 0.90 | `股票/stock_astock_time_sharing_market.yaml`, `股票/stock_astock_mkt_min_trans.yaml` | 分时行情, 分钟行情, 时序 | 分时, 逐笔, 盘口, 分钟, 5分钟, 15分钟, 30分钟, 60分钟, 集合竞价, 竞价匹配 |
| `foreign_holdings` -- 外资/QFII持仓 | 80 | 0.85 | `股票/stock_astock_shareholding_insitutions.yaml` | 外资持股, QFII, 机构持仓 | 外资/QFII/合格境外+持股/持仓/占比/变动/比例/市值/换手 |
| `institutional_holdings` -- 机构持仓(社保/保险等) | 78 | 0.85 | `股票/stock_astock_shareholding_insitutions.yaml`, `股票/stock_astock_institutional_stat.yaml` | 机构持仓, 持仓变动 | 社保/保险/券商/QFII/信托/基金/机构+持仓/持股/换手/市值/变动/占比/比例/数量 |
| `astock_financial` -- A股财务数据 | 77 | 0.85 | `股票/stock_astock_company_financial_data.yaml`, `股票/stock_astock_company_financial_data_new.yaml` | 财务数据, 财报 | 财报, 财务, 营收, 净利润, 归母净利, 扣非, 毛利, EPS, ROE, ROA, 资产负债, 现金流, 利润表 |
| `performance_forecast` -- 业绩预告/预警 | 76 | 0.90 | `股票/stock_astock_company_performance_forecast.yaml` | 业绩预告, 报告期, 报告期截止日 | 业绩预告, 业绩预警, 业绩报坏, 业绩报好, 预亏, 预增, 预减, 预盈, 预警 |
| `astock_profit_forecast` -- A股盈利预测 | 76 | 0.85 | `股票/stock_astock_institutional_performance_forcast.yaml` | 盈利预测, 业绩预测, 净利润增速 | 预测/预期/预计+净利润/利润/业绩/营收/收入/增速, 盈利预测, 业绩预测 |
| `margin_trading` -- 融资融券 | 75 | 0.85 | `股票/stock_astock_mkt_daily_trans.yaml` | 融资融券, 两融 | 融资/融券+买入/卖出/净买入/净卖出/余额/金额 |
| `basic_info_profile` -- 基本资料/概念/市场类型 | 74 | 0.90 | `股票/stock_astock_basic_info.yaml`, `股票/stock_astock_mkt_daily_trans.yaml` | 基本资料, 股票代码, 股票简称, 所属概念 | 所属概念, 概念股, 所属行业, 行业分类, 所属板块, 股票市场类型, 上市日期, 主营业务 |
| `astock_top_shareholders` -- A股十大股东 | 73 | 0.85 | `股票/stock_astock_top10_shareholders_detail.yaml`, `股票/stock_astock_top10_shareholders_detail_latest.yaml`, `股票/stock_astock_top10_shareholders_stat.yaml`, `股票/stock_astock_top10_circulate_shareholders_detail.yaml`, `股票/stock_astock_top10_circulate_shareholders_detail_latest.yaml`, `股票/stock_astock_top10_circulate_shareholders_stat.yaml`, `股票/stock_astock_num_shareholders_capital_chg.yaml` | 十大股东, 流通股东, 股东变动 | 十大股东, 前十大股东, 流通股东, 十大流通, 股东变动, 股东户数, 股东人数, 控股股东 |
| `increase_decrease` -- 增减持/套现 | 72 | 0.85 | `股票/stock_astock_increase_decrease.yaml`, `股票/stock_astock_increase_decrease_plan.yaml` | 增减持, 股东变动, 减持金额 | 减持, 增持, 套现, 高管买/卖, 股东买/卖/减/增 |
| `astock_research` -- A股研报/评级/机构调研 | 71 | 0.82 | `股票/stock_astock_research_report_rating.yaml`, `股票/stock_astock_institutional_research.yaml`, `股票/stock_astock_institutional_research_stat.yaml`, `股票/stock_astock_institutional_performance_forcast.yaml` | 研报, 评级, 分析师 | 研报, 研究报告, 评级, 目标价, 分析师, 机构调研, 调研, 一致预期, 买入评级 |
| `main_force_flow` -- 主力资金流向 | 70 | 0.75 | `股票/stock_astock_mkt_daily_trans.yaml` | 主力资金, 资金流向 | 主力+流入/流出/净流入/净流出/资金/买入/卖出/拉升/增仓/减仓/控盘/进攻/建仓/出货/吸筹/洗盘 |
| `astock_fund_flow_generic` -- 通用资金流向(无主力前缀) | 69 | 0.78 | `股票/stock_astock_mkt_daily_trans.yaml`, `股票/stock_astock_latest_index.yaml` | 资金流向, 资金 | 净流入金额, 净流出金额, 资金流入, 资金流出, 资金流向, 资金进场, 资金出逃, 暗盘资金, 实时资金 |
| `astock_pledge` -- A股股权质押 | 68 | 0.85 | `股票/stock_astock_equity_pledge.yaml`, `股票/stock_astock_pledge_stat.yaml`, `股票/stock_astock_pledgor_stituation.yaml` | 股权质押, 质押 | 股权质押, 质押率, 质押比例, 质押股份, 质押数量, 解质押, 质押风险 |
| `astock_major_shareholder_freeze` -- 大股东冻结 | 67 | 0.82 | `股票/stock_astock_top10_shareholders_detail.yaml`, `股票/stock_astock_top10_shareholders_detail_latest.yaml`, `股票/stock_astock_top10_shareholders_stat.yaml` | 大股东, 冻结 | 大股东/股东+冻结/股份冻结/司法冻结 |
| `astock_equity_freeze` -- 股权冻结 | 67 | 0.82 | `股票/stock_astock_equity_freeze.yaml` | 股权冻结, 冻结 | 股权冻结, 股份冻结, 司法冻结 |
| `astock_ma` -- A股并购重组/资产重组 | 66 | 0.82 | `股票/stock_astock_mergers_acquisitions.yaml`, `股票/stock_astock_asset_injection.yaml`, `股票/stock_astock_asset_purchase.yaml`, `股票/stock_astock_asset_sale.yaml`, `股票/stock_astock_asset_replacement.yaml`, `股票/stock_astock_backdoor_list.yaml`, `股票/stock_astock_equity_transfer.yaml`, `股票/stock_astock_tender_offer.yaml`, `股票/stock_astock_divestiture.yaml` | 并购重组, 收购 | 并购, 重组, 收购, 借壳, 资产注入, 资产购买, 资产出售, 资产置换, 吸收合并, 要约收购, 股权转让, 资产剥离 |
| `large_order_flow` -- 大单/特大单资金流 | 65 | 0.75 | `股票/stock_astock_mkt_daily_trans.yaml` | 资金流向, DDE | 大单/特大单/中单/小单+流入/流出/净流入/净额/买入/卖出 |
| `limit_up_down` -- 涨停/跌停/连板 | 64 | 0.90 | `股票/stock_astock_mkt_daily_trans.yaml`, `股票/stock_astock_latest_index.yaml` | 涨停, 涨停板, 跌停, 封板, 连板 | 涨停, 跌停, 连板, 涨停板, 跌停板, 一字涨停, 封板, 开板, 炸板, 连续涨停 |
| `astock_equity_financing` -- A股IPO/定增/再融资 | 64 | 0.82 | `股票/stock_astock_ipo.yaml`, `股票/stock_astock_seo.yaml`, `股票/stock_astock_sright_issue.yaml`, `股票/stock_astock_financing.yaml`, `股票/stock_astock_new_stock_evaluation.yaml`, `股票/stock_astock_participart_in_new_stock.yaml` | IPO, 定增, 再融资 | IPO, 首次公开发行, 首发, 新股上市/发行/申购/中签, 打新, 定增, 定向增发, 配股, 增发, 再融资, 募集资金 |
| `active_passive_trade` -- 内盘外盘/主动买卖 | 63 | 0.80 | `股票/stock_astock_mkt_daily_trans.yaml` | 主动成交, 内盘, 外盘 | 内盘, 外盘, 内外盘, 主动买入/卖出/成交, 被动买入/卖出/成交, 挂单 |
| `astock_daily_quote` -- A股日行情/股价 | 62 | 0.80 | `股票/stock_astock_mkt_daily_trans.yaml`, `股票/stock_astock_latest_index.yaml` | 股价, 行情, 日K | 股价, 收盘价, 开盘价, 最高价, 最低价, 成交量, 成交额, 换手率, 最新价, 复权价 |
| `astock_revenue_composition` -- A股主营构成/收入结构 | 61 | 0.82 | `股票/stock_astock_main_business_composition.yaml`, `股票/stock_astock_main_business_composition_latest.yaml`, `股票/stock_astock_cost_structure.yaml` | 主营构成, 收入结构 | 主营业务构成, 收入构成, 收入结构, 营收结构, 产品构成, 业务构成, 分产品, 分地区, 分行业收入 |
| `price_change` -- 股价变动/涨跌幅 | 60 | 0.70 | `股票/stock_astock_mkt_daily_trans.yaml`, `股票/stock_astock_latest_index.yaml` | 价格变动, 行情, 涨跌 | 涨跌幅, 涨幅, 跌幅, 阶段涨幅, 区间涨幅, 增长率, 涨了多少, 跌了多少, 表现, 行情 |
| `astock_equity_incentive` -- A股股权激励 | 59 | 0.85 | `股票/stock_astock_equity_incentives.yaml`, `股票/stock_astock_employee_stock_ownership_plan.yaml` | 股权激励, 激励计划 | 股权激励, 期权激励, 限制性股票, 员工持股计划, ESOP, 股票期权, 激励计划 |
| `annual_dividend` -- 股息/分红金额(年度) | 58 | 0.90 | `股票/stock_astock_annual_dividend.yaml` | 股息支付金额, 年度分红, 分红 | 股息支付, 股息金额, 分红金额, 年度分红, 派息金额, 现金分红, 每股股利, 每股派息 |
| `astock_retail_flow` -- 散户资金流向 | 58 | 0.78 | `股票/stock_astock_mkt_daily_trans.yaml` | 散户, 散户资金 | 散户+流入/流出/增仓/减仓/资金/买入/卖出/净买入/净卖出 |
| `corporate_bond` -- 公司债券发行 | 57 | 0.85 | `股票/stock_astock_comporate_bond.yaml` | 债券发行, 公司债 | 债券+规模/金额/利率/期限/发行, 发行债券 |
| `astock_block_trading` -- A股大宗交易 | 56 | 0.82 | `股票/stock_astock_block_trading.yaml`, `股票/stock_astock_block_trading_stat.yaml` | 大宗交易 | 大宗交易, 大宗, 折价, 溢价交易, 协议转让 |
| `dividend` -- 分红送转(通用) | 55 | 0.85 | `股票/stock_astock_annual_dividend.yaml`, `股票/stock_astock_dividend_status.yaml` | 分红送转, 利润分配 | 分红, 派息, 送转, 股息 |
| `astock_buyback` -- A股回购 | 54 | 0.82 | `股票/stock_astock_repurchase_of_shares.yaml` | 回购, 股票回购 | 回购, 股票回购, 回购股份, 回购金额, 回购数量, 回购预案, 回购计划 |
| `unlock_shares` -- 限售解禁 | 53 | 0.85 | `股票/stock_astock_unlock_shareholds.yaml` | 限售解禁, 解禁股 | 解禁, 限售股, 限售解禁 |
| `astock_popularity` -- 热度/人气/排名 | 52 | 0.82 | `股票/stock_astock_mkt_daily_trans.yaml`, `股票/stock_astock_latest_index.yaml` | 热度, 人气, 排名 | 个股热度, 人气排名, 热度排名, 同花顺人气, 人气龙头 |
| `astock_trading_signal` -- 买入/卖出信号 | 51 | 0.82 | `股票/stock_astock_mkt_daily_trans.yaml`, `股票/stock_astock_latest_index.yaml` | 买入信号, 卖出信号 | 买入信号, 卖出信号, 交易信号, 买卖信号 |
| `continuous_days` -- 连续交易日数据 | 50 | 0.70 | `股票/stock_astock_mkt_daily_trans.yaml`, `股票/stock_astock_charts.yaml` | 日频, 每日, 明细 | 连续N个交易日 |
| `astock_valuation` -- 估值指标(PE/PB/PS) | 49 | 0.78 | `股票/stock_astock_mkt_daily_trans.yaml`, `股票/stock_astock_latest_index.yaml` | 估值, 市盈率, 市净率 | 市净率, 市盈率, 市销率, PEG |
| `astock_share_capital` -- A股股本/股份结构 | 48 | 0.78 | `股票/stock_astock_share_capital.yaml`, `股票/stock_astock_tequity_structure.yaml`, `股票/stock_astock_mkt_daily_trans.yaml` | 股本, 总股本 | 总股本, 流通股本, 股本结构, 股份变动, 限售股, 流通市值, 总市值, 市值 |
| `astock_announcement_event` -- 公告事件(复牌/停牌) | 48 | 0.82 | `股票/stock_astock_economic_events.yaml`, `股票/stock_astock_trading_suspended_resumed.yaml` | 公告, 复牌, 停牌 | 公告+复牌/停牌, 什么时候+开盘/复牌/停牌, 公告事件 |
| `astock_cattle_track` -- 牛散持股/跟踪 | 47 | 0.88 | `股票/stock_astock_most_cattletrack.yaml` | 牛散, 牛散持股, 超级散户 | 牛散, 超级散户, 知名散户, 知名股东 |
| `astock_concept` -- A股概念板块 | 47 | 0.78 | `股票/stock_astock_concept.yaml`, `股票/stock_astock_basic_info.yaml` | 概念, 板块 | 概念板块, 同花顺概念, 概念成份/成分, 板块个股, 板块轮动 |
| `astock_industry` -- A股行业分类 | 46 | 0.80 | `股票/stock_astock_basic_info.yaml`, `股票/pub_sec_mkt_industrial.yaml`, `股票/pub_sec_mkt_industrial_chain.yaml` | 行业, 行业分类, 所属行业 | 行业板块, 产业链, 行业成份/成分, 成份/成分股, 行业龙头 |
| `controller_info` -- 控股股东/实际控制人 | 45 | 0.80 | `股票/stock_astock_controller.yaml` | 控股股东, 实际控制人 | 控股股东/实际控制人/大股东+是谁/信息/变更/变动 |

---

## 2. 可转债 (priority 150 ~ 180)

| intent_category (意图分类) | 最高优先级 | 置信度 | yaml_scopes (YAML 路径范围) | typical_query_expansions (典型扩展词) | typical_triggers (典型触发词) |
|---|---|---|---|---|---|
| `cb_basic` -- 可转债基本信息/发行 | 175 | 0.88 | `可转债/convertiblebond_basic_info.yaml`, `可转债/convertiblebond_issue_info.yaml`, `可转债/convertiblebond_terms.yaml` | 可转债, 发行信息 | 可转债/转债+基本/信息/发行/条款/规模/期限/利率/票面 |
| `cb_market` -- 可转债行情/价格 | 170 | 0.88 | `可转债/convertiblebond_market.yaml`, `可转债/convertiblebond_market_new.yaml` | 可转债行情, 转股溢价率 | 可转债/转债+行情/价格/涨跌/成交/溢价/收盘/开盘 |
| `cb_conversion` -- 转股/下修/回售/赎回 | 165 | 0.85 | `可转债/convertiblebond_terms.yaml`, `可转债/convertiblebond_terms_exercise.yaml`, `可转债/convertiblebond_transfer_price_adjustments.yaml`, `可转债/convertiblebond_payments_and_redemptions.yaml` | 转股价, 下修, 回售 | 转股, 转股价, 下修, 回售, 强赎, 赎回 |
| `cb_rating` -- 可转债评级/信用 | 160 | 0.85 | `可转债/convertiblebond_credit_rating.yaml`, `可转债/convertiblebond_credit_rating_new.yaml`, `可转债/convertiblebond_entity_rating.yaml` | 信用评级, 债券评级 | 可转债/转债+评级/信用/AAA/AA/评分 |
| `cb_holder` -- 可转债持仓/持有人 | 155 | 0.85 | `可转债/convertiblebond_holder.yaml`, `可转债/convertiblebond_holder_statistics.yaml`, `可转债/convertiblebond_institutional_purchase.yaml` | 持有人, 机构持仓 | 可转债/转债+持仓/持有/持有人/机构/前十 |

---

## 3. 全量指数 (priority 180 ~ 200)

| intent_category (意图分类) | 最高优先级 | 置信度 | yaml_scopes (YAML 路径范围) | typical_query_expansions (典型扩展词) | typical_triggers (典型触发词) |
|---|---|---|---|---|---|
| `index_quote` -- 指数行情/点位 | 195 | 0.88 | `全量指数/index_mkt_daily_trans.yaml`, `全量指数/index_latest_index.yaml` | 指数行情, 点位 | 指数/沪深300/上证指数/深证成指/创业板指/科创50/中证N+行情/点位/涨跌/收盘/开盘/成交/K线/走势 |
| `index_info` -- 指数基本信息/成分股 | 190 | 0.88 | `全量指数/index_basic_info.yaml`, `全量指数/index_constituents.yaml` | 成分股, 指数信息, 权重 | 指数+基本/成分/权重/样本/编制/简介 |
| `index_minute_quote` -- 指数分钟行情 | 188 | 0.88 | `全量指数/index_mkt_min_trans.yaml` | 指数分钟行情, 分时 | 指数+分钟/分时/盘口/1分钟/5分钟/15分钟/30分钟/60分钟 |
| `index_weekly_monthly_quote` -- 指数周/月线行情 | 186 | 0.85 | `全量指数/index_mkt_weekly_trans.yaml`, `全量指数/index_mkt_monthly_trans.yaml` | 指数周线, 指数月线 | 指数+周线/月线/周K/月K/周行情/月行情/周涨幅/月涨幅 |
| `index_valuation` -- 指数估值/PE/PB | 185 | 0.88 | `全量指数/index_fin_data.yaml`, `全量指数/index_ttm_data.yaml` | 指数PE, 指数PB, 估值 | 指数+PE/PB/估值/市盈率/市净率/盈利 |
| `index_profit_forecast` -- 指数盈利预测 | 183 | 0.85 | `全量指数/index_profit_forecast.yaml` | 指数盈利预测, 一致预期 | 指数+盈利预测/利润预测/EPS预测/一致预期/预期收益 |

---

## 4. 基金 (priority 200 ~ 250)

| intent_category (意图分类) | 最高优先级 | 置信度 | yaml_scopes (YAML 路径范围) | typical_query_expansions (典型扩展词) | typical_triggers (典型触发词) |
|---|---|---|---|---|---|
| `fund_nav` -- 基金净值 | 245 | 0.92 | `基金/fund_mkt_daily_trans_latest.yaml`, `基金/fund_mkt_daily_trans.yaml`, `基金/fund_basic_info.yaml` | 净值, 单位净值, 累计净值 | 基金/ETF+净值/单位净值/累计净值 |
| `fund_performance` -- 基金收益/业绩/回报 | 240 | 0.90 | `基金/fund_history_statistics.yaml`, `基金/fund_mkt_daily_trans_latest.yaml`, `基金/fund_comprehensive_diagnosis.yaml` | 收益率, 业绩, 涨幅 | 基金/ETF+收益/业绩/回报/涨幅/涨跌/夏普/波动/最大回撤/年化/排名 |
| `fund_holdings` -- 基金持仓/重仓/资产配置 | 235 | 0.88 | `基金/fund_hold_detail.yaml`, `基金/fund_hold_detail_latest.yaml`, `基金/fund_asset_allocation.yaml` | 持仓, 重仓股, 十大重仓 | 基金/ETF+持仓/重仓/十大/资产配置/持股/仓位/股票配置/债券配置 |
| `fund_dividend` -- 基金分红 | 230 | 0.90 | `基金/fund_dividend_detail.yaml`, `基金/fund_annual_dividend.yaml` | 基金分红, 分红记录 | 基金/ETF+分红/派息/红利/分红记录 |
| `fund_subscription` -- 基金申购/赎回 | 225 | 0.85 | `基金/fund_subscription_redemption.yaml`, `基金/fund_subscription_redemption_rate.yaml` | 申购赎回, 申赎 | 基金/ETF+申购/赎回/申赎/购买/卖出/认购 |
| `fund_size` -- 基金规模/份额 | 220 | 0.88 | `基金/fund_shares_size.yaml`, `基金/fund_basic_info.yaml` | 基金规模, 份额, 资产规模 | 基金/ETF+规模/份额/资产/总资产/AUM |
| `fund_rate` -- 基金费率 | 215 | 0.88 | `基金/fund_rate.yaml`, `基金/fund_rate_stat.yaml` | 费率, 管理费率 | 基金/ETF+费率/管理费/托管费/申购费/赎回费/销售服务费 |
| `fund_industry_allocation` -- 基金行业/概念配置 | 210 | 0.85 | `基金/fund_industry_concept_allocation.yaml`, `基金/fund_industry_concept_allocation_latest.yaml` | 行业配置, 概念配置 | 基金/ETF+行业配置/概念配置/行业分布/板块配置/行业持仓 |
| `fund_fof_holding` -- FOF持仓 | 208 | 0.85 | `基金/fof_fund_hold_detail.yaml` | FOF持仓, 基金中基金 | FOF/基金中基金/母基金+持仓/配置/持有/重仓/投向 |
| `fund_block_trading` -- 基金大宗交易 | 207 | 0.82 | `基金/fund_block_trading.yaml` | 基金大宗交易 | 基金/ETF+大宗交易/大宗/折价/溢价 |
| `fund_financial_data` -- 基金财务数据 | 206 | 0.82 | `基金/fund_financial_data.yaml` | 基金财务, 基金财报 | 基金/ETF+财务/财报/利润/资产负债/现金流/收入/成本/费用支出 |
| `fund_basic_info` -- 基金基本信息(兜底) | 205 | 0.82 | `基金/fund_basic_info.yaml` | 基金信息, 基金类型 | 基金/ETF+基本/信息/简介/成立/类型/投资策略/托管/管理 |
| `fund_major_holder` -- 基金大额持有人 | 204 | 0.82 | `基金/fund_major_holder.yaml` | 基金持有人, 大额持有 | 基金/ETF+大额持有/机构持有/持有人结构/持有人/大户/机构占比 |

---

## 5. 基金经理 (priority 250 ~ 280)

| intent_category (意图分类) | 最高优先级 | 置信度 | yaml_scopes (YAML 路径范围) | typical_query_expansions (典型扩展词) | typical_triggers (典型触发词) |
|---|---|---|---|---|---|
| `fund_manager_performance` -- 基金经理业绩/排名 | 275 | 0.90 | `基金经理/fundmanager_latest_index.yaml`, `基金经理/fund_manager_return_risk_level.yaml`, `基金经理/fund_manager_performance_stat.yaml` | 基金经理, 业绩, 排名 | 基金经理+业绩/收益/回报/排名/夏普/回撤/表现/评分 |
| `fund_manager_info` -- 基金经理信息/履历 | 270 | 0.88 | `基金经理/fund_manager_basic_info.yaml`, `基金经理/fund_manager_comprehensive_diagnosis.yaml` | 基金经理, 任职信息 | 基金经理+信息/履历/简介/任职/管理/资历/学历/从业 |
| `fund_manager_holdings` -- 基金经理持仓/重仓 | 265 | 0.88 | `基金经理/fundmanager_hold_detail.yaml`, `基金经理/fundmanager_hold_detail_latest.yaml`, `基金经理/fundmanager_asset_allocation.yaml` | 基金经理持仓, 重仓 | 基金经理+持仓/重仓/配置/持股 |

---

## 6. 基金公司 (priority 280 ~ 300)

| intent_category (意图分类) | 最高优先级 | 置信度 | yaml_scopes (YAML 路径范围) | typical_query_expansions (典型扩展词) | typical_triggers (典型触发词) |
|---|---|---|---|---|---|
| `fund_company_info` -- 基金公司信息/规模 | 295 | 0.88 | `基金公司/fund_company_basic_info.yaml`, `基金公司/fund_company_latest_index.yaml`, `基金公司/fund_company_shares_size.yaml` | 基金公司, 管理规模 | 基金公司/管理人/管理公司+信息/规模/AUM/管理规模/排名/评价/评级/人员 |
| `fund_company_performance` -- 基金公司业绩/产品 | 290 | 0.85 | `基金公司/fund_company_performance_stat.yaml`, `基金公司/fund_company_evaluation.yaml` | 基金公司业绩, 旗下基金 | 基金公司/管理人/管理公司+业绩/收益/旗下/产品数/基金数量 |

---

## 7. 港股 (priority 300 ~ 350)

| intent_category (意图分类) | 最高优先级 | 置信度 | yaml_scopes (YAML 路径范围) | typical_query_expansions (典型扩展词) | typical_triggers (典型触发词) |
|---|---|---|---|---|---|
| `hk_daily_quote` -- 港股日行情/价格 | 345 | 0.90 | `港股/stock_hkstock_mkt_daily_trans.yaml`, `港股/stock_hkstock_mkt_trans_latest.yaml` | 港股行情, 港币 | 港股/恒生指数/恒指/.HK/H股+行情/价格/涨跌/成交/收盘/开盘/K线/走势/换手/量价 |
| `hk_basic_info` -- 港股基本信息 | 340 | 0.88 | `港股/stock_hkstock_basic_info.yaml` | 港股信息, 基本资料 | 港股/恒指/.HK/H股+基本/信息/简介/上市/公司/主营 |
| `hk_financial` -- 港股财务/财报 | 335 | 0.88 | `港股/stock_hkstock_company_financial_data.yaml`, `港股/stock_hkstock_finc_analys.yaml`, `港股/stock_hkstock_finc_analys_latest.yaml` | 港股财报, 财务数据 | 港股/.HK/H股+财报/营收/利润/EPS/ROE/资产负债/现金流/财务 |
| `hk_financial_latest` -- 港股最新财务指标 | 334 | 0.85 | `港股/stock_hkstock_finc_analys_latest.yaml`, `港股/stock_hkstock_finc_analys.yaml` | 港股财务指标, 最新财报 | 港股/.HK/H股+最新财务/最新财报/财务分析/财务指标/PE/PB/PS/市盈率/市净率 |
| `hk_dividend` -- 港股分红/派息 | 330 | 0.88 | `港股/stock_hkstock_annual_dividend.yaml`, `港股/stock_hkstock_annual_dividend_latest.yaml`, `港股/stock_hkstock_dividend_status.yaml` | 港股分红, 股息 | 港股/.HK/H股+分红/派息/股息/红利 |
| `hk_connect` -- 港股通/互联互通 | 325 | 0.90 | `港股/stock_hkstock_shc.yaml`, `港股/stock_hkstock_szc.yaml` | 港股通, 互联互通 | 港股通/沪港通/深港通/南向资金/南下资金+持股/成交/额度/流入/流出/净买入/净流入 |
| `hk_short_selling` -- 港股卖空/沽空 | 320 | 0.88 | `港股/stock_hkstock_parallel_trading.yaml`, `港股/stock_hkstock_mkt_daily_trans.yaml` | 沽空, 卖空 | 沽空, 卖空, 孖展, 做空+比例/金额/数量/成交 |
| `hk_buyback` -- 港股回购 | 318 | 0.85 | `港股/stock_hkstcok_buyback.yaml` | 港股回购 | 港股/.HK/H股+回购/股份回购/回购金额 |
| `hk_financing` -- 港股IPO/融资 | 316 | 0.85 | `港股/stock_hkstock_financing.yaml`, `港股/stock_hkstock_share_capital.yaml` | 港股IPO, 融资 | 港股/.HK/H股+IPO/上市/新股/发行/融资/配股/供股 |
| `hk_investor_hold` -- 港股投资者持股 | 315 | 0.85 | `港股/stock_hkstcok_investor_hold.yaml`, `港股/stock_hkstcok_investor_hold_latest.yaml`, `港股/stock_hkstock_participate_in_holding.yaml` | 投资者持股, 大股东 | 港股/.HK/H股+持股/股东/投资者/大股东/机构 |
| `hk_revenue_composition` -- 港股主营构成 | 314 | 0.82 | `港股/stock_hkstock_main_business_composition.yaml` | 港股主营, 收入构成 | 港股/.HK/H股+主营/收入构成/收入结构/业务构成/主营构成/分产品/分地区 |
| `hk_esg_history` -- 港股ESG/历史统计 | 312 | 0.82 | `港股/stock_hkstock_esg_rating.yaml`, `港股/stock_hkstock_history_statistics.yaml` | ESG, 港股统计 | 港股/.HK/H股+ESG/环境/社会责任/公司治理/历史统计/历史数据/统计汇总 |
| `hk_research` -- 港股研报/评级 | 310 | 0.85 | `港股/stock_hkstock_research_report_rating.yaml`, `港股/stock_hkstock_institutional_performance_forcast.yaml` | 研报, 评级, 目标价 | 港股/.HK/H股+研报/评级/目标价/分析师/研究报告 |
| `hk_performance_forecast` -- 港股业绩预告 | 305 | 0.85 | `港股/stock_hkstock_company_performance_forecast.yaml` | 业绩预告, 盈利预测 | 港股/.HK/H股+业绩预告/盈利预测/预警/业绩快报 |

---

## 8. 美股 (priority 400 ~ 450)

| intent_category (意图分类) | 最高优先级 | 置信度 | yaml_scopes (YAML 路径范围) | typical_query_expansions (典型扩展词) | typical_triggers (典型触发词) |
|---|---|---|---|---|---|
| `us_daily_quote` -- 美股日行情/价格 | 445 | 0.90 | `美股/stock_ustock_mkt_daily_trans.yaml`, `美股/stock_ustock_mkt_daily_trans_latest.yaml` | 美股行情, 美元 | 美股/纳斯达克/纽交所/NYSE/NASDAQ/.US/标普/道琼斯+行情/价格/涨跌/成交/收盘/开盘/K线/走势 |
| `us_basic_info` -- 美股基本信息 | 440 | 0.88 | `美股/stock_ustock_basic_info.yaml` | 美股信息, 基本资料 | 美股/纳斯达克/纽交所/NYSE/NASDAQ/.US+基本/信息/简介/上市/公司/主营 |
| `us_financial` -- 美股财务/财报 | 435 | 0.88 | `美股/stock_ustock_fin_data.yaml`, `美股/stock_ustock_fin_data_new.yaml`, `美股/stock_ustock_finc_analys.yaml` | 美股财报, 财务数据 | 美股/纳斯达克/纽交所/NYSE/NASDAQ/.US+财报/营收/利润/EPS/ROE/资产负债/现金流/财务/revenue/earnings |
| `us_dividend` -- 美股分红/派息 | 430 | 0.88 | `美股/stock_ustock_dividend_fy.yaml`, `美股/stock_ustock_dividend_record.yaml` | 美股分红, 股息 | 美股/纳斯达克/纽交所/NYSE/NASDAQ/.US+分红/派息/股息/红利/dividend |
| `us_shareholding` -- 美股持股/股东 | 425 | 0.85 | `美股/stock_ustock_shareholding.yaml`, `美股/stock_ustock_shareholding_new.yaml`, `美股/stock_ustock_participation_holding.yaml` | 持股, 股东 | 美股/纳斯达克/纽交所/NYSE/NASDAQ/.US+持股/股东/投资者/大股东/机构 |
| `us_forecast` -- 美股预测/展望 | 420 | 0.85 | `美股/stock_ustock_fin_forecast.yaml`, `美股/stock_ustock_research_report_rating.yaml` | 美股预测, 分析师预期 | 美股/纳斯达克/纽交所/NYSE/NASDAQ/.US+预测/预期/展望/分析师/研报/目标价/评级 |
| `us_capital_structure` -- 美股资本结构 | 418 | 0.82 | `美股/stock_ustock_capital_structure.yaml` | 美股资本结构, 股本 | 美股/纳斯达克/纽交所/NYSE/NASDAQ/.US+资本结构/股本/股份/流通股/总股本/市值 |
| `us_offering` -- 美股IPO/发行 | 416 | 0.85 | `美股/stock_ustock_offering.yaml` | 美股IPO, 发行 | 美股/纳斯达克/纽交所/NYSE/NASDAQ/.US+IPO/上市/发行/新股/offering/SPO/二次发行 |
| `us_fda` -- 美股FDA审批 | 415 | 0.90 | `美股/stock_ustock_fda.yaml` | FDA, 药品审批 | FDA, 药品审批, 新药上市, 生物制药, biotech+审批/通过/获批/进展/申请 |
| `us_management` -- 美股管理层 | 414 | 0.82 | `美股/ustock_company_mgmt.yaml` | 美股管理层, 高管 | 美股/纳斯达克/纽交所/NYSE/NASDAQ/.US+管理层/高管/CEO/CFO/董事/管理团队/薪酬 |
| `us_historical_stats` -- 美股历史统计 | 412 | 0.82 | `美股/stock_ustock_historical_statistics.yaml` | 美股历史统计 | 美股/纳斯达克/纽交所/NYSE/NASDAQ/.US+历史统计/历史数据/统计汇总/历史表现 |

---

## 9. 期货 (priority 500 ~ 550)

| intent_category (意图分类) | 最高优先级 | 置信度 | yaml_scopes (YAML 路径范围) | typical_query_expansions (典型扩展词) | typical_triggers (典型触发词) |
|---|---|---|---|---|---|
| `futures_contract` -- 期货合约信息 | 545 | 0.90 | `期货/futu_contract_info.yaml`, `期货/futu_contract_trade_info.yaml` | 期货合约, 合约信息 | 期货/合约+信息/代码/合约规格/交割/保证金/手续费/到期/交易单位 |
| `futures_daily_quote` -- 期货日行情/价格 | 540 | 0.90 | `期货/futu_mkt_daily_quo.yaml`, `期货/futu_mkt_daily_quo_latest.yaml`, `期货/futu_mkt_quo_latest.yaml`, `期货/futu_contract_info.yaml` | 期货行情, 主力合约, 期货 | 期货/主力合约/合约+行情/价格/涨跌/成交/收盘/开盘/结算/持仓量/成交量 (含通用兜底 priority=500) |
| `futures_position` -- 期货持仓/多空 | 535 | 0.88 | `期货/futu_mbr_position_contract_status.yaml`, `期货/futu_mbr_position_contract_status_latest.yaml` | 期货持仓, 多空 | 期货/合约+持仓/多空/净多/净空/多头/空头/持仓量/增仓/减仓 |
| `futures_member_position` -- 期货会员/席位持仓排名 | 530 | 0.88 | `期货/futu_mbr_position_contract_stat.yaml`, `期货/futu_mbr_position_contract_stat_latest.yaml`, `期货/futu_mbr_list.yaml` | 会员持仓, 席位排名 | 期货/合约+会员/席位/排名/龙虎/前20/十大 |
| `futures_spot` -- 期现货/基差/升贴水 | 525 | 0.92 | `期货/futu_contract_spot_status.yaml`, `期货/futu_contract_spot_status_latest.yaml` | 基差, 升贴水, 期现价差 | 基差, 升贴水, 期现, 现货价格, 期货现货, 期现价差 |
| `futures_warehouse` -- 期货仓单 | 520 | 0.88 | `期货/futu_contract_warehouse_receipt_stat.yaml`, `期货/futu_contract_warehouse_receipt_stat_latest.yaml` | 仓单, 库存 | 仓单, 注册仓单, 仓单数量, 仓单变化, 库存 |
| `futures_variety` -- 期货品种/产品信息 | 515 | 0.85 | `期货品种/futu_pdt_info.yaml`, `期货品种/futu_pdt_trade_info.yaml`, `期货品种/futu_pdt_sales_situation_latest.yaml` | 期货品种, 品种 | 期货品种, 品种信息, 商品期货, 金融期货, 农产品期货, 有色金属期货, 黑色系期货, 能源化工期货 |
| `futures_variety_position` -- 期货品种持仓排名 | 510 | 0.85 | `期货品种/futu_mbr_position_variety_status.yaml`, `期货品种/futu_mbr_position_variety_status_latest.yaml`, `期货品种/futu_mbr_position_variety_stat.yaml` | 品种持仓, 品种排名 | 期货品种/品种+持仓/多空/排名/净多/净空 |
| `futures_variety_risk` -- 品种风险 | 508 | 0.82 | `期货品种/futu_variety_risk.yaml` | 品种风险, 波动率 | 期货品种/品种+风险/波动/波动率/VaR/风险指标/风险分析 |
| `futures_variety_spot` -- 品种现货 | 506 | 0.82 | `期货品种/futu_variety_spot_status.yaml` | 品种现货, 现货价格 | 期货品种/品种+现货/现货价/现货状态/产销/供需/库存/产量/消费量 |
| `futures_variety_warehouse` -- 品种仓单明细 | 504 | 0.82 | `期货品种/futu_variety_warehouse_receipt_stat.yaml`, `期货品种/futu_warehosue_receipt_detail.yaml` | 品种仓单, 仓单明细 | 期货品种/品种+仓单/仓单明细/仓单统计/注册仓单/有效仓单 |

---

## 10. 新三板 (priority 700 ~ 750)

| intent_category (意图分类) | 最高优先级 | 置信度 | yaml_scopes (YAML 路径范围) | typical_query_expansions (典型扩展词) | typical_triggers (典型触发词) |
|---|---|---|---|---|---|
| `threeboard_daily_quote` -- 新三板行情/价格 | 745 | 0.90 | `新三板/stock_threeboard_mkt_daily_trans.yaml`, `新三板/stock_threeboard_mkt_trans_latest.yaml` | 新三板行情, 三板 | 新三板/三板/北交所/精选层/创新层/基础层+行情/价格/涨跌/成交/收盘/开盘/走势/换手 |
| `threeboard_basic_info` -- 新三板基本信息 | 740 | 0.88 | `新三板/stock_threeboard_basic_info.yaml` | 新三板信息, 层级 | 新三板/三板/北交所/精选层/创新层/基础层+基本/信息/简介/上市/公司/主营/层级/分层 |
| `threeboard_financial` -- 新三板财务/财报 | 735 | 0.88 | `新三板/stock_threeboard_company_financial_data.yaml` | 新三板财报, 财务数据 | 新三板/三板/北交所+财报/营收/利润/EPS/ROE/资产负债/现金流/财务 |
| `threeboard_dividend` -- 新三板分红/派息 | 730 | 0.88 | `新三板/stock_threeboard_annual_dividend.yaml`, `新三板/stock_threeboard_dividend_status.yaml` | 新三板分红, 股息 | 新三板/三板/北交所+分红/派息/股息/红利/送转 |
| `threeboard_shareholders` -- 新三板股东/持股 | 725 | 0.85 | `新三板/stock_threeboard_top10_shareholders_detail.yaml`, `新三板/stock_threeboard_top10_shareholders_stat.yaml`, `新三板/stock_threeboard_top10_circulate_shareholders_detail.yaml`, `新三板/stock_threeboard_top10_circulate_shareholders_stat.yaml` | 股东, 十大股东 | 新三板/三板/北交所+股东/持股/十大/前十/股东变动 |
| `threeboard_tier_transfer` -- 新三板转板/层级变动 | 720 | 0.88 | `新三板/stock_threeboard_tier_changes.yaml`, `新三板/stock_threeboard_transfer_to_the_board.yaml` | 转板, 层级变动 | 新三板/三板/北交所+转板/层级变动/升层/降层/转A/IPO/转主板 |
| `threeboard_seo` -- 新三板定增/再融资 | 715 | 0.85 | `新三板/stock_threeboard_seo.yaml`, `新三板/stock_threeboard_share_capital.yaml` | 定增, 再融资 | 新三板/三板/北交所+定增/增发/再融资/融资/募集 |
| `threeboard_market_maker` -- 新三板做市商 | 710 | 0.85 | `新三板/stock_threeboard_market_maker.yaml` | 做市商, 转让方式 | 新三板/三板/北交所+做市商/做市/做市转让/协议转让/竞价转让 |
| `threeboard_equity` -- 新三板股权质押/激励 | 705 | 0.85 | `新三板/stock_threeboard_equity_pledge.yaml`, `新三板/stock_threeboard_equity_incentives.yaml`, `新三板/stock_threeboard_equity_transfer.yaml` | 股权质押, 股权激励 | 新三板/三板/北交所+股权质押/质押/股权激励/激励/期权 |

---

## 11. 全量债券 (priority 800 ~ 850)

| intent_category (意图分类) | 最高优先级 | 置信度 | yaml_scopes (YAML 路径范围) | typical_query_expansions (典型扩展词) | typical_triggers (典型触发词) |
|---|---|---|---|---|---|
| `bond_quote` -- 债券行情 | 845 | 0.88 | `全量债券/bond_mkt_quo.yaml`, `全量债券/bond_broker_mkt_quo.yaml`, `全量债券/bond_interbank_mkt_quo.yaml`, `全量债券/bond_sse_fixed_income_platform_quo.yaml` | 债券行情, 收益率, 净价 | 债券/国债/企业债/公司债/信用债/利率债/城投债+行情/价格/涨跌/成交/收盘/收益率/到期收益/报价/净价/全价 |
| `bond_basic_info` -- 债券基本信息/发行 | 840 | 0.88 | `全量债券/bond_basic_info.yaml`, `全量债券/bond_issue_info.yaml`, `全量债券/bond_basic_info_time_params.yaml` | 债券信息, 发行信息 | 债券/国债/企业债/公司债/信用债/利率债/城投债+基本/信息/发行/票面/期限/付息/兑付/规模/面值 |
| `bond_rating` -- 债券评级 | 835 | 0.85 | `全量债券/bond_rate_issuer.yaml`, `全量债券/bond_rate_specified_date.yaml`, `全量债券/bond_latest_bond_rate.yaml`, `全量债券/bond_credit_derivative.yaml` | 债券评级, 信用评级 | 债券/国债/企业债/公司债/信用债+评级/信用评级/主体评级/债项评级/评级变动/违约/信用风险/CDS |
| `bond_valuation` -- 债券估值 | 830 | 0.88 | `全量债券/bond_ccdc_valuation_index.yaml`, `全量债券/bond_cfets_valuation_index.yaml`, `全量债券/bond_csi_valuation_index.yaml`, `全量债券/bond_ihs_valuation.yaml`, `全量债券/bond_yy_valuation_index.yaml` | 债券估值, 中债估值, 久期 | 债券/国债/企业债/公司债/信用债+估值/中债估值/中证估值/收益率曲线/久期/凸性/修正久期/利差/信用利差/期限利差 |
| `bond_holding` -- 债券持仓/持有人 | 825 | 0.85 | `全量债券/bond_fund_hold.yaml`, `全量债券/bond_hold_index.yaml`, `全量债券/bond_institution_restricted.yaml` | 债券持仓, 持有人 | 债券/国债/企业债/公司债/信用债+持仓/持有/基金持债/机构持有/托管/限售 |
| `bond_convertible_abs` -- ABS/资产证券化(债券视角) | 820 | 0.85 | `全量债券/bond_basic_abs.yaml`, `全量债券/bond_basic_abs_spc_data.yaml`, `全量债券/bond_convertible_bond_analysis_index.yaml`, `全量债券/bond_convertible_bond_issue_info.yaml` | ABS, 资产证券化 | ABS, 资产支持证券, 资产证券化, CLO, MBS, RMBS, CMBS |
| `bond_risk_return` -- 债券风险/收益分析 | 815 | 0.82 | `全量债券/bond_risk_return.yaml` | 债券风险, 债券收益 | 债券/国债/企业债/公司债/信用债+风险/收益/回报/夏普/波动/最大回撤/年化收益 |
| `bond_general` -- 债券通用兜底 | 800 | 0.72 | `全量债券/bond_mkt_quo.yaml`, `全量债券/bond_basic_info.yaml` | 债券 | 债券, 国债, 企业债, 公司债, 信用债, 利率债, 城投债, 地方债, 政府债, 金融债, 短融, 超短融, 中票, 中期票据 |

---

## 12. 期权 (priority 850 ~ 870)

| intent_category (意图分类) | 最高优先级 | 置信度 | yaml_scopes (YAML 路径范围) | typical_query_expansions (典型扩展词) | typical_triggers (典型触发词) |
|---|---|---|---|---|---|
| `options_quote` -- 期权行情 | 865 | 0.90 | `期权/options_mkt_daily.yaml`, `期权/options_mkt_lastest.yaml`, `期权/options_mkt_minute.yaml`, `期权/options_mkt_monthly.yaml`, `期权/options_mkt_weekly.yaml` | 期权行情, 隐含波动率 | 期权/认购期权/认沽期权/看涨期权/看跌期权+行情/价格/涨跌/成交/收盘/隐含波动率/IV/Greeks/Delta/Gamma/Vega/Theta |
| `options_basic_info` -- 期权基本信息 | 860 | 0.88 | `期权/options_basics.yaml`, `期权/options_etf_conversion.yaml` | 期权信息, 合约 | 期权/认购期权/认沽期权/看涨/看跌+基本/信息/合约/行权/到期/标的/ETF期权/股指期权/商品期权 |
| `options_general` -- 期权通用兜底 | 850 | 0.75 | `期权/options_mkt_daily.yaml`, `期权/options_basics.yaml` | 期权 | 期权, 认购, 认沽, 行权价, 行权日, 期权链, 波动率微笑, 波动率曲面, 期权定价, Black-Scholes, BS模型 |

---

## 13. 银行理财 (priority 870 ~ 890)

| intent_category (意图分类) | 最高优先级 | 置信度 | yaml_scopes (YAML 路径范围) | typical_query_expansions (典型扩展词) | typical_triggers (典型触发词) |
|---|---|---|---|---|---|
| `bwmp_nav` -- 理财产品行情/净值 | 885 | 0.90 | `银行理财/bwmp_daily_market_data.yaml`, `银行理财/bwmp_daily_market_data_new.yaml`, `银行理财/bwmp_performance_risk_analysis.yaml` | 理财净值, 理财收益 | 银行理财/理财产品/净值型理财+净值/行情/价格/收益/涨跌/回报/七日年化/万份收益/业绩比较基准 |
| `bwmp_basic_info` -- 理财产品信息 | 880 | 0.88 | `银行理财/bwmp_basic_info.yaml`, `银行理财/bwmp_fee_rate_info.yaml`, `银行理财/bwmp_hist_stats.yaml` | 理财产品信息, 费率 | 银行理财/理财产品/净值型理财+基本/信息/期限/类型/风险等级/发行/规模/门槛/起购/费率 |
| `bwmp_holding` -- 理财持仓/配置 | 877 | 0.85 | `银行理财/bwmp_position_detail.yaml`, `银行理财/bwmp_position_detail_new.yaml`, `银行理财/bwmp_share_and_scale_changes.yaml`, `银行理财/bwmp_share_and_scale_changes_new.yaml` | 理财持仓, 投资配置 | 银行理财/理财产品+持仓/配置/投向/资产配置/债券配置/股票配置/份额/规模变动 |
| `bwmp_general` -- 银行理财通用兜底 | 870 | 0.72 | `银行理财/bwmp_daily_market_data.yaml`, `银行理财/bwmp_basic_info.yaml` | 银行理财 | 银行理财, 理财产品, 净值型理财, 固收理财, 固定收益理财, 理财到期, 理财赎回, 理财风险等级R1-R5 |

---

## 14. 外盘期货 (priority 890 ~ 910)

| intent_category (意图分类) | 最高优先级 | 置信度 | yaml_scopes (YAML 路径范围) | typical_query_expansions (典型扩展词) | typical_triggers (典型触发词) |
|---|---|---|---|---|---|
| `foreign_futures_quote` -- 外盘期货行情 | 905 | 0.90 | `外盘期货/futu_mkt_daily_quo_foris.yaml`, `外盘期货/futu_mkt_monthly_quo_foris.yaml`, `外盘期货/futu_mkt_weekly_quo_foris.yaml`, `外盘期货/futu_mkt_yearly_quo_foris.yaml` | 外盘期货行情, 外盘 | 外盘期货, 伦铜, 伦铝, 伦锌, 伦镍, 伦铅, 伦锡, WTI, 布伦特, Brent, COMEX, LME, NYMEX, ICE, CME |
| `foreign_futures_general` -- 外盘期货通用兜底 | 890 | 0.75 | `外盘期货/futu_mkt_daily_quo_foris.yaml`, `外盘期货/futu_contract_info_foris.yaml` | 外盘期货 | 外盘期货, 外盘, 伦敦金属, 纽约原油, 芝加哥, 外盘合约 |

---

## 15. 市场环境 (priority 910 ~ 930)

| intent_category (意图分类) | 最高优先级 | 置信度 | yaml_scopes (YAML 路径范围) | typical_query_expansions (典型扩展词) | typical_triggers (典型触发词) |
|---|---|---|---|---|---|
| `market_calendar_events` -- 交易日历/经济事件 | 925 | 0.88 | `市场环境/pub_sec_mkt_trade_calendar.yaml`, `市场环境/pub_sec_mkt_economic_events.yaml` | 交易日历, 经济事件 | 交易日历, 休市安排, 开市安排, 节假日安排, 经济事件, CPI发布, GDP发布, PMI发布, 非农, FOMC, 美联储, 降息, 加息, MLF, LPR, 公开市场操作 |
| `market_sentiment` -- 市场分析/情绪 | 920 | 0.85 | `市场环境/pub_sec_mkt_trade_performance.yaml`, `市场环境/pub_sec_mkt_travel_capital.yaml`, `市场环境/stock_astock_evaluate_new_fortune.yaml` | 市场情绪, 市场分析 | 市场温度, 市场情绪, 大盘情绪, 赚钱效应, 涨跌家数, 涨停数, 跌停数, 新财富, 旅游资金, 交易活跃度 |
| `market_env_general` -- 市场环境通用兜底 | 910 | 0.72 | `市场环境/pub_sec_mkt_trade_calendar.yaml`, `市场环境/pub_sec_mkt_trade_performance.yaml`, `市场环境/private_product_nav.yaml` | 市场环境 | 市场环境, 宏观环境, 大盘环境, 交易环境, 私募产品净值 |

---

## 16. 同花顺保险 (priority 930 ~ 940)

| intent_category (意图分类) | 最高优先级 | 置信度 | yaml_scopes (YAML 路径范围) | typical_query_expansions (典型扩展词) | typical_triggers (典型触发词) |
|---|---|---|---|---|---|
| `insurance_product` -- 保险产品 | 935 | 0.85 | `同花顺保险/insurance_basic.yaml`, `同花顺保险/insurance_protection_plan.yaml` | 保险产品, 保险 | 保险, 保险产品, 寿险, 财险, 车险, 健康险, 意外险, 医疗险, 重疾险, 年金险, 万能险, 投连险, 保障计划, 保险条款, 保费, 赔付, 理赔 |

---

## 17. 英股 (priority 940 ~ 950)

| intent_category (意图分类) | 最高优先级 | 置信度 | yaml_scopes (YAML 路径范围) | typical_query_expansions (典型扩展词) | typical_triggers (典型触发词) |
|---|---|---|---|---|---|
| `uk_stock_ipo` -- 英股IPO | 945 | 0.85 | `英股/stock_ukstock_ipo.yaml` | 英股, IPO | 英股, 伦敦证券, LSE, 伦交所, 英国上市, FTSE, 富时 |

---

## 18. 通用兜底 (`_MARKET_FALLBACKS`) -- 对比类查询多市场补全

> 以下条目来自 `_MARKET_FALLBACKS` 字典，用于对比类查询下当精确规则无法命中某个显式市场时，自动补齐多意图输出。

| market (市场) | fallback_intent | 置信度 | yaml_scopes (YAML 路径范围) | typical_query_expansions (典型扩展词) |
|---|---|---|---|---|
| A股 | `price_change` | 0.68 | `股票/stock_astock_mkt_daily_trans.yaml`, `股票/stock_astock_latest_index.yaml` | A股, 行情, 涨跌 |
| 港股 | `hk_daily_quote` | 0.78 | `港股/stock_hkstock_mkt_daily_trans.yaml`, `港股/stock_hkstock_mkt_trans_latest.yaml` | 港股, 行情, 涨跌 |
| 美股 | `us_daily_quote` | 0.78 | `美股/stock_ustock_mkt_daily_trans.yaml`, `美股/stock_ustock_mkt_daily_trans_latest.yaml` | 美股, 行情, 涨跌 |
| 基金 | `fund_nav` | 0.80 | `基金/fund_mkt_daily_trans_latest.yaml`, `基金/fund_mkt_daily_trans.yaml`, `基金/fund_basic_info.yaml` | 基金, 净值 |
| 期货 | `futures_daily_quote` | 0.80 | `期货/futu_mkt_daily_quo_latest.yaml`, `期货/futu_mkt_daily_quo.yaml` | 期货, 主力合约, 行情 |
| 可转债 | `cb_market` | 0.80 | `可转债/convertiblebond_market.yaml`, `可转债/convertiblebond_market_new.yaml` | 可转债, 行情 |
| 指数 | `index_quote` | 0.78 | `全量指数/index_mkt_daily_trans.yaml`, `全量指数/index_latest_index.yaml` | 指数, 行情 |
| 新三板 | `threeboard_daily_quote` | 0.78 | `新三板/stock_threeboard_mkt_daily_trans.yaml`, `新三板/stock_threeboard_mkt_trans_latest.yaml` | 新三板, 三板, 行情 |
| 基金公司 | `fund_company_info` | 0.78 | `基金公司/fund_company_basic_info.yaml`, `基金公司/fund_company_latest_index.yaml` | 基金公司, 管理规模 |
| 基金经理 | `fund_manager_performance` | 0.78 | `基金经理/fundmanager_latest_index.yaml`, `基金经理/fund_manager_basic_info.yaml` | 基金经理, 业绩 |
| 期货品种 | `futures_variety` | 0.78 | `期货品种/futu_pdt_info.yaml`, `期货品种/futu_pdt_trade_info.yaml` | 期货品种, 品种 |
| 全量债券 | `bond_quote` | 0.78 | `全量债券/bond_mkt_quo.yaml`, `全量债券/bond_basic_info.yaml` | 债券, 行情 |
| 期权 | `options_quote` | 0.78 | `期权/options_mkt_daily.yaml`, `期权/options_basics.yaml` | 期权, 行情 |
| 银行理财 | `bwmp_nav` | 0.78 | `银行理财/bwmp_daily_market_data.yaml`, `银行理财/bwmp_basic_info.yaml` | 银行理财, 理财产品 |

---

## 附录: 统计摘要

| 维度 | 数量 |
|---|---|
| RouterRule 总条数 | 142 |
| 去重后 intent 数 | ~111 |
| 覆盖市场数 | 17 (A股, 可转债, 全量指数, 基金, 基金经理, 基金公司, 港股, 美股, 期货, 期货品种, 新三板, 全量债券, 期权, 银行理财, 外盘期货, 市场环境, 同花顺保险, 英股) |
| 市场兜底条数 | 14 (`_MARKET_FALLBACKS`) |
| YAML 路径总数 (去重) | ~160+ |
| 优先级范围 | 45 ~ 945 |

### Ensemble 路由架构 (LLM + Rule-based Fusion)

Pipeline 采用 **ensemble 融合**，LLM 路由与规则路由始终同时运行，结果合并：

```
Query
  ├─ LLM 路由 (agent 提供)  → {intent, yaml_scopes, query_expansions, confidence}
  ├─ 规则路由 (regex-based)  → {intent, yaml_scopes, query_expansions, confidence}
  └─ Ensemble 融合:
       ├─ market: 规则路由为锚 (regex 无幻觉)
       ├─ yaml_scopes: 高置信 LLM 才能扩 scope；与规则有交集时取交集，低置信冲突时保留规则 scope
       ├─ query_expansions: 规则路由优先；LLM 仅在高置信或 scope 对齐时补充
       └─ confidence: 高置信融合才做 agreement 调整，低置信冲突不拉低规则置信度
                        ↓
         ┌──────────────┼────────────────────┐
         ↓              ↓                    ↓
   BM25 (w=3.0)    Vector Scoped (w=1.0)  Vector Global (w=1.0)
   market 软过滤    yaml_path 过滤         无过滤
   (全域搜索)       (Ensemble 偏置)        (全域搜索)
         ↓              ↓                    ↓
         └──────── RRF Fusion ───────────────┘
                        ↓
   Ensemble 推荐表: 出现在 BM25 + Scoped + Global = 3路 (自然 boost)
   其他相关表:    出现在 BM25 + Global = 2路 (仍有竞争力)
```

**设计原则**：
- 规则路由提供可靠的 market 锚定和领域专有扩展词（446 条 regex，零幻觉）。
- LLM 路由提供语义理解和长尾意图识别（规则难以覆盖的模糊查询）。
- 两者互补而非互斥：BM25 的 term matching 天然将相关列排在前面，ensemble 提供偏置而非硬过滤。

### 隐式 A股 信号 (Fallback 层)

当全部 141 条规则均未命中时，若 query 包含以下信号词之一，`DomainRouter` 将推断为 A股 查询（通过 `_ASTOCK_IMPLICIT_SIGNALS` 和 `ASTOCK_JARGON_SET`）：

- **技术形态 Jargon**: 青龙取水, 龙腾四海, 空方炮, 多方炮, 仙人指路, 三元联动, 金针探底, 老鸭头, 蛟龙出海, ...（共 80+ 个同花顺自创形态/指标名）
- **隐式信号关键词**: 涨停, 跌停, 连板, 封板, 炸板, 打板, 龙头股, 妖股, 牛散, 游资, 主力, 控盘, 金叉, 死叉, 均线, MACD, KDJ, RSI, BOLL, 融资, 融券, 北向, 陆股通, 概念股, 板块, ST, 退市, 商誉, 质押, 解禁, 年报, 季报, 大阳, 大阴, 放量, 缩量, 十字星, 个股, 筹码, 资金流, 委比, 换手率, 量比, A股, 沪市, 深市, 创业板, 科创板, 龙虎榜, 大宗交易, 回购, 分红, 十大股东, 市盈率, 市净率, PB, PE, 成交量, 成交额, 威廉指数, WR, OBV, CCI, DMI, TRIX, ...
