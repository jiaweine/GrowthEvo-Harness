const ROUTE_PARENT={
  opportunities:'evidence',realtime:'evidence',campaignStudio:'campaigns',experiments:'campaigns',execution:'campaigns',
  approvals:'harness',evolution:'harness',creative:'campaigns'
};

Object.assign(DEMO,{
  opportunityRows:[
    {segment:'新用户 0–7 天未首购',kind:'Persuadables',population:864210,natural:12.4,best_action:'首单免邮',incremental_lift_pp:8.4,incremental_value:1840000,confidence:'95% CI +6.8 ~ +10.1pp',support:.91,evidence_tier:'A',freshness:'3 分钟前'},
    {segment:'沉默 30–60 天会员',kind:'Channel-sensitive',population:320510,natural:3.1,best_action:'召回 Push + 商品卡',incremental_lift_pp:4.7,incremental_value:612000,confidence:'95% CI +3.2 ~ +6.0pp',support:.89,evidence_tier:'A',freshness:'7 分钟前'},
    {segment:'高意向加购未支付',kind:'Cost-sensitive',population:86210,natural:28.7,best_action:'免邮 / NO_TREATMENT',incremental_lift_pp:5.3,incremental_value:438000,confidence:'OPE SE 0.0041',support:.84,evidence_tier:'B',freshness:'2 分钟前'},
    {segment:'高频浏览低客单用户',kind:'Sleeping Dogs',population:241880,natural:18.3,best_action:'NO_TREATMENT',incremental_lift_pp:-1.8,incremental_value:126000,confidence:'95% CI -2.7 ~ -0.6pp',support:.93,evidence_tier:'A',freshness:'9 分钟前'},
    {segment:'会员到期前 14 天',kind:'Timing-sensitive',population:72881,natural:41.2,best_action:'会员权益提醒',incremental_lift_pp:3.9,incremental_value:294000,confidence:'95% CI +2.2 ~ +5.4pp',support:.81,evidence_tier:'B',freshness:'12 分钟前'}
  ],
  experiments:[
    {id:'EXP-281',name:'新用户首购激励 · 免邮 vs ¥10 券',status:'Running',unit:'user_id',population:'128,421',variants:'3 个实验组',assignment:'40/30/30',metric:'7日首购增量',guardrail:'退订率 < 0.3%',maturity:'7 天',estimate:'+8.4pp',impact:'¥ 724k',uncertainty:'±1.7pp'},
    {id:'EXP-294',name:'沉默用户召回渠道测试',status:'Matured',unit:'member_id',population:'88,210',variants:'应用推送 / 邮件 / 保留组',assignment:'35/35/30',metric:'7日活跃增量',guardrail:'投诉率 < 0.1%',maturity:'14 天',estimate:'+4.7pp',impact:'¥ 312k',uncertainty:'±1.2pp'},
    {id:'EXP-301',name:'结算页实时免邮策略',status:'5% Canary',unit:'decision_id',population:'42,880',variants:'策略组 / 对照组',assignment:'5/95',metric:'增量支付率',guardrail:'毛利率 > 24%',maturity:'3 天',estimate:'+5.3pp',impact:'¥ 438k',uncertainty:'离线评估 → 线上验证'}
  ],
  decisions:[
    {id:'dec_920184',entity:'user_28419',placement:'checkout_banner',action:'free_shipping',creative:'cr_281',propensity:.23,policy:'policy_growth_safe',evidence:'A',latency:41,result:'served'},
    {id:'dec_920183',entity:'user_77410',placement:'home_feed',action:'NO_TREATMENT',creative:'—',propensity:.62,policy:'policy_growth_safe',evidence:'A',latency:37,result:'suppressed'},
    {id:'dec_920182',entity:'user_19028',placement:'push_next_best_action',action:'member_reminder',creative:'cr_188',propensity:.18,policy:'policy_growth_safe',evidence:'B',latency:52,result:'served'},
    {id:'dec_920181',entity:'user_01948',placement:'checkout_banner',action:'NO_TREATMENT',creative:'—',propensity:.71,policy:'policy_growth_safe',evidence:'A',latency:39,result:'frequency_cap'}
  ],
  traces:[
    {glyph:'G',name:'整理任务目标',detail:'整理目标、预算与保护指标',latency:'118 ms',cost:'$0.01'},
    {glyph:'C',name:'读取工作上下文',detail:'读取数据仓库、会话事件与证据索引',latency:'392 ms',cost:'$0.02'},
    {glyph:'M',name:'读取经验',detail:'按权限检索活动、证据与品牌经验',latency:'84 ms',cost:'$0.00'},
    {glyph:'T',name:'读取候选人群',detail:'返回 864,210 个候选新用户',latency:'226 ms',cost:'$0.00'},
    {glyph:'E',name:'核对增量证据',detail:'A级证据 · 支持度 91% · 保留不触达对照',latency:'63 ms',cost:'$0.00'},
    {glyph:'A',name:'请求人工审批',detail:'L3 风险 · 申请 5% 小流量验证',latency:'42 ms',cost:'$0.00'}
  ],
  approvalsFull:[
    {id:'APR-281',title:'新用户首购计划扩大至 25%',desc:'5% Canary 已运行 48 小时，申请扩大流量。',users:'186,421',budget:'¥286,000',risk:'¥71,500',channel:'应用推送与站内消息',value:'¥724,000',evidence:'A',uncertainty:'95% CI +5.9 ~ +10.7pp',complaint:'退订 +0.08pp',agent:'growth_agent',harness:'growth_harness',policy:'policy_growth_safe',change:'Traffic 5% → 25%；其余 treatment、creative、frequency cap 不变。',level:'L3'},
    {id:'APR-404',title:'Creative Set #12 发布到 Email',desc:'新生成的 Email 变体通过 Brand Check，等待有限外发。',users:'72,881',budget:'¥62,000',risk:'¥15,500',channel:'Email',value:'¥134,000',evidence:'B',uncertainty:'OPE SE 0.0041',complaint:'投诉 <0.05%',agent:'creative_agent',harness:'growth_harness',policy:'policy_growth_safe',change:'新增 Creative B/C；价格与优惠声明沿用 approved facts。',level:'L3'},
    {id:'APR-517',title:'线上 Champion Policy 更新',desc:'Evolution candidate EV-281 已通过 replay 和 shadow。',users:'全量实时决策',budget:'Hard cap 不变',risk:'全站策略切换',channel:'Realtime API',value:'预计 +2.8%',evidence:'A',uncertainty:'Shadow delta +2.1 ~ +3.4%',complaint:'guardrail 全通过',agent:'operator_agent',harness:'growth_harness',policy:'policy_growth_safe_candidate',change:'Audience creation 前新增 eligibility distribution check。',level:'L4'}
  ],
  evolution:[
    {id:'EV-281',source:'387 条活动创建演示记录',problem:'演示记录中，部分任务过早创建受众，随后发现不满足触达频次条件。',candidate:'创建受众前，先检查触达资格与频次分布。',metrics:[['任务通过率','+6.4%'],['工具调用次数','-8.2%'],['规则违反率','0%'],['Cost','-4.1%']],stage:'Canary ready'},
    {id:'EV-294',source:'126 条创意生成演示记录',problem:'同一商品卖点在推送与邮件间重复，可能引起用户疲劳。',candidate:'生成创意前对比不同渠道的近期内容，减少重复。',metrics:[['任务通过率','+3.1%'],['重复率','-21.4%'],['规则违反率','0%'],['Cost','+0.8%']],stage:'Shadow'},
    {id:'EV-307',source:'72 条增长机会分析演示记录',problem:'低支持度人群偶尔被过度解释为可执行机会。',candidate:'证据为 C/D 级时，优先说明不确定性与验证要求。',metrics:[['事实准确度','+5.8%'],['无证据断言','-44%'],['规则违反率','0%'],['Latency','+1.9%']],stage:'Offline replay'}
  ],
  executions:[
    {name:'新用户首购提升计划',status:'Running',audience:'128,421',channel:'应用推送与站内消息',connector:'演示推送',action:'free_shipping',delivery:'62.1%',cost:'¥82,410',approval:'APR-281'},
    {name:'沉默会员召回',status:'Preflight',audience:'88,210',channel:'Email',connector:'演示邮件',action:'reactivation_card',delivery:'—',cost:'¥0',approval:'APR-404'},
    {name:'结算页实时免邮',status:'Running',audience:'Realtime',channel:'Web/App',connector:'Decision API',action:'policy_growth_safe',delivery:'99.98%',cost:'¥21,084',approval:'小流量验证策略'}
  ],
  connectors:[
    {logo:'WH',name:'Warehouse',detail:'演示数据，支持后续接入 PostgreSQL',status:'ready'},
    {logo:'RT',name:'实时事件',detail:'浏览器演示事件流',status:'ready'},
    {logo:'PS',name:'Push',detail:'无需凭证的演示连接',status:'ready'},
    {logo:'EM',name:'Email',detail:'无需凭证的演示连接',status:'ready'},
    {logo:'AD',name:'Ads',detail:'待接入适配器',status:'planned'},
    {logo:'LLM',name:'模型服务',detail:'可选模型接入',status:'planned'}
  ]
});
