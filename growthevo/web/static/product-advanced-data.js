Object.assign(DEMO,{
  creatives:[
    {id:'cr_281',channel:'Push',title:'首单免邮 · 简洁权益版',status:'Approved',uplift:'+6.8pp',fatigue:'Low',checks:['Brand','Claim','Offer','Length'],copy:'你的首单免邮已到账。选好喜欢的商品，结算时自动生效。'},
    {id:'cr_282',channel:'Email',title:'首购指南 · 商品卡版',status:'Experiment',uplift:'+2.1pp',fatigue:'Medium',checks:['Brand','Product','Price'],copy:'精选热销商品 + 首单免邮权益，帮助新用户更快完成第一次购买。'},
    {id:'cr_283',channel:'Banner',title:'免邮权益 · 强视觉版',status:'Draft',uplift:'+0.4pp',fatigue:'Low',checks:['Brand','Offer'],copy:'首单免邮｜结算自动生效'},
    {id:'cr_188',channel:'Push',title:'会员到期提醒',status:'Approved',uplift:'+3.9pp',fatigue:'Low',checks:['Brand','Legal','Facts'],copy:'你的会员权益将在 14 天后到期，续费前可先查看本期已节省金额。'}
  ],
  journeys:[
    {id:'JNY-18',name:'新用户首购 7 日旅程',status:'Running',entry:'signup_completed',nodes:9,policy:'policy_growth_safe',population:'128,421',goal:'7日首购增量',path:['Event','Eligibility','Decision','Experiment','Channel','Outcome']},
    {id:'JNY-24',name:'沉默会员召回旅程',status:'Canary',entry:'inactive_30d',nodes:11,policy:'policy_reactivation_safe',population:'32,510',goal:'7日活跃增量',path:['Timer','Eligibility','Approval','Decision','Wait','Outcome']},
    {id:'JNY-31',name:'会员到期保护旅程',status:'Draft',entry:'membership_expiry_14d',nodes:8,policy:'policy_membership_safe',population:'72,881',goal:'续费增量',path:['Event','Condition','Decision','No Treatment','Channel','Outcome']}
  ],
  memories:[
    {id:'mem_brand_41',scope:'organization',type:'Brand Fact',source:'brand-guideline',status:'Active',confidence:'1.00',freshness:'2d',ttl:'—',owner:'Brand Ops',why:'匹配 organization scope + verified source',content:'涉及“首单免邮”时禁止表述为永久权益；必须说明适用条件。'},
    {id:'mem_ev_281',scope:'campaign:CAM-842',type:'Evidence',source:'EXP-281',status:'Active',confidence:'0.97',freshness:'3h',ttl:'90d',owner:'Evidence Store',why:'campaign scope + Tier A experiment',content:'新用户 0–7 天未首购：首单免邮增量 +8.4pp，support 91%。'},
    {id:'mem_skill_17',scope:'agent:campaign',type:'Experience',source:'387 historical runs',status:'Verified',confidence:'0.91',freshness:'1d',ttl:'180d',owner:'Harness',why:'task match + verified abstract experience',content:'创建 Audience 前先检查 frequency eligibility distribution。'},
    {id:'mem_product_9',scope:'organization',type:'Product Fact',source:'catalog-sync-2026-09-28',status:'Active',confidence:'1.00',freshness:'5h',ttl:'7d',owner:'Commerce',why:'fresh company source outranks older web context',content:'免邮权益仅适用于标准配送商品，跨境与超大件除外。'}
  ],
  models:[
    {name:'Growth Planner LLM',provider:'OpenAI-compatible adapter',identity:'planner_stable',purpose:'Agent planning',eval:'92.4%',latency:'1.8s',cost:'$0.041/run',scope:'approved context only',deployment:'Shadow + Canary',owner:'Agent Platform',status:'Champion'},
    {name:'Purchase CATE',provider:'GrowthEvo',identity:'purchase_cate',purpose:'Incremental treatment effect',eval:'Qini 0.184',latency:'13ms',cost:'—',scope:'warehouse features',deployment:'Serving',owner:'Causal ML',status:'Champion'},
    {name:'Behavior Propensity',provider:'GrowthEvo',identity:'behavior_propensity',purpose:'OPE logging',eval:'ECE 0.021',latency:'4ms',cost:'—',scope:'decision context',deployment:'Serving',owner:'Decisioning',status:'Champion'},
    {name:'Creative Vision',provider:'optional vision adapter',identity:'creative_vision',purpose:'Creative understanding',eval:'Brand QA 96.1%',latency:'820ms',cost:'$0.008/item',scope:'creative assets',deployment:'On demand',owner:'Creative AI',status:'Challenger'}
  ],
  policies:[
    {id:'policy_growth_safe',name:'Checkout Incremental Policy',status:'Champion',objective:'incremental_profit',actions:'NO_TREATMENT + 3 actions',budget:'¥50 / decision cap',trust:'±8%',exploration:'5%',fallback:'NO_TREATMENT',evidence:'Tier A/B',unit:'decision_id'},
    {id:'policy_growth_safe_candidate',name:'Checkout Incremental Policy Candidate',status:'Canary',objective:'incremental_profit',actions:'same registry',budget:'unchanged',trust:'±6%',exploration:'3%',fallback:'NO_TREATMENT',evidence:'Tier A/B',unit:'decision_id'},
    {id:'policy_membership_safe',name:'Membership Renewal Policy',status:'Validated',objective:'incremental_renewal',actions:'NO_TREATMENT + reminder',budget:'¥8 / member',trust:'±10%',exploration:'0%',fallback:'NO_TREATMENT',evidence:'Tier B+',unit:'member_id'}
  ],
  entities:[
    {id:'user_28419',type:'Consumer',segment:'新用户 0–7 天未首购',ltv:'¥1,284',consent:'Allowed',channels:'Push · Email · App',fatigue:'Low',churn:'12%',natural:'12.4%',uplift:'+8.4pp',support:'91%'},
    {id:'acct_9012',type:'Account',segment:'高价值家庭账户',ltv:'¥18,420',consent:'Allowed',channels:'Email · App',fatigue:'Medium',churn:'4%',natural:'41.7%',uplift:'+3.1pp',support:'86%'},
    {id:'merchant_188',type:'Merchant',segment:'活跃商家',ltv:'¥92,100',consent:'N/A',channels:'Console · Email',fatigue:'Low',churn:'8%',natural:'67.1%',uplift:'+2.2pp',support:'82%'}
  ],
  entityTimeline:[
    ['10:02','Behavior','浏览 3 个商品','session_774'],['10:08','Behavior','加入购物车 · ¥198','cart_902'],['10:10','Decision','Decision Requested','dec_920184'],['10:10','Policy','FREE_SHIPPING 0.52 · NO_TREATMENT 0.31 · COUPON_10 0.17','policy_growth_safe'],['10:10','Chosen','FREE_SHIPPING · propensity 0.52','Tier A'],['10:11','Exposure','Banner Exposed · cr_281','exp_8821'],['13:42','Outcome','Purchase · ¥218','order_10928'],['+7d','Matured','Outcome matured · incremental attribution locked','evidence_281']
  ],
  attribution:[
    {name:'新用户首购计划',observed:'¥3.21m',incremental:'¥2.84m',counterfactual:'¥0.37m',cost:'¥0.64m',iroi:'4.42x',evidence:'A'},
    {name:'沉默会员召回',observed:'¥0.94m',incremental:'¥0.61m',counterfactual:'¥0.33m',cost:'¥0.19m',iroi:'3.21x',evidence:'A'},
    {name:'会员到期提醒',observed:'¥0.48m',incremental:'¥0.29m',counterfactual:'¥0.19m',cost:'¥0.08m',iroi:'3.63x',evidence:'B'}
  ]
});
