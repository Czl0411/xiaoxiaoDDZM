const $ = (id) => document.getElementById(id);

let config = {};
var sysCmds = [
  { key: "checkin", name: "签到", tk: "checkin_commands",
    tpls: [{ id: "checkinReply", lb: "签到成功回复", nt: "{user}=用户昵称 {streak}=连续天数 {reward}=本次奖励 {balance}=当前余额 {currency}=货币名" },
           { id: "checkinRepeatReply", lb: "重复签到回复", nt: "{user}=用户昵称 {streak}=连续天数 {balance}=当前余额 {currency}=货币名" },
           { id: "checkinDisabledReply", lb: "签到关闭回复" }],
    nums: [{ id: "checkinBaseReward", lb: "基础奖励" }, { id: "checkinStreakBonus", lb: "连续签到加成" }],
    sw: "checkin_enabled"
  },
  { key: "balance", name: "余额", tk: "balance_commands",
    tpls: [{ id: "balanceReply", lb: "余额回复", nt: "{user}=用户昵称 {balance}=当前余额 {currency}=货币名" }]
  },
  { key: "facilityWageClaim", name: "领取工资", tk: "facility_wage_claim_commands",
    tpls: [
      { id: "facilityWageClaimSuccessReply", lb: "领取成功回复", nt: "{user}=用户称呼 {wage_date}=工资日期 {amount}=工资合计 {balance}=当前余额 {keyword}=匹配规则 {match_count}=匹配数量 {wage_details}=逐条工资明细 {currency}=货币名" },
      { id: "facilityWageClaimNoActivityReply", lb: "昨日未发言回复", nt: "{user}=用户称呼" },
      { id: "facilityWageClaimIneligibleReply", lb: "昵称不合规回复", nt: "{user}=用户称呼" },
      { id: "facilityWageClaimAlreadyReply", lb: "重复领取回复", nt: "{user}=用户称呼 {wage_date}=工资日期" },
      { id: "facilityWageClaimNoRulesReply", lb: "无启用规则回复" }
    ]
  },
  { key: "shop", name: "商店", tk: "shop_commands",
    tpls: [{ id: "shopHeader", lb: "商店标题" }, { id: "shopItemLine", lb: "商品行模板", nt: "{number}=商品序号 {item}=商品名 {price}=价格 {stock}=库存 {description}=商品说明 {currency}=货币名" },
           { id: "shopFooter", lb: "商店底部提示" }, { id: "shopEmptyReply", lb: "商店为空回复" }, { id: "shopDisabledReply", lb: "商店关闭回复" }],
    sw: "shop_enabled"
  },
  { key: "buy", name: "购买", tk: "buy_commands",
    tpls: [{ id: "purchaseSuccessReply", lb: "购买成功回复", nt: "{user}=用户昵称 {item}=商品名 {price}=价格 {balance}=当前余额 {currency}=货币名" },
           { id: "purchaseNoItemReply", lb: "商品不存在回复" }, { id: "purchaseNoStockReply", lb: "库存不足回复" },
           { id: "purchaseNoMoneyReply", lb: "余额不足回复", nt: "{user}=用户昵称 {missing}=差额 {currency}=货币名" },
           { id: "buyUsageReply", lb: "格式错误回复" }]
  },
  { key: "inventory", name: "背包", tk: "inventory_commands",
    tpls: [{ id: "inventoryHeader", lb: "背包标题", nt: "{user}=用户昵称" },
           { id: "inventoryItemLine", lb: "背包物品行", nt: "{number}=物品序号 {item}=物品名 {quantity}=数量" },
           { id: "inventoryEmptyReply", lb: "背包为空回复" }]
  },
  { key: "profile", name: "个人信息", tk: "profile_commands",
    tpls: [{ id: "profileReply", lb: "个人信息回复", nt: "{title}=用户称呼 {balance}=当前余额 {checkins}=签到次数 {statuses}=状态列表 {contracts}=奴隶契约关系 {newline}=换行符" },
           { id: "debtStatusTemplate", lb: "负债状态模板", nt: "{user}=用户称呼 {debt}=欠债金额 {balance}=当前余额 {currency}=货币名" }]
  },
  { key: "slaveContractRequest", name: "发起奴隶契约", tk: "slave_contract_request_commands",
    tpls: [
      { id: "slaveContractUsageReply", lb: "命令格式提示" },
      { id: "slaveContractRequestReply", lb: "申请发布回复", nt: "{borrower}=欠款人 {lender}=放款人 {amount}=金额 {currency}=货币名" },
      { id: "slaveContractTargetNotFoundReply", lb: "目标不存在回复", nt: "{target}=输入的称呼" },
      { id: "slaveContractSelfReply", lb: "不能和自己签约提示" },
      { id: "slaveContractBorrowerLimitReply", lb: "欠款人已有主人提示" },
      { id: "slaveContractBorrowerPendingReply", lb: "欠款人已有待确认申请提示" },
      { id: "slaveContractLenderLimitReply", lb: "主人达到奴隶上限提示", nt: "{lender}=主人 {max_slaves}=最多奴隶数" },
      { id: "slaveContractLenderPendingReply", lb: "放款人已有待确认申请提示", nt: "{lender}=放款人" },
      { id: "slaveContractStatusTemplate", lb: "奴隶强制状态模板", nt: "{lender}=主人 {amount}=欠款 {currency}=货币名" },
      { id: "slaveContractProfileHeader", lb: "/我 契约标题" },
      { id: "slaveContractProfileMasterLine", lb: "/我 主人关系行", nt: "{lender}=主人 {amount}=欠款 {currency}=货币名" },
      { id: "slaveContractProfileSlaveLine", lb: "/我 奴隶关系行", nt: "{number}=序号 {borrower}=奴隶 {amount}=欠款 {currency}=货币名" }
    ],
    nums: [
      { id: "slaveContractMaxSlaves", key: "slave_contract_max_slaves", lb: "每位主人最多拥有奴隶数", min: 1, max: 100 }
    ]
  },
  { key: "slaveContractAgree", name: "同意奴隶契约", tk: "slave_contract_agree_commands",
    tpls: [
      { id: "slaveContractAgreeNoPendingReply", lb: "没有待确认申请提示" },
      { id: "slaveContractAgreeNoMoneyReply", lb: "放款余额不足提示", nt: "{lender}=放款人 {amount}=金额 {balance}=余额 {currency}=货币名" },
      { id: "slaveContractAgreeSuccessReply", lb: "契约成立回复", nt: "{lender}=主人 {borrower}=奴隶 {amount}=金额 {lender_balance}=主人余额 {borrower_balance}=奴隶余额" }
    ]
  },
  { key: "slaveContractReject", name: "拒绝奴隶契约", tk: "slave_contract_reject_commands",
    tpls: [
      { id: "slaveContractRejectNoPendingReply", lb: "没有待确认申请提示" },
      { id: "slaveContractRejectSuccessReply", lb: "拒绝成功回复", nt: "{lender}=被申请人 {borrower}=申请人 {amount}=金额 {currency}=货币名" }
    ]
  },
  { key: "slaveContractRepay", name: "偿还奴隶契约", tk: "slave_contract_repay_commands",
    tpls: [
      { id: "slaveContractRepayNoneReply", lb: "没有契约提示" },
      { id: "slaveContractRepayNoMoneyReply", lb: "还款余额不足提示", nt: "{borrower}=欠款人 {amount}=应还 {balance}=余额 {missing}=还差 {currency}=货币名" },
      { id: "slaveContractRepaySuccessReply", lb: "还款成功回复", nt: "{borrower}=原奴隶 {lender}=原主人 {amount}=金额 {borrower_balance}=还款后余额" }
    ]
  },
  { key: "status", name: "我的状态", tk: "status_commands",
    tpls: [{ id: "statusHeader", lb: "状态标题", nt: "{user}=用户昵称" }, { id: "statusEmptyReply", lb: "无状态回复" }]
  },
  { key: "debtList", name: "欠债便器人员列表", tk: "debt_list_commands",
    tpls: [{ id: "debtListHeader", key: "debt_list_header", lb: "列表标题", default: "当前欠债便器人员列表：" },
           { id: "debtListItemLine", key: "debt_list_item_line", lb: "列表每行模板", default: "{number}. {target}：欠债 {debt} {currency}（余额 {balance}）", nt: "{number}=序号 {target}=用户称呼 {debt}=欠债金额 {balance}=当前余额 {currency}=货币名" },
           { id: "debtListEmptyReply", key: "debt_list_empty_reply", lb: "空列表回复", default: "当前没有欠债人员。" }]
  },
  { key: "removeStatus", name: "解除状态", tk: "remove_status_commands",
    tpls: [{ id: "removeStatusSuccessReply", lb: "解除成功回复", nt: "{user}=用户昵称 {status}=状态文本 {price}=解除价格 {balance}=当前余额 {currency}=货币名" },
           { id: "removeStatusNoMoneyReply", lb: "余额不足回复" }, { id: "removeStatusUsageReply", lb: "格式错误回复" }]
  },
  { key: "myTitle", name: "我的称呼", tk: "my_title_commands",
    tpls: [{ id: "myTitleReply", lb: "称呼回复", nt: "{user}=用户昵称 {title}=当前称呼" }]
  },
  { key: "setTitle", name: "自定义称呼", tk: "set_title_commands",
    tpls: [{ id: "setTitleSuccessReply", lb: "设置成功回复", nt: "{title}=新称呼内容" }]
  },
  { key: "redPacket", name: "红包", tk: "send_red_packet_commands", tk2: "claim_red_packet_commands",
    tpls: [{ id: "redPacketCreatedReply", lb: "发红包成功回复", nt: "{user}=用户昵称 {amount}=红包金额 {count}=红包个数 {currency}=货币名" },
           { id: "redPacketUsageReply", lb: "发红包格式提示", nt: "管理员格式：/发红包100金币10个，表示总额 100 金币随机拆成 10 份" },
           { id: "redPacketAdminOnlyReply", lb: "非管理员提示", nt: "普通群友尝试发红包时回复" },
           { id: "redPacketClaimReply", lb: "抢红包成功回复", nt: "{user}=用户昵称 {amount}=抢到金额 {balance}=当前余额 {currency}=货币名" },
           { id: "redPacketEmptyReply", lb: "红包抢完回复" }, { id: "redPacketNoneReply", lb: "无红包回复" },
           { id: "redPacketClaimedReply", lb: "重复抢回复" }]
  },
  { key: "givePoints", name: "赠送金币", tk: "give_points_commands",
    tpls: [{ id: "givePointsSuccessReply", lb: "赠送成功回复", nt: "{user}=管理员称呼 {target}=目标称呼 {amount}=赠送金币 {balance}=目标余额 {currency}=货币名" },
           { id: "givePointsUsageReply", lb: "格式提示", nt: "示例：/赠送大祭司100" },
           { id: "givePointsTargetNotFoundReply", lb: "目标不存在回复", nt: "{target}=目标称呼 {currency}=货币名" },
           { id: "givePointsAdminOnlyReply", lb: "非管理员提示" }]
  },
  { key: "finePoints", name: "罚款", tk: "fine_points_commands",
    tpls: [
      { id: "finePointsSuccessReply", lb: "罚款成功回复", nt: "{user}=管理员称呼 {target}=目标称呼 {amount}=罚款数量 {balance}=目标余额 {currency}=货币名" },
      { id: "finePointsUsageReply", lb: "格式提示", nt: "示例：/罚款大祭司5" },
      { id: "finePointsTargetNotFoundReply", lb: "目标不存在回复", nt: "{target}=输入的昵称或称呼" },
      { id: "finePointsAdminOnlyReply", lb: "非管理员提示" },
      { id: "finePointsLimitReply", lb: "余额下限提示", nt: "{target}=目标称呼 {min_balance}=最低余额 {currency}=货币名" }
    ],
    nums: [
      { id: "finePointsMinBalance", key: "fine_points_min_balance", lb: "罚款后最低余额", min: -100000, max: 0 }
    ]
  },
  { key: "otherStatus", name: "查询他人状态", tk: "other_status_commands",
    tpls: [
      { id: "otherStatusNotFoundReply", lb: "目标不存在回复", nt: "{target}=目标名称" },
      { id: "otherStatusEmptyReply", lb: "无状态回复", nt: "{target}=目标名称" },
      { id: "otherStatusHeader", lb: "状态标题", nt: "{target}=目标名称" },
      { id: "otherStatusItemLine", lb: "状态条目行", nt: "{number}=序号 {status}=状态文案 {price}=解除价格 {currency}=货币名" }
    ]
  },
  { key: "begTip", name: "乞讨 / 打赏", tk: "beg_commands", tk2: "tip_commands",
    tpls: [{ id: "begReply", key: "beg_reply", lb: "乞讨成功回复", default: "{user}跑到门口，捧起自己的乞讨碗，眼巴巴地向群友乞讨。群友可发送 /打赏10 给TA一点{currency}。", nt: "{user}=乞讨者 {balance}=当前余额 {currency}=货币名" },
           { id: "begFailureReply", key: "beg_failure_reply", lb: "乞讨失败回复", default: "🚨 {user} 第 {attempt} 次出门求助，没想到先遇上了假慈善推销，损失 {loss} {currency}。当前功德点：{balance}。（本次失败，无法接受打赏）", nt: "{user}=乞讨者 {attempt}=今日第几次 {risk}=失败风险百分比 {loss}=损失数量 {balance}=失败后余额 {currency}=货币名" },
           { id: "begTooRichReply", key: "beg_too_rich_reply", lb: "余额充足提示", default: "{user}，你当前还有 {balance} {currency}，金币充足就别好吃懒做了。", nt: "{user}=用户 {balance}=当前余额 {currency}=货币名" },
           { id: "begActiveReply", key: "beg_active_reply", lb: "已有乞讨者提示", default: "{target}已经在乞讨了，5 分钟内只能有一个人乞讨。群友可发送 /打赏10 给TA一点{currency}。", nt: "{target}=当前乞讨者 {currency}=货币名" },
           { id: "tipSuccessReply", key: "tip_success_reply", lb: "打赏成功回复", default: "{giver} 打赏了 {target} {amount} {currency}。{target} 当前余额 {balance} {currency}。", nt: "{giver}=打赏者 {target}=乞讨者 {amount}=金额 {balance}=乞讨者余额 {currency}=货币名" },
           { id: "tipUsageReply", key: "tip_usage_reply", lb: "打赏格式提示", default: "请发送 /打赏10，给当前正在乞讨的人打赏。" },
           { id: "tipNoBeggarReply", key: "tip_no_beggar_reply", lb: "无人乞讨提示", default: "当前没有人在乞讨。" },
           { id: "tipSelfReply", key: "tip_self_reply", lb: "不能打赏自己提示", default: "不能给自己打赏，碗都端手里了还想左手倒右手。" },
           { id: "tipNoMoneyReply", key: "tip_no_money_reply", lb: "打赏者余额不足提示", default: "{user}，你余额不足，当前只有 {balance} {currency}。", nt: "{user}=打赏者 {balance}=当前余额 {amount}=打赏金额 {currency}=货币名" }],
    nums: [{ id: "begMaxBalance", lb: "可乞讨最高余额" }]
  },
  { key: "theft", name: "偷窃", tk: "theft_commands",
    tpls: [
      { id: "theftUsageReply", key: "theft_usage_reply", lb: "命令格式提示", nt: "{daily_limit}=每日次数上限" },
      { id: "theftSelfReply", key: "theft_self_reply", lb: "偷自己提示", nt: "{user}=发起者" },
      { id: "theftTargetNotFoundReply", key: "theft_target_not_found_reply", lb: "目标不存在提示", nt: "{target}=输入的目标称呼" },
      { id: "theftActorBalanceReply", key: "theft_actor_balance_reply", lb: "发起者功德点不足提示", nt: "{user}=发起者 {min_points}=最低要求 {balance}=当前功德点 {currency}=货币名" },
      { id: "theftDailyLimitReply", key: "theft_daily_limit_reply", lb: "每日次数用尽提示", nt: "{user}=发起者 {attempts}=已尝试次数 {daily_limit}=每日上限" },
      { id: "theftTargetFloorReply", key: "theft_target_floor_reply", lb: "目标已到负债下限提示", nt: "{target}=目标 {balance}=目标功德点 {currency}=货币名" },
      { id: "theftSuccessReply", key: "theft_success_reply", lb: "普通偷窃成功回复", nt: "{user}=发起者 {target}=目标 {amount}=实际金额 {actor_balance}=发起者余额 {target_balance}=目标余额 {currency}=货币名" },
      { id: "theftCaughtReply", key: "theft_caught_reply", lb: "普通偷窃失败回复", nt: "{user}=发起者 {target}=目标 {amount}=赔偿金额 {actor_balance}=发起者余额 {target_balance}=目标余额 {currency}=货币名" },
      { id: "theftSingleProtectedReply", key: "theft_single_protected_reply", lb: "单次防偷券触发回复", nt: "{user}=发起者 {target}=目标 {protection_remaining}=剩余防护次数" },
      { id: "theftMultiProtectedReply", key: "theft_multi_protected_reply", lb: "多次防偷券触发回复", nt: "{user}=发起者 {target}=目标 {protection_remaining}=剩余防护次数" },
      { id: "theftSpecialSuccessReply", key: "theft_special_success_reply", lb: "绝对掠夺成功回复", nt: "{user}=发起者 {target}=目标 {amount}=实际金额 {actor_balance}=发起者余额 {target_balance}=目标余额 {currency}=货币名" },
      { id: "theftSpecialProtectedReply", key: "theft_special_protected_reply", lb: "绝对掠夺被抵挡回复", nt: "{user}=发起者 {target}=目标 {protection_item}=防护券名 {protection_remaining}=剩余防护次数" },
      { id: "theftSpecialItemMissingReply", key: "theft_special_item_missing_reply", lb: "绝对掠夺物品无效提示", nt: "{user}=发起者" }
    ],
    nums: [
      { id: "theftDailyLimit", key: "theft_daily_limit", lb: "每日最多偷窃次数" },
      { id: "theftSuccessRate", key: "theft_success_rate", lb: "普通偷窃成功率（%）" },
      { id: "theftMinPoints", key: "theft_min_points", lb: "发起偷窃最低功德点（必须高于）" },
      { id: "theftActorDebtLimit", key: "theft_actor_debt_limit", lb: "失败赔偿最低余额" },
      { id: "theftTargetDebtLimit", key: "theft_target_debt_limit", lb: "被偷者最低余额" }
    ]
  }
];

var gameCmds = [
  { key: "rps", name: "石头剪刀布", icon: "🎮", tk: "rock_paper_scissors_commands", sw: "game_rps_enabled", triggerDefault: "/石头剪刀布,/rps",
    tpls: [
      { id: "game_rps_win_reply", lb: "胜利回复", default: "🎮 石头剪刀布 ══════════{newline}👤 {user} 下注：{bet} {currency}{newline}🤖 系统出了：{system_choice}{newline}👤 你出了：{user_choice}{newline}🎉 你赢了！获得 {win_amount} {currency}{newline}💰 当前余额：{balance} {currency}", nt: "{user}={bet}={system_choice}={user_choice}={win_amount}={balance}={currency}" },
      { id: "game_rps_lose_reply", lb: "失败回复", default: "🎮 石头剪刀布 ══════════{newline}👤 {user} 下注：{bet} {currency}{newline}🤖 系统出了：{system_choice}{newline}👤 你出了：{user_choice}{newline}😢 你输了！损失 {bet} {currency}{newline}💰 当前余额：{balance} {currency}", nt: "{user}={bet}={system_choice}={user_choice}={balance}={currency}" },
      { id: "game_rps_draw_reply", lb: "平局回复", default: "🎮 石头剪刀布 ══════════{newline}👤 {user} 下注：{bet} {currency}{newline}🤖 系统出了：{system_choice}{newline}👤 你出了：{user_choice}{newline}🤝 平局！已退还 {bet} {currency}{newline}💰 当前余额：{balance} {currency}", nt: "{user}={bet}={system_choice}={user_choice}={balance}={currency}" }
    ]
  },
  { key: "zjh", name: "炸金花", icon: "🃏", tk: "zha_jin_hua_commands", sw: "game_zjh_enabled", triggerDefault: "/炸金花,/zjh",
    nums: [{ id: "game_zjh_win_rate", lb: "玩家胜率（%）", min: 0, max: 100, default: 40 }],
    tpls: [
      { id: "game_zjh_win_reply", lb: "胜利回复", default: "🃏 炸金花 ════════════{newline}👤 {user} 下注：{bet} {currency}{newline}{newline}🤖 系统手牌：{system_cards}{newline}   牌型：{system_hand_type}{newline}👤 你的手牌：{user_cards}{newline}   牌型：{user_hand_type}{newline}{newline}🎉 你赢了！获得 {win_amount} {currency}{newline}💰 当前余额：{balance} {currency}", nt: "{user}={bet}={system_cards}={system_hand_type}={user_cards}={user_hand_type}={win_amount}={balance}={currency}" },
      { id: "game_zjh_lose_reply", lb: "失败回复", default: "🃏 炸金花 ════════════{newline}👤 {user} 下注：{bet} {currency}{newline}{newline}🤖 系统手牌：{system_cards}{newline}   牌型：{system_hand_type}{newline}👤 你的手牌：{user_cards}{newline}   牌型：{user_hand_type}{newline}{newline}😢 你输了！损失 {bet} {currency}{newline}💰 当前余额：{balance} {currency}", nt: "{user}={bet}={system_cards}={system_hand_type}={user_cards}={user_hand_type}={balance}={currency}" },
      { id: "game_zjh_draw_reply", lb: "平局回复", default: "🃏 炸金花 ════════════{newline}👤 {user} 下注：{bet} {currency}{newline}{newline}🤖 系统手牌：{system_cards}{newline}   牌型：{system_hand_type}{newline}👤 你的手牌：{user_cards}{newline}   牌型：{user_hand_type}{newline}{newline}🤝 平局！已退还 {bet} {currency}{newline}💰 当前余额：{balance} {currency}", nt: "{user}={bet}={system_cards}={system_hand_type}={user_cards}={user_hand_type}={balance}={currency}" }
    ]
  },
  { key: "dice", name: "骰子比大小", icon: "🎲", tk: "dice_commands", sw: "game_dice_enabled", triggerDefault: "/骰子比大小,/骰子,/dice",
    tpls: [
      { id: "game_dice_win_reply", lb: "胜利回复", default: "🎲 骰子比大小 ══════════{newline}👤 {user} 下注：{bet} {currency}{newline}{newline}🤖 系统骰子：{system_dice}{newline}   点数合计：{system_total}{newline}👤 你的骰子：{user_dice}{newline}   点数合计：{user_total}{newline}{newline}🎉 你赢了！获得 {win_amount} {currency}{newline}💰 当前余额：{balance} {currency}", nt: "{user}={bet}={system_dice}={system_total}={user_dice}={user_total}={win_amount}={balance}={currency}" },
      { id: "game_dice_lose_reply", lb: "失败回复", default: "🎲 骰子比大小 ══════════{newline}👤 {user} 下注：{bet} {currency}{newline}{newline}🤖 系统骰子：{system_dice}{newline}   点数合计：{system_total}{newline}👤 你的骰子：{user_dice}{newline}   点数合计：{user_total}{newline}{newline}😢 你输了！损失 {bet} {currency}{newline}💰 当前余额：{balance} {currency}", nt: "{user}={bet}={system_dice}={system_total}={user_dice}={user_total}={balance}={currency}" },
      { id: "game_dice_draw_reply", lb: "平局回复", default: "🎲 骰子比大小 ══════════{newline}👤 {user} 下注：{bet} {currency}{newline}{newline}🤖 系统骰子：{system_dice}{newline}   点数合计：{system_total}{newline}👤 你的骰子：{user_dice}{newline}   点数合计：{user_total}{newline}{newline}🤝 平局！已退还 {bet} {currency}{newline}💰 当前余额：{balance} {currency}", nt: "{user}={bet}={system_dice}={system_total}={user_dice}={user_total}={balance}={currency}" }
    ]
  },
  { key: "battle_zjh", name: "炸金花群对战", icon: "👥", tk: "battle_zjh_create_commands", tk2: "battle_join_commands", sw: "battle_zjh_enabled",
    nums: [{ id: "battle_zjh_max_players", lb: "最大人数" }],
    tpls: [
      { id: "battle_zjh_create_reply", lb: "发起对战回复", default: "🃏 炸金花群对战 ════════════{newline}👤 {user} 发起群对战{newline}💰 每人下注：{bet} {currency}{newline}👥 对战人数：{max_players} 人{newline}{newline}📢 发送 /加入 参与对战！{newline}{newline}已加入（{count}/{max_players}）{newline}{players}", nt: "{user}={bet}={max_players}={count}={players}={currency}" },
      { id: "battle_zjh_join_reply", lb: "加入成功回复", default: "🃏 炸金花群对战 ════════════{newline}👤 {user} 加入对战！{newline}{newline}已加入（{count}/{max_players}）{newline}{players}", nt: "{user}={count}={max_players}={players}" },
      { id: "battle_zjh_full_reply", lb: "满员公布回复", default: "🃏 炸金花群对战 ════════════{newline}👥 对战结果公布{newline}{newline}━━━━━━━━━━━━━━━━{newline}{player_results}{newline}━━━━━━━━━━━━━━━━{newline}{newline}🏆 {winner} 获胜！{newline}💰 总奖池：{prize} {currency}（每人赢得 {win_amount} {currency}）", nt: "{bet}={prize}={player_results}={winner}={win_amount}" },
      { id: "battle_zjh_player_line", lb: "每人结果行", default: " {winner_mark} 👤 {name}：{hand} → {type}", nt: "{name}={hand}={type}={winner_mark}" },
      { id: "battle_no_money_reply", lb: "余额不足回复", default: "{user}，你的 {currency} 不足，需要 {bet}，当前余额 {balance}。", nt: "{user}={bet}={balance}={currency}" },
      { id: "battle_already_joined_reply", lb: "重复加入回复", default: "你已经在这个对战中了。" },
      { id: "battle_exists_reply", lb: "已有对战回复", default: "当前已有进行中的对战，请等待结束。" },
      { id: "battle_no_game_reply", lb: "无对战回复", default: "当前没有进行中的对战。发送 /发起炸金花对战 金额 来创建一个。" }
    ]
  },
  { key: "six_seal", name: "欲望圣裁", icon: "💗", tk: "six_seal_create_commands", sw: "six_seal_enabled", customOnly: true, triggerDefault: "/六印圣裁",
    nums: [
      { id: "six_seal_base_wager", lb: "基础圣契额", min: 1, max: 100000, default: 50 },
      { id: "six_seal_max_wager", lb: "圣契上限／入场余额要求", min: 1, max: 100000, default: 200 },
      { id: "six_seal_wager_step", lb: "每增加一次连按的涨幅", min: 1, max: 100000, default: 40 },
      { id: "six_seal_high_priest_base_wager", lb: "大祭司局基础圣契额", min: 1, max: 100000, default: 300 },
      { id: "six_seal_high_priest_max_wager", lb: "大祭司局圣契上限", min: 1, max: 100000, default: 500 },
      { id: "six_seal_high_priest_wager_step", lb: "大祭司局每次连按涨幅", min: 1, max: 100000, default: 75 },
      { id: "six_seal_high_priest_min_balance", lb: "大祭司局最低余额", min: -100000, max: 0, default: -100 },
      { id: "six_seal_high_priest_chance_percent", lb: "大祭司隐藏局出现概率（%）", min: 0, max: 100, default: 22 },
      { id: "six_seal_wait_seconds", lb: "等待加入秒数", min: 30, max: 3600, default: 300 },
      { id: "six_seal_turn_timeout_seconds", lb: "每回合操作超时（秒）", min: 30, max: 3600, default: 120 }
    ],
    tpls: [
      { id: "six_seal_create_reply", lb: "发起招募回复", nt: "{user} {base_wager} {max_wager} {wait_minutes} {currency}" },
      { id: "six_seal_join_started_reply", lb: "满员开场回复", nt: "{initiator} {opponent} {subject} {current_player} {base_wager} {max_wager} {currency}" },
      { id: "six_seal_safe_reply", lb: "安全按压回复", nt: "{actor} {subject} {revealed} {old_wager} {new_wager} {remaining} {next_player} {max_count}" },
      { id: "six_seal_failed_reply", lb: "触发结算回复", nt: "{actor} {subject} {winner} {curse_position} {wager} {winner_received} {actor_balance} {winner_balance}" },
      { id: "six_seal_final_reply", lb: "最后一次自动裁决回复", nt: "{actor} {subject} {winner} {loser} {revealed} {wager} {winner_received} {loser_balance} {winner_balance}" },
      { id: "six_seal_expired_reply", lb: "五分钟无人加入取消提示", nt: "{initiator} {wait_minutes} {max_wager} {currency}" },
      { id: "six_seal_turn_expired_reply", lb: "回合超时逃战提示", default: "⌛ {loser}在 {turn_timeout_minutes} 分钟内没有按压，已判定逃战失败。{newline}{loser}支付 {wager} {currency}，{winner}获胜并获得 {winner_received}。{newline}双方余额：{loser} {loser_balance} / {winner} {winner_balance}。", nt: "{loser} {winner} {turn_timeout_minutes} {wager} {winner_received} {loser_balance} {winner_balance} {currency}" },
      { id: "six_seal_no_money_reply", lb: "余额不足回复", nt: "{user} {required} {balance} {currency}" },
      { id: "six_seal_no_male_subject_reply", lb: "没有可用真实男性提示" },
      { id: "six_seal_exists_reply", lb: "已有游戏回复" },
      { id: "six_seal_join_no_game_reply", lb: "无等待游戏回复" },
      { id: "six_seal_join_self_reply", lb: "发起者重复加入回复" },
      { id: "six_seal_not_player_reply", lb: "非参与者操作回复" },
      { id: "six_seal_not_turn_reply", lb: "尚未轮到回复", nt: "{current_player}" },
      { id: "six_seal_reveal_usage_reply", lb: "按压次数错误回复", nt: "{max_count} {choices}" },
      { id: "six_seal_waiting_status_reply", lb: "等待状态回复" },
      { id: "six_seal_active_status_reply", lb: "进行状态回复" },
      { id: "six_seal_high_priest_no_money_reply", lb: "大祭司局余额不足回复", nt: "{participant} {max_wager} {min_balance} {balance} {currency}" },
      { id: "six_seal_high_priest_join_started_reply", lb: "大祭司隐藏局开场", nt: "{initiator} {opponent} {subject} {current_player} {base_wager} {max_wager} {min_balance} {remaining} {currency}" },
      { id: "six_seal_high_priest_safe_reply", lb: "大祭司局安全按压", nt: "{actor} {subject} {revealed} {old_wager} {new_wager} {remaining} {next_player} {max_count} {choices}" },
      { id: "six_seal_high_priest_failed_reply", lb: "大祭司局触发结算", nt: "{actor} {winner} {curse_position} {wager} {winner_received} {actor_balance} {winner_balance} {currency}" },
      { id: "six_seal_high_priest_final_reply", lb: "大祭司局最终裁决", nt: "{actor} {winner} {loser} {revealed} {wager} {winner_received} {loser_balance} {winner_balance} {currency}" },
      { id: "six_seal_high_priest_active_status_reply", lb: "大祭司局状态", nt: "{initiator} {opponent} {subject} {current_player} {current_wager} {max_wager} {remaining} {total_slots} {max_count} {choices}" },
      { id: "six_seal_cancel_not_allowed_reply", lb: "取消权限不足回复" },
      { id: "six_seal_cancelled_reply", lb: "主动取消回复" },
      { id: "six_seal_disabled_reply", lb: "功能关闭回复" }
    ]
  },
  { key: "nipple_guess", name: "猜乳头", icon: "🎴", tk: "nipple_guess_commands", sw: "nipple_guess_enabled", customOnly: true, triggerDefault: "/猜乳头",
    nums: [
      { id: "nipple_guess_base_bet", lb: "猜乳头基础下注", min: 1, max: 100000, default: 100 },
      { id: "nipple_guess_key_drop_rate", lb: "钥匙掉落率（%）", min: 0, max: 100, default: 33.333333 }
    ],
    tpls: [
      { id: "nipple_guess_start_reply", lb: "游戏开始回复", nt: "{user} {stake} {balance} {currency}" },
      { id: "nipple_guess_no_money_reply", lb: "余额不足回复", nt: "{user} {stake} {balance} {currency}" },
      { id: "nipple_guess_active_reply", lb: "已有进行中游戏回复" },
      { id: "nipple_guess_global_busy_reply", lb: "全局游戏占用回复" },
      { id: "nipple_guess_wrong_reply", lb: "第一轮猜错回复", nt: "{side} {stake} {balance} {currency}" },
      { id: "nipple_guess_right_reply", lb: "第一轮猜对回复", nt: "{side} {first_prize} {currency}" },
      { id: "nipple_guess_stop_reply", lb: "第一轮收手回复", nt: "{user} {first_prize} {balance} {currency}" },
      { id: "nipple_guess_second_wrong_reply", lb: "第二轮失败回复", nt: "{side} {first_prize} {balance} {currency}" },
      { id: "nipple_guess_second_right_reply", lb: "第二轮成功回复", nt: "{user} {side} {second_prize} {balance} {drop_text} {currency}" },
      { id: "nipple_guess_key_drop_reply", lb: "钥匙掉落附加回复", nt: "{user}" },
      { id: "nipple_guess_choice_reply", lb: "选择格式提示" }
    ]
  },
  { key: "blind_box", name: "曦曦盲盒", icon: "🎁", tk: "blind_box_commands", sw: "blind_box_enabled", customOnly: true, hideGlobalBet: true, triggerDefault: "/盲盒",
    nums: [
      { id: "blind_box_cost", lb: "入场费用", min: 1, max: 100000, default: 100 },
      { id: "blind_box_double_rate", lb: "双人大奖胜率（%）", min: 0, max: 100, default: 5 },
      { id: "blind_box_single_rate", lb: "单人奖胜率（%）", min: 0, max: 100, default: 10 },
      { id: "blind_box_fail_rate", lb: "空盒概率（%）", min: 0, max: 100, default: 85 },
      { id: "blind_box_double_reward", lb: "双人大奖奖励", min: 0, max: 1000000, default: 500 },
      { id: "blind_box_single_reward", lb: "单人奖奖励", min: 0, max: 1000000, default: 200 }
    ],
    tpls: [
      { id: "blind_box_double_reply", lb: "双人大奖回复", nt: "{user} {outcome} {cost} {reward} {balance} {currency}" },
      { id: "blind_box_single_reply", lb: "单人奖回复", nt: "{user} {outcome} {cost} {reward} {balance} {currency}" },
      { id: "blind_box_empty_reply", lb: "空盒回复", nt: "{user} {outcome} {cost} {reward} {balance} {currency}" },
      { id: "blind_box_no_money_reply", lb: "余额不足回复", nt: "{user} {cost} {balance} {currency}" },
      { id: "blind_box_disabled_reply", lb: "游戏关闭回复" }
    ]
  }
];

