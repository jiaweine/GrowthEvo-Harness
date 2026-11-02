import React, { useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";

import { approve, Dashboard, getDashboard } from "./src/api";

type Tab = "home" | "campaigns" | "approvals";

const NIGHTFALL = {
  bg: "#090e18", panel: "#111a29", raised: "#162235", line: "#29364a",
  text: "#eef5ff", muted: "#a3b5ca", accent: "#68e4e0",
  success: "#68dfb1", danger: "#ff7b95", dangerPanel: "#30202d",
};
const STATUS_LABELS: Record<string, string> = {
  Draft: "草案", Running: "运行中", Completed: "已完成", Paused: "已暂停",
  pending: "待审批", approve_shadow: "已批准影子验证", approve_1: "已批准 1%",
  approve_5: "已批准 5%", approve_25: "已批准 25%", reject: "已拒绝", return: "已退回",
  "5% Canary": "5% 小流量验证", "pending causal evaluation": "等待增量验证",
};
const statusLabel = (value: string) => Object.prototype.hasOwnProperty.call(STATUS_LABELS, value) ? STATUS_LABELS[value] : value;

const money = (value: number) => `¥${new Intl.NumberFormat("zh-CN").format(value)}`;
const errorMessage = (error: unknown) => error instanceof Error ? error.message : "工作区请求失败";

function AppBody() {
  const [tab, setTab] = useState<Tab>("home");
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = async () => {
    try {
      const next = await getDashboard();
      setData(next);
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const pending = useMemo(
    () => data?.approvals.filter((item) => item.status === "pending") ?? [],
    [data],
  );

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await load();
    } finally {
      setRefreshing(false);
    }
  };

  const decide = async (id: string, decision: "approve_5" | "approve_25" | "reject") => {
    setBusyId(id);
    setError(null);
    try {
      await approve(id, decision);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusyId(null);
    }
  };

  if (!data && !error) {
    return <View style={styles.center}><ActivityIndicator size="large" color={NIGHTFALL.accent} /></View>;
  }

  const online = Boolean(data) && !error;

  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]}>
      <StatusBar barStyle="light-content" />
      <View style={styles.header}>
        <View>
          <Text style={styles.brand}>GrowthEvo</Text>
          <Text style={styles.subtitle}>智能增长工作台</Text>
        </View>
        <View style={[styles.live, !online && styles.liveError]}>
          <View style={[styles.liveDot, !online && styles.liveDotError]}/>
          <Text style={[styles.liveText, !online && styles.liveTextError]}>{online ? "已连接" : "未连接"}</Text>
        </View>
      </View>

      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      >
        {error ? (
          <View style={styles.error}>
            <Text style={styles.errorText}>{error}</Text>
            <Pressable onPress={() => void load()} style={styles.retryButton}>
              <Text style={styles.retryText}>重新连接</Text>
            </Pressable>
          </View>
        ) : null}

        {tab === "home" && data ? (
          <>
            <Text style={styles.title}>增长驾驶舱</Text>
            <Text style={styles.description}>只看增量结果、风险与需要你批准的动作。</Text>
            <View style={styles.kpiGrid}>
              {data.kpis.map((kpi) => (
                <View style={styles.kpi} key={kpi.id}>
                  <Text style={styles.kpiLabel}>{kpi.label}</Text>
                  <Text style={styles.kpiValue}>{kpi.formatted}</Text>
                  <Text style={styles.positive}>↑ {kpi.delta}</Text>
                </View>
              ))}
            </View>
            <SectionTitle title="需要处理" meta={`${pending.length} pending`} />
            {pending.length === 0 ? <Empty text="当前没有待审批事项" /> : pending.map((item) => (
              <ApprovalCard key={item.id} item={item} busy={busyId === item.id} onDecision={decide} compact />
            ))}
          </>
        ) : null}

        {tab === "campaigns" && data ? (
          <>
            <Text style={styles.title}>活动</Text>
            <Text style={styles.description}>移动端用于健康检查与异常处置；复杂编排留在桌面端。</Text>
            {data.campaigns.map((item) => (
              <View style={styles.card} key={item.id}>
                <View style={styles.rowBetween}>
                  <Text style={styles.cardTitle}>{item.name}</Text>
                  <Badge text={statusLabel(item.status)} />
                </View>
                <Text style={styles.meta}>目标 · {item.goal}</Text>
                <View style={styles.divider}/>
                <View style={styles.rowBetween}>
                  <Text style={styles.meta}>预期增量</Text>
                  <Text style={item.expected_lift.startsWith("-") ? styles.negative : styles.positive}>{statusLabel(item.expected_lift)}</Text>
                </View>
              </View>
            ))}
          </>
        ) : null}

        {tab === "approvals" && data ? (
          <>
            <Text style={styles.title}>审批中心</Text>
            <Text style={styles.description}>批准的是影响范围与预算，不是“相信 AI”。证据和风险始终可见。</Text>
            {data.approvals.map((item) => (
              <ApprovalCard key={item.id} item={item} busy={busyId === item.id} onDecision={decide} />
            ))}
          </>
        ) : null}
      </ScrollView>

      <View style={styles.tabs}>
        <TabButton active={tab === "home"} label="首页" icon="⌂" onPress={() => setTab("home")} />
        <TabButton active={tab === "campaigns"} label="活动" icon="▦" onPress={() => setTab("campaigns")} />
        <TabButton active={tab === "approvals"} label="审批" icon="✓" onPress={() => setTab("approvals")} count={pending.length} />
      </View>
    </SafeAreaView>
  );
}

