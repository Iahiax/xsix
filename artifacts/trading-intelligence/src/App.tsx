import { useState, type FormEvent, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { Link, Route, Switch, useLocation, Router as WouterRouter } from 'wouter';
import {
  Activity, ArrowDownLeft, ArrowUpLeft, BarChart3, Bell, Check, ChevronDown, ChevronLeft,
  CircleAlert, Cloud, Code2, Cpu, Database, Gauge, GitBranch, LockKeyhole,
  MessageSquareText, MoreHorizontal, Play, RefreshCw, Search, Send, Settings2,
  Shield, ShieldCheck, Sparkles, TrendingDown,
  X, Zap, Layers3, CandlestickChart, Radio, Menu, ListChecks,
} from 'lucide-react';
import {
  getGetBacktestsQueryKey, getGetCapitalMarketsQueryKey, getGetCompanyFundamentalsQueryKey, getGetConnectorStatusQueryKey, getGetEconomicDataQueryKey, getGetLiveMarketQueryKey, getGetLiveReadinessQueryKey,
  getGetSystemDiagnosticsQueryKey,
  getGetTradingBackupsQueryKey,
  getGetTrainingStatusQueryKey, getGetTradingActivitiesQueryKey, getGetTradingDashboardQueryKey,
  getGetTradingSettingsQueryKey,
  useCreateTradingBackup, useGetBacktests,
  useGetTradingBackups,
  useGetCapitalAccount, useGetCapitalMarkets, useGetCompanyFundamentals, useGetConnectorStatus, useGetEconomicData, useGetLiveMarket, useGetLiveReadiness, useGetTrainingStatus, useGetTradingActivities,
  useGetTradingDashboard, useGetTradingSettings,
  useGetSystemDiagnostics, useHealthCheck, useSendAssistantMessage, useStartRetraining,
  useUpdateTradingSettings,
} from '@workspace/api-client-react';
import type {
  Activity as ActivityType, ChatInputContext, RetrainInput, TradingSettingsUpdate,
} from '@workspace/api-client-react';
import './index.css';
import './backup.css';

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 12_000, refetchOnWindowFocus: true } } });

const navigation = [
  { href: '/', label: 'نظرة عامة', icon: Gauge },
  { href: '/research', label: 'مختبر الأبحاث', icon: CandlestickChart },
  { href: '/training', label: 'التدريب', icon: GitBranch },
  { href: '/universe', label: 'مراقبة السوق', icon: Layers3 },
  { href: '/assistant', label: 'المحلل الذكي', icon: MessageSquareText },
  { href: '/settings', label: 'الضوابط والربط', icon: Settings2 },
];

const fmt = (value: number, digits = 2) => new Intl.NumberFormat('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
const money = (value: number) => `$${fmt(value)}`;
const moneyCurrency = (value: number | null | undefined, currency?: string | null) => {
  if (value == null) return '—';
  const code = currency && /^[A-Z]{3}$/.test(currency) ? currency : 'USD';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: code, maximumFractionDigits: 2 }).format(value);
};
const dateShort = (value?: string | Date | null) => value ? (value instanceof Date ? value : new Date(value)).toLocaleString('ar', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—';
const sourceLabel = (source?: string) => source === 'capital_live' ? 'حساب Capital.com الحي' : source === 'capital_demo' ? 'حساب Capital.com التجريبي' : 'غير متاح';
const nullableNumber = (value: number | null | undefined, digits = 2) => value == null ? '—' : fmt(value, digits);

function App() {
  return <QueryClientProvider client={queryClient}>
    <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, '')}>
      <Shell />
    </WouterRouter>
  </QueryClientProvider>;
}

function Shell() {
  const [path] = useLocation();
  const [mobileMenu, setMobileMenu] = useState(false);
  const current = navigation.find(item => item.href === path);
  return <div className="app-frame" dir="rtl">
    <aside className={`sidebar ${mobileMenu ? 'sidebar-open' : ''}`}>
      <div className="brand-lockup">
        <div className="brand-symbol"><span /><span /><span /></div>
        <div><div className="brand-name">مِرصاد</div><div className="brand-sub">TRADING INTELLIGENCE</div></div>
        <button className="icon-button mobile-close" aria-label="إغلاق القائمة" onClick={() => setMobileMenu(false)}><X size={17} /></button>
      </div>
      <div className="workspace-select"><div className="workspace-mark">م</div><div className="workspace-name"><b>مكتب التداول</b><small>مساحة عمل خاصة</small></div><ChevronDown size={15} /></div>
      <div className="nav-caption">مساحة العمل</div>
      <nav className="nav-list">
        {navigation.map(({ href, label, icon: Icon }) => <Link key={href} href={href} onClick={() => setMobileMenu(false)} className={`nav-link ${path === href ? 'active' : ''}`} data-testid={`link-nav-${href.replace('/', 'dashboard')}`}>
          <Icon size={18} strokeWidth={1.7} /><span>{label}</span>{path === href && <span className="nav-indicator" />}
        </Link>)}
      </nav>
      <div className="sidebar-bottom">
        <div className="sidebar-note">
          <div className="note-icon"><ShieldCheck size={17} /></div>
          <div><strong>وضع محمي</strong><p>التداول الحقيقي مقفل<br />حتى اكتمال الجاهزية.</p></div>
          <LockKeyhole size={13} className="note-lock" />
        </div>
        <div className="profile-row"><div className="profile-avatar">ع</div><div><b>المشغّل</b><small>محلل مستقل</small></div><MoreHorizontal size={18} className="profile-more" /></div>
      </div>
    </aside>
    {mobileMenu && <button aria-label="إغلاق التنقل" className="mobile-scrim" onClick={() => setMobileMenu(false)} />}
    <main className="main-panel">
      <header className="topbar">
        <div className="topbar-start">
          <button className="icon-button mobile-menu" aria-label="فتح القائمة" onClick={() => setMobileMenu(true)}><Menu size={19} /></button>
          <div className="breadcrumbs"><span>مرصاد</span><ChevronLeft size={13} /><b>{current?.label ?? 'نظرة عامة'}</b></div>
          <div className="market-state"><span className="health-dot attention" /> قراءة فقط <span className="market-divider" /> لا تُرسل أوامر تداول</div>
        </div>
        <div className="topbar-end"><div className="top-date">{new Date().toLocaleDateString('ar', { weekday: 'long', day: 'numeric', month: 'long' })}</div>
          <div className="icon-button notification" aria-label="التنبيهات"><Bell size={17} /><i /></div>
          <div className="top-avatar">ع</div>
        </div>
      </header>
      <div className="page-content">
        <Switch>
          <Route path="/" component={DashboardPage} />
          <Route path="/research" component={ResearchPage} />
          <Route path="/training" component={TrainingPage} />
          <Route path="/universe" component={CapitalMarketsPage} />
          <Route path="/assistant" component={AssistantPage} />
          <Route path="/settings" component={SettingsPage} />
          <Route component={NotFound} />
        </Switch>
      </div>
    </main>
  </div>;
}

function PageHeading({ eyebrow, title, detail, action }: { eyebrow: string; title: string; detail: string; action?: ReactNode }) {
  return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{detail}</p></div>{action && <div className="heading-action">{action}</div>}</div>;
}
function Panel({ children, className = '', ...props }: { children: ReactNode; className?: string; 'data-testid'?: string }) { return <section className={`panel ${className}`} {...props}>{children}</section>; }
function PanelTitle({ title, eyebrow, action }: { title: string; eyebrow?: string; action?: React.ReactNode }) {
  return <div className="panel-title"><div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h2>{title}</h2></div>{action}</div>;
}
function QueryState({ loading, error, retry, children, label = 'البيانات' }: { loading: boolean; error: unknown; retry: () => void; children: React.ReactNode; label?: string }) {
  if (loading) return <div className="skeleton-block" aria-label={`جار تحميل ${label}`}><div className="skeleton-line wide" /><div className="skeleton-line" /><div className="skeleton-line short" /></div>;
  if (error) return <div className="state-box error-state"><CircleAlert size={22} /><strong>تعذر تحميل {label}</strong><span>تحقق من الاتصال بالخدمة ثم أعد المحاولة.</span><button className="button button-quiet" onClick={retry}>إعادة المحاولة <RefreshCw size={14} /></button></div>;
  return <>{children}</>;
}
function EmptyState({ title, detail }: { title: string; detail: string }) { return <div className="empty-state"><div className="empty-glyph"><Database size={21} /></div><b>{title}</b><span>{detail}</span></div>; }
function Tag({ children, tone = 'neutral' }: { children: ReactNode; tone?: string }) { return <span className={`tag tag-${tone}`}>{children}</span>; }
function Stat({ label, value, suffix, foot, tone, icon: Icon }: { label: string; value: ReactNode; suffix?: string; foot?: ReactNode; tone?: string; icon: typeof Gauge }) {
  return <div className="stat-card"><div className="stat-head"><span>{label}</span><span className={`stat-icon ${tone ?? ''}`}><Icon size={16} /></span></div><div className="stat-value">{value}<small>{suffix}</small></div>{foot && <div className="stat-foot">{foot}</div>}</div>;
}
function DataCaption({ children = 'تعرض البيانات فقط عند تأكيد مصدرها؛ لا تُستخدم قيم بديلة أو تركيبية.' }: { children?: ReactNode }) { return <div className="data-caption"><span className="caption-mark">i</span>{children}</div>; }
function ActivityList({ items }: { items: ActivityType[] }) {
  if (!items.length) return <EmptyState title="لا توجد أحداث بعد" detail="ستظهر هنا تحديثات النظام والمخاطر." />;
  return <div className="activity-list">{items.map(item => <div className="activity-item" key={item.id} data-testid={`activity-item-${item.id}`}><span className={`activity-mark severity-${item.severity}`}><Activity size={14} /></span><div className="activity-copy"><div><b>{item.title}</b><span>{dateShort(item.createdAt)}</span></div><p>{item.detail}</p></div></div>)}</div>;
}