// 教堂主题展示当前保留的纸牌、裁决与图片小游戏。
gameCmds = gameCmds.filter(function(cmd) { return cmd.key === "zjh" || cmd.key === "battle_zjh" || cmd.key === "six_seal" || cmd.key === "nipple_guess" || cmd.key === "blind_box"; });
gameCmds.forEach(function(cmd) {
  if (cmd.key === "zjh") { cmd.name = "修女纸牌"; cmd.triggerDefault = "/修女纸牌,/zjh"; }
  if (cmd.key === "battle_zjh") { cmd.name = "修女纸牌群试炼"; cmd.triggerDefault = "/发起修女纸牌对战"; }
});
sysCmds.forEach(function(cmd) {
  if (cmd.key === "checkin") cmd.name = "祈福";
  if (cmd.key === "balance") cmd.name = "功德点";
  if (cmd.key === "shop") cmd.name = "神殿仓库";
  if (cmd.key === "givePoints") cmd.name = "赠送功德点";
  if (cmd.key === "finePoints") cmd.name = "罚款功德点";
  if (cmd.key === "redPacket") cmd.name = "功德福袋";
  if (cmd.key === "debtList") cmd.name = "功德修补名单";
});

var sysCmdSource = sysCmds;
var sysTriggerFormatHints = {
  buy_commands: "{command}商品编号",
  remove_status_commands: "{command}状态编号",
  set_title_commands: "{command} 新称呼",
  send_red_packet_commands: "{command} 总金额 份数",
  admin_red_packet_commands: "{command} 总金额 份数",
  user_red_packet_commands: "{command} 总金额 份数",
  give_points_commands: "{command} 对方昵称 金额",
  fine_points_commands: "{command} 对方昵称或称呼 金额",
  paid_interaction_enable_commands: "{command}",
  paid_interaction_disable_commands: "{command}",
  other_status_commands: "/对方昵称的状态",
  tip_commands: "{command} 金额",
  theft_commands: "{command} 对方昵称",
  slave_contract_request_commands: "{command}（公开求主人） 或 {command} 主人昵称 金额（定向申请）",
  slave_contract_lender_request_commands: "{command}（公开招收） 或 {command} 奴隶昵称 金额（定向邀请）"
};
var sysCmdGroupDefinitions = [
  { key: "merit", name: "功德与奖励", parts: ["checkin", "balance", "facilityWageClaim"] },
  { key: "storage", name: "神殿仓库", parts: ["shop", "buy", "inventory"] },
  { key: "profileStatus", name: "个人资料与状态", parts: ["profile", "status", "otherStatus", "removeStatus", "debtList"] },
  { key: "titles", name: "用户称呼", parts: ["myTitle", "setTitle"] },
  { key: "slaveContract", name: "奴隶契约", parts: ["slaveContractRequest", "slaveContractAgree", "slaveContractReject", "slaveContractRepay"] },
  { key: "interactions", name: "群聊互动", parts: ["begTip", "theft"] }
];

sysCmds = sysCmdGroupDefinitions.map(function(group) {
  var parts = group.parts.map(function(key) {
    return sysCmdSource.find(function(cmd) { return cmd.key === key; });
  }).filter(Boolean);
  var triggers = [];
  var templates = [];
  var numbers = [];
  parts.forEach(function(part) {
    if (part.tk) triggers.push({ key: part.tk, label: part.name + "触发词", hint: sysTriggerFormatHints[part.tk] || "" });
    if (part.tk2) triggers.push({ key: part.tk2, label: part.name + "第二触发词", hint: sysTriggerFormatHints[part.tk2] || "" });
    templates = templates.concat(part.tpls || []);
    numbers = numbers.concat(part.nums || []);
  });
  if (group.key === "paidInteraction") {
    triggers.push(
      { key: "paid_interaction_enable_commands", label: "开启接受触发词", hint: sysTriggerFormatHints.paid_interaction_enable_commands },
      { key: "paid_interaction_disable_commands", label: "关闭接受触发词", hint: sysTriggerFormatHints.paid_interaction_disable_commands }
    );
  }
  if (group.key === "slaveContract") {
    triggers.splice(1, 0, { key: "slave_contract_lender_request_commands", label: "主人发起触发词", hint: sysTriggerFormatHints.slave_contract_lender_request_commands });
    templates.splice(2, 0,
      { id: "slaveContractLenderUsageReply", lb: "主人发起格式提示" },
      { id: "slaveContractLenderRequestReply", lb: "主人发起申请回复", nt: "{lender}=主人 {borrower}=预定奴隶 {amount}=金额 {currency}=货币名" },
      { id: "slaveContractLenderRequestNoMoneyReply", lb: "主人发起余额不足提示", nt: "{lender}=主人 {amount}=金额 {balance}=余额 {currency}=货币名" },
      { id: "slaveContractPublicBorrowerReply", lb: "公开求主人发布回复", nt: "{borrower}=申请人 {debt}=当前负债 {balance}=当前余额 {currency}=货币名" },
      { id: "slaveContractPublicLenderReply", lb: "公开招收奴隶发布回复", nt: "{lender}=招收者 {balance}=当前余额 {currency}=货币名" },
      { id: "slaveContractPublicNoDebtReply", lb: "公开申请没有负债提示", nt: "{borrower}=申请人 {balance}=当前余额 {currency}=货币名" },
      { id: "slaveContractPublicAcceptNoDebtReply", lb: "接受公开招收但没有负债提示", nt: "{borrower}=接受者 {balance}=当前余额 {currency}=货币名" },
      { id: "slaveContractPublicDuplicateReply", lb: "重复发布公开申请提示" },
      { id: "slaveContractPublicLenderBusyReply", lb: "已有公开招收悬赏提示", nt: "{lender}=当前悬赏发布者 {currency}=货币名" },
      { id: "slaveContractPublicNotFoundReply", lb: "没有可接受公开申请提示" },
      { id: "slaveContractPublicAcceptSuccessReply", lb: "公开契约成立回复", nt: "{lender}=主人 {borrower}=奴隶 {amount}=代偿金额 {lender_balance}=主人余额 {borrower_balance}=奴隶余额 {currency}=货币名" },
      { id: "slaveContractPublicLenderExpiredReply", lb: "公开招收超时取消通知", nt: "{lender}=悬赏发布者 {currency}=货币名" }
    );
  }
  return {
    key: group.key,
    name: group.name,
    parts: parts,
    triggers: triggers,
    tpls: templates,
    nums: numbers
  };
});

var luckyBagCmds = [
  {
    key: "luckyBagAdmin",
    name: "管理员权限",
    parts: [
      sysCmdSource.find(function(cmd) { return cmd.key === "givePoints"; }),
      sysCmdSource.find(function(cmd) { return cmd.key === "finePoints"; })
    ].filter(Boolean),
    triggers: [
      { key: "give_points_commands", label: "管理员赠送功德点触发词", hint: "{command} 对方昵称 金额" },
      { key: "fine_points_commands", label: "管理员罚款触发词", hint: "{command} 对方昵称或称呼 金额" },
      { key: "admin_red_packet_commands", label: "管理员系统福袋触发词", hint: "{command} 总金额 份数" }
    ],
    tpls: [
      { id: "givePointsSuccessReply", lb: "管理员赠送成功回复", nt: "{user} {target} {amount} {balance} {currency}" },
      { id: "givePointsUsageReply", lb: "管理员赠送格式提示" },
      { id: "givePointsTargetNotFoundReply", lb: "赠送目标不存在回复" },
      { id: "givePointsAdminOnlyReply", lb: "赠送权限不足回复" },
      { id: "finePointsSuccessReply", lb: "管理员罚款成功回复", nt: "{user} {target} {amount} {balance} {currency}" },
      { id: "finePointsUsageReply", lb: "管理员罚款格式提示" },
      { id: "finePointsTargetNotFoundReply", lb: "罚款目标不存在回复" },
      { id: "finePointsAdminOnlyReply", lb: "罚款权限不足回复" },
      { id: "finePointsLimitReply", lb: "罚款余额下限回复" },
      { id: "adminRedPacketUsageReply", key: "admin_red_packet_usage_reply", lb: "管理员福袋格式提示" },
      { id: "adminRedPacketCreatedReply", key: "admin_red_packet_created_reply", lb: "管理员福袋创建回复", nt: "{user} {amount} {count} {currency}" },
      { id: "redPacketAdminOnlyReply", key: "red_packet_admin_only_reply", lb: "管理员福袋权限不足回复" }
    ],
    nums: [
      { id: "finePointsMinBalance", key: "fine_points_min_balance", lb: "罚款后最低余额", min: -100000, max: 0 }
    ]
  },
  {
    key: "luckyBagUsers",
    name: "普通用户福袋",
    parts: [],
    triggers: [
      { key: "user_red_packet_commands", label: "普通用户发福袋触发词", hint: "{command} 总金额 份数" },
      { key: "claim_red_packet_commands", label: "领取福袋触发词", hint: "{command}" }
    ],
    tpls: [
      { id: "userRedPacketUsageReply", key: "user_red_packet_usage_reply", lb: "用户福袋格式提示" },
      { id: "userRedPacketCreatedReply", key: "user_red_packet_created_reply", lb: "用户福袋创建回复", nt: "{user} {amount} {count} {balance} {currency}" },
      { id: "userRedPacketNoMoneyReply", key: "user_red_packet_no_money_reply", lb: "用户余额不足回复", nt: "{user} {amount} {balance} {currency}" },
      { id: "redPacketClaimReply", key: "red_packet_claim_reply", lb: "领取成功回复", nt: "{user} {amount} {balance} {currency}" },
      { id: "redPacketEmptyReply", key: "red_packet_empty_reply", lb: "福袋领完回复" },
      { id: "redPacketNoneReply", key: "red_packet_none_reply", lb: "当前无福袋回复" },
      { id: "redPacketClaimedReply", key: "red_packet_claimed_reply", lb: "重复领取回复" }
    ],
    nums: []
  }
];

function renderSysCmds() {
  var f = config.features || {};
  var html = "";
  sysCmds.forEach(function(cmd) {
    var triggerCount = (cmd.triggers || []).reduce(function(total, trigger) {
      return total + String(f[trigger.key] || "").split(/[,，]/).filter(Boolean).length;
    }, 0);
    html += "<div class=\"command-row\" style=\"cursor:pointer\" onclick=\"editSysCmd('" + cmd.key + "')\">" +
      "<div class=\"command-main\"><div><b>" + h(cmd.name) + "</b><span>" + (cmd.parts || []).length + " 项相关功能 · " + triggerCount + " 个触发词</span></div></div>" +
      "<div class=\"command-flags\"><span class=\"badge\">系统模块</span></div></div>";
  });
  $("sysCmdList").innerHTML = html || "加载中...";
}

function renderLuckyBagCommands() {
  var f = config.features || {};
  var html = "";
  luckyBagCmds.forEach(function(cmd) {
    var triggerCount = (cmd.triggers || []).reduce(function(total, trigger) {
      return total + String(f[trigger.key] || "").split(/[,，]/).filter(Boolean).length;
    }, 0);
    html += "<div class=\"command-row\" style=\"cursor:pointer\" onclick=\"editSysCmd('" + cmd.key + "')\">" +
      "<div class=\"command-main\"><div><b>" + h(cmd.name) + "</b><span>" + triggerCount + " 个触发词 · 点击编辑命令和回复</span></div></div>" +
      "<div class=\"command-flags\"><span class=\"badge\">福袋模块</span></div></div>";
  });
  $("luckyBagCommandList").innerHTML = html || "加载中...";
}

function editSysCmd(cmdKey) {
  var cmd = sysCmds.concat(luckyBagCmds).find(function(c) { return c.key === cmdKey; });
  if (!cmd) return;
  var f = config.features || {};
  $("sysCmdTitle").textContent = "编辑系统命令：" + cmd.name;
  $("sysCmdTriggerFields").innerHTML = (cmd.triggers || []).map(function(trigger) {
    var value = String(f[trigger.key] || "");
    var firstCommand = value.split(/[,，]/).map(function(item) { return item.trim(); }).filter(Boolean)[0] || "/命令";
    var formatHint = trigger.hint ? trigger.hint.replace(/\{command\}/g, firstCommand) : "";
    return "<label>" + h(trigger.label) + "<span>这里只填写触发词前缀，多个用英文逗号分隔。</span><input class=\"sysTrigger\" data-id=\"" + h(trigger.key) + "\" value=\"" + h(value) + "\">" +
      (formatHint ? "<small class=\"trigger-usage\"><b>完整用法</b><code>" + h(formatHint) + "</code><em>昵称、编号和金额不需要写进触发词输入框。</em></small>" : "") +
      "</label>";
  }).join("");
  var tplHtml = "";
  if (cmd.key === "paidInteraction") {
    tplHtml += "<div class=\"template-code-guide\"><b>回复模板代码</b>" +
      "<div><code>{user}</code><span>发起人的名字</span></div>" +
      "<div><code>{target}</code><span>被使用人的名字</span></div>" +
      "<div><code>{amount}</code><span>本次支付的功德点</span></div>" +
      "<div><code>{balance}</code><span>发起人支付后的余额</span></div>" +
      "<div><code>{target_balance}</code><span>对方收款后的余额</span></div>" +
      "<div><code>{currency}</code><span>货币名称</span></div>" +
      "<small>四个性别组合分别编辑；无法识别性别时统一按女性。示例：<code>{user} 对 {target} 发起了互动，并支付 {amount} {currency}。</code></small></div>";
  }
  (cmd.tpls || []).forEach(function(tpl) {
    var snakeKey = tpl.key || tpl.id.replace(/[A-Z]/g, function(m){return '_'+m.toLowerCase();}); var val = f[snakeKey] || f[tpl.id] || tpl.default || "";
    tplHtml += "<label>" + h(tpl.lb);
    if (tpl.nt) tplHtml += "<span>" + h(tpl.nt) + "</span>";
    tplHtml += "<textarea class=\"sysTpl\" data-id=\"" + h(snakeKey) + "\">" + h(val) + "</textarea></label>";
  });
  $("sysCmdTemplates").innerHTML = tplHtml;
  var numHtml = "";
  if (cmd.nums) {
    cmd.nums.forEach(function(num) {
      var numKey = num.key || num.id.replace(/[A-Z]/g, function(m){return '_'+m.toLowerCase();});
      numHtml += "<label>" + h(num.lb) +
        "<input type=\"number\" class=\"sysNum\" data-id=\"" + h(numKey) +
        "\" min=\"" + (num.min ?? 0) + "\" max=\"" + (num.max ?? 100000) +
        "\" value=\"" + (f[numKey] || f[num.id] || 0) + "\"></label>";
    });
  }
  $("sysCmdNumbers").innerHTML = numHtml;
  $("sysCmdModal").classList.remove("hidden");
  $("sysCmdModal").dataset.cmdKey = cmdKey;
}

async function saveSysCmd() {
  var cmdKey = $("sysCmdModal").dataset.cmdKey;
  var cmd = sysCmds.concat(luckyBagCmds).find(function(c) { return c.key === cmdKey; });
  if (!cmd) return;
  var f = JSON.parse(JSON.stringify(config.features || {}));
  document.querySelectorAll(".sysTrigger").forEach(function(el) { f[el.dataset.id] = el.value.trim(); });
  document.querySelectorAll(".sysTpl").forEach(function(el) { f[el.dataset.id] = el.value; });
  document.querySelectorAll(".sysNum").forEach(function(el) { f[el.dataset.id] = Number(el.value); });
  var result = await api("/api/features", { method: "POST", body: f });
  config.features = result.features;
  $("sysCmdModal").classList.add("hidden");
  renderSysCmds();
  renderLuckyBagCommands();
  alert(cmd.name + " 已保存。");
}

function renderGameCmds() {
  var f = config.features || {};
  var html = "";
  gameCmds.forEach(function(cmd) {
    var triggers = f[cmd.tk] || cmd.triggerDefault || "";
    if (cmd.tk2) { triggers += (triggers && f[cmd.tk2] ? "," : "") + (f[cmd.tk2] || ""); }
    var enabled = f[cmd.sw] !== "false";
    var minBet = f.game_min_bet || 10;
    var maxBet = f.game_max_bet || 1000;
    var numsInfo = "";
    if (cmd.nums) { cmd.nums.forEach(function(num) {
      var numValue = f[num.id] !== undefined && f[num.id] !== null ? f[num.id] : (num.default ?? "");
      numsInfo += (numsInfo ? " · " : "") + h(num.lb) + " " + h(numValue);
    }); }
    html += "<article class=\"game-card\">" +
      "<div class=\"game-card-icon\" aria-hidden=\"true\">" + h(cmd.icon || "🎮") + "</div>" +
      "<div class=\"game-card-copy\"><h2>" + h(cmd.name) + "</h2><code>" + h(triggers || "未设置") + "</code>" +
      "<p>" + (cmd.hideGlobalBet ? "独立设置" : "押注 " + h(minBet) + "–" + h(maxBet) + " " + h(f.currency_name || "金币")) + (numsInfo ? " · " + numsInfo : "") + "</p></div>" +
      "<div class=\"game-card-actions\"><span class=\"status-pill " + (enabled ? "is-enabled" : "is-disabled") + "\">" + (enabled ? "已启用" : "已禁用") + "</span>" +
      "<button onclick=\"editGameCmd('" + cmd.key + "')\" type=\"button\">编辑模板</button></div></article>";
  });
  $("gameList").innerHTML = html || "<div class=\"empty\">加载中...</div>";
}

function editGameCmd(cmdKey) {
  var cmd = gameCmds.find(function(c) { return c.key === cmdKey; });
  if (!cmd) return;
  var f = config.features || {};
  $("gameModalTitle").textContent = "编辑游戏命令：" + cmd.name;
  $("gameModal").dataset.cmdKey = cmdKey;
  var triggers = f[cmd.tk] || cmd.triggerDefault || "";
  if (cmd.tk2) { triggers += (triggers && f[cmd.tk2] ? "," : "") + (f[cmd.tk2] || ""); }
  var enabled = f[cmd.sw] !== "false";
  var minBet = f.game_min_bet || 10;
  var maxBet = f.game_max_bet || 1000;
  var minBalance = f.game_min_balance || -100;
  var currency = f.currency_name || "金币";
  var html = "";
  html += "<label>命令触发词<span>多个用英文逗号分隔，必须以 / 开头。</span><input id=\"gameTriggers\" value=\"" + h(triggers) + "\"></label>";
  html += "<label class=\"switch\"><input id=\"gameEnabled\" type=\"checkbox\"" + (enabled ? " checked" : "") + "> 启用游戏</label>";
  if (!cmd.customOnly) {
    html += "<div class=\"three\"><label>最小押注<input id=\"gameMinBet\" type=\"number\" min=\"1\" value=\"" + h(minBet) + "\"></label><label>最大押注<input id=\"gameMaxBet\" type=\"number\" min=\"1\" value=\"" + h(maxBet) + "\"></label><label>最低余额<span>输后不能低于该值</span><input id=\"gameMinBalance\" type=\"number\" value=\"" + h(minBalance) + "\"></label></div>";
    html += "<label>负债状态模板<span>余额为负时显示在 /我的状态 和 /我 中。变量：{user} {debt} {balance} {currency}</span><input id=\"debtStatusTemplate\" value=\"" + h(f.debt_status_template || "公开泄欲工具（欠债 {debt} {currency}）") + "\"></label>";
    html += "<label>债务底线提示<span>变量：{user} {bet} {balance} {min_balance} {currency}</span><input id=\"gameDebtLimitReply\" value=\"" + h(f.game_debt_limit_reply || "{user}，你的{currency}已经接近债务底线，最多只能负债到 {min_balance} {currency}。") + "\"></label>";
  }
  if (cmd.nums) { cmd.nums.forEach(function(num) {
    var numValue = f[num.id] !== undefined && f[num.id] !== null ? f[num.id] : (num.default ?? "");
    html += "<label>" + h(num.lb) + "<input type=\"number\" class=\"gameNum\" data-id=\"" + h(num.id) +
      "\" min=\"" + (num.min ?? 0) + "\" max=\"" + (num.max ?? 100000) +
      "\" value=\"" + h(numValue) + "\"></label>";
  }); }
  html += "<div class=\"section-title\" style=\"margin-top:16px\"><h3>回复模板 <small>货币名：" + h(currency) + "</small></h3></div>";
  (cmd.tpls || []).forEach(function(tpl) {
    html += "<label>" + h(tpl.lb);
    if (tpl.nt) html += "<span>" + h(tpl.nt) + "</span>";
    html += "<textarea class=\"gameTpl\" data-id=\"" + h(tpl.id) + "\" rows=\"6\">" + h(f[tpl.id] || tpl.default || "") + "</textarea></label>";
  });
  $("gameModalContent").innerHTML = html;
  $("gameModal").classList.remove("hidden");
}

async function saveGameCmd() {
  var cmdKey = $("gameModal").dataset.cmdKey;
  var cmd = gameCmds.find(function(c) { return c.key === cmdKey; });
  if (!cmd) return;
  var f = JSON.parse(JSON.stringify(config.features || {}));
  var rawTriggers = $("gameTriggers").value.trim();
  if (cmd.tk2) {
    var parts = rawTriggers.split(",").map(function(x){return x.trim();}).filter(Boolean);
    var mid = Math.ceil(parts.length / 2);
    f[cmd.tk] = parts.slice(0, mid).join(",");
    f[cmd.tk2] = parts.slice(mid).join(",");
  } else { f[cmd.tk] = rawTriggers; }
  f[cmd.sw] = $("gameEnabled").checked ? "true" : "false";
  if (!cmd.customOnly) {
    f.game_min_bet = $("gameMinBet").value;
    f.game_max_bet = $("gameMaxBet").value;
    f.game_min_balance = $("gameMinBalance").value;
    f.debt_status_template = $("debtStatusTemplate").value;
    f.game_debt_limit_reply = $("gameDebtLimitReply").value;
  }
  document.querySelectorAll(".gameTpl").forEach(function(el) { f[el.dataset.id] = el.value; });
  document.querySelectorAll(".gameNum").forEach(function(el) { f[el.dataset.id] = Number(el.value); });
  if (cmdKey === "nipple_guess") {
    var baseBet = Number(f.nipple_guess_base_bet);
    if (!Number.isInteger(baseBet) || baseBet < 1 || baseBet > 100000) {
      throw new Error("猜乳头基础下注必须是 1～100000 的整数。");
    }
  }
  if (cmdKey === "blind_box") {
    var blindCost = Number(f.blind_box_cost);
    var blindRates = [Number(f.blind_box_double_rate), Number(f.blind_box_single_rate), Number(f.blind_box_fail_rate)];
    if (!Number.isInteger(blindCost) || blindCost < 1 || blindCost > 100000) throw new Error("盲盒入场费用必须是 1～100000 的整数。");
    if (blindRates.some(function(value) { return !Number.isFinite(value) || value < 0 || value > 100; })) throw new Error("盲盒的三个概率都必须在 0～100 之间。");
    if (Math.abs(blindRates.reduce(function(total, value) { return total + value; }, 0) - 100) > 0.000001) throw new Error("盲盒的双人、单人和空盒概率相加必须等于 100%。");
  }
  var result = await api("/api/features", { method: "POST", body: f });
  config.features = result.features;
  $("gameModal").classList.add("hidden");
  renderGameCmds();
  alert(cmd.name + " 已保存。");
}

let rules = [];
let shopItems = [];
let compensationPreviewData = null;
let compensationRequestId = "";
let facilityWageRules = [];
let itemEconomy = { settings: {}, items: [], drop_pool: [], offers: [], history: [] };

const replyModes = { fixed: "固定回复", random: "随机回复", sequence: "顺序回复", multi: "多段回复" };

async function api(url, options = {}) {
  const csrf = sessionStorage.getItem("dzmm_csrf") || "";
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(csrf ? { "X-CSRF-Token": csrf } : {}) },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined
  });
  if (res.status === 401) {
    location.href = "/login";
    throw new Error("管理登录已失效");
  }
  if (!res.ok) {
    const raw = await res.text();
    let message = raw;
    try {
      const data = JSON.parse(raw);
      message = data.detail || data.message || raw;
    } catch (_) {}
    throw new Error(String(message || `请求失败（HTTP ${res.status}）`));
  }
  return res.json();
}

function h(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#039;" }[ch]));
}

function setResult(message, type = "info") {
  const el = $("actionResult");
  if (!el) return;
  el.className = `notice ${type}`;
  el.textContent = message;
}

async function runAction(label, fn) {
  setResult(`${label}中...`);
  try {
    const data = await fn();
    setResult(data.message || `${label}成功`, "success");
    if (data && Object.keys(data).length) $("settingsResult").textContent = JSON.stringify(data, null, 2);
    await loadStatus();
    return data;
  } catch (err) {
    setResult(`${label}失败：${err.message}`, "error");
    throw err;
  }
}

const PAGE_TITLES = {
  dashboard: "仪表盘",
  connect: "连接设置",
  commands: "命令管理",
  "lucky-bags": "福袋系统",
  games: "游戏命令",
  "paid-interaction": "付费互动",
  fortune: "塔罗牌",
  bounties: "群友委托所",
  rp: "RP结界",
  "random-events": "随机事件",
  "image-generation": "图片生成",
  "ai-character": "AI角色",
  shop: "神殿仓库",
  users: "用户数据",
  messages: "消息监控",
  logs: "日志中心",
  safety: "安全设置",
  help: "使用帮助",
};

function showPage(name) {
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("active", p.id === name));
  document.querySelectorAll(".sidebar button").forEach((b) => b.classList.toggle("active", b.dataset.page === name));
  if ($("currentPageTitle")) $("currentPageTitle").textContent = PAGE_TITLES[name] || "控制台";
  document.title = `${PAGE_TITLES[name] || "控制台"} · DZMM 群聊机器人`;
  if (name === "commands") { loadRules(); renderSysCmds(); }
  if (name === "lucky-bags") { renderLuckyBagCommands(); loadLuckyBags(); }
  if (name === "games") { renderGameCmds(); }
  if (name === "paid-interaction") { loadPaidInteractionSettings(); }
  if (name === "fortune") { loadFortuneSettings(); }
  if (name === "connect") {
    loadConnectionAiSettings().catch(function(error) {
      if ($("fortuneConnectionSaveResult")) {
        $("fortuneConnectionSaveResult").textContent = "AI 设置加载失败：" + error.message;
        $("fortuneConnectionSaveResult").className = "notice error";
      }
    });
    loadImageGenerationSettings().catch(function(error) {
      if ($("imageApiConnectionResult")) {
        $("imageApiConnectionResult").textContent = "图片API设置加载失败：" + error.message;
        $("imageApiConnectionResult").className = "notice error";
      }
    });
  }
  if (name === "bounties") loadBountySettings();
  if (name === "rp") { loadRpSettings(); loadRpAdmin(); }
  if (name === "random-events") { loadRandomEventSettings(); loadRandomEventsAdmin(); }
  if (name === "image-generation") { loadImageGenerationSettings(); loadImageGenerationHistory(); }
  if (name === "ai-character") loadAiCharacter();
  if (name === "shop") { loadShopItems(); loadItemEconomy(); }
  if (name === "users") loadUsers();
  if (name === "messages") loadMessages();
  if (name === "logs") loadLogs();
}

function fillSelect(id, options) {
  $(id).innerHTML = Object.entries(options).map(([v, t]) => `<option value="${v}">${t}</option>`).join("");
}

function splitNames(value) {
  return value.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean);
}

function joinNames(value) {
  return (value || []).join(", ");
}