function SectionTitle({ title, meta }: { title: string; meta: string }) {
  return <View style={styles.sectionHead}><Text style={styles.sectionTitle}>{title}</Text><Text style={styles.meta}>{meta}</Text></View>;
}

function Empty({ text }: { text: string }) {
  return <View style={styles.card}><Text style={styles.meta}>{text}</Text></View>;
}

function Badge({ text }: { text: string }) {
  return <View style={styles.badge}><Text style={styles.badgeText}>{text}</Text></View>;
}

function ApprovalCard({
  item,
  busy,
  onDecision,
  compact = false,
}: {
  item: Dashboard["approvals"][number];
  busy: boolean;
  onDecision: (id: string, decision: "approve_5" | "approve_25" | "reject") => void;
  compact?: boolean;
}) {
  return (
    <View style={styles.card}>
      <View style={styles.rowBetween}>
        <Text style={styles.cardTitle}>{item.title}</Text>
        <View style={styles.evidence}><Text style={styles.evidenceText}>{item.evidence_tier}</Text></View>
      </View>
      <Text style={styles.meta}>{new Intl.NumberFormat("zh-CN").format(item.affected_users)} 人 · 预算 {money(item.budget)}</Text>
      {!compact ? <Text style={styles.meta}>状态 · {statusLabel(item.status)}</Text> : null}
      {item.status === "pending" ? (
        <View style={styles.actions}>
          <Pressable disabled={busy} onPress={() => onDecision(item.id, "reject")} style={styles.secondaryButton}><Text style={styles.secondaryButtonText}>拒绝</Text></Pressable>
          <Pressable disabled={busy} onPress={() => onDecision(item.id, "approve_5")} style={styles.primaryButton}><Text style={styles.primaryButtonText}>{busy ? "处理中…" : "批准 5%"}</Text></Pressable>
        </View>
      ) : null}
    </View>
  );
}

function TabButton({ active, label, icon, onPress, count }: { active: boolean; label: string; icon: string; onPress: () => void; count?: number }) {
  return (
    <Pressable onPress={onPress} style={styles.tabButton}>
      <View><Text style={[styles.tabIcon, active && styles.tabActive]}>{icon}</Text>{count ? <View style={styles.count}><Text style={styles.countText}>{count}</Text></View> : null}</View>
      <Text style={[styles.tabText, active && styles.tabActive]}>{label}</Text>
    </Pressable>
  );
}

export default function App() {
  return <SafeAreaProvider><AppBody /></SafeAreaProvider>;
}