function DashboardPage() {
  const dashboard = useGetTradingDashboard();
  const account = useGetCapitalAccount();
  const activities = useGetTradingActivities();
  const health = useHealthCheck();
  const refresh = () => { void dashboard.refetch(); void account.refetch(); void activities.refetch(); void health.refetch(); };
  const d = dashboard.data;
  const accountData = account.data;
  const openPositions = accountData?.positions ?? [];
  const riskUsage = d?.dailyPnlPct == null || d.dailyLossLimitPct == null || d.dailyLossLimitPct <= 0
    ? null
    : Math.min(Math.max(0, -d.dailyPnlPct) / d.dailyLossLimitPct * 100, 100);
  return (
    <div className="page-stack">
      <PageHeading
        eyebrow="مرصاد · لوحة العمليات"
        title="صورة الحساب، كما هي."
        detail="مراجعة موثّقة للحساب والمخاطر والنشاط. مرصاد للقراءة والتحليل فقط."
        action={<button className="button button-outline" onClick={refresh}><RefreshCw size={15} /> تحديث اللوحة</button>}
      />
      <QueryState loading={dashboard.isLoading} error={dashboard.error} retry={refresh} label="لوحة التداول">
        {d ? (
          <>
            <div className="hero-strip">
              <div className="hero-intro">
                <div className="hero-kicker"><span className={`health-dot ${accountData?.state === 'connected' ? 'healthy' : accountData?.state === 'unavailable' || accountData?.state === 'unauthorized' ? 'offline' : 'attention'}`} /> {sourceLabel(d.dataSource)} <span className="hero-date">آخر تحقق {dateShort(accountData?.checkedAt ?? d.updatedAt)}</span></div>
                <div className="hero-equity">{moneyCurrency(accountData?.balance, accountData?.currency)}<span>رصيد الحساب من Capital.com</span></div>
                <div className="hero-sub">قراءة فقط — لن تُرسل أوامر أو تُغيّر المراكز</div>
              </div>
              <div className="hero-performance">
                <div className="hero-perf-label">الربح / الخسارة حسب حساب الوسيط</div>
                <div className={`hero-pnl ${(accountData?.profitLoss ?? 0) >= 0 ? 'positive' : 'negative'}`}>{accountData?.profitLoss == null ? '—' : `${accountData.profitLoss >= 0 ? '+' : ''}${moneyCurrency(accountData.profitLoss, accountData.currency)}`}</div>
                <div className="hero-pnl-percent">نسبة اليوم: {d.dailyPnlPct == null ? '—' : `${nullableNumber(d.dailyPnlPct)}٪`}</div>
              </div>
              <div className="hero-meta">
                <Tag tone={accountData?.state === 'connected' ? 'green' : accountData?.state === 'unavailable' || accountData?.state === 'unauthorized' ? 'red' : 'neutral'}>{accountData?.state === 'connected' ? 'متصل ومتحقق' : accountData?.state === 'unauthorized' ? 'يتطلب تفويضاً' : accountData?.state === 'unavailable' ? 'غير متاح' : 'غير مضبوط'}</Tag>
                <div className="hero-meta-row"><span>النمط</span><b>قراءة فقط</b></div>
                <div className="hero-meta-row"><span>المصدر</span><b>{sourceLabel(d.dataSource)}</b></div>
                <div className="hero-meta-row"><span>إصدار النموذج</span><b className="mono">{d.modelVersion}</b></div>
                <div className="hero-meta-row"><span>التداول الحقيقي</span><b className="locked-state"><LockKeyhole size={12} /> مقفل</b></div>
              </div>
            </div>
            <div className="stats-grid">
              <Stat label="مراكز Capital.com المفتوحة" value={d.openPositions} foot={<span className="muted">قراءة مباشرة من الوسيط</span>} icon={Layers3} />
              <Stat label="معدل الفوز" value={d.winRate == null ? '—' : fmt(d.winRate)} suffix={d.winRate == null ? '' : '%'} foot={<span className="muted">{d.winRate == null ? 'لا تتوفر قراءة موثّقة' : 'وفق بيانات اللوحة'}</span>} tone="sage" icon={BarChart3} />
              <Stat label="أقصى تراجع" value={d.maxDrawdown == null ? '—' : fmt(d.maxDrawdown)} suffix={d.maxDrawdown == null ? '' : '%'} foot={<span className="muted">{d.maxDrawdown == null ? 'لا تتوفر قراءة موثّقة' : 'وفق بيانات اللوحة'}</span>} tone="amber" icon={TrendingDown} />
              <Stat label="أدوات متتبعة" value={d.trackedSymbols == null ? '—' : d.trackedSymbols} foot={<span className="muted">{d.trackedSymbols == null ? 'لا تتوفر قراءة موثّقة' : 'ضمن نطاق الرصد'}</span>} icon={Radio} />
            </div>
            <div className="dashboard-grid">
              <Panel className="positions-panel">
                <PanelTitle title="المراكز المفتوحة" eyebrow="من Capital.com" action={<Link href="/universe" className="text-link">السوق <ChevronLeft size={14} /></Link>} />
                <QueryState loading={account.isLoading} error={account.error} retry={() => void account.refetch()} label="المراكز">
                  {openPositions.length ? (
                    <div className="table-scroll">
                      <table>
                        <thead><tr><th>الأداة</th><th>الاتجاه</th><th>سعر الدخول</th><th>السعر الحالي</th><th>الحجم</th><th>الربح / الخسارة</th></tr></thead>
                        <tbody>
                          {openPositions.map(position => (
                            <tr key={position.id}>
                              <td><b className="instrument-ticker">{position.epic}</b><small className="cell-sub">{position.name}</small></td>
                              <td><Tag tone={position.direction === 'buy' ? 'green' : 'red'}>{position.direction === 'buy' ? 'شراء' : 'بيع'}</Tag></td>
                              <td className="mono">{nullableNumber(position.entryPrice, 4)}</td>
                              <td className="mono">{nullableNumber(position.currentPrice, 4)}</td>
                              <td className="mono">{nullableNumber(position.size, 4)}</td>
                              <td className={`mono ${position.profitLoss == null ? '' : position.profitLoss >= 0 ? 'positive-text' : 'negative-text'}`}>{position.profitLoss == null ? '—' : `${position.profitLoss >= 0 ? '+' : ''}${moneyCurrency(position.profitLoss, position.currency)}`}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : <EmptyState title={accountData?.state === 'connected' ? 'لا توجد مراكز مفتوحة' : 'حساب الوسيط غير متصل'} detail={accountData?.state === 'connected' ? 'لم يُرجع حساب Capital.com مراكز مفتوحة.' : accountData?.detail ?? 'جار التحقق من اتصال Capital.com.'} />}
                </QueryState>
              </Panel>
              <Panel className="risk-panel">
                <PanelTitle title="مراقبة المخاطر" eyebrow="حدود الحساب" />
                <div className="risk-gauge">
                  <div className="risk-gauge-copy">
                     <span>استهلاك حد الخسارة اليومية</span>
                     <b>{riskUsage == null ? '—' : fmt(riskUsage, 1)}<small>{riskUsage == null ? '' : '%'}</small></b>
                  </div>
                   <div className="progress-track"><span style={{ width: `${riskUsage ?? 0}%` }} /></div>
                   <div className="risk-scale"><span>{d.dailyLossLimitPct == null ? 'غير محسوب' : `حد الخسارة اليومي ${fmt(d.dailyLossLimitPct)}٪`}</span><span>{riskUsage == null ? 'حد الخسارة غير مضبوط' : 'من إجمالي الحد'}</span></div>
                </div>
                <div className="risk-summary">
                  <div className="risk-summary-icon"><Shield size={17} /></div>
                   <div><b>التداول للقراءة فقط</b><span>لا توجد أوامر مفعّلة في التطبيق</span></div>
                  <Tag tone={d.riskState === 'clear' ? 'green' : d.riskState === 'halted' ? 'red' : 'gold'}>{d.riskState}</Tag>
                </div>
                <div className="mini-metrics">
                  <div><span>صحة النظام</span><b className="health-value"><i className={`health-dot ${d.systemHealth}`} />{d.systemHealth === 'healthy' ? 'مستقر' : d.systemHealth === 'attention' ? 'يتطلب انتباهاً' : 'غير متصل'}</b></div>
                   <div><span>التدريب</span><b>{d.trainingProgress == null ? 'غير متاح' : `${d.trainingProgress}% مكتمل`}</b></div>
                </div>
                 <div className="risk-progress"><span style={{ width: `${d.trainingProgress ?? 0}%` }} /></div>
              </Panel>
              <Panel className="activity-panel">
                <PanelTitle title="سجل النشاط" eyebrow="أحداث النظام" action={<button className="icon-button tiny-button" onClick={() => void activities.refetch()} aria-label="تحديث النشاط"><RefreshCw size={14} /></button>} />
                <QueryState loading={activities.isLoading} error={activities.error} retry={() => void activities.refetch()} label="سجل النشاط"><ActivityList items={(activities.data ?? []).slice(0, 5)} /></QueryState>
              </Panel>
              <Panel className="readiness-panel">
                <div className="readiness-art"><ShieldCheck size={22} /></div>
                 <div className="readiness-copy"><div className="eyebrow">حدود التنفيذ</div><b>لا تُرسل أوامر.</b><p>البيانات للقراءة فقط. إعداد الاتصال يظهر في شاشة الضوابط.</p><Link href="/settings" className="text-link">فحص الاتصال <ChevronLeft size={14} /></Link></div>
                <LockKeyhole className="readiness-lock" size={18} />
              </Panel>
            </div>
          </>
        ) : null}
      </QueryState>
      <div className="health-footer">
        {health.isLoading ? <span className="health-dot attention" /> : <span className={`health-dot ${health.isError ? 'offline' : 'healthy'}`} />}
        {health.isLoading ? 'جار فحص خدمة النظام' : health.isError ? <><span>تعذر فحص خدمة النظام</span><button className="text-button" onClick={() => void health.refetch()}>إعادة الفحص</button></> : <>خدمة النظام {health.data?.status === 'ok' ? 'تعمل' : health.data?.status}</>}
         <span className="footer-sep" />مصدر كل قيمة موضح؛ لا تُستبدل البيانات غير المتاحة بتقديرات.
      </div>
    </div>
  );
}

function ResearchPage() {
  const backtests = useGetBacktests();
  return <div className="page-stack">
    <PageHeading eyebrow="بحث كمي · مختبر الاستراتيجيات" title="الاختبار التاريخي متوقف حالياً." detail="لن تُنشأ نتائج حتى تُوصل بيانات تاريخية حقيقية وتُتحقق جودتها." action={<Tag tone="gold">لا نتائج اصطناعية</Tag>} />
    <Panel><PanelTitle title="متطلبات فتح المختبر" eyebrow="مصدر البيانات" /><div className="guardrail-list">
      <div><CircleAlert size={15} /><span>واجهة الأسعار الحالية توفر أسعاراً لحظية فقط، ولا توفر شموعاً تاريخية قابلة للتحقق.</span></div>
      <div><CircleAlert size={15} /><span>لم تُضف بعد بيانات الرسوم والسبريد التاريخي اللازمة لحساب أداء واقعي.</span></div>
      <div><CircleAlert size={15} /><span>لا تُعرض أي عوائد أو صفقات اختبارية حتى تكتمل هذه المتطلبات.</span></div>
    </div><DataCaption>قراءة Capital.com اللحظية متاحة في صفحة مراقبة السوق؛ هذا لا يكفي وحده لاختبار تاريخي صادق.</DataCaption></Panel>
    <Panel className="history-panel"><PanelTitle title="سجل الاختبارات" eyebrow="الأرشيف" action={<button className="button button-quiet" onClick={() => void backtests.refetch()}><RefreshCw size={14} /> تحديث</button>} />
      <QueryState loading={backtests.isLoading} error={backtests.error} retry={() => void backtests.refetch()} label="سجل الاختبارات">{backtests.data?.length ? <div className="table-scroll"><table><thead><tr><th>الاستراتيجية / الأداة</th><th>الفترة</th><th>العائد</th><th>معدل الفوز</th><th>أقصى تراجع</th><th>عامل الربح</th><th>صفقات</th><th>المصدر</th><th>التاريخ</th></tr></thead><tbody>{backtests.data.map(test => <tr key={test.id}><td><b>{test.strategy}</b><small className="cell-sub">{test.symbol} · {test.timeframe}</small></td><td>{test.windowDays} يوم</td><td className={test.returnPct >= 0 ? 'positive-text mono' : 'negative-text mono'}>{test.returnPct > 0 ? '+' : ''}{fmt(test.returnPct)}%</td><td className="mono">{fmt(test.winRate)}%</td><td className="mono">{fmt(test.maxDrawdown)}%</td><td className="mono">{fmt(test.profitFactor)}</td><td className="mono">{test.totalTrades}</td><td><Tag tone="gold">{sourceLabel(test.dataSource)}</Tag></td><td>{dateShort(test.createdAt)}</td></tr>)}</tbody></table></div> : <EmptyState title="لا توجد نتائج اختبار" detail="لن تظهر نتائج حتى يُوصل مصدر تاريخي حقيقي وتُعتمد منهجية التحقق." />}</QueryState>
    </Panel>
  </div>;
}

function TrainingPage() {
  const training = useGetTrainingStatus();
  const start = useStartRetraining();
  const qc = useQueryClient();
  const [form, setForm] = useState<RetrainInput>({ universe: 'watchlist', timeframe: 'H1', validationWindowDays: 180 });
  const [message, setMessage] = useState('');
  const run = (e: FormEvent) => { e.preventDefault(); setMessage(''); start.mutate({ data: form }, { onSuccess: () => { setMessage('تم إرسال طلب إعادة التدريب. يجري تحديث حالة خط الأنابيب.'); void qc.invalidateQueries({ queryKey: getGetTrainingStatusQueryKey() }); void qc.invalidateQueries({ queryKey: getGetTradingDashboardQueryKey() }); }, onError: () => setMessage('تعذر بدء التدريب؛ راجع حالة الخدمة والضوابط.') }); };
  const t = training.data;
  return <div className="page-stack"><PageHeading eyebrow="تطوير النموذج · سجل الإصدارات" title="إعادة تدريب، بلا استعجال." detail="النموذج المرشح لا يحل محل البطل. الترقية تمر عبر تحقق، حواجز، وفترة مراقبة." action={<Tag tone="green"><ShieldCheck size={13} /> ترقية محروسة</Tag>} />
    <QueryState loading={training.isLoading} error={training.error} retry={() => void training.refetch()} label="حالة التدريب">{t && <>
      <div className="training-overview">
        <Panel className="pipeline-panel"><PanelTitle title="خط أنابيب التدريب" eyebrow="الحالة الراهنة" action={<Tag tone={t.status === 'running' ? 'gold' : t.status === 'failed' ? 'red' : 'neutral'}>{t.status}</Tag>} />
          <div className="pipeline-status"><div className="pipeline-glyph"><Cpu size={22} /></div><div><span>المرحلة الحالية</span><b>{t.stage || 'بانتظار التشغيل'}</b></div><div className="pipeline-progress-label"><b>{t.progress}%</b><span>اكتمال</span></div></div>
          <div className="progress-track large-track"><span style={{ width: `${t.progress}%` }} /></div>
          <div className="pipeline-steps"><div className={t.progress >= 15 ? 'done' : ''}><i>{t.progress >= 15 ? <Check size={12} /> : '01'}</i><span>تجهيز البيانات</span></div><div className={t.progress >= 40 ? 'done' : ''}><i>{t.progress >= 40 ? <Check size={12} /> : '02'}</i><span>تدريب المرشح</span></div><div className={t.progress >= 70 ? 'done' : ''}><i>{t.progress >= 70 ? <Check size={12} /> : '03'}</i><span>اختبار الحواجز</span></div><div className={t.status === 'promoted' ? 'done' : ''}><i>{t.status === 'promoted' ? <Check size={12} /> : '04'}</i><span>قرار الترقية</span></div></div>
          <div className="version-row"><div><span>النموذج البطل</span><b className="mono">{t.currentVersion}</b></div><ArrowDownLeft size={16} /><div><span>النموذج المرشح</span><b className="mono">{t.candidateVersion ?? 'لا يوجد مرشح'}</b></div></div>
        </Panel>
        <Panel className="retrain-panel"><div className="retrain-icon"><GitBranch size={18} /></div><div className="eyebrow">إطلاق دورة جديدة</div><h3>ابدأ من بيانات مضبوطة.</h3><form className="stack-fields" onSubmit={run}>
          <label className="field"><span>مجموعة الأدوات</span><select value={form.universe} onChange={e => setForm({ ...form, universe: e.target.value as RetrainInput['universe'] })}><option value="watchlist">قائمة المراقبة</option><option value="forex">الفوركس</option><option value="indices">المؤشرات</option><option value="stocks">الأسهم</option><option value="all">جميع الأدوات</option></select></label>
          <div className="field-pair"><label className="field"><span>الإطار</span><select value={form.timeframe} onChange={e => setForm({ ...form, timeframe: e.target.value as RetrainInput['timeframe'] })}>{['M1','M5','M15','H1','H4','D1'].map(x => <option key={x}>{x}</option>)}</select></label><label className="field"><span>تحقق · أيام</span><input type="number" min="30" max="730" value={form.validationWindowDays} onChange={e => setForm({ ...form, validationWindowDays: Number(e.target.value) })} /></label></div>
          {message && <div className={`form-notice ${start.isError ? 'notice-error' : ''}`}>{message}</div>}
          <button className="button button-primary full-button" disabled={start.isPending || t.status === 'blocked'}><LockKeyhole size={15} /> التدريب غير متاح حتى توفير بيانات وأوزان قابلة للتحقق</button>
        </form><DataCaption>لا توجد أوزان مشروع معتمدة؛ لن يُنشأ مرشح أو مقياس توضيحي.</DataCaption></Panel>
      </div>
      <div className="training-lower">
         <Panel><PanelTitle title="مقاييس المرشح والبطل" eyebrow="مقارنة الأداء" /><div className="metrics-compare"><div className="metric-labels"><span>شارب</span><span>أقصى تراجع</span><span>عامل الربح</span></div><div className="metric-col"><Tag>البطل</Tag><b>{nullableNumber(t.championMetrics?.sharpe)}</b><b>{nullableNumber(t.championMetrics?.maxDrawdown)}%</b><b>{nullableNumber(t.championMetrics?.profitFactor)}</b></div><div className="metric-col challenger"><Tag tone="gold">المرشح</Tag><b>{nullableNumber(t.challengerMetrics?.sharpe)}</b><b>{nullableNumber(t.challengerMetrics?.maxDrawdown)}%</b><b>{nullableNumber(t.challengerMetrics?.profitFactor)}</b></div></div><DataCaption>لن تظهر مقاييس حتى تتوفر نتائج تقييم فعلية.</DataCaption></Panel>
        <Panel><PanelTitle title="حواجز الترقية" eyebrow="لا استثناءات" /><div className="guardrail-list">{t.guardrails.length ? t.guardrails.map((guard, i) => <div key={`${guard}-${i}`}><ShieldCheck size={15} /><span>{guard}</span><Check size={14} className="guardrail-check" /></div>) : <EmptyState title="لا توجد حواجز مسجلة" detail="تحقق من إعدادات الخادم." />}</div></Panel>
      </div>
      <Panel className="history-panel"><PanelTitle title="تاريخ دورات التدريب" eyebrow="الأثر التشغيلي" /><ActivityList items={t.history ?? []} /></Panel>
    </>}</QueryState>
  </div>;
}

function CapitalMarketsPage() {
  const [search, setSearch] = useState('');
  const [submittedSearch, setSubmittedSearch] = useState('');
  const markets = useGetCapitalMarkets(
    { searchTerm: submittedSearch || undefined },
    { query: { queryKey: getGetCapitalMarketsQueryKey({ searchTerm: submittedSearch || undefined }), enabled: Boolean(submittedSearch), refetchInterval: 15_000, staleTime: 10_000 } },
  );
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSubmittedSearch(search.trim());
  };
  return <div className="page-stack">
    <PageHeading eyebrow="أسواق Capital.com" title="أسعار من المصدر، بلا بدائل." detail="ابحث في أسواق Capital.com مباشرة. الأسعار المعروضة ليست إشارات تداول ولا تفتح أوامر." action={<Tag tone="gold"><LockKeyhole size={13} /> قراءة فقط</Tag>} />
    <form className="universe-toolbar" onSubmit={submit}>
      <div className="search-wrap"><Search size={16} /><input type="search" placeholder="ابحث برمز السوق أو اسمه…" value={search} onChange={event => setSearch(event.target.value)} aria-label="بحث في أسواق Capital.com" /></div>
      <button className="button button-primary" type="submit" disabled={!search.trim() || markets.isFetching}><Search size={15} /> بحث حقيقي</button>
      <button className="icon-button" type="button" aria-label="تحديث الأسواق" onClick={() => void markets.refetch()} disabled={!submittedSearch || markets.isFetching}><RefreshCw size={16} /></button>
    </form>
    <QueryState loading={markets.isLoading && Boolean(submittedSearch)} error={markets.error} retry={() => void markets.refetch()} label="أسواق Capital.com">
      {markets.data ? <Panel className="universe-panel">
        <div className="panel-title"><div><div className="eyebrow">{markets.data.environment === 'live' ? 'حساب حي' : markets.data.environment === 'demo' ? 'حساب تجريبي' : 'مصدر غير مضبوط'}</div><h2>{markets.data.detail}</h2></div><span className="muted">آخر فحص {dateShort(markets.data.checkedAt)}</span></div>
        {markets.data.markets.length ? <div className="table-scroll"><table className="universe-table"><thead><tr><th>الأداة</th><th>Bid</th><th>Ask</th><th>التغير</th><th>الحالة</th><th>نوع السوق</th><th>آخر تحديث</th></tr></thead><tbody>{markets.data.markets.map(market => <tr key={market.epic}><td><b className="instrument-ticker">{market.epic}</b><small className="cell-sub">{market.name}</small></td><td className="mono">{nullableNumber(market.bid, 5)}</td><td className="mono">{nullableNumber(market.offer, 5)}</td><td className={`mono ${market.changePct == null ? '' : market.changePct >= 0 ? 'positive-text' : 'negative-text'}`}>{market.changePct == null ? '—' : `${market.changePct > 0 ? '+' : ''}${fmt(market.changePct)}%`}</td><td><Tag tone={market.marketStatus?.toUpperCase() === 'TRADEABLE' ? 'green' : 'neutral'}>{market.marketStatus ?? 'غير معروف'}</Tag></td><td>{market.instrumentType ?? '—'}</td><td>{dateShort(market.updatedAt)}</td></tr>)}</tbody></table></div> : <EmptyState title={markets.data.state === 'connected' ? 'لا توجد أدوات مطابقة' : 'بيانات السوق غير متاحة'} detail={markets.data.detail} />}
        <div className="panel-footer"><DataCaption>المصدر: Capital.com. لا توجد أسعار أو تغيّرات اصطناعية عند فشل المصدر.</DataCaption><span>{markets.data.markets.length} نتيجة</span></div>
      </Panel> : <Panel><EmptyState title="ابحث لعرض بيانات حقيقية" detail="أدخل رمزاً أو اسم سوق. يتطلب الاتصال إعداد Capital.com في أسرار الخدمة." /></Panel>}
    </QueryState>
  </div>;
}

function AssistantPage() {
  const send = useSendAssistantMessage();
  const connectors = useGetConnectorStatus();
  const market = useGetLiveMarket(
    { symbols: 'AAPL,NVDA,TSLA,SPY' },
    { query: { queryKey: getGetLiveMarketQueryKey({ symbols: 'AAPL,NVDA,TSLA,SPY' }), refetchInterval: 30_000, staleTime: 15_000 } },
  );
  const economic = useGetEconomicData({
    query: { queryKey: getGetEconomicDataQueryKey(), refetchInterval: 5 * 60_000, staleTime: 5 * 60_000 },
  });
  const fundamentals = useGetCompanyFundamentals(
    { symbols: 'AAPL,NVDA,TSLA,MSFT' },
    {
      query: {
        queryKey: getGetCompanyFundamentalsQueryKey({ symbols: 'AAPL,NVDA,TSLA,MSFT' }),
        refetchInterval: 15 * 60_000,
        staleTime: 15 * 60_000,
      },
    },
  );
  const training = useGetTrainingStatus();
  const health = useHealthCheck();
  const diagnostics = useGetSystemDiagnostics({
    query: {
      queryKey: getGetSystemDiagnosticsQueryKey(),
      refetchInterval: 60_000,
    },
  });
  const qc = useQueryClient();
  const [message, setMessage] = useState('');
  const [conversationId] = useState(() => crypto.randomUUID());
  const [context, setContext] = useState<ChatInputContext>('general');
  const [conversation, setConversation] = useState<Array<{ role: 'user' | 'assistant'; text: string; source?: string; suggestions?: string[] }>>([]);
  const [sendError, setSendError] = useState('');
  const localModel = connectors.data?.find(connector => connector.id === 'local-model');
  const localReady = localModel?.state === 'connected';
  const sendMessage = (text = message) => {
    if (!text.trim() || send.isPending || !localReady) return;
    const clean = text.trim();
    const payload = { conversationId, message: clean, context };
    setSendError('');
    setConversation(previous => [...previous, { role: 'user', text: clean }]);
    setMessage('');
    send.mutate({ data: payload }, {
      onSuccess: (reply) => {
        if (reply.source !== 'local_model') {
          setSendError('النموذج الخاص غير متاح لهذه المحادثة. لم يُستخدم أي نموذج بديل.');
          void qc.invalidateQueries({ queryKey: getGetConnectorStatusQueryKey() });
          return;
        }
        setConversation(previous => [...previous, { role: 'assistant', text: reply.reply, source: 'local_model', suggestions: reply.suggestions }]);
      },
      onError: () => setSendError('تعذر الوصول إلى Space الخاص بنموذج المشروع. لم يتم إنشاء رد بديل.'),
    });
  };
  const statusLabel = (state?: string) => state === 'connected' ? 'جاهز' : state === 'needs_credentials' ? 'يحتاج بيانات اعتماد' : state === 'blocked' ? 'يتعذر الوصول أو التحقق' : state === 'not_configured' ? 'إعدادات ناقصة' : 'غير معروف';
  const providerStateLabel = (state?: string, configured = false) => !configured ? 'غير مضبوط' : state === 'connected' ? 'متصل' : state === 'partial' ? 'بيانات جزئية' : 'غير متاح';
  const providerStateTone = (state?: string, configured = false) => !configured ? 'neutral' : state === 'connected' ? 'green' : state === 'partial' ? 'gold' : 'red';
  const freshnessLabel = (freshness: string) => freshness === 'fresh' ? 'حديث' : freshness === 'delayed' ? 'متأخر' : freshness === 'stale' ? 'قديم' : freshness === 'unavailable' ? 'غير متاح' : 'غير معروف';
  const modelTone = localReady ? 'green' : localModel?.state === 'blocked' ? 'red' : 'gold';
  const trainingData = training.data;
  const marketData = market.data;
  const smartSuggestions: Array<{ id: string; title: string; reason: string; action: string; href: string }> = [];
  if (market.isError) {
    smartSuggestions.push({ id: 'market-query', title: 'أعد فحص اتصال السوق', reason: 'تعذر تحميل نتيجة استعلام السوق.', action: 'فتح مراقبة السوق', href: '/universe' });
  } else if (marketData) {
    if (marketData.state !== 'connected' || marketData.errors.length > 0) {
      smartSuggestions.push({ id: 'market-provider', title: 'راجع حالة مزود السوق', reason: marketData.errors.length ? `أبلغ المصدر عن ${marketData.errors.length} خطأ.` : `حالة المصدر الحالية: ${marketData.state}.`, action: 'فتح مراقبة السوق', href: '/universe' });
    }
    const agedQuotes = marketData.quotes.filter(quote => quote.freshness !== 'fresh');
    if (agedQuotes.length > 0) {
      smartSuggestions.push({ id: 'market-freshness', title: 'تحقق من حداثة الأسعار قبل استخدامها', reason: `${agedQuotes.length} من ${marketData.quotes.length} لقطة ليست موسومة «حديثة».`, action: 'مراجعة لقطات السوق', href: '/universe' });
    }
    if (!marketData.quotes.length) {
      smartSuggestions.push({ id: 'market-empty', title: 'انتظر لقطة موثوقة من المزود', reason: 'لم تُرجع نتيجة السوق أي أسعار؛ لا توجد بيانات يعتمد عليها هنا.', action: 'مراجعة السوق', href: '/universe' });
    }
  }
  if (connectors.isError) {
    smartSuggestions.push({ id: 'connector-query', title: 'أعد فحص موصل النموذج', reason: 'تعذر قراءة حالة الموصل، لذلك لا يمكن التحقق من جاهزية المحادثة.', action: 'فتح الضوابط والربط', href: '/settings' });
  } else if (localModel && !localReady) {
    smartSuggestions.push({ id: 'connector-unavailable', title: 'راجع موصل نموذج المشروع', reason: `حالة الموصل المسجلة: ${statusLabel(localModel.state)}. لن يُستخدم نموذج بديل.`, action: 'فتح الضوابط والربط', href: '/settings' });
  } else if (!connectors.isLoading && !localModel) {
    smartSuggestions.push({ id: 'connector-missing', title: 'تحقق من تسجيل موصل النموذج', reason: 'لا يوجد موصل باسم local-model ضمن نتيجة الموصلات.', action: 'فتح الضوابط والربط', href: '/settings' });
  }
  if (training.isError) {
    smartSuggestions.push({ id: 'training-query', title: 'أعد فحص سجل التدريب', reason: 'تعذر تحميل حالة التدريب والمرشح.', action: 'فتح التدريب', href: '/training' });
  } else if (trainingData?.status === 'failed') {
    smartSuggestions.push({ id: 'training-failed', title: 'راجع مرحلة التدريب والحواجز', reason: `حالة خط الأنابيب المسجلة: ${trainingData.status}${trainingData.stage ? ` · ${trainingData.stage}` : ''}.`, action: 'فتح سجل التدريب', href: '/training' });
  } else if (trainingData && (trainingData.status === 'running' || trainingData.status === 'queued')) {
    smartSuggestions.push({ id: 'training-active', title: 'تابع دورة التدريب الحالية', reason: `الحالة ${trainingData.status} والتقدم المسجل ${trainingData.progress}%.`, action: 'متابعة التدريب', href: '/training' });
  } else if (trainingData?.candidateVersion) {
    smartSuggestions.push({ id: 'training-candidate', title: 'قارن المرشح بحواجز التقييم', reason: `يوجد مرشح مسجل (${trainingData.candidateVersion})؛ وجوده وحده لا يعني اجتياز التقييم أو الترقية.`, action: 'مراجعة مقارنة النماذج', href: '/training' });
  }
  if (diagnostics.isError) {
    smartSuggestions.push({ id: 'diagnostics-query', title: 'أعد تحميل تشخيصات الخادم', reason: 'تعذر تحميل ملخص أخطاء الخادم.', action: 'عرض لوحة التشخيص', href: '/assistant' });
  } else if (diagnostics.data && diagnostics.data.errorCount > 0) {
    smartSuggestions.push({ id: 'diagnostics-errors', title: 'افحص بيانات أخطاء الخادم', reason: `سجل الخادم ${diagnostics.data.errorCount} خطأ ضمن نافذة ${diagnostics.data.windowMinutes} دقيقة.`, action: 'عرض لوحة التشخيص', href: '/assistant' });
  }
  if (health.isError || (health.data && health.data.status !== 'ok')) {
    smartSuggestions.push({ id: 'health-status', title: 'تحقق من صحة الخدمة', reason: health.isError ? 'تعذر فحص نقطة صحة الخدمة.' : `أعادت الخدمة الحالة: ${health.data?.status}.`, action: 'فتح التشخيصات', href: '/assistant' });
  }
  const suggestionsHaveEvidence = !market.isLoading && !connectors.isLoading && !training.isLoading && !diagnostics.isLoading;
  return <div className="page-stack assistant-page">
    <PageHeading eyebrow="مِرصاد · غرفة التحكم الذكي" title="التحليل يبدأ من المصدر." detail="نموذج المشروع وحده للمحادثة؛ حالة الموصل والبيانات مرئية قبل طرح السؤال." action={<Tag tone="gold"><ShieldCheck size={13} /> فشل آمن · بلا بدائل</Tag>} />

    <section className="control-banner" data-testid="status-ai-control-room">
      <div className="control-banner-copy"><div className="control-overline"><span className={`health-dot ${connectors.isLoading ? 'attention' : localReady ? 'healthy' : 'offline'}`} /> حالة نموذج المشروع</div>
        <h2>{connectors.isLoading ? 'جار فحص جاهزية النموذج' : localReady ? 'نموذج المشروع متاح الآن' : connectors.isError ? 'تعذر فحص حالة النموذج' : localModel?.state === 'not_configured' ? 'إعدادات النموذج ناقصة' : 'تعذر الوصول إلى نموذج المشروع'}</h2>
        <p>{connectors.isError ? 'تعذر قراءة حالة الموصل. أعد الفحص قبل إرسال رسالة.' : localModel?.detail ?? 'لا تُرسل الرسائل إلى نموذج أساسي أو مزود مستضاف آخر؛ عند غياب النموذج تتوقف المحادثة دون إجابة بديلة.'}</p>
      </div>
      <div className="control-banner-side"><Tag tone={modelTone}>{connectors.isLoading ? 'جار الفحص' : localReady ? 'جاهز' : localModel ? statusLabel(localModel.state) : 'غير مسجل'}</Tag><button className="button button-outline button-small" onClick={() => { void connectors.refetch(); void health.refetch(); }} data-testid="button-refresh-model-status"><RefreshCw size={13} /> فحص الحالة</button></div>
      <div className="control-banner-foot"><span><Activity size={13} /> الخدمة: {health.isLoading ? 'جار الفحص' : health.isError ? 'تعذر الفحص' : health.data?.status === 'ok' ? 'تعمل' : health.data?.status ?? 'غير معروف'}</span><span><Cloud size={13} /> Hugging Face ZeroGPU مجاني</span><span><LockKeyhole size={13} /> قد ينام ومحدود الحصة</span></div>
    </section>

    <div className="assistant-diagnostics-grid">
      <Panel className="system-diagnostics-panel">
        <PanelTitle title="تشخيصات الخادم" eyebrow="بيانات أخطاء منقّاة" action={<button className="button button-outline button-small" onClick={() => void diagnostics.refetch()} disabled={diagnostics.isFetching} data-testid="button-refresh-system-diagnostics" aria-label="تحديث تشخيصات الخادم"><RefreshCw size={13} className={diagnostics.isFetching ? 'refreshing-icon' : ''} />{diagnostics.isFetching ? 'جار التحديث' : 'تحديث'}</button>} />
        {diagnostics.isLoading ? <div className="diagnostics-skeleton" role="status" data-testid="status-system-diagnostics-loading"><span /><span /><span /></div> : diagnostics.isError ? <div className="diagnostics-error" role="alert" data-testid="status-system-diagnostics-error"><CircleAlert size={17} /><div><b>تعذر تحميل تشخيصات الخادم</b><span>لا تتوفر نتيجة موثوقة الآن. أعد المحاولة يدوياً.</span></div><button className="button button-quiet button-small" onClick={() => void diagnostics.refetch()} data-testid="button-retry-system-diagnostics">إعادة المحاولة</button></div> : diagnostics.data ? <>
          <div className="diagnostics-summary" data-testid="status-system-diagnostics">
            <span className={`health-dot ${diagnostics.data.state === 'healthy' ? 'healthy' : 'attention'}`} />
            <b>{diagnostics.data.state === 'healthy' ? 'لا أخطاء مرصودة' : 'يتطلب مراجعة'}</b>
            <span className="diagnostics-window">آخر {diagnostics.data.windowMinutes} دقيقة</span>
            <strong className={diagnostics.data.errorCount > 0 ? 'diagnostics-count attention-text' : 'diagnostics-count'}>{diagnostics.data.errorCount}</strong>
            <small>أخطاء</small>
          </div>
          <div className="diagnostics-meta">
            <div><span>آخر خطأ</span><b data-testid="text-diagnostics-last-error">{diagnostics.data.lastErrorAt ? dateShort(diagnostics.data.lastErrorAt) : 'لا يوجد'}</b></div>
            <div><span>آخر فحص</span><b data-testid="text-diagnostics-checked-at">{dateShort(diagnostics.data.checkedAt)}</b></div>
          </div>
          {diagnostics.data.recentErrors.length > 0 ? <div className="diagnostics-events" role="list" aria-label="الأخطاء الأخيرة">
            {diagnostics.data.recentErrors.map(error => <div className="diagnostics-event" role="listitem" key={error.id} data-testid={`diagnostic-event-${error.id}`}>
              <Tag tone="red">{error.statusCode}</Tag><span className="diagnostics-method">{error.method}</span><code dir="ltr">{error.path}</code><time dateTime={error.occurredAt}>{dateShort(error.occurredAt)}</time>
            </div>)}
          </div> : <div className="diagnostics-empty" data-testid="status-diagnostics-empty"><ShieldCheck size={15} />لا توجد أخطاء مسجلة في النافذة المعروضة.</div>}
          <p className="diagnostics-retention" data-testid="text-diagnostics-retention">يحتفظ الخادم ببيانات وصفية منقّاة لأخطاء 5xx فقط، في ذاكرة العملية، لمدة لا تتجاوز 24 ساعة وبحد أقصى 100 حدث. لا تُحفظ المطالبات أو الأسرار. {diagnostics.data.retentionNote}</p>
        </> : <div className="diagnostics-empty" role="status" data-testid="status-diagnostics-unavailable">لا توجد نتيجة تشخيص موثوقة لعرضها.</div>}
      </Panel>

      <Panel className="smart-suggestions-panel">
        <PanelTitle title="خطوات مقترحة" eyebrow="اقتراحات تشغيلية وبحثية" action={<span className="suggestions-count" data-testid="text-smart-suggestions-count">{smartSuggestions.length} مقترح</span>} />
        <p className="suggestions-intro">اقتراحات حتمية مبنية على نتائج الاستعلامات الظاهرة؛ لا ترسل شيئاً إلى المحادثة.</p>
        {smartSuggestions.length ? <div className="smart-suggestion-list" data-testid="list-smart-suggestions">
          {smartSuggestions.map(item => <article className="smart-suggestion" key={item.id} data-testid={`smart-suggestion-${item.id}`}>
            <div className="suggestion-mark"><ListChecks size={15} /></div>
            <div className="smart-suggestion-copy"><b>{item.title}</b><span>{item.reason}</span><Link href={item.href} className="text-link" data-testid={`link-smart-suggestion-${item.id}`}>{item.action}<ChevronLeft size={13} /></Link></div>
          </article>)}
        </div> : suggestionsHaveEvidence ? <div className="suggestions-empty" role="status" data-testid="status-smart-suggestions-empty"><ShieldCheck size={17} /><span><b>لا توجد خطوة مشروطة حالياً</b><small>لم تُظهر النتائج الحالية حالة تستدعي اقتراحاً تشغيلياً إضافياً.</small></span></div> : <div className="suggestions-empty" role="status" data-testid="status-smart-suggestions-unavailable"><CircleAlert size={17} /><span><b>لا تتوفر بيانات موثوقة بعد</b><small>انتظر نتائج المصدر؛ لن نستنتج اقتراحات من بيانات مفقودة.</small></span></div>}
      </Panel>
    </div>

    <div className="assistant-control-grid">
      <Panel className="chat-panel assistant-chat-room">
        <div className="chat-top"><div className="assistant-avatar"><Sparkles size={18} /></div><div><b>محادثة مرصاد</b><span><i className={`health-dot ${localReady ? 'healthy' : 'offline'}`} />{localReady ? 'إرسال عبر endpoint نموذج المشروع فقط' : 'الإرسال معطل حتى يتصل النموذج'}</span></div><Tag tone="neutral">غير تنفيذي</Tag></div>
        <div className="chat-thread" data-testid="chat-thread">
          {!conversation.length && <div className="chat-welcome"><div className="welcome-orbit"><MessageSquareText size={23} /></div><div className="eyebrow">مساحة تحليل عربية</div><h2>{localReady ? 'ما الفرضية التي تريد فحصها؟' : 'لا يوجد نموذج متاح للمحادثة.'}</h2><p>{localReady ? 'اختر سياقاً واضحاً. الإجابة، إن وصلت، من نموذج المشروع الخاص فقط.' : connectors.isError ? 'تعذر فحص حالة الموصل؛ أعد المحاولة قبل الإرسال.' : 'عند تعذر Space لا ينتج النظام إجابة. لا يوجد fallback إلى نموذج آخر.'}</p>
            {!localReady && <div className="local-unavailable" data-testid="status-model-unavailable"><div><LockKeyhole size={15} /><b>{connectors.isLoading ? 'جار التحقق من الموصل' : localModel ? statusLabel(localModel.state) : 'لا يوجد موصل نموذج مسجل'}</b></div><span>يستخدم التطبيق موصل API للمحادثة. أدوات MCP في Replit تخص الوكيل ومساحة العمل ولا تستدعيها واجهة التطبيق المنشورة.</span><Link href="/settings" className="text-link">حالة الموصلات <ChevronLeft size={14} /></Link></div>}
            {localReady && <div className="suggestion-grid">{['لخّص المخاطر التي يجب مراجعتها قبل أي تنفيذ.','كيف أقارن المرشح بالنموذج البطل؟','ما حدود هذه البيانات قبل بناء فرضية؟'].map((suggestion, index) => <button key={suggestion} onClick={() => sendMessage(suggestion)} data-testid={`button-chat-prompt-${index}`}>{suggestion}<ChevronLeft size={14} /></button>)}</div>}</div>}
          {conversation.map((item, i) => <div key={`${i}-${item.role}`} className={`chat-message ${item.role}`} data-testid={`chat-message-${item.role}-${i}`}><div className="chat-bubble">{item.text}{item.role === 'assistant' && item.source && <div className="reply-source"><Sparkles size={12} />رد من نموذج المشروع · Hugging Face</div>}{item.role === 'assistant' && item.suggestions?.length ? <div className="reply-suggestions">{item.suggestions.map((s, index) => <button key={`${s}-${index}`} onClick={() => sendMessage(s)} data-testid={`button-reply-suggestion-${i}-${index}`}>{s}<ChevronLeft size={12} /></button>)}</div> : null}</div></div>)}
          {sendError && <div className="chat-error" role="alert" data-testid="status-chat-error"><CircleAlert size={15} />{sendError}</div>}
          {send.isPending && <div className="chat-message assistant" aria-label="جار انتظار رد النموذج"><div className="chat-bubble typing"><span /><span /><span /></div></div>}
        </div>
        <form className="chat-composer" onSubmit={e => { e.preventDefault(); sendMessage(); }}><div className="context-select"><span>السياق</span><select value={context} onChange={e => setContext(e.target.value as ChatInputContext)} aria-label="سياق المحادثة" data-testid="select-chat-context"><option value="general">عام</option><option value="risk">المخاطر</option><option value="training">التدريب</option><option value="backtest">الاختبارات</option><option value="instruments">الأدوات</option></select><ChevronDown size={12} /></div><input value={message} maxLength={4000} disabled={!localReady || send.isPending} onChange={e => setMessage(e.target.value)} placeholder={localReady ? 'اكتب سؤالاً تحليلياً…' : 'المحادثة متوقفة: نموذج المشروع غير متاح'} aria-label="رسالة للمساعد" data-testid="input-chat-message" /><button className="send-button" disabled={!localReady || !message.trim() || send.isPending} aria-label="إرسال الرسالة" data-testid="button-send-message"><Send size={16} /></button></form>
        <div className="chat-disclaimer">الردود ليست توصية استثمارية. فشل الطلب لا يستدعي نموذجاً أساسياً أو خدمة محادثة مستضافة.</div>
      </Panel>

      <div className="assistant-side-stack">
        <Panel className="market-quotes-panel"><PanelTitle title="لقطات السوق" eyebrow="مزود حقيقي · دون بدائل" action={<button className="icon-button tiny-button" aria-label="تحديث أسعار السوق" onClick={() => void market.refetch()} data-testid="button-refresh-live-quotes"><RefreshCw size={14} /></button>} />
          <QueryState loading={market.isLoading} error={market.error} retry={() => void market.refetch()} label="أسعار المزود">
            {marketData ? <><div className="market-provider-line"><Tag tone={marketData.state === 'connected' ? 'green' : marketData.state === 'unavailable' ? 'red' : 'neutral'}>{marketData.state === 'connected' ? 'متصل' : marketData.state === 'unavailable' ? 'غير متاح' : 'غير مضبوط'}</Tag><span>{marketData.provider || 'لم يحدد مزود'}</span></div>
              {marketData.quotes.length ? <div className="live-quote-list">{marketData.quotes.map(quote => <div className="live-quote-row" key={quote.symbol} data-testid={`quote-row-${quote.symbol}`}><div><b className="instrument-ticker">{quote.symbol}</b><small>{dateShort(quote.timestamp)} · {quote.freshness === 'fresh' ? 'حديث' : quote.freshness === 'delayed' ? 'متأخر' : 'قديم'}</small></div><div className="live-quote-price"><b className="mono">${fmt(quote.price, 2)}</b><span className={quote.changePct == null ? '' : quote.changePct >= 0 ? 'positive-text' : 'negative-text'}>{quote.changePct == null ? '—' : `${quote.changePct > 0 ? '+' : ''}${fmt(quote.changePct)}%`}</span></div></div>)}</div> : <EmptyState title={marketData.configured ? 'لا توجد أسعار من المزود' : 'مزود الأسعار غير مضبوط'} detail={marketData.errors[0] || 'لا توجد أسعار بديلة أو قيم محاكاة في هذا القسم.'} />}
              {marketData.errors.length > 0 && marketData.quotes.length > 0 && <div className="provider-error-note" data-testid="status-market-errors">تعذر جلب بعض الرموز من المزود. لم تُعرض لها قيم بديلة.</div>}
              <div className="quote-source-note" data-testid="text-market-source">{marketData.sourceNote || 'المصدر حسب موصل السوق المسجل'} <span>فُحصت: {dateShort(marketData.checkedAt)}</span></div>
              <div className="quote-caveat">هذه أسعار أسهم أمريكية من Finnhub عند توفره، وليست أسعار عقود الفروقات لدى Capital.com.</div>
            </> : null}
          </QueryState>
        </Panel>
        <Panel className="provider-data-panel" data-testid="panel-economic-data"><PanelTitle title="المؤشرات الاقتصادية" eyebrow="FRED · بيانات منشورة" action={<button className="icon-button tiny-button" aria-label="تحديث البيانات الاقتصادية" onClick={() => void economic.refetch()} data-testid="button-refresh-economic-data"><RefreshCw size={14} /></button>} />
          <QueryState loading={economic.isLoading} error={economic.error} retry={() => void economic.refetch()} label="المؤشرات الاقتصادية">
            {economic.data && <><div className="market-provider-line"><Tag tone={providerStateTone(economic.data.state, economic.data.configured)}>{providerStateLabel(economic.data.state, economic.data.configured)}</Tag><span>{economic.data.provider}</span></div>
              {economic.data.indicators.length ? <div className="provider-record-list">{economic.data.indicators.map(indicator => <div className="provider-record" key={indicator.seriesId} data-testid={`economic-record-${indicator.seriesId}`}>
                <div className="provider-record-head"><div><b>{indicator.label}</b><small>{indicator.seriesId} · {indicator.source}</small></div><div className="provider-record-value"><b>{indicator.value == null ? '—' : `${fmt(indicator.value, 2)} ${indicator.unit}`}</b><Tag tone={indicator.freshness === 'fresh' ? 'green' : indicator.freshness === 'delayed' ? 'gold' : indicator.freshness === 'stale' ? 'red' : 'neutral'}>{freshnessLabel(indicator.freshness)}</Tag></div></div>
                <div className="provider-record-meta"><span>تاريخ الرصد: {dateShort(indicator.observationDate)}</span><span>جُلب: {dateShort(indicator.retrievedAt)}</span></div>
                {indicator.error && <small className="provider-record-error">{indicator.error}</small>}
              </div>)}</div> : <EmptyState title={economic.data.configured ? 'لا توجد مؤشرات متاحة' : 'مصدر FRED غير مضبوط'} detail={economic.data.errors[0] || 'لم يُرجع المصدر سجلات اقتصادية.'} />}
              {economic.data.errors.length > 0 && economic.data.indicators.some(indicator => indicator.value != null) && <div className="provider-error-note">{economic.data.errors.join(' ')}</div>}
              <div className="quote-source-note"><span>{economic.data.sourceNote}</span><span>آخر فحص: {dateShort(economic.data.checkedAt)}</span></div>
            </>}
          </QueryState>
        </Panel>
        <Panel className="provider-data-panel" data-testid="panel-company-fundamentals"><PanelTitle title="أساسيات الشركات" eyebrow="FMP · بيانات مالية" action={<button className="icon-button tiny-button" aria-label="تحديث أساسيات الشركات" onClick={() => void fundamentals.refetch()} data-testid="button-refresh-company-fundamentals"><RefreshCw size={14} /></button>} />
          <QueryState loading={fundamentals.isLoading} error={fundamentals.error} retry={() => void fundamentals.refetch()} label="أساسيات الشركات">
            {fundamentals.data && <><div className="market-provider-line"><Tag tone={providerStateTone(fundamentals.data.state, fundamentals.data.configured)}>{providerStateLabel(fundamentals.data.state, fundamentals.data.configured)}</Tag><span>{fundamentals.data.provider}</span></div>
              {fundamentals.data.fundamentals.length ? <div className="company-fundamental-list">{fundamentals.data.fundamentals.map(company => <article className="company-fundamental" key={company.symbol} data-testid={`fundamental-record-${company.symbol}`}>
                <div className="company-fundamental-head"><div><b className="instrument-ticker">{company.symbol}</b><span>{company.companyName || 'اسم الشركة غير متاح'}</span><small>{[company.sector, company.industry].filter(Boolean).join(' · ') || 'تصنيف النشاط غير متاح'}</small></div><Tag tone={company.freshness === 'fresh' ? 'green' : company.freshness === 'delayed' ? 'gold' : company.freshness === 'stale' ? 'red' : 'neutral'}>{freshnessLabel(company.freshness)}</Tag></div>
                <div className="fundamental-metrics"><span>القيمة السوقية<b>{company.marketCap == null ? '—' : `${fmt(company.marketCap, 0)} ${company.currency || ''}`}</b></span><span>P/E<b>{nullableNumber(company.peRatio)}</b></span><span>P/B<b>{nullableNumber(company.pbRatio)}</b></span><span>P/S<b>{nullableNumber(company.priceToSalesRatio)}</b></span><span>ROE<b>{company.returnOnEquity == null ? '—' : fmt(company.returnOnEquity)}</b></span></div>
                <div className="provider-record-meta"><span>تاريخ البيانات: {dateShort(company.asOf)}</span><span>المصدر: {company.source} · جُلب: {dateShort(company.retrievedAt)}</span></div>
              </article>)}</div> : <EmptyState title={fundamentals.data.configured ? 'لا توجد أساسيات متاحة' : 'مصدر FMP غير مضبوط'} detail={fundamentals.data.errors[0] || 'لم يُرجع المصدر بيانات الشركات المطلوبة.'} />}
              {fundamentals.data.errors.length > 0 && fundamentals.data.fundamentals.length > 0 && <div className="provider-error-note">{fundamentals.data.errors.join(' ')}</div>}
              <div className="quote-source-note"><span>{fundamentals.data.sourceNote}</span><span>آخر فحص: {dateShort(fundamentals.data.checkedAt)}</span></div>
            </>}
          </QueryState>
        </Panel>
        <Panel className="training-intel-panel"><PanelTitle title="التدريب والتقييم" eyebrow="سجل النموذج" action={<Link href="/training" className="text-link">التفاصيل <ChevronLeft size={13} /></Link>} />
          <QueryState loading={training.isLoading} error={training.error} retry={() => void training.refetch()} label="حالة التدريب">{trainingData && <div data-testid="status-training-current">
            <div className="training-mini-head"><Tag tone={trainingData.status === 'failed' || trainingData.status === 'rejected' ? 'red' : trainingData.status === 'running' || trainingData.status === 'queued' ? 'gold' : 'neutral'}>{trainingData.status}</Tag><span>{trainingData.stage || 'لا توجد مرحلة نشطة'}</span></div>
            <div className="mini-progress"><span style={{ width: `${Math.min(100, Math.max(0, trainingData.progress))}%` }} /></div>
            <div className="training-version-pair"><div><small>البطل</small><b className="mono">{trainingData.currentVersion}</b></div><div><small>المرشح</small><b className="mono">{trainingData.candidateVersion || 'غير موجود'}</b></div></div>
            <div className="metric-compare"><span>المقياس</span><b>البطل</b><b>المرشح</b><span>Sharpe</span><b className="mono">{nullableNumber(trainingData.championMetrics?.sharpe)}</b><b className="mono">{nullableNumber(trainingData.challengerMetrics?.sharpe)}</b><span>أقصى تراجع</span><b className="mono">{nullableNumber(trainingData.championMetrics?.maxDrawdown)}%</b><b className="mono">{nullableNumber(trainingData.challengerMetrics?.maxDrawdown)}%</b><span>عامل الربح</span><b className="mono">{nullableNumber(trainingData.championMetrics?.profitFactor)}</b><b className="mono">{nullableNumber(trainingData.challengerMetrics?.profitFactor)}</b></div>
            <div className="training-stamps"><span>بدأ: {dateShort(trainingData.lastStartedAt)}</span><span>اكتمل: {dateShort(trainingData.lastCompletedAt)}</span><span>ظلّ: {trainingData.shadowMinutes} دقيقة</span></div>
            {trainingData.guardrails.length > 0 && <div className="guardrail-list"><b>حواجز التقييم</b>{trainingData.guardrails.slice(0, 3).map((rule, i) => <span key={`${rule}-${i}`}><Check size={12} />{rule}</span>)}</div>}
          </div>}</QueryState>
        </Panel>
      </div>
    </div>

    <div className="assistant-lower-grid">
      <Panel className="assistant-connectors-panel"><PanelTitle title="حالة الموصلات المسجلة" eyebrow="شفافية الاعتماد" action={<button className="button button-quiet button-small" onClick={() => void connectors.refetch()} data-testid="button-refresh-connectors"><RefreshCw size={13} /> تحديث</button>} />
        <QueryState loading={connectors.isLoading} error={connectors.error} retry={() => void connectors.refetch()} label="الموصلات">{connectors.data?.length ? <div className="assistant-connector-list">{connectors.data.map(connector => <div className="assistant-connector" key={connector.id} data-testid={`connector-status-${connector.id}`}><div className="connector-icon">{connector.id.toLowerCase().includes('model') || connector.id.toLowerCase().includes('hugging') || connector.id.toLowerCase().includes('ai') ? <Sparkles size={16} /> : <Database size={16} />}</div><div><b>{connector.name}</b><small>{connector.id === 'local-model' ? connector.detail : connector.requiredForLive ? 'مطلوب للجاهزية الحية' : 'تكامل اختياري'}</small></div><Tag tone={connector.state === 'connected' ? 'green' : connector.state === 'blocked' ? 'red' : 'neutral'}>{statusLabel(connector.state)}</Tag></div>)}</div> : <EmptyState title="لا توجد موصلات مسجلة" detail="لم يُرجع الخادم حالات تكامل؛ لن نفترض اتصال Drive أو MCP." />}</QueryState>
        <div className="mcp-note"><Code2 size={15} /><span><b>حدود MCP:</b> التطبيق المنشور يستخدم موصلات API وOAuth. أدوات Replit MCP للوكيل ومساحة العمل فقط، وليست موصلات مباشرة لواجهة التطبيق.</span></div>
      </Panel>
      <Panel className="safe-reference-panel"><PanelTitle title="مرجع آمن للكود" eyebrow="جرد وحدات · ليس ملفات حية" />
        <p>هذا جرد وظيفي وأمثلة قصيرة غير حساسة. لا تعرض هذه الشاشة ملفات المشروع كاملة؛ لا توجد مصادقة مستخدم في التطبيق.</p>
        <div className="module-inventory"><div><Code2 size={14} /><span><b>محادثة النموذج</b><small>طلب API إلى نموذج المشروع؛ لا مسار احتياطي</small></span><code>sendAssistantMessage()</code></div><div><Activity size={14} /><span><b>سوق حي</b><small>بيانات مزود حقيقي مع حالة المصدر والطابع الزمني</small></span><code>useGetLiveMarket()</code></div><div><ShieldCheck size={14} /><span><b>حواجز النظام</b><small>تعطيل الإرسال عند فشل تحقق النموذج</small></span><code>source === 'local_model'</code></div></div>
        <div className="snippet-label">مثال توضيحي غير مأخوذ من ملف حي</div><pre dir="ltr"><code>{`if (reply.source !== 'local_model') {
  stopAndReportUnavailable();
}`}</code></pre>
      </Panel>
    </div>
  </div>;
}

function SettingsPage() {
  const settings = useGetTradingSettings();
  const readiness = useGetLiveReadiness();
  const connectors = useGetConnectorStatus();
  const backups = useGetTradingBackups();
  const createBackup = useCreateTradingBackup();
  const update = useUpdateTradingSettings();
  const qc = useQueryClient();
  const [draft, setDraft] = useState<TradingSettingsUpdate | null>(null);
  const [feedback, setFeedback] = useState('');
  const base = settings.data;
  const current = base ? { ...base, ...draft } : null;
  const patch = (values: TradingSettingsUpdate) => setDraft(previous => ({ ...(previous ?? {}), ...values }));
  const save = () => { if (!draft || !Object.keys(draft).length) return; setFeedback(''); update.mutate({ data: draft }, { onSuccess: () => { setDraft(null); setFeedback('تم حفظ الضوابط.'); void qc.invalidateQueries({ queryKey: getGetTradingSettingsQueryKey() }); void qc.invalidateQueries({ queryKey: getGetLiveReadinessQueryKey() }); }, onError: () => setFeedback('تعذر حفظ الإعدادات. راجع الحدود ثم أعد المحاولة.') }); };
  const saveDriveSnapshot = () => createBackup.mutate(undefined, {
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: getGetTradingBackupsQueryKey() });
      void qc.invalidateQueries({ queryKey: getGetTradingActivitiesQueryKey() });
    },
  });
  const retryAll = () => { void settings.refetch(); void readiness.refetch(); void connectors.refetch(); };
  return <div className="page-stack"><PageHeading eyebrow="إعدادات التشغيل · الحوكمة" title="ضوابط قبل السرعة." detail="إدارة حدود المخاطر والتكاملات وقراءة صريحة لمتطلبات الجاهزية الحية." action={<button className="button button-primary" disabled={!draft || !Object.keys(draft).length || update.isPending} onClick={save}><Check size={15} />{update.isPending ? 'جار الحفظ…' : 'حفظ التغييرات'}</button>} />
    {feedback && <div className={`form-notice global-notice ${update.isError ? 'notice-error' : ''}`}>{feedback}</div>}
    <div className="settings-grid">
      <div className="settings-main">
        <Panel><PanelTitle title="حدود الحساب والمخاطر" eyebrow="إعدادات قابلة للتعديل" action={<Tag tone="gold">وضع ورقي</Tag>} />
          <QueryState loading={settings.isLoading} error={settings.error} retry={() => void settings.refetch()} label="إعدادات المخاطر">{current && <div className="settings-fields">
            <label className="field"><span>الرصيد الابتدائي · USD</span><input type="number" min="100" step="100" value={current.startingBalance} onChange={e => patch({ startingBalance: Number(e.target.value) })} /></label>
            <label className="field"><span>المخاطرة لكل صفقة · %</span><input type="number" min=".1" max="1" step=".1" value={current.maxRiskPerTradePct} onChange={e => patch({ maxRiskPerTradePct: Number(e.target.value) })} /></label>
            <label className="field"><span>قاطع الخسارة اليومية · %</span><input type="number" min=".5" max="3" step=".1" value={current.dailyCircuitBreakerPct} onChange={e => patch({ dailyCircuitBreakerPct: Number(e.target.value) })} /></label>
            <label className="field"><span>الحد الأقصى للتراجع · %</span><input type="number" min="1" max="10" step=".5" value={current.maxDrawdownPct} onChange={e => patch({ maxDrawdownPct: Number(e.target.value) })} /></label>
            <label className="field"><span>مراكز متزامنة كحد أقصى</span><input type="number" min="1" max="10" value={current.maxConcurrentPositions} onChange={e => patch({ maxConcurrentPositions: Number(e.target.value) })} /></label>
            <label className="field"><span>رموز مفتوحة كحد أقصى</span><input type="number" min="1" max="2" value={current.maxOpenSymbols} onChange={e => patch({ maxOpenSymbols: Number(e.target.value) })} /></label>
            <label className="field"><span>خسائر قبل فترة التهدئة</span><input type="number" min="1" max="10" value={current.cooldownAfterLosses} onChange={e => patch({ cooldownAfterLosses: Number(e.target.value) })} /></label>
            <div className="setting-divider" /><div className="toggle-list">
              <ToggleRow title="حواجز السوق" detail="منع الدخول أثناء ظروف السوق غير الملائمة." checked={current.useMarketShields} onChange={v => patch({ useMarketShields: v })} />
              <ToggleRow title="مرشح الأخبار الاقتصادية" detail="تجنب النوافذ عالية التأثير وفق تكامل الأخبار." checked={current.useMacroNewsFilter} onChange={v => patch({ useMacroNewsFilter: v })} />
              <ToggleRow title="السماح بإعادة التدريب الآلية" detail="السماح للمنظومة بجدولة تدريب مرشحين جدد." checked={current.allowAutoRetraining} onChange={v => patch({ allowAutoRetraining: v })} />
            </div>
          </div>}</QueryState>
        </Panel>
        <Panel className="connector-panel"><PanelTitle title="التكاملات ومصادر البيانات" eyebrow="حالة الربط" action={<button className="icon-button tiny-button" aria-label="تحديث التكاملات" onClick={() => void connectors.refetch()}><RefreshCw size={14} /></button>} />
          <QueryState loading={connectors.isLoading} error={connectors.error} retry={() => void connectors.refetch()} label="التكاملات">{connectors.data?.length ? <div className="connector-list">{connectors.data.map(connector => <div className="connector-row" key={connector.id}><div className="connector-icon">{connector.id.toLowerCase().includes('data') ? <Database size={17} /> : connector.id.toLowerCase().includes('ai') ? <Sparkles size={17} /> : <Cloud size={17} />}</div><div className="connector-copy"><b>{connector.name}</b><span>{connector.detail}</span></div><div className="connector-tags">{connector.requiredForLive && <Tag tone="gold">مطلوب للحي</Tag>}<Tag tone={connector.state === 'connected' ? 'green' : connector.state === 'blocked' ? 'red' : 'neutral'}>{connector.state === 'connected' ? 'متصل' : connector.state === 'needs_credentials' ? 'يحتاج بيانات اعتماد' : connector.state === 'blocked' ? 'محظور' : 'غير مضبوط'}</Tag></div></div>)}</div> : <EmptyState title="لا توجد تكاملات مسجلة" detail="لم يقدّم الخادم أي حالة تكامل." />}</QueryState>
          <div className="connector-foot"><LockKeyhole size={14} /> بيانات الاعتماد الإنتاجية لا تظهر داخل واجهة المستخدم.</div>
        </Panel>
        <Panel className="backup-panel">
          <PanelTitle
            title="نسخ الإصدارات إلى Google Drive"
            eyebrow="حفظ قابل للمراجعة"
            action={<button className="button button-outline" disabled={createBackup.isPending} onClick={saveDriveSnapshot}><Cloud size={14} />{createBackup.isPending ? 'جار الحفظ…' : 'حفظ نسخة جديدة'}</button>}
          />
          <p className="backup-description">يحفظ ملفات المصدر المختارة وحالة التداول الورقي في مجلد إصدارات المشروع. لا يتضمن أسرار البيئة أو المحادثات أو الملفات المرفقة.</p>
          {createBackup.isError && <div className="form-notice notice-error">تعذر الحفظ في Drive. تحقق من الاتصال ثم أعد المحاولة.</div>}
          {createBackup.isSuccess && <div className="form-notice">تم حفظ الإصدار {createBackup.data.version} في Google Drive.</div>}
          <QueryState loading={backups.isLoading} error={backups.error} retry={() => void backups.refetch()} label="نسخ Drive">
            {backups.data?.length ? (
              <div className="backup-list">
                {backups.data.slice(0, 8).map(snapshot => (
                  <a className="backup-row" href={snapshot.webViewLink} target="_blank" rel="noreferrer" key={snapshot.id}>
                    <span className="backup-mark"><Cloud size={15} /></span>
                    <span><b>{snapshot.version}</b><small>{dateShort(snapshot.createdAt)} · {snapshot.name}</small></span>
                    <ChevronLeft size={15} />
                  </a>
                ))}
              </div>
            ) : <EmptyState title="لا توجد نسخ محفوظة بعد" detail="احفظ أول إصدار ليُنشأ مجلد المشروع وتسلسل نسخه في Drive." />}
          </QueryState>
        </Panel>
      </div>
      <div className="settings-aside">
        <Panel className="live-gate"><div className="gate-top"><div className="gate-lock"><LockKeyhole size={20} /></div><Tag tone="red">مقفل دائماً</Tag></div><div className="eyebrow">جاهزية التداول الحي</div><h2>الحساب لا ينفّذ أوامر حقيقية.</h2><p>هذه المنظومة مهيأة للتداول الورقي والبحث فقط. حتى عند اكتمال المتطلبات، لا يوجد مفتاح في هذه الشاشة لفتح التنفيذ الحي.</p>
          <QueryState loading={readiness.isLoading} error={readiness.error} retry={() => void readiness.refetch()} label="تقييم الجاهزية">{readiness.data && <div className="readiness-check"><div><span>التقييم</span><b>{readiness.data.ready ? 'مستوفٍ' : 'غير مستوفٍ'}</b></div><div><span>التنفيذ الحي</span><b className="locked-state"><LockKeyhole size={12} />{readiness.data.liveTradingEnabled ? 'مقفل في الواجهة' : 'مقفل'}</b></div><div><span>الوضع</span><b>{readiness.data.mode === 'demo' ? 'تجريبي' : 'حي مقفل'}</b></div>{readiness.data.blockers.length > 0 && <div className="blocker-list"><b>المتطلبات غير المكتملة</b>{readiness.data.blockers.map((blocker, i) => <span key={`${blocker}-${i}`}><CircleAlert size={13} />{blocker}</span>)}</div>}</div>}</QueryState>
          <button className="button button-locked full-button" disabled><LockKeyhole size={15} /> التداول الحي غير متاح</button><DataCaption>حالة الجاهزية لا تفتح التداول الحي تلقائياً.</DataCaption>
        </Panel>
        <Panel className="settings-health"><PanelTitle title="سلامة النظام" eyebrow="مراجعة الاتصال" action={<button className="icon-button tiny-button" onClick={retryAll} aria-label="تحديث الحالة"><RefreshCw size={14} /></button>} /><StatusRow label="إعدادات المخاطر" query={settings} /><StatusRow label="جاهزية التنفيذ" query={readiness} /><StatusRow label="التكاملات" query={connectors} /><div className="status-row ssh-status"><span>SSH · وصول المضيف</span><b><i className="health-dot attention" />غير مضبوط · غير متحقق</b><small>لا يوجد عميل أو إعداد SSH أو نقطة فحص صحية في هذا المستودع؛ لم يُجرَ أي تحقق.</small></div><div className="health-foot"><Zap size={13} /> تتحدث البيانات عند إعادة الفحص.</div></Panel>
        <div className="settings-caution"><ShieldCheck size={16} /><span>غيّر حدوداً واحدة في كل مرة. راجع أثرها في سجل النشاط بعد الحفظ.</span></div>
      </div>
    </div>
  </div>;
}
function ToggleRow({ title, detail, checked, onChange }: { title: string; detail: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return <label className="toggle-row"><span><b>{title}</b><small>{detail}</small></span><input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} /><i className="toggle-track"><b /></i></label>;
}
function StatusRow({ label, query }: { label: string; query: { isLoading: boolean; isError: boolean } }) {
  return <div className="status-row"><span>{label}</span><b>{query.isLoading ? 'جار الفحص' : query.isError ? 'تعذر الفحص' : 'تم الفحص'}<i className={`health-dot ${query.isLoading ? 'attention' : query.isError ? 'offline' : 'healthy'}`} /></b></div>;
}
function NotFound() { return <div className="not-found"><div className="empty-glyph"><Search size={22} /></div><div className="eyebrow">404 · غير موجود</div><h1>هذه الصفحة ليست ضمن النطاق.</h1><p>ارجع إلى لوحة العمليات لمتابعة عملك.</p><Link href="/" className="button button-primary">العودة للوحة <ChevronLeft size={14} /></Link></div>; }

export default App;