async function loadConfig() {
  config = await api("/api/config");
  const d = config.dzmm || {};
  const safe = config.safety || {};
  const ui = config.ui || {};
  $("homeUrl").value = d.home_url || "";
  $("groupUrl").value = d.group_url || "";
  $("bountyGroupUrl").value = d.bounty_group_url || "";
  $("imageGroupUrl").value = d.image_group_url || "";
  $("scanInterval").value = d.scan_interval_seconds || 2;
  $("sendDelay").value = d.send_delay_seconds || 1.5;
  $("botEnabled").checked = !!d.bot_enabled;
  $("groupUrlLockEnabled").checked = !!d.lock_group_urls;
  $("groupUrlLockResult").textContent = d.lock_group_urls
    ? "当前已开启：浏览器会自动保持在配置的群聊页面。"
    : "当前未开启，登录页面不会被自动抢走。";
  $("autoOpenManager").checked = ui.auto_open_manager !== false;
  $("requireSlash").checked = true;
  $("unknownCommandReply").value = d.unknown_command_reply || "命令错误";
  $("safeEnabled").checked = !!safe.enabled;
  $("maxMinute").value = safe.max_replies_per_minute || 10;
  $("maxHour").value = safe.max_replies_per_hour || 100;
  $("globalCooldown").value = safe.global_cooldown_seconds || 2;
  var f = config.features || {};
  $("tarotDailyLimitSafety").value = Math.max(1, Math.min(100, Number(f.fortune_daily_limit || 1)));
  $("gameLimitEnabled").checked = f.game_limit_enabled !== "false";
  $("gameOpenWindows").value = f.game_open_windows || "08:00-10:00,14:00-17:00";
  $("gameDailySystemLimit").value = f.game_daily_system_limit || 3;
  $("gameDailyBattleLimit").value = f.game_daily_battle_limit || 1;
  $("gameDailySixSealLimit").value = f.game_daily_six_seal_limit || 2;
  $("gameDailyNippleGuessLimit").value = f.game_daily_nipple_guess_limit || 3;
  $("gameDailyBlindBoxLimit").value = f.game_daily_blind_box_limit || 3;
  $("gameClosedReply").value = f.game_closed_reply || "{user}，当前不在游戏开放时间。开放时间：{open_windows}。";
  $("gameLimitReply").value = f.game_limit_reply || "{user}，你今天已发起 {played} 次{game_kind}（上限 {max_plays} 次），请明天 00:00 后再来。";
  // fillFeatures 已移除：系统命令现通过 sysCmdModal 弹窗编辑
}

function collectConfig() {
  config.dzmm = {
    ...(config.dzmm || {}),
    home_url: $("homeUrl").value.trim(),
    group_url: $("groupUrl").value.trim(),
    bounty_group_url: $("bountyGroupUrl").value.trim(),
    image_group_url: $("imageGroupUrl").value.trim(),
    scan_interval_seconds: Number($("scanInterval").value || 2),
    send_delay_seconds: Number($("sendDelay").value || 1.5),
    bot_enabled: $("botEnabled").checked,
    auto_open_group: false,
    lock_group_urls: $("groupUrlLockEnabled").checked,
    allow_multi_rule_reply: false,
    require_slash_prefix: true,
    unknown_command_reply: $("unknownCommandReply").value.trim() || "命令错误"
  };
  config.ui = { ...(config.ui || {}), auto_open_manager: $("autoOpenManager").checked };
  collectSafety();
  return config;
}

function collectSafety() {
  config.safety = {
    ...(config.safety || {}),
    enabled: $("safeEnabled").checked,
    max_replies_per_minute: Number($("maxMinute").value || 10),
    max_replies_per_hour: Number($("maxHour").value || 100),
    global_cooldown_seconds: Number($("globalCooldown").value || 2),
    ignore_self_messages: true
  };
  var f = config.features || {};
  config.features = f;
  f.fortune_daily_limit = Math.max(1, Math.min(100, Math.trunc(Number($("tarotDailyLimitSafety").value) || 1)));
  f.game_limit_enabled = $("gameLimitEnabled").checked ? "true" : "false";
  f.game_open_windows = $("gameOpenWindows").value.trim();
  f.game_daily_system_limit = $("gameDailySystemLimit").value;
  f.game_daily_battle_limit = $("gameDailyBattleLimit").value;
  f.game_daily_six_seal_limit = $("gameDailySixSealLimit").value;
  f.game_daily_nipple_guess_limit = $("gameDailyNippleGuessLimit").value;
  f.game_daily_blind_box_limit = $("gameDailyBlindBoxLimit").value;
  f.game_closed_reply = $("gameClosedReply").value;
  f.game_limit_reply = $("gameLimitReply").value;
}

let aiSettings = {};
let aiProfile = {};

function setAiValue(id, value) {
  const el = $(id);
  if (!el) return;
  if (el.type === "checkbox") el.checked = !!value;
  else el.value = value ?? "";
}

async function loadAiCharacter() {
  const [overview, settings, profile, groupMemory, relationships, capabilities, pending, tasks, events] = await Promise.all([
    api("/api/ai-character/overview"), api("/api/ai-character/settings"), api("/api/ai-character/profile"),
    api("/api/ai-character/group-memory"), api("/api/ai-character/relationships"), api("/api/ai-character/capabilities"),
    api("/api/ai-character/pending-actions"), api("/api/ai-character/tasks?limit=60"), api("/api/ai-character/events?group_id=main")
  ]);
  aiSettings = settings;
  aiProfile = profile;
  $("aiOverview").innerHTML = [
    ["当前角色", overview.character], ["今日请求", overview.requests || 0], ["输入Token", overview.token_input || 0],
    ["输出Token", overview.token_output || 0], ["今日收费", overview.fee || 0],
    ["当前排队", overview.queued || 0], ["当前处理中", overview.processing || 0]
  ].map(([name, value]) => `<div><span>${h(name)}</span><strong>${h(value)}</strong></div>`).join("");
  const profileFields = {
    aiName:"name", aiSpecies:"species", aiSelfName:"self_name", aiIdentity:"identity", aiAppearance:"appearance",
    aiOrigin:"origin", aiWorld:"world", aiCreatorRelation:"creator_relation", aiWorldview:"worldview", aiPersonality:"personality",
    aiTone:"tone", aiCreatorTitle:"creator_title", aiMemberTitle:"member_title", aiHumor:"humor_level", aiTeasing:"teasing_level",
    aiEmoji:"emoji_level", aiReplyLength:"reply_length", aiUseHeadings:"use_headings", aiUseNumbering:"use_numbering",
    aiArchiveStyle:"allow_archive_style", aiImagination:"allow_imagination", aiInheritRelations:"inherit_creator_relations",
    aiPersonaPrompt:"persona_prompt"
  };
  Object.entries(profileFields).forEach(([id, key]) => setAiValue(id, profile[key]));
  setAiValue("aiRelationRules", JSON.stringify(profile.inherit_relation_rules || {}, null, 2));
  const settingFields = {
    aiEnabled:"enabled", aiPrimaryModel:"primary_model", aiBackupModel:"backup_model", aiNormalThinking:"normal_thinking",
    aiAllowThinking:"allow_thinking_command", aiFallbackModel:"fallback_model_enabled", aiFallbackNormal:"fallback_to_normal",
    aiNormalTimeout:"normal_timeout_seconds", aiThinkingTimeout:"thinking_timeout_seconds",
    aiSupremeSystemPrompt:"supreme_system_prompt", aiSystemRules:"system_rules",
    aiMaxReplyMessages:"max_reply_messages", aiNormalFee:"normal_fee", aiThinkingFee:"thinking_fee", aiRecipientFee:"recipient_fee", aiFeeEnabled:"fee_enabled",
    aiAllowInsufficient:"allow_insufficient", aiAllowNegative:"allow_negative", aiAdminFree:"admin_free",
    aiFeeRecipientUserId:"fee_recipient_user_id",
    aiTokenFooter:"token_footer_enabled", aiTokenFooterFormat:"token_footer_format", aiRecentGroup:"recent_group_messages",
    aiRecentUser:"recent_user_messages", aiNormalTools:"normal_max_tool_calls", aiThinkingTools:"thinking_max_tool_calls",
    aiRawTurns:"conversation_raw_turns", aiConversationSummary:"conversation_summary_chars", aiContextMax:"context_max_chars",
    aiRelatedUsers:"related_user_limit", aiNormalConcurrency:"normal_concurrency", aiThinkingConcurrency:"thinking_concurrency",
    aiBackgroundConcurrency:"background_concurrency", aiUserQueue:"per_user_queue", aiGroupQueue:"per_group_queue",
    aiQueueWait:"queue_wait_seconds",
    aiMemoryEnabled:"memory_enabled", aiMemoryThreshold:"memory_message_threshold", aiMemoryChars:"memory_summary_chars",
    aiEventLimit:"memory_event_limit", aiGroupMemoryEnabled:"group_memory_enabled", aiGroupMemoryMin:"group_memory_min_messages",
    aiProactiveEnabled:"proactive_enabled", aiProactiveChars:"proactive_max_chars", aiQuietStart:"proactive_quiet_start",
    aiQuietEnd:"proactive_quiet_end", aiProactiveRp:"proactive_during_rp", aiProactiveGames:"proactive_during_games",
    aiProactiveModel:"proactive_model", aiProactiveThinking:"proactive_thinking", aiProactiveToken:"proactive_token_footer"
  };
  Object.entries(settingFields).forEach(([id, key]) => setAiValue(id, settings[key]));
  setAiValue("aiFreeUsers", (settings.free_user_ids || []).join("\n"));
  setAiValue("aiProactiveMain", !!(settings.proactive_groups || {}).main);
  setAiValue("aiProactiveBounty", !!(settings.proactive_groups || {}).bounty);
  $("aiGroupMemoryStatus").textContent = `状态：${groupMemory.status || "idle"}｜上次更新：${groupMemory.updated_at || "尚未生成"}｜处理消息：${groupMemory.processed_message_count || 0}｜错误：${groupMemory.last_error || "无"}`;
  const relationshipUserLabel = (r, side) => {
    const displayName = String(r[`${side}_display_name`] || "").trim();
    const nickname = String(r[`${side}_nickname`] || "").trim();
    const userId = String(r[`${side}_user_id`] || "");
    if (displayName && nickname && displayName !== nickname) return `${displayName}（${nickname}）`;
    if (displayName || nickname) return displayName || nickname;
    return `未知用户（${userId.slice(-8) || "无ID"}）`;
  };
  $("aiRelationships").innerHTML = relationships.length ? `<table><thead><tr><th>来源</th><th>主体</th><th>关系</th><th>对象</th><th>可信度</th><th></th></tr></thead><tbody>${relationships.map((r) => `<tr><td>${h(r.source_type)}</td><td title="${h(r.subject_user_id)}">${h(relationshipUserLabel(r, "subject"))}</td><td>${h(r.forward_relation)}</td><td title="${h(r.object_user_id)}">${h(relationshipUserLabel(r, "object"))}</td><td>${h(r.confidence)}</td><td>${r.source_type === "admin" && r.active ? `<button onclick="deleteAiRelationship(${Number(r.id)})">停用</button>` : ""}</td></tr>`).join("")}</tbody></table>` : "暂无已记录关系；正式奴隶契约仍会实时直接加载。";
  $("aiCapabilities").innerHTML = `<table><thead><tr><th>功能</th><th>风险</th><th>确认</th><th>回复方式</th></tr></thead><tbody>${capabilities.map((c) => `<tr><td>${h(c.name)}</td><td>${h(c.risk)}</td><td>${c.confirmation ? "需要" : "不需要"}</td><td>${h(c.reply_mode)}</td></tr>`).join("")}</tbody></table>`;
  $("aiPendingActions").innerHTML = pending.length ? `<table><thead><tr><th>用户</th><th>操作</th><th>过期</th><th></th></tr></thead><tbody>${pending.map((p) => `<tr><td>${h(p.user_id)}</td><td>${h(p.command_text)}</td><td>${h(p.expires_at)}</td><td><button onclick="cancelAiPending('${h(p.action_id)}')">取消异常草稿</button></td></tr>`).join("")}</tbody></table>` : "暂无待确认操作。";
  $("aiTaskList").innerHTML = tasks.length ? `<table><thead><tr><th>时间</th><th>用户</th><th>原话</th><th>模式</th><th>状态</th><th>Token</th><th>费用</th><th>错误</th><th></th></tr></thead><tbody>${tasks.map((t) => `<tr><td>${h(t.created_at)}</td><td>${h(t.nickname)}</td><td>${h(t.request_text || "")}</td><td>${h(t.mode)}</td><td>${h(t.status)}</td><td>${t.token_input == null ? "不可用" : `${t.token_input}/${t.token_output}`}</td><td>${t.fee_snapshot}</td><td>${h(t.error || "")}</td><td><button onclick="loadAiTaskDetail('${h(t.task_id)}')">详情</button></td></tr>`).join("")}</tbody></table>` : "暂无AI任务。";
  $("aiEvents").innerHTML = events.length ? `<table><thead><tr><th>日期</th><th>用户</th><th>类型</th><th>摘要</th><th>来源消息</th><th></th></tr></thead><tbody>${events.map((e) => `<tr><td>${h(e.event_date)}</td><td>${h(e.user_id)}</td><td>${h(e.event_type)}</td><td>${h(e.summary)}</td><td>${h(e.source_message_id || "")}</td><td>${e.active ? `<button onclick="deleteAiEvent('${h(e.event_id)}')">停用</button>` : "已停用"}</td></tr>`).join("")}</tbody></table>` : "暂无事件卡。";
  if (overview.recent_error) $("aiModelResult").textContent = `最近错误：${overview.recent_error}`;
}

function collectAiProfile() {
  let relationRules;
  try { relationRules = JSON.parse($("aiRelationRules").value || "{}"); } catch (_) { throw new Error("关系继承规则不是有效JSON"); }
  return {
    name:$("aiName").value.trim(), species:$("aiSpecies").value.trim(), self_name:$("aiSelfName").value.trim(),
    identity:$("aiIdentity").value.trim(), appearance:$("aiAppearance").value.trim(), origin:$("aiOrigin").value.trim(),
    world:$("aiWorld").value.trim(), creator_relation:$("aiCreatorRelation").value.trim(), worldview:$("aiWorldview").value.trim(),
    personality:$("aiPersonality").value.trim(), tone:$("aiTone").value.trim(), creator_title:$("aiCreatorTitle").value.trim(),
    member_title:$("aiMemberTitle").value.trim(), humor_level:$("aiHumor").value.trim(), teasing_level:$("aiTeasing").value,
    emoji_level:$("aiEmoji").value, reply_length:$("aiReplyLength").value, use_headings:$("aiUseHeadings").checked,
    use_numbering:$("aiUseNumbering").checked, allow_archive_style:$("aiArchiveStyle").checked,
    allow_imagination:$("aiImagination").checked, inherit_creator_relations:$("aiInheritRelations").checked,
    inherit_relation_rules:relationRules
  };
}

async function saveAiSettings(values, message) {
  await api("/api/ai-character/settings", {method:"PUT", body:values});
  await loadAiCharacter();
  alert(message || "AI角色设置已保存。保存后立即生效。");
}

window.cancelAiPending = async (id) => {
  if (!confirm("确定取消这条异常确认草稿？不会执行业务操作。")) return;
  await api(`/api/ai-character/pending-actions/${id}/cancel`, {method:"POST"});
  await loadAiCharacter();
};

window.deleteAiRelationship = async (id) => {
  if (!confirm("确定停用这条管理员关系？正式契约关系不会受影响。")) return;
  await api(`/api/ai-character/relationships/${id}`, {method:"DELETE"});
  await loadAiCharacter();
};

window.deleteAiEvent = async (id) => {
  if (!confirm("确定停用这张事件卡？")) return;
  await api(`/api/ai-character/events/${id}`, {method:"DELETE"});
  await loadAiCharacter();
};

window.loadAiTaskDetail = async (id) => {
  const detail = await api(`/api/ai-character/tasks/${encodeURIComponent(id)}`);
  $("aiTaskDetail").textContent = JSON.stringify(detail, null, 2);
};

async function testAiModel(target, thinking) {
  $("aiModelResult").textContent = "正在测试，请稍等……";
  try {
    const result = await api("/api/ai-character/model-test", {method:"POST", body:{target, thinking}});
    $("aiModelResult").textContent = `${result.message}｜模型：${result.model}｜Token：${result.token_available ? `${result.token_input}/${result.token_output}` : "统计不可用"}`;
  } catch (error) {
    $("aiModelResult").textContent = `测试失败：${error.message}`;
  }
}

async function testAiPersona() {
  $("aiModelResult").textContent = "正在生成角色测试回复……";
  try {
    const result = await api("/api/ai-character/persona-test", {method:"POST", body:{}});
    $("aiModelResult").textContent = `${result.reply}\n\n模型：${result.model}｜Token：${result.token_input == null ? "统计不可用" : `${result.token_input}/${result.token_output}`}`;
  } catch (error) {
    $("aiModelResult").textContent = `人格测试失败：${error.message}`;
  }
}

var paidInteractionSettingsLoaded = false;
var fortuneSettingsLoaded = false;

function setConnectionAiSaveEnabled(enabled) {
  if ($("savePaidInteractionConnection")) $("savePaidInteractionConnection").disabled = !enabled;
  if ($("saveFortuneSettingsConnection")) $("saveFortuneSettingsConnection").disabled = !enabled;
}

async function loadConnectionAiSettings() {
  setConnectionAiSaveEnabled(false);
  try {
    await Promise.all([loadPaidInteractionSettings(), loadFortuneSettings()]);
    if ($("paidConnectionSaveResult")) {
      $("paidConnectionSaveResult").textContent = "付费互动提示词已从后台载入。";
      $("paidConnectionSaveResult").className = "notice success";
    }
    if ($("fortuneConnectionSaveResult")) {
      $("fortuneConnectionSaveResult").textContent = "塔罗牌提示词已从后台载入。";
      $("fortuneConnectionSaveResult").className = "notice success";
    }
  } finally {
    setConnectionAiSaveEnabled(paidInteractionSettingsLoaded && fortuneSettingsLoaded);
  }
}

var paidInteractionFieldMap = {
  paidEnableCommands: "paid_interaction_enable_commands",
  paidDisableCommands: "paid_interaction_disable_commands",
  paidAmount: "paid_interaction_amount",
  paidMinBalance: "paid_interaction_min_balance",
  paidMaxActionChars: "paid_interaction_max_action_chars",
  paidAiEnabled: "paid_interaction_ai_enabled",
  paidAiBaseUrl: "paid_interaction_ai_base_url",
  paidAiModel: "paid_interaction_ai_model",
  paidAiTimeout: "paid_interaction_ai_timeout_seconds",
  paidAiSystemPrompt: "paid_interaction_ai_system_prompt",
  paidAiUserPrompt: "paid_interaction_ai_user_prompt",
  paidAiTemperature: "paid_interaction_ai_temperature",
  paidAiMaxTokens: "paid_interaction_ai_max_tokens",
  paidAiMaxOutputChars: "paid_interaction_ai_max_output_chars",
  paidSettlementFooter: "paid_interaction_settlement_footer",
  paidAiDisabledReply: "paid_interaction_ai_disabled_reply",
  paidAiNotConfiguredReply: "paid_interaction_ai_not_configured_reply",
  paidAiErrorReply: "paid_interaction_ai_error_reply",
  paidActionTooLongReply: "paid_interaction_action_too_long_reply",
  paidEnabledReply: "paid_interaction_enabled_reply",
  paidDisabledReply: "paid_interaction_disabled_reply",
  paidTargetDisabledReply: "paid_interaction_target_disabled_reply",
  paidUsageReply: "paid_interaction_usage_reply",
  paidTargetNotFoundReply: "paid_interaction_target_not_found_reply",
  paidIdentityInvalidReply: "paid_interaction_identity_invalid_reply",
  paidSelfReply: "paid_interaction_self_reply",
  paidLimitReply: "paid_interaction_limit_reply",
};

var paidInteractionNumberFields = new Set([
  "paidAmount",
  "paidMinBalance",
  "paidMaxActionChars",
  "paidAiTimeout",
  "paidAiTemperature",
  "paidAiMaxTokens",
  "paidAiMaxOutputChars",
]);

async function loadPaidInteractionSettings() {
  var data = await api("/api/paid-interaction/settings");
  Object.entries(paidInteractionFieldMap).forEach(function(entry) {
    var id = entry[0];
    var key = entry[1];
    var element = $(id);
    if (!element) return;
    if (element.type === "checkbox") element.checked = !!data[key];
    else element.value = data[key] ?? "";
  });
  var sourceText = data.api_key_source === "manual" ? "手动密钥" : (data.api_key_source === "embedded" ? "内置备用密钥" : "未配置");
  $("paidAiKeyStatus").textContent = data.api_key_configured ? (sourceText + " " + (data.api_key_hint || "")) : "未配置";
  $("paidAiKeyStatus").classList.toggle("online", !!data.api_key_configured);
  paidInteractionSettingsLoaded = true;
  setConnectionAiSaveEnabled(paidInteractionSettingsLoaded && fortuneSettingsLoaded);
  return data;
}

function collectPaidInteractionSettings() {
  var payload = {};
  Object.entries(paidInteractionFieldMap).forEach(function(entry) {
    var id = entry[0];
    var key = entry[1];
    var element = $(id);
    if (element.type === "checkbox") payload[key] = element.checked;
    else if (paidInteractionNumberFields.has(id)) payload[key] = Number(element.value);
    else payload[key] = element.value;
  });
  var apiKey = $("paidAiKey").value.trim();
  if (apiKey) payload.api_key = apiKey;
  return payload;
}

async function savePaidInteractionSettings(showMessage = true) {
  try {
    var data = await api("/api/paid-interaction/settings", {
      method: "POST",
      body: collectPaidInteractionSettings(),
    });
    $("paidAiKey").value = "";
    var sourceText = data.api_key_source === "manual" ? "手动密钥" : (data.api_key_source === "embedded" ? "内置备用密钥" : "未配置");
    $("paidAiKeyStatus").textContent = data.api_key_configured ? (sourceText + " " + (data.api_key_hint || "")) : "未配置";
    $("paidSaveResult").textContent = "付费互动设置已保存，密钥替换会立即生效。";
    $("paidSaveResult").className = "notice success";
    if (showMessage) alert("付费互动设置已保存。");
    return data;
  } catch (error) {
    $("paidSaveResult").textContent = "保存失败：" + error.message;
    $("paidSaveResult").className = "notice error";
    throw error;
  }
}

async function restoreEmbeddedDeepseekKey() {
  if (!confirm("确定删除手动替换的 DeepSeek 密钥，恢复使用 EXE 内置备用密钥？")) return;
  var payload = collectPaidInteractionSettings();
  delete payload.api_key;
  payload.clear_api_key = true;
  await api("/api/paid-interaction/settings", {method:"POST", body:payload});
  $("paidAiKey").value = "";
  await loadPaidInteractionSettings();
  $("paidAiTestResult").textContent = "已恢复使用内置备用密钥。";
  $("paidAiTestResult").className = "notice success";
}

async function testPaidInteractionAi() {
  $("paidAiTestResult").textContent = "正在保存设置并连接 DeepSeek……";
  try {
    await savePaidInteractionSettings(false);
    var data = await api("/api/paid-interaction/test", { method: "POST" });
    $("paidAiTestResult").textContent = data.message || "DeepSeek 连接成功。";
    $("paidAiTestResult").className = "notice success";
  } catch (error) {
    $("paidAiTestResult").textContent = "连接失败：" + error.message;
    $("paidAiTestResult").className = "notice error";
  }
}

var fortuneFieldMap = {
  fortuneEnabled: "fortune_enabled",
  fortuneReaderName: "fortune_reader_name",
  fortuneCost: "fortune_cost",
  fortuneAiBaseUrl: "fortune_ai_base_url",
  fortuneAiModel: "fortune_ai_model",
  fortuneAiTemperature: "fortune_ai_temperature",
  fortuneAiMaxTokens: "fortune_ai_max_tokens",
  fortuneAiMaxOutputChars: "fortune_ai_max_output_chars",
  fortuneAiTimeout: "fortune_ai_timeout_seconds",
  fortuneAiSystemPrompt: "fortune_ai_system_prompt",
  fortuneAiUserPrompt: "fortune_ai_user_prompt",
  fortuneAiRepairPrompt: "fortune_ai_repair_prompt",
  fortuneDrawReply: "fortune_draw_reply",
  fortuneUsageReply: "fortune_usage_reply",
  fortuneTopicTooLongReply: "fortune_topic_too_long_reply",
  fortuneDisabledReply: "fortune_disabled_reply",
  fortuneIdentityInvalidReply: "fortune_identity_invalid_reply",
  fortuneAlreadyReply: "fortune_already_reply",
  fortuneNoMoneyReply: "fortune_no_money_reply",
  fortuneAiNotConfiguredReply: "fortune_ai_not_configured_reply",
  fortuneImageErrorReply: "fortune_image_error_reply",
  fortuneAiErrorReply: "fortune_ai_error_reply",
  fortuneFormatErrorReply: "fortune_format_error_reply",
  fortuneSettlementFooter: "fortune_settlement_footer",
};

var fortuneNumberFields = new Set([
  "fortuneCost",
  "fortuneAiTemperature",
  "fortuneAiMaxTokens",
  "fortuneAiMaxOutputChars",
  "fortuneAiTimeout",
]);

function renderFortuneStats(stats) {
  stats = stats || {};
  var currency = (config.features || {}).currency_name || "功德点";
  $("fortuneTodayCount").textContent = (stats.today_count || 0) + " 人";
  $("fortuneTotalCount").textContent = (stats.total_count || 0) + " 次";
  $("fortuneTotalCost").textContent = (stats.total_cost || 0) + " " + currency;
  var recent = stats.recent || [];
  $("fortuneHistory").innerHTML = recent.length
    ? "<table><thead><tr><th>用户</th><th>唯一 ID</th><th>主题</th><th>牌面</th><th>消耗</th><th>占卜时间</th></tr></thead><tbody>" +
      recent.map(function(row) {
        return "<tr><td>" + h(row.nickname) + "</td><td><code>" +
          h(row.user_id) + "</code></td><td><b>「" + h(row.character) +
          "」</b></td><td>" + h(row.card_name || "历史运势记录") +
          h(row.orientation ? "（" + row.orientation + "）" : "") +
          "</td><td>" + h(row.cost) + " " + h(currency) +
          "</td><td>" + h(row.created_at) + "</td></tr>";
      }).join("") + "</tbody></table>"
    : "暂无占卜记录。";
}

async function loadFortuneSettings() {
  var data = await api("/api/fortune/settings");
  Object.entries(fortuneFieldMap).forEach(function(entry) {
    var element = $(entry[0]);
    if (!element) return;
    var value = data[entry[1]];
    if (element.type === "checkbox") element.checked = !!value;
    else element.value = value ?? "";
  });
  $("fortuneAiKeyStatus").textContent = data.api_key_configured
    ? "内置密钥已锁定"
    : "未检测到内置密钥";
  $("fortuneAiKeyStatus").classList.toggle("online", !!data.api_key_configured);
  renderFortuneStats(data.stats);
  fortuneSettingsLoaded = true;
  setConnectionAiSaveEnabled(paidInteractionSettingsLoaded && fortuneSettingsLoaded);
  return data;
}

function collectFortuneSettings() {
  var payload = {};
  Object.entries(fortuneFieldMap).forEach(function(entry) {
    var element = $(entry[0]);
    if (element.type === "checkbox") payload[entry[1]] = element.checked;
    else if (fortuneNumberFields.has(entry[0])) {
      payload[entry[1]] = Number(element.value);
    } else payload[entry[1]] = element.value;
  });
  return payload;
}

async function saveFortuneSettings() {
  try {
    var data = await api("/api/fortune/settings", {
      method: "POST",
      body: collectFortuneSettings(),
    });
    renderFortuneStats(data.stats);
    $("fortuneSaveResult").textContent =
      "塔罗牌设置已保存，付费互动提示词未作任何修改。";
    $("fortuneSaveResult").className = "notice success";
    alert("塔罗牌设置已保存。");
    return data;
  } catch (error) {
    $("fortuneSaveResult").textContent = "保存失败：" + error.message;
    $("fortuneSaveResult").className = "notice error";
    throw error;
  }
}