const styles = StyleSheet.create({
  safe:{flex:1,backgroundColor:NIGHTFALL.bg},center:{flex:1,alignItems:"center",justifyContent:"center",backgroundColor:NIGHTFALL.bg},
  header:{height:62,paddingHorizontal:18,backgroundColor:NIGHTFALL.panel,borderBottomWidth:1,borderBottomColor:NIGHTFALL.line,flexDirection:"row",alignItems:"center",justifyContent:"space-between"},
  brand:{fontSize:20,fontWeight:"800",color:NIGHTFALL.text,letterSpacing:-.6},subtitle:{fontSize:10,color:NIGHTFALL.muted,marginTop:2},live:{flexDirection:"row",alignItems:"center",gap:6,paddingHorizontal:9,paddingVertical:5,borderRadius:999,backgroundColor:NIGHTFALL.raised},liveError:{backgroundColor:NIGHTFALL.dangerPanel},liveDot:{width:6,height:6,borderRadius:3,backgroundColor:NIGHTFALL.success},liveDotError:{backgroundColor:NIGHTFALL.danger},liveText:{fontSize:9,fontWeight:"700",color:NIGHTFALL.success},liveTextError:{color:NIGHTFALL.danger},
  content:{padding:15,paddingBottom:96},title:{fontSize:27,fontWeight:"800",color:NIGHTFALL.text,letterSpacing:-1},description:{fontSize:12,lineHeight:18,color:NIGHTFALL.muted,marginTop:5,marginBottom:14},
  kpiGrid:{flexDirection:"row",flexWrap:"wrap",gap:9},kpi:{width:"48.5%",backgroundColor:NIGHTFALL.panel,borderWidth:1,borderColor:NIGHTFALL.line,borderRadius:12,padding:13},kpiLabel:{fontSize:10,color:NIGHTFALL.muted,fontWeight:"600"},kpiValue:{fontSize:19,color:NIGHTFALL.text,fontWeight:"800",letterSpacing:-.5,marginTop:9,marginBottom:4},positive:{fontSize:11,color:NIGHTFALL.success,fontWeight:"700"},negative:{fontSize:11,color:NIGHTFALL.danger,fontWeight:"700"},
  sectionHead:{marginTop:18,marginBottom:8,flexDirection:"row",alignItems:"center",justifyContent:"space-between"},sectionTitle:{fontSize:15,fontWeight:"700",color:NIGHTFALL.text},card:{backgroundColor:NIGHTFALL.panel,borderWidth:1,borderColor:NIGHTFALL.line,borderRadius:12,padding:14,marginBottom:9},cardTitle:{fontSize:13,fontWeight:"700",color:NIGHTFALL.text,flex:1,paddingRight:10},meta:{fontSize:10,color:NIGHTFALL.muted,lineHeight:16,marginTop:5},rowBetween:{flexDirection:"row",alignItems:"center",justifyContent:"space-between"},divider:{height:1,backgroundColor:NIGHTFALL.line,marginVertical:12},badge:{backgroundColor:NIGHTFALL.raised,borderRadius:999,paddingHorizontal:8,paddingVertical:4},badgeText:{fontSize:9,color:NIGHTFALL.success,fontWeight:"700"},evidence:{width:28,height:28,borderRadius:8,backgroundColor:NIGHTFALL.raised,alignItems:"center",justifyContent:"center"},evidenceText:{fontSize:11,color:NIGHTFALL.success,fontWeight:"800"},
  actions:{flexDirection:"row",gap:8,marginTop:12},secondaryButton:{height:34,flex:1,borderWidth:1,borderColor:NIGHTFALL.line,borderRadius:8,alignItems:"center",justifyContent:"center"},secondaryButtonText:{fontSize:10,color:NIGHTFALL.text,fontWeight:"700"},primaryButton:{height:34,flex:1,backgroundColor:NIGHTFALL.accent,borderRadius:8,alignItems:"center",justifyContent:"center"},primaryButtonText:{fontSize:10,color:NIGHTFALL.bg,fontWeight:"800"},
  tabs:{height:70,backgroundColor:NIGHTFALL.panel,borderTopWidth:1,borderTopColor:NIGHTFALL.line,flexDirection:"row",paddingBottom:8},tabButton:{flex:1,alignItems:"center",justifyContent:"center",gap:2},tabIcon:{fontSize:18,color:NIGHTFALL.muted},tabText:{fontSize:9,color:NIGHTFALL.muted,fontWeight:"600"},tabActive:{color:NIGHTFALL.accent},count:{position:"absolute",right:-10,top:-3,minWidth:16,height:16,borderRadius:8,backgroundColor:NIGHTFALL.danger,alignItems:"center",justifyContent:"center",paddingHorizontal:3},countText:{fontSize:8,color:NIGHTFALL.bg,fontWeight:"800"},error:{backgroundColor:NIGHTFALL.dangerPanel,borderRadius:10,padding:12,marginBottom:12},errorText:{fontSize:10,color:NIGHTFALL.danger,lineHeight:15},retryButton:{alignSelf:"flex-start",marginTop:8,borderWidth:1,borderColor:NIGHTFALL.danger,borderRadius:7,paddingHorizontal:10,paddingVertical:6},retryText:{fontSize:9,color:NIGHTFALL.danger,fontWeight:"700"},
});