var bountyFieldMap = {
  bountyEnabled: "bounty_enabled",
  bountyInviteUrl: "bounty_invite_url",
  bountyPublishCommands: "bounty_publish_commands",
  bountyListCommands: "bounty_list_commands",
  bountyDetailCommands: "bounty_detail_commands",
  bountyAcceptCommands: "bounty_accept_commands",
  bountyMyCommands: "bounty_my_commands",
  bountyCompleteCommands: "bounty_complete_commands",
  bountyConfirmCommands: "bounty_confirm_commands",
  bountyCancelCommands: "bounty_cancel_commands",
  bountyAiDraftTtl: "bounty_ai_draft_ttl_seconds",
  bountyAiBaseUrl: "bounty_ai_base_url",
  bountyAiModel: "bounty_ai_model",
  bountyAiTimeout: "bounty_ai_timeout_seconds",
  bountyAiSystemPrompt: "bounty_ai_system_prompt",
  bountyAiUserPrompt: "bounty_ai_user_prompt",
  bountyAiFailureReply: "bounty_ai_failure_reply",
  bountyAiNotConfiguredReply: "bounty_ai_not_configured_reply",
  bountyAiErrorReply: "bounty_ai_error_reply",
  bountyAiPreviewReply: "bounty_ai_preview_reply",
  bountyAiPublishedReply: "bounty_ai_published_reply",
  bountyAiCancelledReply: "bounty_ai_cancelled_reply",
  bountyAiExpiredReply: "bounty_ai_expired_reply",
  bountyAiMissingReply: "bounty_ai_missing_reply",
  bountyAiInvalidReply: "bounty_ai_invalid_reply",
  bountyBusinessErrorReply: "bounty_business_error_reply",
  bountyHelpReply: "bounty_help_reply",
  bountyDisabledReply: "bounty_disabled_reply",
  bountyGroupOnlyReply: "bounty_group_only_reply",
  bountyCardReply: "bounty_card_reply",
  bountyCardAcceptLine: "bounty_card_accept_line",
  bountySyncedReply: "bounty_synced_reply",
  bountyListHeaderReply: "bounty_list_header_reply",
  bountyListItemReply: "bounty_list_item_reply",
  bountyListEmptyReply: "bounty_list_empty_reply",
  bountyListFooterReply: "bounty_list_footer_reply",
  bountyDetailUsageReply: "bounty_detail_usage_reply",
  bountyDetailNotFoundReply: "bounty_detail_not_found_reply",
  bountyAcceptUsageReply: "bounty_accept_usage_reply",
  bountyAcceptNotFoundReply: "bounty_accept_not_found_reply",
  bountyAcceptNotWaitingReply: "bounty_accept_not_waiting_reply",
  bountyAcceptDuplicateReply: "bounty_accept_duplicate_reply",
  bountyAcceptFullReply: "bounty_accept_full_reply",
  bountyAcceptSelfReply: "bounty_accept_self_reply",
  bountyAcceptBannedReply: "bounty_accept_banned_reply",
  bountyAcceptFailedReply: "bounty_accept_failed_reply",
  bountyAcceptSuccessReply: "bounty_accept_success_reply",
  bountyMyHeaderReply: "bounty_my_header_reply",
  bountyMyPublishedHeaderReply: "bounty_my_published_header_reply",
  bountyMyTakenHeaderReply: "bounty_my_taken_header_reply",
  bountyMyItemReply: "bounty_my_item_reply",
  bountyMyEmptyReply: "bounty_my_empty_reply",
  bountyCompleteUsageReply: "bounty_complete_usage_reply",
  bountyCompleteNotFoundReply: "bounty_complete_not_found_reply",
  bountyCompleteNotTakerReply: "bounty_complete_not_taker_reply",
  bountyCompleteAlreadyReply: "bounty_complete_already_reply",
  bountyCompleteInvalidReply: "bounty_complete_invalid_reply",
  bountyCompleteFailedReply: "bounty_complete_failed_reply",
  bountyCompleteIndividualReply: "bounty_complete_individual_reply",
  bountyConfirmUsageReply: "bounty_confirm_usage_reply",
  bountyConfirmNotFoundReply: "bounty_confirm_not_found_reply",
  bountyConfirmNotPublisherReply: "bounty_confirm_not_publisher_reply",
  bountyConfirmInvalidReply: "bounty_confirm_invalid_reply",
  bountyConfirmFailedReply: "bounty_confirm_failed_reply",
  bountyConfirmPartialSuccessReply: "bounty_confirm_partial_success_reply",
  bountyConfirmFinalSuccessReply: "bounty_confirm_final_success_reply",
  bountyCancelUsageReply: "bounty_cancel_usage_reply",
  bountyCancelNotFoundReply: "bounty_cancel_not_found_reply",
  bountyCancelInvalidReply: "bounty_cancel_invalid_reply",
  bountyCancelNotPartyReply: "bounty_cancel_not_party_reply",
  bountyCancelNotPublisherReply: "bounty_cancel_not_publisher_reply",
  bountyCancelFailedReply: "bounty_cancel_failed_reply",
  bountyCancelSuccessReply: "bounty_cancel_success_reply",
  bountyCancelPartialSuccessReply: "bounty_cancel_partial_success_reply",
  bountyCancelAbandonmentReply: "bounty_cancel_abandonment_reply",
  bountyCancelBanReply: "bounty_cancel_ban_reply",
  commissionRequestPublishCommands: "commission_request_publish_commands",
  commissionServicePublishCommands: "commission_service_publish_commands",
  commissionConfirmDraftCommands: "commission_confirm_draft_commands",
  commissionCancelDraftCommands: "commission_cancel_draft_commands",
  commissionRequestListCommands: "commission_request_list_commands",
  commissionServiceListCommands: "commission_service_list_commands",
  commissionRequestDetailCommands: "commission_request_detail_commands",
  commissionServiceDetailCommands: "commission_service_detail_commands",
  commissionRequestAcceptCommands: "commission_request_accept_commands",
  commissionServiceAcceptCommands: "commission_service_accept_commands",
  commissionMyPostsCommands: "commission_my_posts_commands",
  commissionMyDemandsCommands: "commission_my_demands_commands",
  commissionMyServicesCommands: "commission_my_services_commands",
  commissionMyOrdersCommands: "commission_my_orders_commands",
  commissionOrderDetailCommands: "commission_order_detail_commands",
  commissionOrderCompleteCommands: "commission_order_complete_commands",
  commissionOrderConfirmCommands: "commission_order_confirm_commands",
  commissionOrderCancelCommands: "commission_order_cancel_commands",
  commissionOrderCancelApproveCommands: "commission_order_cancel_approve_commands",
  commissionOrderCancelRejectCommands: "commission_order_cancel_reject_commands",
  commissionCloseRequestCommands: "commission_close_request_commands",
  commissionCloseServiceCommands: "commission_close_service_commands",
  commissionServiceRestockCommands: "commission_service_restock_commands",
  commissionServiceRenewCommands: "commission_service_renew_commands",
  commissionHelpCommands: "commission_help_commands",
  commissionMainGroupOnlyReply: "commission_main_group_only_reply",
  commissionBountyGroupOnlyReply: "commission_bounty_group_only_reply",
  commissionRequestPreviewReply: "commission_request_preview_reply",
  commissionServicePreviewReply: "commission_service_preview_reply",
  commissionPublishedReply: "commission_published_reply",
  commissionDraftCancelledReply: "commission_draft_cancelled_reply",
  commissionDraftMissingReply: "commission_draft_missing_reply",
  commissionDraftExpiredReply: "commission_draft_expired_reply",
  commissionRequestListHeaderReply: "commission_request_list_header_reply",
  commissionRequestListItemReply: "commission_request_list_item_reply",
  commissionRequestListEmptyReply: "commission_request_list_empty_reply",
  commissionRequestListFooterReply: "commission_request_list_footer_reply",
  commissionServiceListHeaderReply: "commission_service_list_header_reply",
  commissionServiceListItemReply: "commission_service_list_item_reply",
  commissionServiceListEmptyReply: "commission_service_list_empty_reply",
  commissionServiceListFooterReply: "commission_service_list_footer_reply",
  commissionLegacyServiceItemReply: "commission_legacy_service_item_reply",
  commissionLegacyServiceFooterReply: "commission_legacy_service_footer_reply",
  commissionRequestCardReply: "commission_request_card_reply",
  commissionServiceCardReply: "commission_service_card_reply",
  commissionOrderCreatedReply: "commission_order_created_reply",
  commissionOrderCompleteReply: "commission_order_complete_reply",
  commissionOrderConfirmReply: "commission_order_confirm_reply",
  commissionOrderCancelRequestedReply: "commission_order_cancel_requested_reply",
  commissionOrderCancelApprovedReply: "commission_order_cancel_approved_reply",
  commissionOrderCancelRejectedReply: "commission_order_cancel_rejected_reply",
  commissionOrderErrorReply: "commission_order_error_reply",
  commissionPostClosedReply: "commission_post_closed_reply",
  commissionHelpReply: "commission_help_reply",
  commissionDemandFeePercent: "commission_demand_fee_percent",
  commissionDemandMinReward: "commission_demand_min_reward",
  commissionDemandMaxPeople: "commission_demand_max_people",
  commissionDemandDefaultDays: "commission_demand_default_recruitment_days",
  commissionServiceCommissionPercent: "commission_service_commission_percent",
  commissionServiceMinPrice: "commission_service_min_price",
  commissionServiceDefaultStock: "commission_service_default_stock",
  commissionServiceMaxStock: "commission_service_max_stock",
  commissionServiceDefaultDays: "commission_service_default_listing_days",
  commissionServiceMaxActive: "commission_service_max_active",
  commissionDemandAiSystemPrompt: "commission_demand_ai_system_prompt",
  commissionDemandAiUserPrompt: "commission_demand_ai_user_prompt",
  commissionServiceAiSystemPrompt: "commission_service_ai_system_prompt",
  commissionServiceAiUserPrompt: "commission_service_ai_user_prompt",
};

var commissionHouseData = {demands:[], services:[], orders:[], counts:{}};
var commissionOrderData = [];
var commissionStatusText = {recruiting:"招募中",filled:"名额已满",completed:"已完成",closed:"已关闭",on_sale:"在售",sold_out:"售罄",expired:"已到期",off_shelf:"已下架",accepted:"进行中",submitted:"待确认",cancel_requested:"申请取消",cancelled:"已取消"};

function renderBountyStats(stats) {
  stats = stats || {};
  $("bountyWaitingCount").textContent = Number(stats.active_demands || 0) + " 条";
  $("bountyActiveCount").textContent = Number(stats.active_services || 0) + " 条";
  $("bountyBanCount").textContent = Number(stats.active_orders || 0) + " 单";
  $("bountyLockedReward").textContent = Number(stats.escrow || 0) + " 功德";
}

function renderCommissionDemands(rows) {
  var body = (rows || []).map(function(row) {
    return '<tr><td><b>' + h(row.commission_number) + '</b><br><small>' + h(commissionStatusText[row.status] || row.status) + '</small></td>' +
      '<td><b>' + h(row.title) + '</b><br><small>' + h(String(row.content || "").replace(/\s+/g," ").slice(0,100)) + '</small></td>' +
      '<td>' + h(row.publisher_nickname) + '</td><td>' + Number(row.accepted_count) + '/' + Number(row.required_people) + '<br><small>完成 ' + Number(row.completed_count) + '</small></td>' +
      '<td>' + Number(row.reward_per_person) + '/人</td><td>' + (Number(row.reward_escrow_remaining) + Number(row.fee_escrow_remaining)) + '</td><td>' + h(row.recruitment_expires_at || "-") + '</td>' +
      '<td><button type="button" onclick="openCommissionDemandEdit(' + Number(row.id) + ')">编辑需求</button></td></tr>';
  }).join("");
  $("bountyHistory").innerHTML = body ? '<table><thead><tr><th>编号/状态</th><th>需求内容</th><th>发布者</th><th>人数进度</th><th>每人奖励</th><th>剩余托管</th><th>招募截止</th><th>操作</th></tr></thead><tbody>' + body + '</tbody></table>' : '<div class="notice">暂无需求。</div>';
}

function renderCommissionServices(rows) {
  var body = (rows || []).map(function(row) {
    var stock = row.stock_mode === "unlimited" ? "不限" : (Number(row.stock_remaining) + '/' + Number(row.stock_total));
    return '<tr><td><b>' + h(row.commission_number) + '</b><br><small>' + h(commissionStatusText[row.status] || row.status) + '</small></td>' +
      '<td><b>' + h(row.title) + '</b><br><small>' + h(String(row.description || "").replace(/\s+/g," ").slice(0,100)) + '</small></td>' +
      '<td>' + h(row.seller_nickname) + '</td><td>' + Number(row.unit_price) + '/' + h(row.unit_label || "次") + '</td><td>' + h(stock) + '<br><small>已售 ' + Number(row.sold_quantity) + '</small></td>' +
      '<td>' + Number(row.commission_percent) + '%（卖家承担）</td><td>' + h(row.listing_expires_at || "-") + '</td>' +
      '<td><button type="button" onclick="openCommissionServiceEdit(' + Number(row.id) + ')">编辑服务</button></td></tr>';
  }).join("");
  $("commissionServiceTable").innerHTML = body ? '<table><thead><tr><th>编号/状态</th><th>服务商品</th><th>卖家</th><th>单价</th><th>库存</th><th>抽成</th><th>上架截止</th><th>操作</th></tr></thead><tbody>' + body + '</tbody></table>' : '<div class="notice">暂无服务。</div>';
}

function renderCommissionOrders(data) {
  commissionOrderData = (data && data.orders) || [];
  var body = commissionOrderData.map(function(order) {
    var active = ["accepted","submitted","cancel_requested"].includes(order.status);
    var choices = order.status === "accepted" ? '<option value="mark_submitted">标记待确认</option><option value="settle">直接结算</option><option value="refund">退款取消</option>' :
      (["submitted","cancel_requested"].includes(order.status) ? '<option value="settle">确认结算</option><option value="refund">退款取消</option><option value="reopen">恢复进行中</option>' : '');
    var controls = active ? '<div class="row-actions"><select id="commissionOrderAction' + Number(order.id) + '">' + choices + '</select><input id="commissionOrderReason' + Number(order.id) + '" maxlength="200" placeholder="必填：操作原因"><button type="button" onclick="adminCommissionOrder(' + Number(order.id) + ')">执行</button></div>' : '<span class="note">已结束</span>';
    return '<tr><td><b>' + h(order.commission_number) + '</b><br><small>' + h(order.order_kind === "service" ? "服务订单" : "需求订单") + '</small></td><td>' + h(order.content_snapshot) + '</td>' +
      '<td>' + h(order.client_nickname) + '</td><td>' + h(order.provider_nickname) + '</td><td>' + Number(order.quantity) + '</td><td>' + Number(order.gross_amount) + '<br><small>履约方实收 ' + Number(order.provider_net_amount) + '</small></td>' +
      '<td>' + h(commissionStatusText[order.status] || order.status) + '</td><td>' + controls + '</td></tr>';
  }).join("");
  $("commissionOrderTable").innerHTML = body ? '<table><thead><tr><th>订单/类型</th><th>成交快照</th><th>委托方/买家</th><th>履约方/卖家</th><th>数量</th><th>金额</th><th>状态</th><th>管理员操作</th></tr></thead><tbody>' + body + '</tbody></table>' : '<div class="notice">暂无订单。</div>';
}

function renderPromptHistory(rows) {
  var body = (rows || []).map(function(row){return '<tr><td>' + h(row.prompt_key.replace("commission_","").replace("_ai_"," · ")) + '</td><td>' + Number(row.value_length) + '字</td><td>' + h(row.created_at) + '</td><td><button type="button" onclick="restoreCommissionPrompt(' + Number(row.id) + ')">恢复此版</button></td></tr>';}).join("");
  $("commissionPromptHistory").innerHTML = body ? '<table><thead><tr><th>提示词</th><th>长度</th><th>保存时间</th><th>操作</th></tr></thead><tbody>' + body + '</tbody></table>' : '<div class="notice">尚无旧版本；首次修改时会自动生成。</div>';
}

async function loadAllBounties() {
  try {
    commissionHouseData = await api("/api/commission-house/overview");
    renderCommissionDemands(commissionHouseData.demands);
    renderCommissionServices(commissionHouseData.services);
    renderCommissionOrders({orders:commissionHouseData.orders});
    renderBountyStats(commissionHouseData.counts);
    return commissionHouseData;
  } catch (error) {
    $("bountyHistory").innerHTML = '<div class="notice error">委托所数据加载失败：' + h(error.message) + '</div>';
    throw error;
  }
}

async function loadCommissionOrders() { return loadAllBounties(); }

window.adminCommissionOrder = async function(id) {
  var action = $("commissionOrderAction" + id).value;
  var reason = $("commissionOrderReason" + id).value.trim();
  if (!reason) return alert("必须填写管理员操作原因，避免误操作和资金去向不明。");
  if (!confirm("确定执行这次订单操作吗？涉及资金的操作会立即记账。")) return;
  try {
    await api("/api/commission-house/orders/" + id, {method:"PUT", body:{action:action, reason:reason}});
    await loadAllBounties();
  } catch (error) {
    alert("订单处理失败：" + error.message);
  }
};

window.openCommissionDemandEdit = function(id) {
  var row = (commissionHouseData.demands || []).find(function(item){return Number(item.id) === Number(id);});
  if (!row) return;
  $("commissionDemandId").value = row.id;
  $("commissionDemandModalTitle").textContent = "编辑需求 " + row.commission_number;
  $("commissionDemandTitle").value = row.title || "";
  $("commissionDemandContent").value = row.content || "";
  $("commissionDemandPeople").value = Number(row.required_people);
  $("commissionDemandReward").value = Number(row.reward_per_person);
  $("commissionDemandExpiry").value = row.recruitment_expires_at || "";
  $("commissionDemandStatus").value = row.status;
  $("commissionDemandReason").value = "";
  $("commissionDemandModal").classList.remove("hidden");
};

window.openCommissionServiceEdit = function(id) {
  var row = (commissionHouseData.services || []).find(function(item){return Number(item.id) === Number(id);});
  if (!row) return;
  $("commissionServiceId").value = row.id;
  $("commissionServiceModalTitle").textContent = "编辑服务 " + row.commission_number;
  $("commissionServiceTitle").value = row.title || "";
  $("commissionServiceDescription").value = row.description || "";
  $("commissionServicePrice").value = Number(row.unit_price);
  $("commissionServiceUnit").value = row.unit_label || "次";
  $("commissionServiceStockMode").value = row.stock_mode;
  $("commissionServiceStockTotal").value = row.stock_total == null ? "" : Number(row.stock_total);
  $("commissionServiceStockRemaining").value = row.stock_remaining == null ? "" : Number(row.stock_remaining);
  $("commissionServiceExpiry").value = row.listing_expires_at || "";
  $("commissionServiceFee").value = Number(row.commission_percent);
  $("commissionServiceStatus").value = row.status;
  $("commissionServiceReason").value = "";
  syncCommissionServiceStockFields();
  $("commissionServiceModal").classList.remove("hidden");
};

function syncCommissionServiceStockFields() {
  var unlimited = $("commissionServiceStockMode").value === "unlimited";
  $("commissionServiceStockTotal").disabled = unlimited;
  $("commissionServiceStockRemaining").disabled = unlimited;
}

async function saveCommissionDemandEdit(event) {
  event.preventDefault();
  var id = Number($("commissionDemandId").value);
  var payload = {title:$("commissionDemandTitle").value.trim(),content:$("commissionDemandContent").value.trim(),required_people:Number($("commissionDemandPeople").value),reward_per_person:Number($("commissionDemandReward").value),recruitment_expires_at:$("commissionDemandExpiry").value.trim(),status:$("commissionDemandStatus").value,reason:$("commissionDemandReason").value.trim()};
  if (!payload.reason) return alert("必须填写管理员修改原因。");
  if (!confirm("确定保存需求修改吗？人数或奖励变化可能立即调整发布者余额与托管资金。")) return;
  try { await api("/api/commission-house/demands/" + id,{method:"PUT",body:payload}); $("commissionDemandModal").classList.add("hidden"); await loadAllBounties(); }
  catch(error){ alert("需求保存失败：" + error.message); }
}

async function saveCommissionServiceEdit(event) {
  event.preventDefault();
  var id = Number($("commissionServiceId").value), unlimited = $("commissionServiceStockMode").value === "unlimited";
  var payload = {title:$("commissionServiceTitle").value.trim(),description:$("commissionServiceDescription").value.trim(),unit_price:Number($("commissionServicePrice").value),unit_label:$("commissionServiceUnit").value.trim(),stock_mode:$("commissionServiceStockMode").value,stock_total:unlimited?null:Number($("commissionServiceStockTotal").value),stock_remaining:unlimited?null:Number($("commissionServiceStockRemaining").value),listing_expires_at:$("commissionServiceExpiry").value.trim(),commission_percent:Number($("commissionServiceFee").value),status:$("commissionServiceStatus").value,reason:$("commissionServiceReason").value.trim()};
  if (!payload.reason) return alert("必须填写管理员修改原因。");
  try { await api("/api/commission-house/services/" + id,{method:"PUT",body:payload}); $("commissionServiceModal").classList.add("hidden"); await loadAllBounties(); }
  catch(error){ alert("服务保存失败：" + error.message); }
}

window.restoreCommissionPrompt = async function(id) {
  if (!confirm("确定恢复这个提示词版本吗？当前版本也会先自动备份。")) return;
  try { await api("/api/commission-house/prompts/restore/" + id,{method:"POST",body:{}}); await loadBountySettings(); }
  catch(error){ alert("恢复失败：" + error.message); }
};

async function loadBountySettings() {
  var data = await api("/api/bounties/settings");
  Object.entries(bountyFieldMap).forEach(function(entry) {
    var element = $(entry[0]);
    if (!element) return;
    var value = data[entry[1]];
    if (element.type === "checkbox") element.checked = !!value;
    else element.value = value ?? "";
  });
  $("bountyMainGroupUrl").value = data.main_group_url || "";
  $("bountySystemGroupUrl").value = data.bounty_group_url || "";
  $("bountyMainGroupName").textContent = data.main_group_name || "";
  $("bountyGroupName").textContent = data.bounty_group_name || "";
  renderBountyStats(data.stats);
  renderPromptHistory(data.prompt_revisions || []);
  await loadAllBounties();
  return data;
}

var rpFieldMap = {
  rpEnabled: "rp_enabled",
  rpMaxParticipants: "rp_max_participants",
  rpGatherTimeout: "rp_gather_timeout_seconds",
  rpStartReply: "rp_start_reply",
  rpProgressReply: "rp_progress_reply",
  rpLastReply: "rp_last_reply",
  rpAnnouncementReply: "rp_announcement_reply",
  rpYellowWarningReply: "rp_yellow_warning_reply",
  rpSecondViolationReply: "rp_second_violation_reply",
  rpLaterViolationReply: "rp_later_violation_reply",
  rpEndReply: "rp_end_reply",
  rpTimeoutReply: "rp_timeout_reply",
};

async function loadRpSettings() {
  var data = await api("/api/rp/settings");
  Object.entries(rpFieldMap).forEach(function(entry) {
    var element = $(entry[0]);
    if (!element) return;
    if (element.type === "checkbox") element.checked = !!data[entry[1]];
    else element.value = data[entry[1]] ?? "";
  });
  return data;
}

async function saveRpSettings() {
  var payload = {};
  Object.entries(rpFieldMap).forEach(function(entry) {
    var element = $(entry[0]);
    if (element.type === "checkbox") payload[entry[1]] = element.checked;
    else if (element.type === "number") payload[entry[1]] = Number(element.value);
    else payload[entry[1]] = element.value;
  });
  var data = await api("/api/rp/settings", {method:"POST", body:payload});
  $("rpSaveResult").textContent = "RP结界设置已保存，新消息立即使用新文案。";
  $("rpSaveResult").className = "notice success";
  return data;
}

window.loadRpAdmin = async function() {
  var data = await api("/api/rp");
  var sessions = (data.sessions || []).map(function(row) {
    var names = (row.participants || []).map(function(p){ return p.nickname_snapshot; }).join("、");
    return '<article class="bounty-admin-card"><b>' + h(row.status === "active" ? "已开启" : "组队中") +
      '｜群：' + h(row.group_id) + '</b><p>人数：' + Number(row.current_count) + '/' + Number(row.target_count) +
      '｜发起者：' + h(row.initiator_nickname) + '</p><p>参与者：' + h(names) + '</p><p>发起：' + h(row.created_at) +
      '｜开启：' + h(row.started_at || "未开启") + '｜组队剩余：' + Number(row.remaining_seconds || 0) + '秒</p>' +
      '<button onclick="closeRpAdmin(\'' + h(row.group_id) + '\')">强制结束/清除</button></article>';
  }).join("") || '<div class="notice">当前没有组队中或已开启的RP。</div>';
  var violations = (data.violations || []).map(function(row) {
    var pending = row.handling_status === "pending_admin_action";
    return '<article class="bounty-admin-card"><b>' + h(row.nickname_snapshot) + '｜违规' + Number(row.violation_count) +
      '次｜' + h(row.handling_status) + '</b><p>群：' + h(row.group_id) + '｜会话：' + h(row.session_id) +
      '</p><p>最近：' + h(row.latest_at || row.first_at) + '｜' + h(row.latest_summary) + '</p>' +
      (pending ? '<button onclick="resolveRpViolation(' + Number(row.id) + ',\'resolved\')">标记已处理</button> <button onclick="resolveRpViolation(' + Number(row.id) + ',\'ignored\')">忽略</button>' : '') + '</article>';
  }).join("") || '<div class="notice">暂无违规记录。</div>';
  $("rpAdmin").innerHTML = '<h3>当前会话</h3>' + sessions + '<h3>黄牌与待处理记录</h3>' + violations;
  return data;
};

window.closeRpAdmin = async function(groupId) {
  await api("/api/rp/" + encodeURIComponent(groupId) + "/close", {method:"POST", body:{}});
  await loadRpAdmin();
};

window.resolveRpViolation = async function(id, status) {
  var note = prompt("管理员处理备注（可留空）", "") || "";
  await api("/api/rp/violations/" + id, {method:"POST", body:{status:status, note:note}});
  await loadRpAdmin();
};

var randomEventAdminData = {templates:[], current:[], history:[], schedule_runs:[]};
var randomEventFieldMap = {
  randomEventEnabled: "random_event_enabled",
  randomEventCreateCommands: "random_event_create_commands",
  randomEventConfirmCommands: "random_event_confirm_commands",
  randomEventCancelCommands: "random_event_cancel_commands",
  randomEventStartCommands: "random_event_start_commands",
  randomEventStatusCommands: "random_event_status_commands",
  randomEventJoinCommands: "random_event_join_commands",
  randomEventLeaveCommands: "random_event_leave_commands",
  randomEventEndCommands: "random_event_end_commands",
  randomEventRewardCommands: "random_event_reward_commands",
  randomEventRecruitTimeout: "random_event_recruit_timeout_seconds",
  randomEventDraftTtl: "random_event_draft_ttl_seconds",
  randomEventAutoEnabled: "random_event_auto_enabled",
  randomEventAutoCount: "random_event_auto_daily_count",
  randomEventAutoTimes: "random_event_auto_times",
  randomEventAiBaseUrl: "random_event_ai_base_url",
  randomEventAiModel: "random_event_ai_model",
  randomEventAiTimeout: "random_event_ai_timeout_seconds",
  randomEventAiSystemPrompt: "random_event_ai_system_prompt",
  randomEventAiUserPrompt: "random_event_ai_user_prompt",
};

var randomEventReplySpecs = [
  ["random_event_admin_only_reply", "非管理员提示", ""],
  ["random_event_disabled_reply", "功能关闭提示", ""],
  ["random_event_create_usage_reply", "创建格式提示", "{create_command}"],
  ["random_event_ai_not_configured_reply", "AI未配置提示", ""],
  ["random_event_ai_error_reply", "AI解析失败提示", ""],
  ["random_event_draft_preview_reply", "AI草稿预览", "{title} {role_count} {role_lines} {content} {confirm_command} {cancel_command} {newline}"],
  ["random_event_created_reply", "确认入库回复", "{event_number} {title} {role_count}"],
  ["random_event_draft_cancelled_reply", "取消草稿回复", ""],
  ["random_event_draft_missing_reply", "草稿不存在回复", ""],
  ["random_event_library_empty_reply", "事件库为空提示", ""],
  ["random_event_busy_reply", "已有随机事件提示", ""],
  ["random_event_rp_busy_reply", "已有RP结界提示", ""],
  ["random_event_recruit_reply", "发起招募公告", "{event_number} {title} {content} {role_lines} {role_count} {wait_minutes} {join_command} {newline}"],
  ["random_event_join_success_reply", "加入成功回复", "{user} {role_number} {role_name} {role_gender} {current_count} {required_count} {remaining_count} {newline}"],
  ["random_event_join_duplicate_reply", "重复加入提示", ""],
  ["random_event_join_role_taken_reply", "角色已被选择提示", ""],
  ["random_event_join_invalid_role_reply", "角色编号错误提示", "{join_command}"],
  ["random_event_open_reply", "人员到齐并开启RP回复", "{participant_lines} {newline}"],
  ["random_event_status_reply", "事件状态回复", "{title} {status} {current_count} {required_count} {participant_lines} {available_lines} {newline}"],
  ["random_event_leave_reply", "退队回复", "{role_number} {current_count}"],
  ["random_event_end_reply", "事件结束回复", "{reward_command} {newline}"],
  ["random_event_cancelled_reply", "招募取消回复", ""],
  ["random_event_timeout_reply", "招募超时回复", "{event_number} {title}"],
  ["random_event_reward_usage_reply", "奖励格式提示", "{reward_command}"],
  ["random_event_reward_success_reply", "奖励成功回复", "{participant_names} {amount}"],
  ["random_event_reward_missing_reply", "无可奖励事件提示", ""],
];

function ensureRandomEventReplyFields() {
  var root = $("randomEventReplyFields");
  if (!root || root.dataset.ready === "1") return;
  root.innerHTML = randomEventReplySpecs.map(function(spec, index) {
    return '<label>' + h(spec[1]) + (spec[2] ? '<span>变量：' + h(spec[2]) + '</span>' : '') +
      '<textarea id="randomEventReply' + index + '" rows="' + (index === 5 || index === 12 ? 8 : 3) + '"></textarea></label>';
  }).join("");
  root.dataset.ready = "1";
}

async function loadRandomEventSettings() {
  ensureRandomEventReplyFields();
  var data = await api("/api/random-events/settings");
  Object.entries(randomEventFieldMap).forEach(function(entry) {
    var element = $(entry[0]);
    if (!element) return;
    var value = data[entry[1]];
    if (element.type === "checkbox") element.checked = !!value;
    else element.value = value ?? "";
  });
  randomEventReplySpecs.forEach(function(spec, index) {
    $("randomEventReply" + index).value = data[spec[0]] ?? "";
  });
  return data;
}

async function saveRandomEventSettings() {
  ensureRandomEventReplyFields();
  var payload = {};
  Object.entries(randomEventFieldMap).forEach(function(entry) {
    var element = $(entry[0]);
    if (element.type === "checkbox") payload[entry[1]] = element.checked;
    else if (element.type === "number") payload[entry[1]] = Number(element.value);
    else payload[entry[1]] = element.value.trim();
  });
  randomEventReplySpecs.forEach(function(spec, index) {
    payload[spec[0]] = $("randomEventReply" + index).value;
  });
  try {
    var data = await api("/api/random-events/settings", {method:"POST", body:payload});
    $("randomEventSaveResult").textContent = "随机事件命令、定时计划、AI提示词和回复文案已保存。";
    $("randomEventSaveResult").className = "notice success";
    await loadRandomEventSettings();
    return data;
  } catch (error) {
    $("randomEventSaveResult").textContent = "保存失败：" + error.message;
    $("randomEventSaveResult").className = "notice error";
    throw error;
  }
}

function randomEventParticipantText(row) {
  return (row.participants || []).filter(function(item){return !item.left_at;}).map(function(item) {
    return Number(item.role_number) + "号" + item.role_name + "：" + item.nickname_snapshot;
  }).join("、") || "暂无";
}

window.loadRandomEventsAdmin = async function() {
  var data = await api("/api/random-events");
  randomEventAdminData = data;
  $("randomEventTemplates").innerHTML = (data.templates || []).map(function(row) {
    var roles = (row.roles || []).map(function(role){ return Number(role.number) + "号 " + role.name + "（" + role.gender + "）"; }).join("、");
    var state = row.archived_at ? "已归档" : (row.enabled ? "已启用" : "已停用");
    return '<article class="bounty-admin-card"><b>' + h(row.event_number) + '｜' + h(row.title) + '</b>' +
      '<p>' + h(row.content) + '</p><p>角色：' + h(roles) + '</p>' +
      '<p>状态：' + h(state) + '｜发起' + Number(row.start_count || 0) + '次｜最近：' + h(row.last_started_at || "从未") + '</p>' +
      '<button onclick="editRandomEventTemplate(' + Number(row.id) + ')">编辑事件</button></article>';
  }).join("") || '<div class="notice">事件库为空。可以在后台新建，也可以由管理员在群里发送 /创建随机事件：剧情。</div>';
  $("randomEventCurrent").innerHTML = (data.current || []).map(function(row) {
    return '<article class="bounty-admin-card"><b>' + h(row.event.event_number) + '｜' + h(row.event.title) + '｜' + h(row.status) + '</b>' +
      '<p>群：' + h(row.group_id) + '｜进度：' + Number(row.current_count) + '/' + Number(row.required_count) + '</p>' +
      '<p>参与者：' + h(randomEventParticipantText(row)) + '</p><p>发起方式：' + h(row.start_source) + '｜创建：' + h(row.created_at) + '</p>' +
      '<button onclick="closeRandomEventAdmin(\'' + h(row.group_id) + '\')">强制结束/取消</button></article>';
  }).join("") || '<div class="notice">当前没有正在招募或进行中的随机事件。</div>';
  $("randomEventHistory").innerHTML = (data.history || []).slice(0, 30).map(function(row) {
    var reward = row.rewarded_at ? ('｜已奖励每人' + Number(row.reward_amount || 0)) : (row.status === 'ended' ? '｜待管理员决定奖励' : '');
    return '<article class="bounty-admin-card"><b>' + h(row.event.event_number) + '｜' + h(row.event.title) + '｜' + h(row.status) + '</b>' +
      '<p>参与者：' + h(randomEventParticipantText(row)) + '</p><p>结束：' + h(row.ended_at || "") + h(reward) + '</p></article>';
  }).join("") || '<div class="notice">暂无历史场次。</div>';
  $("randomEventScheduleRuns").innerHTML = '<div class="row head"><span>日期时间</span><span>结果</span><span>详情</span></div>' +
    ((data.schedule_runs || []).map(function(row) {
      return '<div class="row"><span>' + h(row.scheduled_date + ' ' + row.scheduled_time) + '</span><span>' + h(row.status) + '</span><span>' + h(row.detail || row.session_id || '-') + '</span></div>';
    }).join("") || '<div class="notice">暂无自动发起记录。</div>');
  return data;
};

window.closeRandomEventAdmin = async function(groupId) {
  await api("/api/random-events/" + encodeURIComponent(groupId) + "/close", {method:"POST", body:{}});
  await loadRandomEventsAdmin();
};

var imageGenerationSettings = {};
var imageHistoryPage = 1;
var imageHistoryTotal = 0;
var selectedImageJobId = "";

var imageGenerationFieldMap = {
  imageEnabled: "enabled",
  imageCaseSensitive: "case_sensitive",
  imageDefaultCommands: "default_commands",
  imagePortraitCommands: "portrait_commands",
  imageLandscapeCommands: "landscape_commands",
  imageDefaultRatio: "default_ratio",
  imagePortraitRatio: "portrait_ratio",
  imageLandscapeRatio: "landscape_ratio",
  imageCost: "cost",
  imageMaxPromptChars: "max_prompt_chars",
  imageCooldownSeconds: "cooldown_seconds",
  imagePerUserDailyLimit: "per_user_daily_limit",
  imageGlobalDailyLimit: "global_daily_limit",
  imageMaxConcurrent: "max_concurrent",
  imageAdminExemptLimits: "admin_exempt_limits",
  imageAdminFree: "admin_free",
  imageRefundApiFailure: "refund_on_api_failure",
  imageRefundUploadFailure: "refund_on_upload_failure",
  imageRefundInterrupt: "refund_on_interrupt",
  imageApiBase: "api_base",
  imageApiModel: "model",
  imageApiTimeout: "api_timeout_seconds",
  imageDownloadTimeout: "download_timeout_seconds",
  imageUploadTimeout: "upload_timeout_seconds",
  imageMaxFileMb: "max_file_mb",
  imageHistoryPageSize: "history_page_size",
  imageHistoryRetentionDays: "history_retention_days",
  imageThumbnailDimension: "thumbnail_max_dimension",
  imageThumbnailQuality: "thumbnail_quality",
  imageHistorySavePrompt: "history_save_prompt",
  imageSendSuccessReply: "send_success_reply",
};

var imageReplySpecs = [
  ["usage_reply", "使用说明"], ["accepted_reply", "任务受理提示"],
  ["busy_reply", "系统繁忙提示"], ["empty_reply", "提示词为空"],
  ["too_long_reply", "提示词过长"], ["cooldown_reply", "冷却提示"],
  ["daily_limit_reply", "个人次数上限"], ["global_limit_reply", "全群次数上限"],
  ["insufficient_reply", "功德不足"], ["api_key_missing_reply", "API未配置"],
  ["group_only_reply", "非绘图群提示"], ["disabled_reply", "功能关闭提示"],
  ["success_reply", "生成成功提示"], ["api_failed_reply", "API失败与退款提示"],
  ["upload_failed_reply", "群聊上传失败提示"], ["resend_success_reply", "历史图片重发成功"],
];

function ensureImageReplyFields() {
  var root = $("imageReplyFields");
  if (!root || root.dataset.ready === "1") return;
  root.innerHTML = imageReplySpecs.map(function(spec, index) {
    return '<label>' + h(spec[1]) + '<textarea id="imageReply' + index + '" rows="3"></textarea></label>';
  }).join("");
  root.dataset.ready = "1";
}

async function loadImageGenerationSettings() {
  ensureImageReplyFields();
  var data = await api("/api/image-generation/settings");
  imageGenerationSettings = data;
  Object.entries(imageGenerationFieldMap).forEach(function(entry) {
    var element = $(entry[0]);
    if (!element) return;
    var value = data[entry[1]];
    if (element.type === "checkbox") element.checked = !!value;
    else element.value = value ?? "";
  });
  imageReplySpecs.forEach(function(spec, index) { $("imageReply" + index).value = data[spec[0]] ?? ""; });
  $("imageModuleGroupUrl").value = data.image_group_url || "";
  $("imageApiBaseConnection").value = data.api_base || "";
  $("imageApiModelConnection").value = data.model || "gpt-image-2";
  $("imageApiKeyStatus").textContent = data.api_key_configured ? ("手动密钥 " + data.api_key_hint) : "尚未配置";
  $("imageApiKeyStatus").className = "badge " + (data.api_key_configured ? "success" : "warning");
  if (data.service && data.service.stats) {
    var stats = data.service.stats;
    $("imageHistoryStats").textContent = "今日 " + Number(stats.total || 0) + " 次｜完成 " + Number(stats.completed || 0) + "｜退款 " + Number(stats.refunded_amount || 0) + "功德";
  }
  return data;
}

function collectImageGenerationSettings(connectionOnly) {
  var payload = { image_group_url: (connectionOnly ? $("imageGroupUrl").value : $("imageModuleGroupUrl").value).trim() };
  if (connectionOnly) {
    payload.api_base = $("imageApiBaseConnection").value.trim();
    payload.model = $("imageApiModelConnection").value.trim();
    payload.api_key = $("imageApiKeyConnection").value.trim();
    return payload;
  }
  Object.entries(imageGenerationFieldMap).forEach(function(entry) {
    var element = $(entry[0]);
    if (element.type === "checkbox") payload[entry[1]] = element.checked;
    else if (element.type === "number") payload[entry[1]] = Number(element.value);
    else payload[entry[1]] = element.value.trim();
  });
  imageReplySpecs.forEach(function(spec, index) { payload[spec[0]] = $("imageReply" + index).value; });
  payload.api_key = $("imageApiKey").value.trim();
  return payload;
}

async function saveImageGenerationSettings(connectionOnly) {
  var resultId = connectionOnly ? "imageApiConnectionResult" : "imageGenerationSaveResult";
  try {
    var data = await api("/api/image-generation/settings", {method:"POST", body:collectImageGenerationSettings(connectionOnly)});
    $(resultId).textContent = connectionOnly ? "图片API连接已保存，密钥不会回显。" : "图片生成命令、费用、限制、API参数和全部文案已保存。";
    $(resultId).className = "notice success";
    $("imageApiKey").value = "";
    $("imageApiKeyConnection").value = "";
    $("imageGroupUrl").value = data.image_group_url || "";
    await loadImageGenerationSettings();
    return data;
  } catch (error) {
    $(resultId).textContent = "保存失败：" + error.message;
    $(resultId).className = "notice error";
    throw error;
  }
}

async function clearImageApiKey(connectionOnly) {
  if (!confirm("确定清除当前图片 API 密钥？清除后图片生成会停止，直到你保存新密钥。")) return;
  var payload = collectImageGenerationSettings(connectionOnly);
  delete payload.api_key;
  payload.clear_api_key = true;
  var data = await api("/api/image-generation/settings", {method:"POST", body:payload});
  $("imageApiKey").value = "";
  $("imageApiKeyConnection").value = "";
  await loadImageGenerationSettings();
  var resultId = connectionOnly ? "imageApiConnectionResult" : "imageGenerationSaveResult";
  $(resultId).textContent = "图片 API 密钥已清除。";
  $(resultId).className = "notice success";
  return data;
}

async function testImageGenerationApi(resultId) {
  var target = $(resultId);
  target.textContent = "正在真实调用Image2生成测试图，请等待……";
  target.className = "notice";
  try {
    var data = await api("/api/image-generation/test", {method:"POST", body:{prompt:"一只可爱猫猫，精致插画", ratio:"3:4"}});
    target.textContent = data.message + "｜" + data.width + "×" + data.height + "｜" + data.format + "｜" + Math.ceil(data.file_size / 1024) + "KB";
    target.className = "notice success";
  } catch (error) {
    target.textContent = "测试失败：" + error.message;
    target.className = "notice error";
  }
}

function imageJobStatusText(value) {
  return ({accepted:"已受理",generating:"生成中",sending:"发送中",completed:"已完成",failed:"生成失败",upload_failed:"上传失败",interrupted:"已中断"})[value] || value || "未知";
}

async function loadImageGenerationHistory(page) {
  if (page) imageHistoryPage = Math.max(1, page);
  var size = Number((imageGenerationSettings || {}).history_page_size || 10);
  var status = $("imageHistoryStatus") ? $("imageHistoryStatus").value : "";
  var search = $("imageHistorySearch") ? $("imageHistorySearch").value.trim() : "";
  var data = await api("/api/image-generation/history?page=" + imageHistoryPage + "&page_size=" + size + "&status=" + encodeURIComponent(status) + "&search=" + encodeURIComponent(search));
  imageHistoryTotal = Number(data.total || 0);
  var totalPages = Math.max(1, Math.ceil(imageHistoryTotal / size));
  if (imageHistoryPage > totalPages) return loadImageGenerationHistory(totalPages);
  $("imageHistoryPageLabel").textContent = "第" + imageHistoryPage + "/" + totalPages + "页｜共" + imageHistoryTotal + "条";
  $("imageHistoryPrev").disabled = imageHistoryPage <= 1;
  $("imageHistoryNext").disabled = imageHistoryPage >= totalPages;
  $("imageHistoryGrid").innerHTML = (data.items || []).map(function(row) {
    var hasImage = !!row.image_path;
    var image = hasImage ? '<button class="image-history-thumb" onclick="openImageHistoryPreview(\'' + h(row.job_id) + '\')"><img src="/api/image-generation/history/' + encodeURIComponent(row.job_id) + '/thumbnail" alt="任务' + h(row.job_id) + '缩略图" loading="lazy"></button>' : '<div class="image-history-placeholder">无可用图片</div>';
    var refund = row.refunded ? ('｜已退款 ' + Number(row.refund_amount || 0)) : '';
    var actions = hasImage ? '<div class="toolbar"><button onclick="openImageHistoryPreview(\'' + h(row.job_id) + '\')">查看大图</button><a class="button-link" href="/api/image-generation/history/' + encodeURIComponent(row.job_id) + '/image?download=true" download>保存原图</a><button onclick="resendImageHistory(\'' + h(row.job_id) + '\')">重新发送</button></div>' : '';
    return '<article class="image-history-card">' + image + '<div class="image-history-copy"><b>' + h(row.nickname) + '｜' + h(row.ratio) + '</b><small>' + h(row.created_at) + '｜任务 ' + h(row.job_id) + '</small><p>' + h(row.prompt || "（未保存提示词）") + '</p><span class="badge">' + h(imageJobStatusText(row.status)) + '｜' + Number(row.cost || 0) + '功德' + h(refund) + '</span>' + (row.error_message ? '<p class="error-text">' + h(row.error_message) + '</p>' : '') + actions + '</div></article>';
  }).join("") || '<div class="notice">暂无符合条件的图片生成记录。</div>';
  return data;
}

window.openImageHistoryPreview = function(jobId) {
  selectedImageJobId = jobId;
  $("imagePreviewTitle").textContent = "任务 " + jobId;
  $("imagePreviewFull").src = "/api/image-generation/history/" + encodeURIComponent(jobId) + "/image";
  $("imagePreviewDownload").href = "/api/image-generation/history/" + encodeURIComponent(jobId) + "/image?download=true";
  $("imagePreviewModal").classList.remove("hidden");
};

window.resendImageHistory = async function(jobId) {
  if (!confirm("确定把任务 " + jobId + " 的原图重新发送到绘图群？")) return;
  try {
    await api("/api/image-generation/history/" + encodeURIComponent(jobId) + "/resend", {method:"POST", body:{}});
    alert("历史图片已重新发送到绘图群。");
    await loadImageGenerationHistory();
  } catch (error) { alert("重新发送失败：" + error.message); }
};

function openRandomEventTemplateModal(row) {
  row = row || {};
  $("randomEventTemplateId").value = row.id || "";
  $("randomEventTemplateTitle").textContent = row.id ? ("编辑 " + row.event_number) : "后台新建随机事件";
  $("randomEventTemplateName").value = row.title || "";
  $("randomEventTemplateContent").value = row.content || "";
  $("randomEventTemplateEnabled").checked = row.id ? !!row.enabled : true;
  $("randomEventTemplateRoles").value = (row.roles || []).map(function(role) {
    return role.name + "｜" + role.gender + "｜" + role.description;
  }).join("\n");
  $("randomEventTemplateNote").value = row.admin_note || "";
  $("archiveRandomEventTemplate").style.display = row.id && !row.archived_at ? "" : "none";
  $("randomEventTemplateResult").textContent = "角色每行使用：角色名称｜男/女/不限｜角色说明。";
  $("randomEventTemplateResult").className = "notice";
  $("randomEventTemplateModal").classList.remove("hidden");
}

window.editRandomEventTemplate = function(id) {
  openRandomEventTemplateModal((randomEventAdminData.templates || []).find(function(row){return Number(row.id) === Number(id);}) || {});
};

function collectRandomEventTemplate() {
  var roles = $("randomEventTemplateRoles").value.split(/\r?\n/).map(function(line) {
    var parts = line.split(/[｜|]/).map(function(item){return item.trim();});
    if (parts.length < 3) throw new Error("每个角色必须使用：角色名称｜男/女/不限｜角色说明");
    return {name:parts[0], gender:parts[1], description:parts.slice(2).join("｜")};
  }).filter(function(role){return role.name;});
  return {
    title: $("randomEventTemplateName").value.trim(),
    content: $("randomEventTemplateContent").value.trim(),
    enabled: $("randomEventTemplateEnabled").checked,
    roles: roles,
    admin_note: $("randomEventTemplateNote").value.trim(),
  };
}

async function saveBountySettings() {
  var payload = { bounty_group_url: $("bountySystemGroupUrl").value.trim() };
  Object.entries(bountyFieldMap).forEach(function(entry) {
    var element = $(entry[0]);
    if (element.type === "checkbox") payload[entry[1]] = element.checked;
    else payload[entry[1]] = element.value.trim();
  });
  try {
    var data = await api("/api/bounties/settings", {
      method: "POST",
      body: payload,
    });
    $("bountyGroupUrl").value = data.bounty_group_url || "";
    if (config.dzmm) config.dzmm.bounty_group_url = data.bounty_group_url || "";
    renderBountyStats(data.stats);
    renderPromptHistory(data.prompt_revisions || []);
    $("bountySaveResult").textContent = "群友委托所设置已保存，悬赏群监听页已重新建立基线。";
    $("bountySaveResult").className = "notice success";
    return data;
  } catch (error) {
    $("bountySaveResult").textContent = "保存失败：" + error.message;
    $("bountySaveResult").className = "notice error";
    throw error;
  }
}

function findBountyById(id) {
  var groups = (bountyGroupedData || {}).groups || {};
  for (var key of Object.keys(groups)) {
    var row = (groups[key].items || []).find(function(item) { return Number(item.id) === Number(id); });
    if (row) return row;
  }
  return null;
}

function syncBountyDurationInput() {
  var single = $("bountyEditDurationType").value === "single";
  $("bountyEditDurationDays").disabled = single;
  if (single) $("bountyEditDurationDays").value = "";
  else if (!$("bountyEditDurationDays").value) $("bountyEditDurationDays").value = 1;
}

window.openBountyEdit = function(id) {
  var row = findBountyById(id);
  if (!row) {
    alert("悬赏数据已经刷新，请重新打开。");
    return;
  }
  $("bountyEditId").value = row.id;
  $("bountyEditTitle").textContent = "编辑悬赏 #" + row.number;
  $("bountyEditNumber").value = "#" + row.number;
  $("bountyEditPublisher").value = row.publisher_title + "｜" + row.publisher_user_id;
  $("bountyEditParticipants").value = (row.participants || []).map(function(p) {
    return (p.display_name || p.display_name_snapshot) + "｜" + p.user_id + "｜" + p.participant_status;
  }).join("\n") || "暂无参与者";
  $("bountyEditContent").value = row.content || "";
  $("bountyEditDurationType").value = row.duration_type;
  $("bountyEditDurationDays").value = row.duration_type === "days" ? Number(row.duration_days) : "";
  $("bountyEditRequiredCount").value = Number(row.required_count);
  $("bountyEditUnlimitedStock").checked = !!row.unlimited_stock;
  $("bountyEditUnlimitedStock").disabled = row.bounty_mode !== "service";
  $("bountyEditReward").value = Number(row.reward_per_person);
  $("bountyEditStatus").value = row.business_status || row.status;
  $("bountyEditAdminNote").value = row.admin_note || "";
  $("bountyEditReason").value = "";
  $("bountyEditResult").textContent = "当前托管：奖励 " + Number(row.reward_escrow) + "，手续费 " + Number(row.fee_escrow) + "，总计 " + Number(row.total_charge) + " 功德。";
  $("bountyEditResult").className = "notice";
  syncBountyDurationInput();
  $("bountyEditModal").classList.remove("hidden");
};

function closeBountyEditModal() {
  $("bountyEditModal").classList.add("hidden");
}

async function saveBountyEdit(event) {
  event.preventDefault();
  var id = Number($("bountyEditId").value);
  var reason = $("bountyEditReason").value.trim();
  if (!reason) {
    $("bountyEditResult").textContent = "保存失败：必须填写操作原因。";
    $("bountyEditResult").className = "notice error";
    return;
  }
  var durationType = $("bountyEditDurationType").value;
  var payload = {
    content: $("bountyEditContent").value.trim(),
    duration_type: durationType,
    duration_days: durationType === "days" ? Number($("bountyEditDurationDays").value) : 0,
    required_count: Number($("bountyEditRequiredCount").value),
    unlimited_stock: !!$("bountyEditUnlimitedStock").checked,
    reward_per_person: Number($("bountyEditReward").value),
    status: $("bountyEditStatus").value,
    admin_note: $("bountyEditAdminNote").value.trim(),
    reason: reason,
  };
  try {
    var result = await api("/api/bounties/" + id, { method: "PUT", body: payload });
    $("bountyEditResult").textContent = "保存成功。发布者余额差额：" + Number(result.balance_delta || 0) + " 功德。";
    $("bountyEditResult").className = "notice success";
    await loadBountySettings();
    closeBountyEditModal();
  } catch (error) {
    $("bountyEditResult").textContent = "保存失败：" + error.message;
    $("bountyEditResult").className = "notice error";
  }
}

async function deleteBountySafely() {
  var id = Number($("bountyEditId").value);
  var reason = $("bountyEditReason").value.trim();
  if (!reason) {
    $("bountyEditResult").textContent = "操作失败：先填写取消或归档原因。";
    $("bountyEditResult").className = "notice error";
    return;
  }
  try {
    var preview = await api("/api/bounties/" + id + "/delete-preview");
    var actionText = preview.action === "cancel_and_archive"
      ? ("将取消并归档，退回发布者 " + Number(preview.refund) + " 功德（含手续费）。")
      : (preview.action === "archive_only" ? "将仅归档，不退款、不撤销历史交易。" : "该悬赏已经归档，不会重复退款。");
    $("bountyEditResult").textContent = "退款预览：" + actionText;
    $("bountyEditResult").className = "notice";
    if (!window.confirm("二次确认：悬赏 #" + preview.bounty.number + "\n" + actionText + "\n不会物理删除数据库记录。")) return;
    var result = await api("/api/bounties/" + id, { method: "DELETE", body: { reason: reason } });
    alert("操作完成：实际退款 " + Number(result.refund || 0) + " 功德，记录已保留。\n");
    closeBountyEditModal();
    await loadBountySettings();
  } catch (error) {
    $("bountyEditResult").textContent = "操作失败：" + error.message;
    $("bountyEditResult").className = "notice error";
  }
}

var marketplaceData = { settings: {}, listings: [], orders: [], stats: {} };
var marketplaceFieldMap = {
  marketEnabled: "market_enabled",
  marketListCommands: "market_list_commands",
  marketHelpCommands: "market_help_commands",
  marketCreateCommands: "market_create_commands",
  marketConfirmCreateCommands: "market_confirm_create_commands",
  marketCancelCreateCommands: "market_cancel_create_commands",
  marketEditCommands: "market_edit_commands",
  marketConfirmEditCommands: "market_confirm_edit_commands",
  marketCancelEditCommands: "market_cancel_edit_commands",
  marketDetailCommands: "market_detail_commands",
  marketPurchaseCommands: "market_purchase_commands",
  marketMineCommands: "market_mine_commands",
  marketOffShelfCommands: "market_off_shelf_commands",
  marketRenewCommands: "market_renew_commands",
  marketCommissionPercent: "market_default_commission_percent",
  marketMaxActive: "market_max_active_listings",
  marketDefaultStock: "market_default_stock",
  marketDefaultDuration: "market_default_duration_days",
  marketMinPrice: "market_min_price",
  marketMaxPrice: "market_max_price",
  marketPageSize: "market_page_size",
  marketMaxStock: "market_max_stock",
  marketMaxDuration: "market_max_duration_days",
  marketDraftTtl: "market_draft_ttl_seconds",
  marketAiBaseUrl: "market_ai_base_url",
  marketAiModel: "market_ai_model",
  marketAiTimeout: "market_ai_timeout_seconds",
  marketAiSystemPrompt: "market_ai_system_prompt",
  marketAiUserPrompt: "market_ai_user_prompt",
  marketDisabledReply: "market_disabled_reply",
  marketAiNotConfiguredReply: "market_ai_not_configured_reply",
  marketAiErrorReply: "market_ai_error_reply",
  marketDraftCancelledReply: "market_draft_cancelled_reply",
  marketDraftMissingReply: "market_draft_missing_reply",
  marketDraftPreviewReply: "market_draft_preview_reply",
  marketCreatedReply: "market_created_reply",
  marketUpdatedReply: "market_updated_reply",
  marketListHeaderReply: "market_list_header_reply",
  marketListItemReply: "market_list_item_reply",
  marketListEmptyReply: "market_list_empty_reply",
  marketListFooterReply: "market_list_footer_reply",
  marketDetailReply: "market_detail_reply",
  marketPurchaseReply: "market_purchase_reply",
  marketOffShelfReply: "market_off_shelf_reply",
  marketRenewedReply: "market_renewed_reply",
  marketHelpReply: "market_help_reply"
};

function marketStatusText(status) {
  return ({on_sale:"在售", sold_out:"售罄", expired:"过期", off_shelf:"下架", suspended:"暂停", archived:"归档"})[status] || status;
}

function renderMarketplace(data) {
  marketplaceData = data || marketplaceData;
  var settings = marketplaceData.settings || {};
  Object.entries(marketplaceFieldMap).forEach(function(entry) {
    var element = $(entry[0]);
    if (!element) return;
    var value = settings[entry[1]];
    if (element.type === "checkbox") element.checked = !!value;
    else element.value = value == null ? "" : value;
  });
  var stats = marketplaceData.stats || {};
  $("marketOnSaleCount").textContent = Number((stats.counts || {}).on_sale || 0) + " 件";
  $("marketOrderCount").textContent = Number(stats.orders || 0) + " 单";
  $("marketGrossAmount").textContent = Number(stats.gross || 0) + " 功德";
  $("marketCommissionAmount").textContent = Number(stats.commission || 0) + " 功德";
  $("marketAiStatus").textContent = marketplaceData.api_key_configured
    ? "DeepSeek 密钥已配置；市场提示词独立保存，不会覆盖其他 AI 项目的提示词。"
    : "DeepSeek 密钥未配置，上架和修改草稿暂不可用；浏览与购买不受影响。";
  $("marketAiStatus").className = marketplaceData.api_key_configured ? "notice success" : "notice error";

  var listings = marketplaceData.listings || [];
  $("marketListingTable").innerHTML = listings.length
    ? '<table><thead><tr><th>编号</th><th>商品</th><th>卖家</th><th>价格</th><th>库存</th><th>状态</th><th>置顶</th><th>到期</th><th></th></tr></thead><tbody>' +
      listings.map(function(item) {
        return '<tr><td>' + h(item.commission_number || item.number) + '</td><td><b>' + h(item.title) + '</b><br><small>' + h(item.description) + '</small></td>' +
          '<td title="' + h(item.seller_user_id) + '">' + h(item.seller_title) + '</td><td>' + Number(item.price) + '</td>' +
          '<td>' + Number(item.stock_remaining) + '/' + Number(item.stock_total) + '</td><td>' + h(marketStatusText(item.status)) + '</td>' +
          '<td>' + (Number(item.pin_rank) ? ('置顶' + Number(item.pin_rank)) : '—') + '</td><td>' + h(item.expires_at) + '</td>' +
          '<td><button type="button" onclick="openMarketEdit(' + Number(item.id) + ')">编辑</button></td></tr>';
      }).join("") + '</tbody></table>'
    : "暂无市场商品。";

  var orders = marketplaceData.orders || [];
  $("marketOrderTable").innerHTML = orders.length
    ? '<table><thead><tr><th>订单</th><th>时间</th><th>商品</th><th>买家</th><th>卖家</th><th>数量</th><th>支付</th><th>卖家实收</th><th>系统回收</th></tr></thead><tbody>' +
      orders.map(function(item) {
        return '<tr><td>' + h(item.commission_order_number || item.number) + '</td><td>' + h(item.created_at) + '</td><td>' + h((item.commission_listing_number || item.listing_number) + ' ' + item.listing_title) + '</td>' +
          '<td title="' + h(item.buyer_user_id) + '">' + h(item.buyer_nickname) + '</td><td title="' + h(item.seller_user_id) + '">' + h(item.seller_nickname) + '</td>' +
          '<td>' + Number(item.quantity) + '</td><td>' + Number(item.gross_amount) + '</td><td>' + Number(item.seller_net_amount) + '</td><td>' + Number(item.commission_amount) + '</td></tr>';
      }).join("") + '</tbody></table>'
    : "暂无市场订单。";
}

async function loadMarketplace() {
  var data = await api("/api/marketplace/settings");
  renderMarketplace(data);
  return data;
}

async function saveMarketplaceSettings() {
  var payload = {};
  Object.entries(marketplaceFieldMap).forEach(function(entry) {
    var element = $(entry[0]);
    if (element.type === "checkbox") payload[entry[1]] = element.checked;
    else if (element.type === "number") payload[entry[1]] = Number(element.value);
    else payload[entry[1]] = element.value.trim();
  });
  try {
    var data = await api("/api/marketplace/settings", {method:"POST", body:payload});
    renderMarketplace(data);
    $("marketSaveResult").textContent = "市场设置与全部文案已保存；官方商店没有改动。";
    $("marketSaveResult").className = "notice success";
    $("marketCommandSaveResult").textContent = "市场全部指令已保存并立即生效。";
    $("marketCommandSaveResult").className = "notice success";
  } catch (error) {
    $("marketSaveResult").textContent = "保存失败：" + error.message;
    $("marketSaveResult").className = "notice error";
    $("marketCommandSaveResult").textContent = "保存失败：" + error.message;
    $("marketCommandSaveResult").className = "notice error";
    throw error;
  }
}

window.openMarketEdit = function(id) {
  var item = (marketplaceData.listings || []).find(function(row) { return Number(row.id) === Number(id); });
  if (!item) return alert("没有找到这件市场商品。");
  $("marketEditId").value = item.id;
  $("marketEditNumber").value = item.commission_number || item.number;
  $("marketEditSeller").value = item.seller_title + "｜" + item.seller_user_id;
  $("marketEditName").value = item.title;
  $("marketEditDescription").value = item.description;
  $("marketEditPrice").value = item.price;
  $("marketEditStock").value = item.stock_remaining;
  $("marketEditDuration").value = item.duration_days;
  $("marketEditStatus").value = item.status;
  $("marketEditPin").value = item.pin_rank;
  $("marketEditSort").value = item.sort_order;
  $("marketEditExpires").value = item.expires_at;
  $("marketEditNote").value = item.admin_note || "";
  $("marketEditReason").value = "";
  $("marketEditResult").textContent = "这里只修改商品资料，不会直接改买卖双方功德或历史订单。";
  $("marketEditResult").className = "notice";
  $("marketEditModal").classList.remove("hidden");
};

function closeMarketEditModal() {
  $("marketEditModal").classList.add("hidden");
}

async function saveMarketEdit(event) {
  event.preventDefault();
  var id = Number($("marketEditId").value);
  var payload = {
    title: $("marketEditName").value.trim(),
    description: $("marketEditDescription").value.trim(),
    price: Number($("marketEditPrice").value),
    stock_remaining: Number($("marketEditStock").value),
    duration_days: Number($("marketEditDuration").value),
    status: $("marketEditStatus").value,
    pin_rank: Number($("marketEditPin").value),
    sort_order: Number($("marketEditSort").value || 0),
    expires_at: $("marketEditExpires").value.trim(),
    admin_note: $("marketEditNote").value.trim(),
    reason: $("marketEditReason").value.trim()
  };
  if (!payload.reason) {
    $("marketEditResult").textContent = "保存失败：必须填写操作原因。";
    $("marketEditResult").className = "notice error";
    return;
  }
  try {
    await api("/api/marketplace/listings/" + id, {method:"PUT", body:payload});
    $("marketEditResult").textContent = "保存成功，审计记录已写入。";
    $("marketEditResult").className = "notice success";
    await loadMarketplace();
    closeMarketEditModal();
  } catch (error) {
    $("marketEditResult").textContent = "保存失败：" + error.message;
    $("marketEditResult").className = "notice error";
  }
}

async function loadStatus() {
  const [data, aiUsage] = await Promise.all([
    api("/api/status"),
    api("/api/ai-character/usage?limit=500").catch(function() { return []; })
  ]);
  const d = data.settings.dzmm || {};
  const status = data.status || {};
  const running = Boolean(d.bot_enabled && !status.paused);
  if ($("groupUrlLockEnabled")) $("groupUrlLockEnabled").checked = !!d.lock_group_urls;
  if ($("groupUrlLockResult")) {
    $("groupUrlLockResult").textContent = d.lock_group_urls
      ? "当前已开启：浏览器会自动保持在配置的群聊页面。"
      : "当前未开启，登录页面不会被自动抢走。";
  }
  const today = new Date().toLocaleDateString("sv-SE");
  const aiTodayCount = (Array.isArray(aiUsage) ? aiUsage : []).reduce(function(total, item) {
    return String(item.created_at || "").slice(0, 10) === today
      ? total + Number(item.model_calls || 0)
      : total;
  }, 0);
  const groupConnected = Boolean(data.logged_in && data.bounty_logged_in);
  const statusItems = [
    ["bot", "机器人状态", running ? "运行中" : "已暂停"],
    ["browser", "浏览器连接", status.browser_connected ? "已连接" : "未连接"],
    ["login", "登录状态", data.logged_in ? "已登录" : "请先登录 DZMM"],
    ["groups", "双群连接状态", groupConnected ? "主群与悬赏群已连接" : (data.logged_in ? "主群已连接，悬赏群未连接" : "群聊尚未连接")],
    ["reply", "今日回复", data.today_reply_count],
    ["activity", "调用统计", `<span><b>${h(data.rule_count)}</b><small>启用命令</small></span><span><b>${h(aiTodayCount)}</b><small>今日 AI 调用</small></span>`]
  ];
  $("statusCards").innerHTML = statusItems.map(([kind, label, value]) =>
    `<div class="card dashboard-status-item metric-${kind}"><div class="label">${label}</div><div class="value">${kind === "activity" ? value : h(value)}</div></div>`
  ).join("");
  renderConnectionOverview(data);
  const updateTopbarState = function(labelId, dotId, label, online) {
    if ($(labelId)) $(labelId).textContent = label;
    if ($(dotId)) $(dotId).className = online ? "online" : "offline";
  };
  updateTopbarState("topbarBotStatus", "topbarStatusDot", running ? "机器人运行中" : "机器人已暂停", running);
  updateTopbarState("topbarBrowserStatus", "topbarBrowserDot", status.browser_connected ? "浏览器已连接" : "浏览器未连接", Boolean(status.browser_connected));
  updateTopbarState("topbarLoginStatus", "topbarLoginDot", data.logged_in ? "登录正常" : "尚未登录", Boolean(data.logged_in));
  updateTopbarState("topbarGroupStatus", "topbarGroupDot", data.logged_in ? "主群已连接" : "主群未连接", Boolean(data.logged_in));
  if ($("sidebarServiceStatus")) {
    $("sidebarServiceStatus").textContent = status.browser_connected ? "服务与浏览器在线" : "本地服务在线";
  }
  $("recentLogs").innerHTML = renderLogs(data.logs);
}

function renderConnectionOverview(data) {
  const dzmm = data.settings?.dzmm || config.dzmm || {};
  const features = data.settings?.features || config.features || {};
  const status = data.status || {};
  const setCard = function(prefix, state, value, detail) {
    const valueEl = $(prefix + "Status");
    const detailEl = $(prefix + "Detail");
    if (!valueEl || !detailEl) return;
    valueEl.textContent = value;
    detailEl.textContent = detail;
    const card = valueEl.closest(".connection-status-card");
    if (card) card.dataset.state = state;
  };
  const shortAddress = function(value) {
    try {
      const url = new URL(value);
      return url.hostname + (url.pathname === "/" ? "" : url.pathname);
    } catch (_) {
      return value ? "地址已配置" : "尚未配置地址";
    }
  };
  const paidEnabled = features.paid_interaction_ai_enabled !== false && features.paid_interaction_ai_enabled !== "false";
  const fortuneEnabled = features.fortune_enabled !== false && features.fortune_enabled !== "false";
  setCard(
    "connectionBrowser",
    status.browser_connected ? "good" : "bad",
    status.browser_connected ? "已连接" : "未连接",
    status.browser_connected ? "本地浏览器环境可用" : "等待浏览器重新连接"
  );
  setCard(
    "connectionLogin",
    data.logged_in ? "good" : "warn",
    data.logged_in ? "已登录" : "未登录",
    data.logged_in ? "DZMM 账号状态正常" : "请在浏览器中完成登录"
  );
  setCard(
    "connectionGroup",
    dzmm.group_url && data.logged_in ? "good" : "warn",
    dzmm.group_url ? "已配置" : "未配置",
    dzmm.group_url ? shortAddress(dzmm.group_url) : "请填写主群地址"
  );
  setCard(
    "connectionBounty",
    dzmm.bounty_group_url && data.bounty_logged_in ? "good" : "warn",
    dzmm.bounty_group_url ? "已配置" : "未配置",
    dzmm.bounty_group_url ? shortAddress(dzmm.bounty_group_url) : "请填写悬赏群地址"
  );
  setCard(
    "connectionImage",
    dzmm.image_group_url && data.image_logged_in ? "good" : "warn",
    dzmm.image_group_url ? "已配置" : "未配置",
    dzmm.image_group_url ? shortAddress(dzmm.image_group_url) : "请填写绘图群地址"
  );
  setCard(
    "connectionPaidAi",
    paidEnabled ? "good" : "muted",
    paidEnabled ? "已启用" : "未启用",
    paidEnabled ? (features.paid_interaction_ai_model || "尚未选择模型") : "付费互动 AI 已关闭"
  );
  setCard(
    "connectionFortuneAi",
    fortuneEnabled ? "good" : "muted",
    fortuneEnabled ? "已启用" : "未启用",
    fortuneEnabled ? (features.fortune_ai_model || "尚未选择模型") : "塔罗牌占卜已关闭"
  );
}

function newCompensationRequestId() {
  compensationRequestId = (window.crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : `comp-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function updateCompensationPreviewText() {
  if (!compensationPreviewData) return;
  const amount = Number($("compensationAmount").value || 0);
  const total = amount * Number(compensationPreviewData.recipient_count || 0);
  $("compensationPreview").className = "notice success";
  $("compensationPreview").textContent =
    `共 ${compensationPreviewData.recipient_count} 人：正常 ${compensationPreviewData.normal_count} 人，` +
    `待校准 ${compensationPreviewData.pending_count} 人，身份冲突 ${compensationPreviewData.conflict_count} 人。` +
    `本次预计发放 ${total} ${compensationPreviewData.currency}。`;
}

async function loadCompensationPreview() {
  $("compensationPreview").className = "notice";
  $("compensationPreview").textContent = "正在核对用户记录……";
  try {
    compensationPreviewData = await api("/api/compensation/preview");
    if (!$("compensationNotification").value.trim()) {
      $("compensationNotification").value = compensationPreviewData.notification_template || "";
    }
    updateCompensationPreviewText();
  } catch (error) {
    compensationPreviewData = null;
    $("compensationPreview").className = "notice error";
    $("compensationPreview").textContent = `人数核对失败：${error.message}`;
  }
}

async function grantCompensation() {
  if (!compensationPreviewData) {
    await loadCompensationPreview();
    if (!compensationPreviewData) return;
  }
  const amount = Number($("compensationAmount").value || 0);
  const reason = $("compensationReason").value.trim();
  const notificationTemplate = $("compensationNotification").value.trim();
  if (!Number.isInteger(amount) || amount < 1 || amount > 100000) {
    alert("每人补偿数量必须是 1 到 100000 之间的整数。");
    return;
  }
  if (!reason || !notificationTemplate) {
    alert("补偿原因和群通知消息不能为空。");
    return;
  }
  const total = amount * Number(compensationPreviewData.recipient_count || 0);
  const confirmed = confirm(
    `确定向全部 ${compensationPreviewData.recipient_count} 位用户各发放 ${amount} ${compensationPreviewData.currency}吗？\n\n` +
    `总计：${total} ${compensationPreviewData.currency}\n` +
    `范围：正常 ${compensationPreviewData.normal_count}、待校准 ${compensationPreviewData.pending_count}、冲突 ${compensationPreviewData.conflict_count}\n\n` +
    "发放会立即写入功德点流水，不能通过关闭页面撤销。"
  );
  if (!confirmed) return;

  if (!compensationRequestId) newCompensationRequestId();
  const button = $("grantCompensationBtn");
  button.disabled = true;
  button.textContent = "正在逐人发放……";
  $("compensationResult").className = "notice";
  $("compensationResult").textContent = "正在发放，请勿重复点击。";
  try {
    const result = await api("/api/compensation/grant", {
      method: "POST",
      body: {
        request_id: compensationRequestId,
        amount,
        reason,
        notification_template: notificationTemplate
      }
    });
    const batch = result.batch || {};
    $("compensationResult").className = result.notification_sent ? "notice success" : "notice error";
    $("compensationResult").textContent =
      `已入账 ${batch.recipient_count || 0} 人，共 ${batch.total_amount || 0} ${compensationPreviewData.currency}。` +
      `正常 ${batch.normal_count || 0}、待校准 ${batch.pending_count || 0}、冲突 ${batch.conflict_count || 0}。` +
      (result.notification_sent ? "群通知已发送。" : "群通知发送失败，可点击按钮重试；同一批次不会重复入账。");
    if (result.notification_sent) {
      newCompensationRequestId();
      button.textContent = "向全部用户发放补偿";
    } else {
      button.textContent = "重试发送群通知";
    }
    await loadCompensationPreview();
    await loadStatus();
  } catch (error) {
    $("compensationResult").className = "notice error";
    $("compensationResult").textContent = `发放请求失败：${error.message}。可直接重试，同一批次号会防止重复入账。`;
    button.textContent = "重试本批次";
  } finally {
    button.disabled = false;
  }
}

function itemOptions(items, selectedId) {
  return (items || []).map((item) =>
    `<option value="${Number(item.id)}" ${Number(item.id) === Number(selectedId) ? "selected" : ""}>` +
    `${h(item.name)}${item.enabled ? "" : "（未上架）"}</option>`
  ).join("");
}

function renderDropPool() {
  const rows = itemEconomy.drop_pool || [];
  const enabledRows = rows.filter(x => x.enabled && Number(x.chance_percent || 0) > 0);
  const weightTotal = enabledRows.reduce((sum, x) => sum + Number(x.chance_percent || 0), 0);
  const totalChance = Number((itemEconomy.settings || {}).chance_percent || 0);
  $("dropProbabilitySummary").textContent = `其他项目总掉落率 ${totalChance}% · 触发后按权重抽取 · 未触发概率 ${(100 - totalChance).toFixed(1).replace(/\.0$/, "")}%`;
  $("dropPoolList").innerHTML = rows.length ? '<table><thead><tr><th>物品</th><th>权重</th><th>触发后概率</th><th>数量</th><th>库存</th><th>状态</th><th>操作</th></tr></thead><tbody>' + rows.map(row =>
    `<tr><td>${h(row.item_name)}</td><td>${Number(row.chance_percent)}</td><td>${row.enabled && weightTotal > 0 ? (Number(row.chance_percent || 0) / weightTotal * 100).toFixed(1).replace(/\.0$/, "") + "%" : "—"}</td><td>${Number(row.min_quantity)}～${Number(row.max_quantity)}</td>` +
    `<td>${row.deduct_stock ? "同步扣减" : "不扣减"}</td><td>${row.enabled ? "启用" : "关闭"}</td><td><button onclick="editDropEntry(${Number(row.id)})">编辑</button><button class="danger" onclick="deleteDropEntry(${Number(row.id)})">删除</button></td></tr>`
  ).join("") + '</tbody></table>' : "暂无掉落项目。";
}

function clearDropEntry() {
  $("dropEntryId").value = ""; $("dropChance").value = 10; $("dropMinQuantity").value = 1; $("dropMaxQuantity").value = 1;
  $("dropSort").value = 0; $("dropReplyTemplate").value = ""; $("dropEntryEnabled").checked = true; $("dropDeductStock").checked = false;
}

window.editDropEntry = function(id) {
  const row = (itemEconomy.drop_pool || []).find(x => Number(x.id) === Number(id)); if (!row) return;
  $("dropEntryId").value = row.id; $("dropItemId").value = row.item_id; $("dropChance").value = row.chance_percent;
  $("dropMinQuantity").value = row.min_quantity; $("dropMaxQuantity").value = row.max_quantity; $("dropSort").value = row.sort_order;
  $("dropReplyTemplate").value = row.reply_template || ""; $("dropEntryEnabled").checked = !!row.enabled; $("dropDeductStock").checked = !!row.deduct_stock;
};

window.deleteDropEntry = async function(id) { if (!confirm("确定删除这个掉落项目？")) return; await api(`/api/item-economy/drop-pool/${id}`, {method:"DELETE"}); await loadItemEconomy(); };

async function saveDropEntry() {
  await api("/api/item-economy/drop-pool", {method:"POST", body:{id:Number($("dropEntryId").value)||null,item_id:Number($("dropItemId").value),chance_percent:Number($("dropChance").value),min_quantity:Number($("dropMinQuantity").value),max_quantity:Number($("dropMaxQuantity").value),deduct_stock:$("dropDeductStock").checked,enabled:$("dropEntryEnabled").checked,reply_template:$("dropReplyTemplate").value,sort_order:Number($("dropSort").value)}});
  clearDropEntry(); await loadItemEconomy();
}

function rewardTypeLabel(type) { return ({points:"功德点",item:"背包物品",medal:"纪念勋章",title:"永久称号"})[type] || type; }
function offerCostsText(rows) { return (rows||[]).map(x => `${x.item_name}×${Number(x.quantity)}`).join("＋"); }
function offerRewardsText(rows) { return (rows||[]).map(x => x.reward_type === "points" ? `${Number(x.quantity)}功德点` : x.reward_type === "title" ? `称号${x.text_value}` : `${x.item_name}×${Number(x.quantity)}`).join("＋"); }

function addExchangeCostRow(data={}) {
  const div=document.createElement("div"); div.className="three exchange-cost-row";
  div.innerHTML=`<label>材料物品<select class="exchange-cost-item">${itemOptions(itemEconomy.items,data.item_id||0)}</select></label><label>需要数量<input class="exchange-cost-quantity" type="number" min="1" value="${Number(data.quantity||1)}"></label><div class="toolbar" style="align-items:end"><button type="button" class="danger">删除材料</button></div>`;
  div.querySelector("button").onclick=()=>div.remove(); $("exchangeCostRows").appendChild(div);
}

function addExchangeRewardRow(data={}) {
  const div=document.createElement("div"); div.className="exchange-reward-row";
  div.innerHTML=`<div class="three"><label>奖励类型<select class="exchange-reward-type"><option value="points">功德点</option><option value="item">背包物品</option><option value="medal">纪念勋章</option><option value="title">永久称号</option></select></label><label>奖励物品<select class="exchange-reward-item">${itemOptions(itemEconomy.items,data.item_id||0)}</select></label><label>数量<input class="exchange-reward-quantity" type="number" min="0" value="${Number(data.quantity||0)}"></label></div><div class="two"><label>称号文字<input class="exchange-reward-text" value="${h(data.text_value||"")}"></label><div class="toolbar" style="align-items:end"><button type="button" class="danger">删除奖励</button></div></div>`;
  div.querySelector(".exchange-reward-type").value=data.reward_type||"points"; div.querySelector("button").onclick=()=>div.remove(); $("exchangeRewardRows").appendChild(div);
}

function clearExchangeOffer() {
  $("exchangeOfferId").value=""; $("exchangeOfferCode").value=""; $("exchangeOfferName").value=""; $("exchangeOfferDescription").value=""; $("exchangeLimitType").value="weekly"; $("exchangeWeeklyLimit").value=1; $("exchangeOfferSort").value=0; $("exchangeOfferEnabled").checked=true; $("exchangeOfferSuccessReply").value=""; $("exchangeCostRows").innerHTML=""; $("exchangeRewardRows").innerHTML=""; addExchangeCostRow(); addExchangeRewardRow({reward_type:"points",quantity:100});
}

function openNewExchangeOfferModal() {
  clearExchangeOffer();
  $("exchangeOfferModalTitle").textContent = "新建兑换商品";
  $("exchangeOfferModal").classList.remove("hidden");
  $("exchangeOfferName").focus();
}

function closeExchangeOfferModal() {
  $("exchangeOfferModal").classList.add("hidden");
}

function renderExchangeOffers() {
  const rows=itemEconomy.offers||[];
  $("exchangeOfferList").innerHTML=rows.length?'<table><thead><tr><th>项目</th><th>材料</th><th>奖励</th><th>限制</th><th>状态</th><th>操作</th></tr></thead><tbody>'+rows.map(row=>`<tr><td>${h(row.name)}</td><td>${h(offerCostsText(row.costs))}</td><td>${h(offerRewardsText(row.rewards))}</td><td>${row.limit_type==="once"?"每人一次":`每周${Number(row.weekly_limit)}次`}</td><td>${row.enabled?"启用":"关闭"}</td><td><button onclick="editExchangeOffer(${Number(row.id)})">编辑</button><button class="danger" onclick="deleteExchangeOffer(${Number(row.id)})">删除</button></td></tr>`).join("")+'</tbody></table>':"暂无兑换项目。";
}

window.editExchangeOffer=function(id){const row=(itemEconomy.offers||[]).find(x=>Number(x.id)===Number(id));if(!row)return;$("exchangeOfferId").value=row.id;$("exchangeOfferCode").value=row.code;$("exchangeOfferName").value=row.name;$("exchangeOfferDescription").value=row.description||"";$("exchangeLimitType").value=row.limit_type;$("exchangeWeeklyLimit").value=row.weekly_limit;$("exchangeOfferSort").value=row.sort_order;$("exchangeOfferEnabled").checked=!!row.enabled;$("exchangeOfferSuccessReply").value=row.success_reply||"";$("exchangeCostRows").innerHTML="";$("exchangeRewardRows").innerHTML="";(row.costs||[]).forEach(addExchangeCostRow);(row.rewards||[]).forEach(addExchangeRewardRow);$("exchangeOfferModalTitle").textContent=`编辑兑换商品：${row.name}`;$("exchangeOfferModal").classList.remove("hidden");$("exchangeOfferName").focus();};
window.deleteExchangeOffer=async function(id){if(!confirm("确定删除这个兑换项目？已有兑换历史的项目会改为停用。"))return;await api(`/api/item-economy/exchange-offers/${id}`,{method:"DELETE"});await loadItemEconomy();};

async function saveExchangeOffer(){const costs=Array.from(document.querySelectorAll(".exchange-cost-row")).map(row=>({item_id:Number(row.querySelector(".exchange-cost-item").value),quantity:Number(row.querySelector(".exchange-cost-quantity").value)}));const rewards=Array.from(document.querySelectorAll(".exchange-reward-row")).map(row=>({reward_type:row.querySelector(".exchange-reward-type").value,item_id:Number(row.querySelector(".exchange-reward-item").value),quantity:Number(row.querySelector(".exchange-reward-quantity").value),text_value:row.querySelector(".exchange-reward-text").value.trim()}));await api("/api/item-economy/exchange-offers",{method:"POST",body:{id:Number($("exchangeOfferId").value)||null,code:$("exchangeOfferCode").value||`custom-${Date.now()}`,name:$("exchangeOfferName").value.trim(),description:$("exchangeOfferDescription").value.trim(),limit_type:$("exchangeLimitType").value,weekly_limit:Number($("exchangeWeeklyLimit").value),enabled:$("exchangeOfferEnabled").checked,sort_order:Number($("exchangeOfferSort").value),success_reply:$("exchangeOfferSuccessReply").value,costs,rewards}});closeExchangeOfferModal();clearExchangeOffer();await loadItemEconomy();}

function renderExchangeHistory(){const rows=itemEconomy.history||[];$("exchangeHistoryList").innerHTML=rows.length?'<table><thead><tr><th>时间</th><th>用户</th><th>项目</th><th>消耗</th><th>奖励</th></tr></thead><tbody>'+rows.map(row=>`<tr><td>${h(row.created_at)}</td><td>${h(row.display_name||row.nickname)}</td><td>${h(row.offer_name)}</td><td>${h((row.costs||[]).map(x=>`${x.item}×${x.quantity}`).join("＋"))}</td><td>${h((row.rewards||[]).map(x=>x.type==="points"?`${x.quantity}功德点`:x.type==="title"?x.title:`${x.item}×${x.quantity}`).join("＋"))}</td></tr>`).join("")+'</tbody></table>':"暂无兑换记录。";}

async function loadItemEconomy() {
  itemEconomy = await api("/api/item-economy");
  const settings = itemEconomy.settings || {};
  $("randomDropEnabled").checked = !!settings.enabled; $("randomDropChance").value=Number(settings.chance_percent ?? 20); $("randomDropReply").value=settings.drop_reply||""; $("dropItemId").innerHTML=itemOptions(itemEconomy.items,0);
  const selectedSources = new Set(settings.sources || []);
  document.querySelectorAll(".drop-source").forEach((input) => { input.checked = selectedSources.has(input.value); });
  $("exchangeShopEnabled").checked=!!settings.exchange_shop_enabled; $("exchangeShopCommands").value=settings.exchange_shop_commands||""; $("exchangeCommands").value=settings.exchange_commands||""; $("exchangeShopHeader").value=settings.exchange_shop_header||""; $("exchangeShopStory").value=settings.exchange_shop_story||""; $("exchangeShopFooter").value=settings.exchange_shop_footer||""; $("exchangeSuccessReply").value=settings.exchange_success_reply||""; $("exchangeMissingReply").value=settings.exchange_missing_reply||""; $("exchangeLimitOnceReply").value=settings.exchange_limit_once_reply||""; $("exchangeLimitWeeklyReply").value=settings.exchange_limit_weekly_reply||"";
  renderDropPool(); renderExchangeOffers(); renderExchangeHistory();
  if (!document.querySelector(".exchange-cost-row")) clearExchangeOffer();
}

async function saveItemEconomy() {
  itemEconomy = await api("/api/item-economy/settings", {
    method: "POST",
    body: {
      enabled: $("randomDropEnabled").checked,
      chance_percent: Number($("randomDropChance").value),
      sources: Array.from(document.querySelectorAll(".drop-source:checked")).map((input) => input.value),
      random_item_drop_reply: $("randomDropReply").value,
      exchange_shop_enabled: $("exchangeShopEnabled").checked, exchange_shop_commands: $("exchangeShopCommands").value, exchange_commands: $("exchangeCommands").value,
      exchange_shop_header: $("exchangeShopHeader").value, exchange_shop_story: $("exchangeShopStory").value, exchange_shop_footer: $("exchangeShopFooter").value,
      exchange_success_reply: $("exchangeSuccessReply").value, exchange_missing_reply: $("exchangeMissingReply").value, exchange_limit_once_reply: $("exchangeLimitOnceReply").value, exchange_limit_weekly_reply: $("exchangeLimitWeeklyReply").value
    }
  });
  await loadItemEconomy();
  alert("掉落与兑换仓库设置已保存。");
}

async function exportFullData() {
  const status = $("exportDataResult");
  status.className = "notice";
  status.textContent = "正在整理全部命令、设置、用户数据和最近聊天记录……";
  try {
    const response = await fetch("/api/export/full");
    if (!response.ok) throw new Error(await response.text());
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match ? match[1] : "dzmm-data-export.zip";
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 3000);
    status.className = "notice success";
    status.textContent = "导出完成，ZIP 已交给浏览器保存。";
  } catch (error) {
    status.className = "notice error";
    status.textContent = `导出失败：${error.message}`;
  }
}

async function loadNewcomerBenefit() {
  const data = await api("/api/newcomer-benefit");
  const currency = (config.features || {}).currency_name || "功德点";
  $("newcomerRecipientCount").textContent = data.recipient_count + " 人";
  $("newcomerTotalAmount").textContent = data.total_amount + " " + currency;
  $("newcomerLastGranted").textContent = data.last_granted_at || "暂无";
  $("newcomerBenefitEnabled").checked = !!data.enabled;
  $("newcomerBenefitAmount").value = data.amount || 60;
  $("newcomerBenefitRecent").innerHTML = (data.recent || []).length
    ? "<table><thead><tr><th>昵称</th><th>唯一 ID</th><th>福利</th><th>领取时间</th></tr></thead><tbody>" +
      data.recent.map(function(row) {
        return "<tr><td>" + h(row.nickname) + "</td><td><code>" + h(row.platform_user_id) +
          "</code></td><td>+" + h(row.amount) + "</td><td>" + h(row.granted_at) + "</td></tr>";
      }).join("") + "</tbody></table>"
    : "暂无领取记录。";
}

async function saveNewcomerBenefit() {
  const data = await api("/api/newcomer-benefit", {
    method: "POST",
    body: {
      enabled: $("newcomerBenefitEnabled").checked,
      amount: Number($("newcomerBenefitAmount").value || 60)
    }
  });
  await loadConfig();
  await loadNewcomerBenefit();
  alert("新人福利设置已保存。");
  return data;
}

async function loadLuckyBags() {
  const data = await api("/api/lucky-bags");
  $("luckyBagSummary").textContent =
    "当前进行中 " + data.active_count + " 个；最近记录中管理员福袋 " +
    data.admin_count + " 个，普通用户福袋 " + data.user_count + " 个。";
  $("luckyBagHistory").innerHTML = (data.packets || []).length
    ? "<table><thead><tr><th>类型</th><th>发送者</th><th>总额/份数</th><th>已领取</th><th>状态</th><th>时间</th></tr></thead><tbody>" +
      data.packets.map(function(packet) {
        var type = packet.funding_type === "user" ? "用户自费" : "管理员系统";
        var status = packet.active ? "领取中" : "已结束";
        return "<tr><td><span class=\"badge\">" + type + "</span></td><td>" +
          h(packet.sender_nickname) + "</td><td>" + h(packet.total_amount) + " " +
          h(data.currency) + " / " + h(packet.total_count) + " 份</td><td>" +
          h(packet.claimed_amount) + " / " + h(packet.claimed_count) +
          " 份</td><td>" + status + "</td><td>" + h(packet.created_at) + "</td></tr>";
      }).join("") + "</tbody></table>"
    : "暂无福袋记录。";
}

async function loadFacilityWages() {
  try {
    const data = await api("/api/facility-wages");
    facilityWageRules = data.rules || [];
    const preview = data.preview || {};
    const claimCommands = String(data.claim_command || "/领取工资").split(/[,，]/).map((item) => item.trim()).filter(Boolean);
    $("facilityWageCommand").textContent = `领取命令：${claimCommands.join("、")}（当天领取昨天的工资）`;
    const names = (preview.matched_users || []).slice(0, 8).map((item) => item.nickname);
    $("facilityWageSummary").className = preview.processed ? "notice success" : "notice";
    $("facilityWageSummary").textContent = preview.processed
      ? `${preview.wage_date} 已有 ${preview.day?.recipient_count || 0} 人手动领取，共 ${preview.day?.total_amount || 0} ${data.currency}。`
      : `${preview.wage_date} 共记录 ${preview.active_count || 0} 位活跃用户，全日昵称符合工资规则的有 ${preview.matched_count || 0} 人。` +
        (names.length ? ` 可领取：${names.join("、")}${preview.matched_count > names.length ? " 等" : ""}` : "");
    if (!facilityWageRules.length) {
      $("facilityWageRules").innerHTML = '<div class="empty">暂无规则。没有规则时不会发放工资。</div>';
      return;
    }
    $("facilityWageRules").innerHTML =
      '<table><thead><tr><th>昵称包含文案</th><th>工资</th><th>排序</th><th>启用</th><th>操作</th></tr></thead><tbody>' +
      facilityWageRules.map((rule) =>
        `<tr data-wage-rule="${rule.id}">` +
        `<td><input data-field="keyword" maxlength="100" value="${h(rule.keyword || "")}"></td>` +
        `<td><input data-field="amount" type="number" min="1" max="100000" value="${Number(rule.amount || 10)}"></td>` +
        `<td><input data-field="sort_order" type="number" value="${Number(rule.sort_order || 0)}"></td>` +
        `<td><input data-field="enabled" type="checkbox" ${rule.enabled ? "checked" : ""}></td>` +
        `<td><button type="button" onclick="saveFacilityWageRule(${rule.id})">保存</button>` +
        `<button type="button" class="danger" onclick="deleteFacilityWageRule(${rule.id})">删除</button></td></tr>`
      ).join("") + "</tbody></table>";
  } catch (error) {
    $("facilityWageSummary").className = "notice error";
    $("facilityWageSummary").textContent = `工资规则读取失败：${error.message}`;
  }
}

async function addFacilityWageRule() {
  const keyword = $("newFacilityWageKeyword").value.trim();
  const amount = Number($("newFacilityWageAmount").value || 0);
  const sortOrder = Number($("newFacilityWageSort").value || 0);
  if (!keyword || !Number.isInteger(amount) || amount < 1) {
    alert("请填写昵称文案和正确的工资数值。");
    return;
  }
  await api("/api/facility-wages/rules", {
    method: "POST",
    body: { keyword, amount, enabled: true, sort_order: sortOrder }
  });
  $("newFacilityWageKeyword").value = "";
  await loadFacilityWages();
}

window.saveFacilityWageRule = async function(id) {
  const row = document.querySelector(`tr[data-wage-rule="${id}"]`);
  if (!row) return;
  await api(`/api/facility-wages/rules/${id}`, {
    method: "PUT",
    body: {
      keyword: row.querySelector('[data-field="keyword"]').value.trim(),
      amount: Number(row.querySelector('[data-field="amount"]').value || 0),
      sort_order: Number(row.querySelector('[data-field="sort_order"]').value || 0),
      enabled: row.querySelector('[data-field="enabled"]').checked
    }
  });
  await loadFacilityWages();
};

window.deleteFacilityWageRule = async function(id) {
  if (!confirm("确定删除这条工资规则？已发放的历史工资不会撤回。")) return;
  await api(`/api/facility-wages/rules/${id}`, { method: "DELETE" });
  await loadFacilityWages();
};

function renderLogs(logs) {
  if (!logs || !logs.length) return "暂无日志。机器人运行后，这里会显示操作记录。";
  return logs.map((x) => `<div class="item"><span class="badge">${h(x.level)}</span>${h(x.message)}<div class="meta">${h(x.created_at)} · ${h(x.kind)}</div></div>`).join("");
}

function fillFeatures(f) {
  $("currencyName").value = f.currency_name || "功德点";
  $("checkinCommands").value = f.checkin_commands || "/祈福,/签到,/qd";
  $("balanceCommands").value = f.balance_commands || "/功德点,/余额,/金币";
  $("shopCommands").value = f.shop_commands || "/神殿仓库,/商店,/shop";
  $("buyCommands").value = f.buy_commands || "/购买,/买,/buy";
  $("inventoryCommands").value = f.inventory_commands || "/背包,/库存,/inventory";
  $("checkinEnabled").checked = f.checkin_enabled !== false;
  $("checkinBaseReward").value = f.checkin_base_reward ?? 10;
  $("checkinStreakBonus").value = f.checkin_streak_bonus ?? 1;
  $("shopEnabled").checked = f.shop_enabled !== false;
  $("balanceReply").value = f.balance_reply || "{user}，当前余额 {balance} {currency}。";
  $("checkinDisabledReply").value = f.checkin_disabled_reply || "签到功能暂未开启。";
  $("shopDisabledReply").value = f.shop_disabled_reply || "商店功能暂未开启。";
  $("checkinReply").value = f.checkin_reply || "";
  $("checkinRepeatReply").value = f.checkin_repeat_reply || "";
  $("purchaseNoItemReply").value = f.purchase_no_item_reply || "";
  $("purchaseNoStockReply").value = f.purchase_no_stock_reply || "这个商品库存不足。";
  $("purchaseNoMoneyReply").value = f.purchase_no_money_reply || "";
  $("purchaseSuccessReply").value = f.purchase_success_reply || "{user}，购买成功：{item}，花费 {price} {currency}，余额 {balance} {currency}。";
  $("buyUsageReply").value = f.buy_usage_reply || "请发送 /购买 商品名";
  $("shopEmptyReply").value = f.shop_empty_reply || "商店暂时没有商品。";
  $("shopHeader").value = f.shop_header || "商店商品：";
  $("shopItemLine").value = f.shop_item_line || "{item}：{price} {currency}，库存 {stock}{description}";
  $("shopFooter").value = f.shop_footer || "发送 /购买 商品名 进行购买。";
  $("inventoryEmptyReply").value = f.inventory_empty_reply || "{user}，你的背包是空的。";
  $("inventoryHeader").value = f.inventory_header || "{user} 的背包：";
  $("inventoryItemLine").value = f.inventory_item_line || "{item} x {quantity}";
}

function collectFeatures() {
  return {
    ...(config.features || {}),
    currency_name: $("currencyName").value.trim() || "功德点",
    checkin_commands: $("checkinCommands").value.trim() || "/祈福,/签到,/qd",
    balance_commands: $("balanceCommands").value.trim() || "/功德点,/余额,/金币",
    shop_commands: $("shopCommands").value.trim() || "/神殿仓库,/商店,/shop",
    buy_commands: $("buyCommands").value.trim() || "/购买,/买,/buy",
    inventory_commands: $("inventoryCommands").value.trim() || "/背包,/库存,/inventory",
    checkin_enabled: $("checkinEnabled").checked,
    checkin_base_reward: Number($("checkinBaseReward").value || 0),
    checkin_streak_bonus: Number($("checkinStreakBonus").value || 0),
    shop_enabled: $("shopEnabled").checked,
    balance_reply: $("balanceReply").value,
    checkin_disabled_reply: $("checkinDisabledReply").value,
    shop_disabled_reply: $("shopDisabledReply").value,
    checkin_reply: $("checkinReply").value,
    checkin_repeat_reply: $("checkinRepeatReply").value,
    purchase_no_item_reply: $("purchaseNoItemReply").value,
    purchase_no_stock_reply: $("purchaseNoStockReply").value,
    purchase_no_money_reply: $("purchaseNoMoneyReply").value,
    purchase_success_reply: $("purchaseSuccessReply").value,
    buy_usage_reply: $("buyUsageReply").value,
    shop_empty_reply: $("shopEmptyReply").value,
    shop_header: $("shopHeader").value,
    shop_item_line: $("shopItemLine").value,
    shop_footer: $("shopFooter").value,
    inventory_empty_reply: $("inventoryEmptyReply").value,
    inventory_header: $("inventoryHeader").value,
    inventory_item_line: $("inventoryItemLine").value,
    help_reply: $("helpReply").value
  };
}

async function loadRules() {
  rules = await api("/api/rules");
  var q = $("ruleSearch").value.trim();
  var group = $("ruleGroupFilter") ? $("ruleGroupFilter").value : "all";
  // Update group filter dropdown
  if ($("ruleGroupFilter")) {
    var groups = [];
    rules.forEach(function(r) {
      var g = (r.group_name || "默认命令").trim() || "默认命令";
      if (groups.indexOf(g) < 0) groups.push(g);
    });
    groups.sort();
    // Fetch empty groups from API
    api("/api/rules/groups").then(function(data) {
      (data.groups || []).forEach(function(g) {
        if (g && g !== "未分组" && groups.indexOf(g) < 0) groups.push(g);
      });
      groups.sort();
      var cur2 = $("ruleGroupFilter").value || "all";
      $("ruleGroupFilter").innerHTML = "<option value=\"all\">全部分组</option>" + groups.map(function(g) { return "<option value=\"" + g + "\">" + g + "</option>"; }).join("");
      $("ruleGroupFilter").value = groups.indexOf(cur2) >= 0 ? cur2 : "all";
    });
    var cur = $("ruleGroupFilter").value || "all";
    $("ruleGroupFilter").innerHTML = "<option value=\"all\">全部分组</option>" + groups.map(function(g) { return "<option value=\"" + g + "\">" + g + "</option>"; }).join("");
    $("ruleGroupFilter").value = groups.indexOf(cur) >= 0 ? cur : "all";
  }
  // Filter
  var list = rules.filter(function(r) {
    var g = (r.group_name || "默认命令").trim() || "默认命令";
    var haystack = r.name + " " + r.trigger_value + " " + (r.note || "") + " " + g;
    return (!q || haystack.indexOf(q) >= 0) && (group === "all" || g === group);
  });
  if (!list.length) {
    $("ruleList").classList.add("empty");
    $("ruleList").innerHTML = "<div class=\"panel empty\">还没有自定义命令。</div>";
    return;
  }
  $("ruleList").classList.remove("empty");
  // Group and render
  var grouped = {};
  list.forEach(function(r) {
    var g = (r.group_name || "默认命令").trim() || "默认命令";
    if (!grouped[g]) grouped[g] = [];
    grouped[g].push(r);
  });
  var html = "";
  Object.keys(grouped).sort().forEach(function(g) {
    html += "<details class=\"command-group\"" + (q ? " open" : "") + "><summary class=\"command-group-title\"><div><h2>" + h(g) + "</h2><small>点击展开当前分组</small></div><span>" + grouped[g].length + " 条</span></summary><div class=\"command-rows\">";
    grouped[g].forEach(function(r) {
      html += "<article class=\"command-row custom-command-card\"><div class=\"command-main\"><b>" + h(r.trigger_value) + "</b></div><div class=\"command-flags\"><span class=\"badge " + (r.enabled ? "is-enabled" : "is-disabled") + "\">" + (r.enabled ? "启用" : "禁用") + "</span></div><div class=\"toolbar compact\"><button onclick=\"editRule(" + r.id + ")\">编辑</button><button onclick=\"moveRule(" + r.id + ")\">移动</button><button class=\"danger\" onclick=\"deleteRule(" + r.id + ")\">删除</button></div></article>";
    });
    html += "</div></details>";
  });
  $("ruleList").innerHTML = html;
}

function openRuleModal(rule = null) {
  $("ruleModalTitle").textContent = rule ? "编辑命令" : "新建命令";
  $("ruleId").value = rule?.id || "";
  var currentGroup = $("ruleGroupFilter") && $("ruleGroupFilter").value !== "all" ? $("ruleGroupFilter").value : "";
  $("ruleGroupName").value = rule ? (rule.group_name || "") : currentGroup;
  $("ruleName").value = rule?.name || "";
  $("rulePriority").value = rule?.priority ?? 0;
  $("triggerValue").value = rule?.trigger_value || "";
  $("replyContent").value = rule?.reply_content || "";
  $("replyMode").value = rule?.reply_mode || "fixed";
  $("userCooldown").value = rule?.user_cooldown_seconds ?? 0;
  $("dailyMax").value = rule?.daily_max_hits ?? 0;
  $("ruleEnabled").checked = rule ? !!rule.enabled : true;
  $("requireAdmin").checked = rule ? !!rule.require_admin : false;
  $("ruleNote").value = rule?.note || "";
  $("ruleModal").classList.remove("hidden");
}

function closeRuleModal() {
  $("ruleModal").classList.add("hidden");
}

window.editRule = (id) => openRuleModal(rules.find((x) => x.id === id));
window.duplicateRule = async (id) => { await api(`/api/rules/${id}/duplicate`, { method: "POST" }); await loadRules(); };
window.deleteRule = async (id) => { if (confirm("确定删除这条命令吗？")) { await api(`/api/rules/${id}`, { method: "DELETE" }); await loadRules(); } };

function collectRule() {
  let trigger = $("triggerValue").value.trim();
  trigger = trigger.split(/[,，\n]+/).map(function(item) {
    item = item.trim();
    if (item && !item.startsWith("/")) item = "/" + item;
    return item;
  }).filter(Boolean).join("，");
  return {
    name: $("ruleName").value.trim(),
    enabled: $("ruleEnabled").checked,
    priority: Number($("rulePriority").value || 0),
    group_name: $("ruleGroupName").value.trim(),
    trigger_type: "exact",
    trigger_value: trigger,
    reply_content: $("replyContent").value,
    reply_mode: $("replyMode").value,
    scope_type: "all",
    scope_value: "",
    exclude_users: "",
    rule_cooldown_seconds: Number(config.safety?.global_cooldown_seconds || 0),
    user_cooldown_seconds: Number($("userCooldown").value || 0),
    global_cooldown_seconds: 0,
    daily_max_hits: Number($("dailyMax").value || 0),
    allow_self: false,
    require_admin: $("requireAdmin").checked,
    note: $("ruleNote").value.trim()
  };
}

async function loadShopItems() {
  shopItems = await api("/api/shop-items");
  $("shopList").classList.remove("empty");
  var currency = config.features?.currency_name || "功德点";
  function renderShopGroup(title, items, categoryClass, isDrop) {
    return '<details class="shop-category system-command-section ' + categoryClass + '">' +
      '<summary><span>' + h(title) + '</span><span class="badge">' + items.length + ' 件</span></summary>' +
      (items.length ? '<div class="shop-product-grid">' +
      items.map(function(item) {
      var stock = item.stock < 0 ? "不限" : item.stock;
      var status = isDrop
        ? '<span class="badge">掉落物品</span>'
        : item.enabled
        ? '<span class="badge shop-status-live">已上架</span>'
        : '<span class="badge">已下架</span>';
      var subtitle = isDrop
        ? "仅用于掉落或游戏奖励"
        : h(item.price) + " " + h(currency);
      var saleMeta = isDrop
        ? '<div><dt>用途</dt><dd>掉落奖励</dd></div>'
        : '<div><dt>库存</dt><dd>' + stock + '</dd></div>';
      var toggleButton = isDrop
        ? ""
        : '<button onclick="toggleShopItem(' + item.id + ', ' + (item.enabled ? 'false' : 'true') + ')">' + (item.enabled ? '下架' : '上架') + '</button>';
      return '<article class="shop-product-card">' +
        '<div class="shop-product-title"><div><h4>' + h(item.name) + '</h4><p>' + subtitle + '</p></div>' + status + '</div>' +
        '<dl class="shop-product-meta">' +
          saleMeta +
          '<div><dt>排序</dt><dd>' + (item.sort_order || 0) + '</dd></div>' +
          '<div><dt>类型</dt><dd>' + h(title) + '</dd></div>' +
        '</dl>' +
        '<div class="shop-product-actions">' +
          toggleButton +
          '<button onclick="openShopItemModal(' + item.id + ')">编辑</button>' +
          '<button class="danger" onclick="deleteShopItem(' + item.id + ')">删除</button>' +
        '</div>' +
      '</article>';
      }).join("") + '</div>' : '<div class="empty">这个分组目前没有物品。</div>') +
      '</details>';
  }
  var dropItems = shopItems.filter(function(item) { return item.item_category === "drop"; });
  var disabledItems = shopItems.filter(function(item) { return item.item_category !== "drop" && !item.enabled; });
  var imageItems = shopItems.filter(function(item) { return item.enabled && item.item_category === "image"; });
  var specialItems = shopItems.filter(function(item) { return item.enabled && item.item_category === "special"; });
  var normalItems = shopItems.filter(function(item) {
    return item.enabled && (item.item_category === "normal" || !item.item_category);
  });
  $("shopList").innerHTML =
    renderShopGroup("正常商品", normalItems, "normal-shop-category", false) +
    renderShopGroup("特殊商品", specialItems, "special-shop-category", false) +
    renderShopGroup("图片商品", imageItems, "image-shop-category", false) +
    renderShopGroup("掉落物品", dropItems, "drop-shop-category", true) +
    renderShopGroup("已下架商品", disabledItems, "disabled-shop-category", false);
}

function clearShopForm() {
  $("shopItemId").value = "";
  $("shopSpecialKind").value = "";
  $("shopName").value = "";
  $("shopDescription").value = "";
  $("shopItemCategory").value = "normal";
  $("shopPrice").value = 10;
  $("shopStock").value = -1;
  $("shopSort").value = 0;
  $("shopItemEnabled").checked = true;
  $("shopImageFolder").value = "";
}

window.openShopItemModal = function(id, defaultCategory) {
  var item = id ? shopItems.find(function(x) { return x.id === id; }) : null;
  $("shopItemModalTitle").textContent = item ? "编辑商品" : "新建商品";
  $("shopItemId").value = item ? item.id : "";
  $("shopSpecialKind").value = item ? (item.special_kind || "") : "";
  $("shopName").value = item ? item.name : "";
  $("shopDescription").value = item ? (item.description || "") : "";
  $("shopItemCategory").value = item ? (item.item_category || "normal") : (defaultCategory || "normal");
  $("shopPrice").value = item ? item.price : 10;
  $("shopStock").value = item ? item.stock : -1;
  $("shopSort").value = item ? (item.sort_order || 0) : 0;
  $("shopItemEnabled").checked = item ? !!item.enabled : true;
  $("shopUseEnabled").checked = item ? item.use_enabled !== false : true;
  $("shopUseTarget").value = item ? (item.use_target || "other") : "other";
  $("shopUseReplyTemplate").value = item ? (item.use_reply_template || "{actor}对{target}使用了{item}。") : "{actor}对{target}使用了{item}。";
  $("shopStatusTemplate").value = item ? (item.status_template || "被{actor}使用了{item}") : "被{actor}使用了{item}";
  $("shopDirectUseReplyTemplate").value = item ? (item.direct_use_reply_template || "{actor}使用了{item}。") : "{actor}使用了{item}。";
  $("shopSelfUseReplyTemplate").value = item ? (item.self_use_reply_template || "{actor}使用了{item}。") : "{actor}使用了{item}。";
  $("shopSelfStatusTemplate").value = item ? (item.self_status_template || "使用了{item}") : "使用了{item}";
  $("shopImageFolder").value = item ? (item.image_folder || "") : "";
  if (!item && defaultCategory === "image") {
    $("shopUseTarget").value = "direct";
    $("shopDirectUseReplyTemplate").value = "{actor}使用了{item}。";
  }
  if (shopRemovePrice) $("shopRemovePrice").value = item ? (item.remove_price || 5) : 5;
  toggleShopTarget();
  $("shopItemModal").classList.remove("hidden");
};

window.toggleShopItem = async function(id, enable) {
  var item = shopItems.find(function(x) { return x.id === id; });
  if (!item) return;
  item.enabled = enable;
  await api("/api/shop-items", { method: "POST", body: item });
  await loadShopItems();
};
window.deleteShopItem = async function(id) {
  var item = shopItems.find(function(x) { return x.id === id; });
  var name = item ? item.name : "该商品";
  if (!confirm("确定删除「" + name + "」？\n\n已有用户购买过该商品，删除会导致商品失效，建议下架即可！\n\n确定要删除吗？")) return;
  await api("/api/shop-items/" + id, { method: "DELETE" });
  await loadShopItems();
};

function collectShopItem() {
  var category = $("shopItemCategory").value;
  var item = {
    id: $("shopItemId").value ? Number($("shopItemId").value) : null,
    name: $("shopName").value.trim(),
    item_category: category,
    special_kind: $("shopSpecialKind").value,
    description: $("shopDescription").value.trim(),
    price: Number($("shopPrice").value || 0),
    stock: Number($("shopStock").value || -1),
    enabled: $("shopItemEnabled").checked,
    sort_order: Number($("shopSort").value || 0),
    use_enabled: $("shopUseEnabled").checked,
    use_target: $("shopUseTarget").value,
    direct_use_reply_template: $("shopDirectUseReplyTemplate") ? $("shopDirectUseReplyTemplate").value : "",
    use_reply_template: $("shopUseReplyTemplate").value,
    status_template: $("shopStatusTemplate").value,
    self_use_reply_template: $("shopSelfUseReplyTemplate").value,
    self_status_template: $("shopSelfStatusTemplate").value,
    remove_price: shopRemovePrice ? Number($("shopRemovePrice").value || 5) : 5,
    image_folder: $("shopImageFolder").value.trim()
  };
  if (category === "drop") {
    item.price = 0;
    item.enabled = false;
    item.use_enabled = false;
    item.image_folder = "";
  }
  return item;
}

async function loadUsers() {
  var search = ($("userSearch") ? $("userSearch").value.trim() : "");
  var userFilter = ($("identityStatusFilter") ? $("identityStatusFilter").value : "");
  var query = new URLSearchParams();
  if (search) query.set("search", search);
  if (userFilter === "nickname_conflict") query.set("nickname_conflict", "true");
  var url = "/api/users" + (query.toString() ? "?" + query.toString() : "");
  const rows = await api(url);
  if (!rows.length) {
    $("userList").innerHTML = "暂无用户数据。用户发送消息、祈福或领取圣物后，这里会出现记录。";
    return;
  }
  $("userList").innerHTML = `<table><thead><tr><th>昵称状态</th><th>当前昵称</th><th>主页唯一 ID</th><th>功德点</th><th>历史总功德</th><th>最后活跃</th><th></th></tr></thead><tbody>${rows.map((u) => {
    const ref = encodeURIComponent(`pk:${u.id}`);
    const nicknameBadge = u.nickname_conflict
      ? `<span class="badge identity-conflict">昵称冲突</span>`
      : `<span class="badge identity-normal">正常</span>`;
    return `<tr><td>${nicknameBadge}</td><td><b>${h(u.nickname)}</b><div class="meta">${h(u.display_name || "")}</div></td><td><code>${h(u.platform_user_id || "未取得唯一ID")}</code></td><td>${u.points || 0}</td><td>${u.total_merit || 0}</td><td>${h((u.last_seen_at || "").substring(0,16))}</td><td style="white-space:nowrap"><button onclick="openUserDetail('${ref}')" class="small">编辑</button><button onclick="deleteUser('${ref}', '${encodeURIComponent(u.nickname)}')" class="small danger" style="margin-left:4px">删除</button></td></tr>`;
  }).join("")}</tbody></table>`;
}

window.openUserDetail = async (encoded) => {
  currentUserRef = encoded;
  const data = await api(`/api/users/${encoded}`);
  let memory = {
    auto_summary:"", admin_correction:"", topics_json:"[]", habits_json:"[]",
    speech_style:"", features_json:"[]", recent_events_json:"[]",
    reference_count:0, locked:0, paused:0, updated_at:null, last_error:""
  };
  try {
    memory = {...memory, ...(await api(`/api/users/${encoded}/ai-memory`))};
  } catch (error) {
    console.warn("AI人物记忆加载失败，用户详情仍继续打开。", error);
  }
  const u = data.user;
  $("userModalTitle").textContent = `${u.nickname} 的用户数据`;
  $("userDetail").innerHTML = `
    <form id="userEditForm" class="form">
      <div class="two"><label>原昵称<input id="editUserNickname" value="${h(u.nickname)}" required></label><label>自定义称呼<input id="editUserDisplayName" value="${h(u.display_name || u.nickname)}"></label></div>
      <div class="two"><label>主页唯一 ID<input id="editUserId" value="${h(u.platform_user_id || u.user_id || "")}" readonly placeholder="尚未取得唯一ID"></label><label>头像记录（不参与识别）<input value="${h(u.avatar_id || "")}" readonly placeholder="未读取"></label></div>
      <div class="two"><label>唯一 ID 状态<input value="${u.platform_user_id ? "已识别" : "尚未取得"}" readonly></label><label>昵称状态<input value="${u.nickname_conflict ? "昵称冲突，请联系管理员" : "正常"}" readonly></label></div>
      <label class="switch"><input id="editUserAdmin" type="checkbox" ${u.is_admin ? "checked" : ""}> 设为管理员</label>
      <div class="four"><label>功德点<input id="editUserPoints" type="number" value="${u.points || 0}"></label><label>历史总功德<input type="number" value="${u.total_merit || 0}" readonly></label><label>命令触发数<input id="editUserHitCount" type="number" min="0" value="${u.hit_count || 0}"></label><label>消息计数<input id="editUserMessageCount" type="number" min="0" value="${u.message_count || 0}"></label></div>
      <div class="three"><label>祈福总数<input id="editUserTotalCheckins" type="number" min="0" value="${u.total_checkins || 0}"></label><label>连续祈福<input id="editUserStreakDays" type="number" min="0" value="${u.streak_days || 0}"></label><label>最后祈福日期<input id="editUserLastCheckin" value="${h(u.last_checkin_date || "")}" placeholder="YYYY-MM-DD"></label></div>
      <div class="two"><label>首次出现时间<input id="editUserFirstSeen" value="${h(u.first_seen_at || "")}"></label><label>最后活跃时间<input id="editUserLastSeen" value="${h(u.last_seen_at || "")}"></label></div>
      <label>历史昵称<textarea id="editUserNicknameHistory">${h(u.nickname_history || "")}</textarea></label>
      <div class="toolbar"><button class="primary" type="submit">保存用户数据</button></div>
    </form>
    <section class="panel form">
      <div class="section-title"><div><p class="eyebrow">AI人物记忆</p><h2>自动摘要与人工修正</h2></div></div>
      <form id="userAiMemoryForm">
        <label>AI自动摘要<span>覆盖更新，管理员可以清空</span><textarea id="editAiAutoSummary" rows="7">${h(memory.auto_summary || "")}</textarea></label>
        <label>管理员人工修正<span>优先级高于自动摘要，自动任务不会改写</span><textarea id="editAiAdminCorrection" rows="7">${h(memory.admin_correction || "")}</textarea></label>
        <div class="two"><label>常见话题<span>JSON数组</span><textarea id="editAiTopics" rows="4">${h(memory.topics_json || "[]")}</textarea></label><label>行为习惯<span>JSON数组</span><textarea id="editAiHabits" rows="4">${h(memory.habits_json || "[]")}</textarea></label></div>
        <label>说话风格<input id="editAiSpeechStyle" value="${h(memory.speech_style || "")}"></label>
        <div class="two"><label>常参与功能<span>JSON数组</span><textarea id="editAiFeatures" rows="4">${h(memory.features_json || "[]")}</textarea></label><label>最近重要事件<span>JSON数组</span><textarea id="editAiRecentEvents" rows="4">${h(memory.recent_events_json || "[]")}</textarea></label></div>
        <p class="note">最后生成：${h(memory.updated_at || "尚未生成")}｜参考消息：${memory.reference_count || 0}｜最近错误：${h(memory.last_error || "无")}</p>
        <div class="two"><label class="switch"><input id="editAiMemoryLocked" type="checkbox" ${memory.locked ? "checked" : ""}> 锁定人工记忆</label><label class="switch"><input id="editAiMemoryPaused" type="checkbox" ${memory.paused ? "checked" : ""}> 暂停自动更新</label></div>
        <div class="toolbar"><button class="primary" type="submit">保存AI人物记忆</button><button id="restoreAiUserMemory" type="button">恢复上一次</button><button id="regenerateAiUserMemory" type="button">重新生成</button><button id="clearAiAutoSummary" type="button">清空AI自动摘要</button></div>
      </form>
    </section>
    ${renderInventoryEditor(data.inventory, encoded)}
    ${renderStatusEditor(data.statuses || [])}
    ${renderDetailTable("积分流水", data.transactions, ["change_amount", "reason", "balance_after", "created_at"])}
    ${renderDetailTable("游戏次数记录", data.game_plays || [], ["game_type", "created_at"])}
    ${renderDetailTable("群对战记录", data.game_battles || [], ["game_type", "bet_amount", "status", "is_winner", "created_at", "finished_at"])}
    ${renderDetailTable("六印圣裁记录", data.six_seal_games || [], ["variant", "current_wager", "status", "result_text", "created_at", "finished_at"])}
    ${renderDetailTable("猜乳头记录", data.nipple_guess_sessions || [], ["stake", "potential_prize", "status", "created_at", "finished_at"])}
    ${renderDetailTable("祈福记录", data.checkins, ["checkin_date", "reward", "streak_days", "created_at"])}
    ${renderDetailTable("规则触发", data.rule_hits, ["rule_id", "reason", "created_at"])}
  `;
  $("userEditForm").onsubmit = saveUserDetail;
  $("userAiMemoryForm").onsubmit = saveUserAiMemory;
  $("clearAiAutoSummary").onclick = () => { $("editAiAutoSummary").value = ""; };
  $("restoreAiUserMemory").onclick = async () => { await api(`/api/users/${currentUserRef}/ai-memory/restore`, {method:"POST"}); await window.openUserDetail(currentUserRef); };
  $("regenerateAiUserMemory").onclick = async () => { const result = await api(`/api/users/${currentUserRef}/ai-memory/regenerate`, {method:"POST"}); alert(result.message); };
  $("userModal").classList.remove("hidden");
};

async function saveUserAiMemory(event) {
  event.preventDefault();
  for (const id of ["editAiTopics", "editAiHabits", "editAiFeatures", "editAiRecentEvents"]) {
    try { JSON.parse($(id).value || "[]"); } catch (_) { alert("人物记忆中的列表字段必须是有效JSON数组。"); return; }
  }
  await api(`/api/users/${currentUserRef}/ai-memory`, {method:"PUT", body:{
    auto_summary:$("editAiAutoSummary").value, admin_correction:$("editAiAdminCorrection").value,
    topics_json:$("editAiTopics").value, habits_json:$("editAiHabits").value,
    speech_style:$("editAiSpeechStyle").value, features_json:$("editAiFeatures").value,
    recent_events_json:$("editAiRecentEvents").value, locked:$("editAiMemoryLocked").checked,
    paused:$("editAiMemoryPaused").checked
  }});
  alert("AI人物记忆已保存。管理员人工修正不会被自动摘要覆盖。");
}

window.openIdentityConflict = async (encodedPlatformId) => {
  const platformId = decodeURIComponent(encodedPlatformId);
  const rows = await api("/api/identity-conflicts");
  const conflict = rows.find((row) => row.platform_user_id === platformId);
  if (!conflict) {
    alert("该身份冲突已经处理或不存在。");
    await loadUsers();
    return;
  }
  $("userModalTitle").textContent = "处理身份冲突用户";
  const candidates = conflict.candidates || [];
  $("userDetail").innerHTML = `
    <div class="panel">
      <p><b>当前昵称：</b>${h(conflict.nickname)}</p>
      <p><b>主页唯一 ID：</b><code>${h(conflict.platform_user_id)}</code></p>
      <p><b>头像 ID：</b><code>${h(conflict.avatar_id || "未读取")}</code></p>
      <p><b>冲突原因：</b>${h(conflict.reason)}</p>
      <p class="meta">处理前该用户所有业务均保持暂停。请核对主页后再操作。</p>
    </div>
    <h2>候选旧用户</h2>
    <div class="table"><table><thead><tr><th>昵称</th><th>头像 ID</th><th>余额</th><th>消息数</th><th></th></tr></thead><tbody>
      ${candidates.map((candidate) => `<tr><td>${h(candidate.nickname)}</td><td><code>${h(candidate.avatar_id || "")}</code></td><td>${candidate.points || 0}</td><td>${candidate.message_count || 0}</td><td><button onclick="resolveIdentityConflict(${conflict.id},'assign',${candidate.id})">确认继承此用户</button></td></tr>`).join("") || `<tr><td colspan="5">没有候选旧用户</td></tr>`}
    </tbody></table></div>
    <div class="toolbar"><button class="danger" onclick="resolveIdentityConflict(${conflict.id},'new',null)">确认这是全新用户</button></div>
  `;
  $("userModal").classList.remove("hidden");
};

window.deleteUser = async (encodedRef, encodedNickname) => {
  const nickname = decodeURIComponent(encodedNickname);
  const warning = `确定删除用户“${nickname}”吗？\n\n功德点、祈福、背包等当前业务数据会从活动数据中移除，但系统会先自动归档，聊天审计日志会保留。该用户再次发言时会作为新用户重新建立。`;
  if (!confirm(warning)) return;
  await api(`/api/users/${encodedRef}`, { method: "DELETE" });
  $("userModal").classList.add("hidden");
  await loadUsers();
  alert(`用户“${nickname}”已删除，删除前数据已归档。`);
};

window.resolveIdentityConflict = async (conflictId, action, candidateUserPk) => {
  const description = action === "assign" ? "把主页 ID 绑定到选中的旧用户并继承数据" : "确认这是全新用户，不继承任何旧数据";
  if (!confirm(description + "？\n\n该操作会写入身份审计记录，请确认你已经人工核对主页。")) return;
  await api(`/api/identity-conflicts/${conflictId}/resolve`, {
    method: "POST",
    body: { action: action, candidate_user_pk: candidateUserPk }
  });
  $("userModal").classList.add("hidden");
  await loadUsers();
  alert("身份冲突已处理。该用户业务已经恢复。");
};



async function openGroupModal() {
  $("groupModal").classList.remove("hidden");
  await loadGroups();
}

async function loadGroups() {
  try {
    var data = await api("/api/rules/groups"); var groups = data.groups || [];
    var html = "";
    if (!groups || !groups.length) {
      html = "暂无分组。";
    } else {
      html = "<table><thead><tr><th>分组名</th><th></th></tr></thead><tbody>" +
        groups.map(function(g) {          return "<tr><td>" + h(g) + "</td><td>" +
            "<button onclick=\"renameGroup('" + g.replace(/'/g, "\\'") + "')\">重命名</button>" +
            "<button class=\"danger\" onclick=\"deleteGroup('" + g.replace(/'/g, "\\'") + "')\">删除</button>" +
            "</td></tr>";
        }).join("") +
        "</tbody></table>";
    }
    $("groupList").innerHTML = html;
  } catch(e) { $("groupList").innerHTML = "加载失败。"; }
}

window.renameGroup = async function(name) {
  var newName = prompt("请输入新分组名", name);
  if (newName && newName.trim() && newName.trim() !== name) {
    await api("/api/rules/groups/rename", { method: "POST", body: { old_name: name, new_name: newName.trim() } });
    await loadGroups();
    await loadRules();
  }
};

window.deleteGroup = async function(name) {
  if (confirm("确定删除分组「" + name + "」？分组内的命令会移到「默认命令」。")) {
    await api("/api/rules/groups/delete", { method: "POST", body: { name: name } });
    await loadGroups();
    await loadRules();
  }
};

async function loadMessages() {
  const rows = await api("/api/messages");
  $("messageList").innerHTML = rows.length ? rows.map((m) => `<div class="item"><b>${h(m.sender)}</b> <span class="badge">${m.is_self ? "自己" : "他人"}</span><span class="badge">${m.processed ? "已处理" : "未处理"}</span><div>${h(m.text)}</div><div class="meta">${h(m.time || "")} · 命中：${h(m.matched_rule || "无")} · 回复：${h(m.reply_text || "无")}</div></div>`).join("") : "暂未读取到群聊消息。";
}

async function loadLogs() {
  $("logList").innerHTML = renderLogs(await api(`/api/logs?kind=${$("logKind").value}`));
}

function toggleShopTarget() {
  var useEnabled = $("shopUseEnabled") && $("shopUseEnabled").checked;
  var useFields = $("shopUseFields");
  var target = $("shopUseTarget");
  var category = $("shopItemCategory") ? $("shopItemCategory").value : "normal";
  var imageFields = $("shopImageFields");
  var specialKind = $("shopSpecialKind") ? $("shopSpecialKind").value : "";
  var isDrop = category === "drop";
  if ($("shopSaleFields")) $("shopSaleFields").style.display = isDrop ? "none" : "";
  if (isDrop) {
    $("shopItemEnabled").checked = false;
    $("shopUseEnabled").checked = false;
    useEnabled = false;
  }
  if (category === "image") {
    $("shopUseEnabled").checked = true;
    target.value = "direct";
    target.disabled = true;
    useEnabled = true;
  } else {
    target.disabled = false;
  }
  if (useFields) useFields.style.display = useEnabled && !isDrop ? "" : "none";
  if (imageFields) imageFields.style.display = category === "image" ? "" : "none";
  var v = target ? target.value : "other";
  var passiveKinds = ["theft_single_defense", "theft_multi_defense", "theft_absolute"];
  var createsStatus = useEnabled && category !== "image" && passiveKinds.indexOf(specialKind) < 0 && (
    (v === "other" && !!$("shopStatusTemplate").value.trim()) ||
    (v === "self" && !!$("shopSelfStatusTemplate").value.trim())
  );
  if ($("shopRemovePriceField")) {
    $("shopRemovePriceField").style.display = createsStatus ? "" : "none";
  }
  if (!useEnabled) return;
  var otherFields = $("shopUseOtherFields");
  var selfFields = $("shopUseSelfFields");
  var directFields = $("shopUseDirectFields");
  if (otherFields) otherFields.style.display = v === "other" ? "" : "none";
  if (selfFields) selfFields.style.display = v === "self" ? "" : "none";
  if (directFields) directFields.style.display = v === "direct" ? "" : "none";
}



async function saveUserDetail(e) {
  e.preventDefault();
  var body = {
    nickname: $("editUserNickname").value.trim(),
    user_id: $("editUserId").value.trim(),
    display_name: $("editUserDisplayName").value.trim(),
    nickname_history: $("editUserNicknameHistory").value,
    is_admin: $("editUserAdmin").checked,
    message_count: Number($("editUserMessageCount").value || 0),
    hit_count: Number($("editUserHitCount").value || 0),
    points: Number($("editUserPoints").value || 0),
    streak_days: Number($("editUserStreakDays").value || 0),
    total_checkins: Number($("editUserTotalCheckins").value || 0),
    last_checkin_date: $("editUserLastCheckin").value.trim() || null,
    first_seen_at: $("editUserFirstSeen").value.trim() || null,
    last_seen_at: $("editUserLastSeen").value.trim() || null
  };
  var result = await api("/api/users/" + currentUserRef, { method: "PUT", body: body });
  await loadUsers();
  alert("用户数据已保存。");
}

function renderInventoryEditor(items, userRef) {
  if (!items || !items.length) return "<h2>背包</h2><p class=\"empty\">暂无物品。</p>";
  var html = "<h2>背包</h2><div class=\"table\"><table><thead><tr><th>物品名</th><th>数量</th><th>更新时间</th><th></th></tr></thead><tbody>";
  items.forEach(function(inv) {
    var name = h(inv.item_name || "");
    var qty = inv.quantity || 0;
    html += "<tr data-item=\"" + name.replace(/"/g, "&quot;") + "\">" +
      "<td><b>" + name + "</b></td>" +
      "<td><input type=\"number\" min=\"0\" value=\"" + qty + "\" class=\"invQty\" style=\"width:80px\"></td>" +
      "<td>" + h(inv.updated_at || "") + "</td>" +
      "<td><button type=\"button\" onclick=\"deleteInventory('" + encodeURIComponent(userRef) + "','" + name.replace(/'/g, "\\'") + "')\">删除</button><button type=\"button\" onclick=\"saveInventory('" + encodeURIComponent(userRef) + "','" + name.replace(/'/g, "\\'") + "')\">保存</button></td></tr>";

  });
  html += "</tbody></table></div>";
  return html;
}

window.deleteInventory = async function(userRef, itemName) {
  if (!confirm("确定删除「" + itemName + "」？")) return;
  await api("/api/users/" + userRef + "/inventory", { method: "PUT", body: { item_name: itemName, quantity: 0 } });
  alert("已删除");
  openUserDetail(userRef);
};

window.saveInventory = async function(userRef, itemName) {
  var row = document.querySelector("tr[data-item=\"" + itemName.replace(/"/g, "&quot;") + "\"]");
  if (!row) return;
  var qty = parseInt(row.querySelector(".invQty").value) || 0;
  await api("/api/users/" + userRef + "/inventory", { method: "PUT", body: { item_name: itemName, quantity: qty } });
  alert("背包已更新。");
};

function renderStatusEditor(rows) {
  if (!rows.length) return "<h2>用户状态</h2><p class=\"empty\">暂无状态。</p>";
  var html = "<h2>用户状态</h2><div class=\"table\"><table><thead><tr><th>物品</th><th>状态文案</th><th>使用者</th><th>解除价</th><th>启用</th><th></th></tr></thead><tbody>";
  rows.forEach(function(s) {
    html += "<tr data-status-id=\"" + s.id + "\">" +
      "<td><input data-field=\"item_name\" value=\"" + h(s.item_name || "") + "\"></td>" +
      "<td><input data-field=\"status_text\" value=\"" + h(s.status_text || "") + "\"></td>" +
      "<td>" + h(s.actor_nickname || "") + "</td>" +
      "<td><input data-field=\"remove_price\" type=\"number\" min=\"0\" value=\"" + (s.remove_price || 5) + "\"></td>" +
      "<td><input data-field=\"active\" type=\"checkbox\" " + (s.active ? "checked" : "") + "></td>" +
      "<td><button type=\"button\" onclick=\"saveStatus(" + s.id + ")\">保存</button></td></tr>";
  });
  html += "</tbody></table></div>";
  return html;
}

window.saveStatus = async function(id) {
  var row = document.querySelector("tr[data-status-id=\"" + id + "\"]");
  if (!row) return;
  var body = {
    item_name: row.querySelector("[data-field=item_name]").value.trim(),
    status_text: row.querySelector("[data-field=status_text]").value.trim(),
    remove_price: Number(row.querySelector("[data-field=remove_price]").value || 0),
    active: row.querySelector("[data-field=active]").checked
  };
  await api("/api/statuses/" + id, { method: "PUT", body: body });
  alert("状态已保存。");
};

function renderDetailTable(title, rows, keys) {
  if (!rows || !rows.length) return "<h2>" + title + "</h2><p class=\"empty\">暂无记录。</p>";
  var html = "<h2>" + title + "</h2><div class=\"table\"><table><thead><tr>";
  keys.forEach(function(k) { html += "<th>" + h(k) + "</th>"; });
  html += "</tr></thead><tbody>";
  rows.forEach(function(r) {
    html += "<tr>";
    keys.forEach(function(k) { html += "<td>" + h(r[k] || "") + "</td>"; });
    html += "</tr>";
  });
  html += "</tbody></table></div>";
  return html;
}


window.promptMerge = async function(encoded) {
  const sourceName = decodeURIComponent(encoded);
  const targetName = prompt("将 " + sourceName + " 合并到哪个用户？\n请输入目标用户的昵称：");
  if (!targetName || targetName.trim() === sourceName) return;
  if (!confirm("确认将 [" + sourceName + "] 的所有数据合并到 [" + targetName.trim() + "]？\n此操作不可撤销！")) return;
  try {
    const result = await api("/api/users/merge", { method: "POST", body: { source: sourceName, target: targetName.trim() } });
    alert("合并成功！");
    await loadUsers();
  } catch(e) {
    alert("合并失败：" + e.message);
  }
};

window.moveRule = async function(id) {
  try {
    var groups = [];
    // Get groups from rules
    rules.forEach(function(r) {
      var g = (r.group_name || "").trim();
      if (g && groups.indexOf(g) < 0) groups.push(g);
    });
    // Also fetch config groups
    try {
      var data = await api("/api/rules/groups");
      (data.groups || []).forEach(function(g) {
        if (g && g !== "未分组" && groups.indexOf(g) < 0) groups.push(g);
      });
    } catch(e) {}
    if (!groups.length) { alert("暂无可用分组"); return; }
    groups.sort();
    var target = prompt("移动到哪个分组？\n\n" + groups.map(function(g,i){return (i+1)+". "+g}).join("\n") + "\n\n输入分组名：");
    if (!target || !target.trim()) return;
    target = target.trim();
    var rule = rules.find(function(r) { return r.id === id; });
    if (!rule) { alert("未找到该命令"); return; }
    rule.group_name = target;
    await api("/api/rules/" + id, { method: "PUT", body: rule });
    alert("已移动到\u300c" + target + "\u300d");
    await loadRules();
  } catch(e) {
    alert("移动失败：" + e.message);
  }
};

async function init() {
  api("/api/app/heartbeat", { method: "POST" }).catch(() => {});
  setInterval(() => api("/api/app/heartbeat", { method: "POST" }).catch(() => {}), 2000);
  window.addEventListener("beforeunload", () => {
    try {
      navigator.sendBeacon("/api/app/client-closed", new Blob(["{}"], { type: "application/json" }));
    } catch (_) {}
  });

  fillSelect("replyMode", replyModes);
  document.querySelectorAll(".sidebar button").forEach((b) => b.addEventListener("click", () => showPage(b.dataset.page)));
  await loadConfig();
  await loadStatus();
  await loadNewcomerBenefit();
  newCompensationRequestId();
  await loadCompensationPreview();
  await loadItemEconomy();
  await loadFacilityWages();
  renderSysCmds();
  renderLuckyBagCommands();
  renderGameCmds();
  await loadRules();
  setInterval(loadStatus, 5000);

  $("refreshDash").onclick = loadStatus;
  $("forceRefreshBtn").onclick = function() {
    const url = new URL(window.location.href);
    url.searchParams.set("refresh", String(Date.now()));
    window.location.replace(url.toString());
  };
  $("refreshNewcomerBenefit").onclick = loadNewcomerBenefit;
  $("saveNewcomerBenefit").onclick = () => saveNewcomerBenefit().catch((error) => alert("保存失败：" + error.message));
  $("refreshLuckyBags").onclick = loadLuckyBags;
  $("saveSettings").onclick = () => runAction("保存设置", () => api("/api/config", { method: "POST", body: collectConfig() }));
  setConnectionAiSaveEnabled(false);
  $("savePaidInteractionConnection").onclick = async () => {
    if (!paidInteractionSettingsLoaded) return alert("付费互动提示词尚未载入，请稍候再保存。");
    try {
      await savePaidInteractionSettings(false);
      $("paidConnectionSaveResult").textContent = "付费互动提示词已保存并重新读取。";
      $("paidConnectionSaveResult").className = "notice success";
      await loadPaidInteractionSettings();
    } catch (error) {
      $("paidConnectionSaveResult").textContent = "保存失败：" + error.message;
      $("paidConnectionSaveResult").className = "notice error";
    }
  };
  $("saveFortuneSettingsConnection").onclick = async () => {
    if (!fortuneSettingsLoaded) return alert("塔罗牌提示词尚未载入，请稍候再保存。");
    try {
      await saveFortuneSettings();
      $("fortuneConnectionSaveResult").textContent = "塔罗牌提示词已保存并重新读取。";
      $("fortuneConnectionSaveResult").className = "notice success";
      await loadFortuneSettings();
    } catch (error) {
      $("fortuneConnectionSaveResult").textContent = "保存失败：" + error.message;
      $("fortuneConnectionSaveResult").className = "notice error";
    }
  };
  $("savePaidInteraction").onclick = () => {
    savePaidInteractionSettings().catch(() => {});
  };
  $("testPaidAi").onclick = testPaidInteractionAi;
  $("restoreEmbeddedDeepseekKey").onclick = () => restoreEmbeddedDeepseekKey().catch((error) => alert("恢复失败：" + error.message));
  $("saveFortuneSettings").onclick = () => saveFortuneSettings().catch(() => {});
  $("refreshFortuneStats").onclick = () => loadFortuneSettings().catch((error) => alert("刷新失败：" + error.message));
  $("saveBountySettings").onclick = () => saveBountySettings().catch(() => {});
  $("refreshBounties").onclick = () => loadBountySettings().catch((error) => alert("刷新失败：" + error.message));
  $("refreshCommissionOrders").onclick = () => loadCommissionOrders().catch((error) => alert("刷新失败：" + error.message));
  $("refreshCommissionHouse").onclick = () => loadAllBounties().catch((error) => alert("刷新失败：" + error.message));
  $("closeCommissionDemandModal").onclick = () => $("commissionDemandModal").classList.add("hidden");
  $("cancelCommissionDemandEdit").onclick = () => $("commissionDemandModal").classList.add("hidden");
  $("commissionDemandForm").onsubmit = saveCommissionDemandEdit;
  $("closeCommissionServiceModal").onclick = () => $("commissionServiceModal").classList.add("hidden");
  $("cancelCommissionServiceEdit").onclick = () => $("commissionServiceModal").classList.add("hidden");
  $("commissionServiceStockMode").onchange = syncCommissionServiceStockFields;
  $("commissionServiceForm").onsubmit = saveCommissionServiceEdit;
  $("saveMarketplaceSettings").onclick = () => saveMarketplaceSettings().catch(() => {});
  $("saveMarketplaceCommands").onclick = () => saveMarketplaceSettings().catch(() => {});
  $("refreshMarketplace").onclick = () => loadMarketplace().catch((error) => alert("刷新失败：" + error.message));
  $("saveRpSettings").onclick = () => saveRpSettings().catch(() => {});
  $("refreshRpSettings").onclick = () => loadRpSettings().catch((error) => alert("刷新失败：" + error.message));
  $("saveRandomEventSettings").onclick = () => saveRandomEventSettings().catch(() => {});
  $("refreshRandomEvents").onclick = () => Promise.all([loadRandomEventSettings(), loadRandomEventsAdmin()]).catch((error) => alert("刷新失败：" + error.message));
  $("saveImageGenerationSettings").onclick = () => saveImageGenerationSettings(false).catch(() => {});
  $("saveImageApiConnection").onclick = () => saveImageGenerationSettings(true).catch(() => {});
  $("clearImageApiKeyConnection").onclick = () => clearImageApiKey(true).catch((error) => alert("清除失败：" + error.message));
  $("clearImageApiKeyModule").onclick = () => clearImageApiKey(false).catch((error) => alert("清除失败：" + error.message));
  $("testImageGenerationApi").onclick = () => testImageGenerationApi("imageGenerationSaveResult");
  $("testImageApiConnection").onclick = () => testImageGenerationApi("imageApiConnectionResult");
  $("refreshImageHistory").onclick = () => Promise.all([loadImageGenerationSettings(), loadImageGenerationHistory()]).catch((error) => alert("刷新失败：" + error.message));
  $("searchImageHistory").onclick = () => loadImageGenerationHistory(1).catch((error) => alert("搜索失败：" + error.message));
  $("imageHistoryStatus").onchange = () => loadImageGenerationHistory(1).catch(() => {});
  $("imageHistoryPrev").onclick = () => loadImageGenerationHistory(imageHistoryPage - 1).catch(() => {});
  $("imageHistoryNext").onclick = () => loadImageGenerationHistory(imageHistoryPage + 1).catch(() => {});
  $("closeImagePreview").onclick = () => { $("imagePreviewModal").classList.add("hidden"); $("imagePreviewFull").src = ""; };
  $("imagePreviewResend").onclick = () => selectedImageJobId && resendImageHistory(selectedImageJobId);
  $("createRandomEventTemplate").onclick = () => openRandomEventTemplateModal({});
  $("closeRandomEventTemplateModal").onclick = () => $("randomEventTemplateModal").classList.add("hidden");
  $("randomEventTemplateForm").onsubmit = async (event) => {
    event.preventDefault();
    try {
      var id = Number($("randomEventTemplateId").value || 0);
      var path = id ? ("/api/random-events/templates/" + id) : "/api/random-events/templates";
      await api(path, {method:"POST", body:collectRandomEventTemplate()});
      $("randomEventTemplateModal").classList.add("hidden");
      await loadRandomEventsAdmin();
    } catch (error) {
      $("randomEventTemplateResult").textContent = "保存失败：" + error.message;
      $("randomEventTemplateResult").className = "notice error";
    }
  };
  $("archiveRandomEventTemplate").onclick = async () => {
    var id = Number($("randomEventTemplateId").value || 0);
    if (!id || !confirm("确定归档这个随机事件？历史场次会保留，归档后不再被抽取。")) return;
    try {
      await api("/api/random-events/templates/" + id + "/archive", {method:"POST", body:{}});
      $("randomEventTemplateModal").classList.add("hidden");
      await loadRandomEventsAdmin();
    } catch (error) { alert("归档失败：" + error.message); }
  };
  $("refreshAiCharacter").onclick = () => loadAiCharacter().catch((error) => alert("刷新失败：" + error.message));
  $("saveAiProfile").onclick = async () => {
    try { await api("/api/ai-character/profile", {method:"PUT", body:collectAiProfile()}); await saveAiSettings({max_reply_messages:Number($("aiMaxReplyMessages").value || 5)}, "角色资料已保存。"); }
    catch (error) { alert("保存失败：" + error.message); }
  };
  $("saveAiPersona").onclick = async () => {
    try { await api("/api/ai-character/profile", {method:"PUT", body:{persona_prompt:$("aiPersonaPrompt").value}}); await loadAiCharacter(); alert("人格设定已保存并立即生效。"); }
    catch (error) { alert("保存失败：" + error.message); }
  };
  $("saveAiSupremeSystemPrompt").onclick = () => saveAiSettings({supreme_system_prompt:$("aiSupremeSystemPrompt").value}, "最高级系统提示词已保存并立即生效。").catch((e) => alert("保存失败：" + e.message));
  $("restoreAiSupremeSystemPromptPrevious").onclick = async () => { await api("/api/ai-character/supreme-system-prompt/restore/previous", {method:"POST"}); await loadAiCharacter(); };
  $("restoreAiSupremeSystemPromptDefault").onclick = async () => { if (confirm("确定只恢复默认最高级系统提示词？其他AI设置不变。")) { await api("/api/ai-character/supreme-system-prompt/restore/default", {method:"POST"}); await loadAiCharacter(); } };
  $("saveAiSystemRules").onclick = () => saveAiSettings({system_rules:$("aiSystemRules").value}, "系统工作规则已保存。").catch((e) => alert("保存失败：" + e.message));
  $("restoreAiPersonaPrevious").onclick = async () => { await api("/api/ai-character/persona/restore/previous", {method:"POST"}); await loadAiCharacter(); };
  $("restoreAiPersonaDefault").onclick = async () => { if (confirm("确定只恢复默认人格提示词？其他角色资料不变。")) { await api("/api/ai-character/persona/restore/default", {method:"POST"}); await loadAiCharacter(); } };
  $("restoreAiProfilePrevious").onclick = async () => { await api("/api/ai-character/profile/restore/previous", {method:"POST"}); await loadAiCharacter(); };
  $("restoreAiProfileDefault").onclick = async () => { if (confirm("确定恢复默认追追模板？当前配置会保留为上一版。")) { await api("/api/ai-character/profile/restore/default", {method:"POST"}); await loadAiCharacter(); } };
  $("restoreAiSettingsPrevious").onclick = async () => { await api("/api/ai-character/system-rules/restore/previous", {method:"POST"}); await loadAiCharacter(); };
  $("restoreAiSettingsDefault").onclick = async () => { if (confirm("确定只恢复默认系统工作规则？其他AI设置不变。")) { await api("/api/ai-character/system-rules/restore/default", {method:"POST"}); await loadAiCharacter(); } };
  $("saveAiModel").onclick = () => saveAiSettings({enabled:$("aiEnabled").checked,primary_model:$("aiPrimaryModel").value,backup_model:$("aiBackupModel").value,normal_thinking:$("aiNormalThinking").checked,allow_thinking_command:$("aiAllowThinking").checked,fallback_model_enabled:$("aiFallbackModel").checked,fallback_to_normal:$("aiFallbackNormal").checked,normal_timeout_seconds:Number($("aiNormalTimeout").value || 30),thinking_timeout_seconds:Number($("aiThinkingTimeout").value || 90)}).catch((e) => alert("保存失败：" + e.message));
  $("saveAiFees").onclick = () => saveAiSettings({normal_fee:Number($("aiNormalFee").value || 0),thinking_fee:Number($("aiThinkingFee").value || 0),recipient_fee:Number($("aiRecipientFee").value || 0),fee_enabled:$("aiFeeEnabled").checked,allow_insufficient:$("aiAllowInsufficient").checked,allow_negative:$("aiAllowNegative").checked,admin_free:$("aiAdminFree").checked,free_user_ids:$("aiFreeUsers").value.split(/\r?\n/).map((x)=>x.trim()).filter(Boolean),fee_recipient_user_id:$("aiFeeRecipientUserId").value.trim(),token_footer_enabled:$("aiTokenFooter").checked,token_footer_format:$("aiTokenFooterFormat").value}).catch((e) => alert("保存失败：" + e.message));
  $("saveAiContext").onclick = () => saveAiSettings({recent_group_messages:Number($("aiRecentGroup").value || 30),recent_user_messages:Number($("aiRecentUser").value || 12),normal_max_tool_calls:Number($("aiNormalTools").value || 4),thinking_max_tool_calls:Number($("aiThinkingTools").value || 8),conversation_raw_turns:Number($("aiRawTurns").value || 8),conversation_summary_chars:Number($("aiConversationSummary").value || 1200),context_max_chars:Number($("aiContextMax").value || 12000),related_user_limit:Number($("aiRelatedUsers").value || 5),normal_concurrency:Number($("aiNormalConcurrency").value || 3),thinking_concurrency:Number($("aiThinkingConcurrency").value || 1),background_concurrency:Number($("aiBackgroundConcurrency").value || 1),per_user_queue:Number($("aiUserQueue").value || 2),per_group_queue:Number($("aiGroupQueue").value || 10),queue_wait_seconds:Number($("aiQueueWait").value || 30),memory_enabled:$("aiMemoryEnabled").checked,memory_message_threshold:Number($("aiMemoryThreshold").value || 20),memory_summary_chars:Number($("aiMemoryChars").value || 1200),memory_event_limit:Number($("aiEventLimit").value || 30),group_memory_enabled:$("aiGroupMemoryEnabled").checked,group_memory_min_messages:Number($("aiGroupMemoryMin").value || 8)}).catch((e) => alert("保存失败：" + e.message));
  $("regenerateAiGroupMemory").onclick = async () => { const result = await api("/api/ai-character/group-memory/regenerate", {method:"POST", body:{group_id:"main"}}); alert(result.message); await loadAiCharacter(); };
  $("saveAiProactive").onclick = () => saveAiSettings({proactive_enabled:$("aiProactiveEnabled").checked,proactive_groups:{main:$("aiProactiveMain").checked,bounty:$("aiProactiveBounty").checked},proactive_model:$("aiProactiveModel").value,proactive_thinking:$("aiProactiveThinking").checked,proactive_token_footer:$("aiProactiveToken").checked,proactive_max_chars:Number($("aiProactiveChars").value || 280),proactive_quiet_start:$("aiQuietStart").value,proactive_quiet_end:$("aiQuietEnd").value,proactive_during_rp:$("aiProactiveRp").checked,proactive_during_games:$("aiProactiveGames").checked}).catch((e) => alert("保存失败：" + e.message));
  $("createAiRelationship").onclick = async () => { try { await api("/api/ai-character/relationships", {method:"POST",body:{group_id:$("aiRelationGroup").value.trim() || "main",subject_user_id:$("aiRelationSubject").value.trim(),object_user_id:$("aiRelationObject").value.trim(),forward_relation:$("aiRelationForward").value.trim(),reverse_relation:$("aiRelationReverse").value.trim(),admin_note:$("aiRelationNote").value.trim(),allow_inheritance:$("aiRelationInheritance").checked,locked:true}}); await loadAiCharacter(); } catch(e) { alert("新增失败：" + e.message); } };
  $("createAiEvent").onclick = async () => { try { await api("/api/ai-character/events", {method:"POST",body:{group_id:$("aiEventGroup").value.trim() || "main",user_id:$("aiEventUser").value.trim(),event_type:$("aiEventType").value.trim(),summary:$("aiEventSummary").value.trim(),importance:Number($("aiEventImportance").value || 3),source_message_id:$("aiEventMessageId").value.trim(),tease_ok:$("aiEventTease").checked}}); $("aiEventSummary").value=""; await loadAiCharacter(); } catch(e) { alert("新增失败：" + e.message); } };
  $("testAiPersona").onclick = testAiPersona;
  document.querySelectorAll(".aiModelTest").forEach((button) => button.onclick = () => testAiModel(button.dataset.target, button.dataset.thinking === "true"));
  $("closeBountyEditModal").onclick = closeBountyEditModal;
  $("bountyEditForm").onsubmit = saveBountyEdit;
  $("bountyEditDurationType").onchange = syncBountyDurationInput;
  $("deleteBounty").onclick = deleteBountySafely;
  $("closeMarketEditModal").onclick = closeMarketEditModal;
  $("marketEditForm").onsubmit = saveMarketEdit;
  
  $("closeGameModal").onclick = function() { $("gameModal").classList.add("hidden"); };
  $("saveGameCmd").onclick = saveGameCmd;
  $("closeSysCmdModal").onclick = function() { $("sysCmdModal").classList.add("hidden"); };
  $("saveSysCmd").onclick = saveSysCmd;
  $("manageGroups").onclick = openGroupModal;
  $("closeGroupModal").onclick = function() { $("groupModal").classList.add("hidden"); };
  $("createGroup").onclick = async function() { var n = $("newGroupName").value.trim(); if (!n) { alert("请输入分组名"); return; } await api("/api/rules/groups/create", { method: "POST", body: { name: n } }); $("newGroupName").value = ""; await loadGroups(); };
  $("saveSafety").onclick = () => runAction("保存安全设置", async () => { collectSafety(); return api("/api/config", { method: "POST", body: config }); });
  $("openHome").onclick = () => runAction("打开 DZMM", () => api("/api/browser/open-home", { method: "POST" }));
  $("saveGroupUrlLock").onclick = () => runAction("保存群聊地址锁定", async () => {
    const data = await api("/api/browser/group-url-lock", {
      method: "POST",
      body: { enabled: $("groupUrlLockEnabled").checked }
    });
    $("groupUrlLockResult").textContent = data.message;
    await loadConfig();
    return data;
  });
  $("openGroup").onclick = () => runAction("打开群聊", () => api("/api/browser/open-group", { method: "POST", body: { url: $("groupUrl").value } }));
  $("openBountyGroup").onclick = () => runAction("打开悬赏群", () => api("/api/browser/open-group", { method: "POST", body: { url: $("bountyGroupUrl").value, group_key: "bounty" } }));
  $("openImageGroup").onclick = () => runAction("打开绘图群", () => api("/api/browser/open-group", { method: "POST", body: { url: $("imageGroupUrl").value, group_key: "image" } }));
  $("openImageGroupModule").onclick = () => api("/api/browser/open-group", { method: "POST", body: { url: $("imageModuleGroupUrl").value, group_key: "image" } }).then(() => { $("imageGenerationSaveResult").textContent = "已打开绘图群页面。"; }).catch((error) => alert("打开失败：" + error.message));
  $("checkLogin").onclick = () => runAction("检测登录", () => api("/api/browser/login-status"));
  $("detectSelectors").onclick = () => runAction("识别页面", async () => { const data = await api("/api/browser/detect-selectors", { method: "POST" }); await loadConfig(); return data; });
  $("debugPage").onclick = () => runAction("页面调试", () => api("/api/debug/page"));
  $("resetProfile").onclick = () => { if (confirm("会清除本地登录状态，需要重新登录。确定继续？")) runAction("重置登录", () => api("/api/browser/reset-profile", { method: "POST" })); };
  $("pauseBtn").onclick = () => api("/api/bot/pause", { method: "POST" }).then(loadStatus);
  $("resumeBtn").onclick = () => api("/api/bot/resume", { method: "POST" }).then(loadStatus);
  $("emergencyStop").onclick = () => api("/api/bot/emergency-stop", { method: "POST" }).then(loadStatus);
  $("readBtn").onclick = async () => { const data = await api("/api/messages/read-test", { method: "POST" }); alert(data.ok ? `读取到 ${data.messages.length} 条消息。` : data.error); await loadMessages(); };
  $("sendBtn").onclick = async () => { const text = $("quickSendText").value.trim() || "/测试"; if (confirm(`确定发送测试消息：${text}？这会真实发到当前群聊。`)) alert(JSON.stringify(await api("/api/messages/send-test", { method: "POST", body: { text } }), null, 2)); };
  $("refreshCompensationPreview").onclick = loadCompensationPreview;
  $("compensationAmount").oninput = updateCompensationPreviewText;
  $("grantCompensationBtn").onclick = grantCompensation;
  $("refreshFacilityWages").onclick = loadFacilityWages;
  $("addFacilityWageRule").onclick = addFacilityWageRule;
  $("refreshItemEconomy").onclick = loadItemEconomy;
  $("saveItemEconomy").onclick = () => saveItemEconomy().catch((error) => alert("保存失败：" + error.message));
  $("saveExchangeSettings").onclick = () => saveItemEconomy().catch((error) => alert("保存失败：" + error.message));
  $("saveDropEntry").onclick = () => saveDropEntry().catch((error) => alert("保存失败：" + error.message));
  $("clearDropEntry").onclick = clearDropEntry;
  $("newExchangeOffer").onclick = openNewExchangeOfferModal;
  $("closeExchangeOfferModal").onclick = closeExchangeOfferModal;
  $("cancelExchangeOffer").onclick = closeExchangeOfferModal;
  $("addExchangeCost").onclick = () => addExchangeCostRow();
  $("addExchangeReward").onclick = () => addExchangeRewardRow({reward_type:"points", quantity:100});
  $("saveExchangeOffer").onclick = () => saveExchangeOffer().catch((error) => alert("保存失败：" + error.message));
  $("refreshExchangeHistory").onclick = async () => { itemEconomy.history = await api("/api/item-economy/exchange-history"); renderExchangeHistory(); };
  $("exportFullData").onclick = exportFullData;
  $("newRule").onclick = () => openRuleModal();
  $("closeRuleModal").onclick = closeRuleModal;
  $("cancelRule").onclick = () => openRuleModal();
  $("ruleSearch").oninput = loadRules;
  if ($("ruleGroupFilter")) $("ruleGroupFilter").onchange = loadRules;
  $("ruleForm").onsubmit = async (e) => { e.preventDefault(); const id = $("ruleId").value; await api(id ? `/api/rules/${id}` : "/api/rules", { method: id ? "PUT" : "POST", body: collectRule() }); closeRuleModal(); await loadRules(); };
  $("exportRules").onclick = async () => { const data = await api("/api/rules/export"); const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }); const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "dzmm-rules.json"; a.click(); };
  $("importRules").onclick = async () => { const text = prompt("粘贴导出的规则 JSON"); if (text) { await api("/api/rules/import", { method: "POST", body: JSON.parse(text) }); await loadRules(); } };
  $("shopItemForm").onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api("/api/shop-items", { method: "POST", body: collectShopItem() });
      $("shopItemModal").classList.add("hidden");
      await loadShopItems();
    } catch (error) {
      alert("商品保存失败：" + error.message);
    }
  };
  $("closeShopItemModal").onclick = function() { $("shopItemModal").classList.add("hidden"); };
  $("cancelShopItem").onclick = function() { $("shopItemModal").classList.add("hidden"); };
  $("newShopItem").onclick = function() { openShopItemModal(null); };
  $("newImageShopItem").onclick = function() { openShopItemModal(null, "image"); };
  $("shopUseEnabled").onchange = toggleShopTarget;
  $("shopUseTarget").onchange = toggleShopTarget;
  $("shopItemCategory").onchange = toggleShopTarget;
  $("shopStatusTemplate").oninput = toggleShopTarget;
  $("shopSelfStatusTemplate").oninput = toggleShopTarget;
  $("chooseShopImageFolder").onclick = async function() {
    var result = await api("/api/folders/select", {
      method: "POST",
      body: { current: $("shopImageFolder").value.trim() }
    });
    if (result.path) $("shopImageFolder").value = result.path;
  };
  $("shopConfigBtn").onclick = function() {
    var f = config.features || {};
    $("shopTriggerWords").value = f.shop_commands || "/神殿仓库,/商店,/shop";
    $("shopConfigHeader").value = f.shop_header || "⛪ 神殿仓库现有圣物：";
    $("shopConfigEmptyReply").value = f.shop_empty_reply || "神殿仓库空空如也。";
    $("shopConfigItemLine").value = f.shop_item_line || "{number}. {item}：{price} {currency}，库存 {stock}{description}";
    $("shopConfigFooter").value = f.shop_footer || "发送 /购买 商品名 进行购买。";
    $("shopConfigModal").classList.remove("hidden");
  };
  $("closeShopConfigModal").onclick = function() { $("shopConfigModal").classList.add("hidden"); };
  $("saveShopConfig").onclick = async function() {
    var feat = JSON.parse(JSON.stringify(config.features || {}));
    feat.shop_commands = $("shopTriggerWords").value.trim() || "/神殿仓库,/商店,/shop";
    feat.shop_header = $("shopConfigHeader").value;
    feat.shop_item_line = $("shopConfigItemLine").value;
    feat.shop_footer = $("shopConfigFooter").value;
    feat.shop_empty_reply = $("shopConfigEmptyReply").value;
    var result = await api("/api/features", { method: "POST", body: feat });
    config.features = result.features;
    $("shopConfigModal").classList.add("hidden");
    alert("神殿仓库配置已保存。");
  };
  $("cleanupUsers").onclick = async () => { const data = await api("/api/users/cleanup", { method: "POST" }); alert(`已清理 ${data.count} 个无效用户条目。`); await loadUsers(); };
  $("refreshUsers").onclick = loadUsers;
  $("userSearch").oninput = loadUsers;
  $("identityStatusFilter").onchange = loadUsers;
  $("closeUserModal").onclick = () => $("userModal").classList.add("hidden");
  $("refreshLogs").onclick = loadLogs;
  $("logKind").onchange = loadLogs;
  $("clearLogs").onclick = async () => { if (confirm("确定清空日志？这个操作不可恢复。")) { await api("/api/logs", { method: "DELETE" }); await loadLogs(); } };
  $("startConfig").onclick = () => { $("guide").classList.add("hidden"); showPage("connect"); };
  $("showHelp").onclick = () => { $("guide").classList.add("hidden"); showPage("help"); };
  $("hideGuide").onclick = async () => { config.ui = { ...(config.ui || {}), hide_guide: true }; await api("/api/config", { method: "POST", body: config }); $("guide").classList.add("hidden"); };
}

init().catch((err) => alert(err.message));
