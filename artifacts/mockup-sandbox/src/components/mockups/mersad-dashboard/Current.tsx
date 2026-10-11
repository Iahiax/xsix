import type * as React from 'react';
import { type ReactNode } from 'react';
import { Activity, BarChart3, ChevronLeft, CircleAlert, Database, Gauge, Layers3, LockKeyhole, RefreshCw, Radio, Shield, ShieldCheck, TrendingDown } from 'lucide-react';
import './_group.css';
type ActivityType = { id: string; severity: string; title: string; createdAt: string; detail: string };
type DashboardStub = { dailyPnlPct: number | null; dailyLossLimitPct: number | null; openPositions: number; dataSource: string; updatedAt: string; modelVersion: string; riskState: string; systemHealth: string; trainingProgress: number | null };
type PositionStub = { id: string; epic: string; name: string; direction: string; entryPrice: number | null; currentPrice: number | null; size: number | null; profitLoss: number | null; currency: string | null };
type AccountStub = { state: string; positions: PositionStub[]; checkedAt: string; detail: string; balance?: number | null; currency?: string | null; profitLoss?: number | null };
const sample: DashboardStub = { dailyPnlPct: null, dailyLossLimitPct: null, openPositions: 0, dataSource: 'unavailable', updatedAt: '', modelVersion: '—', riskState: 'guarded', systemHealth: 'attention', trainingProgress: null };
const stub = <T,>(data: T) => ({ data, isLoading: false, error: null, isError: false, refetch: () => Promise.resolve({}) });
const useGetTradingDashboard = () => stub(sample);
const useGetCapitalAccount = () => stub<AccountStub>({ state: 'not_configured', positions: [], checkedAt: '', detail: 'اتصال Capital.com غير مضبوط.' });
const useGetTradingActivities = () => stub<ActivityType[]>([]);
const useHealthCheck = () => stub({ status: 'غير متحقق' });
function Link({ href, children, className }: { href: string; children: ReactNode; className?: string }) { return <a href={href} className={className}>{children}</a>; }
const fmt = (value: number, digits = 2) => new Intl.NumberFormat('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
const moneyCurrency = (value: number | null | undefined, currency?: string | null) => {
  if (value == null) return '—';
  const code = currency && /^[A-Z]{3}$/.test(currency) ? currency : 'USD';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: code, maximumFractionDigits: 2 }).format(value);
};
const dateShort = (value?: string | null) => value ? new Date(value).toLocaleString('ar', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—';
const sourceLabel = (source?: string) => source === 'capital_live' ? 'حساب Capital.com الحي' : source === 'capital_demo' ? 'حساب Capital.com التجريبي' : 'غير متاح';
const nullableNumber = (value: number | null | undefined, digits = 2) => value == null ? '—' : fmt(value, digits);
function PageHeading({ eyebrow, title, detail, action }: { eyebrow: string; title: string; detail: string; action?: ReactNode }) {
  return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{detail}</p></div>{action && <div className="heading-action">{action}</div>}</div>;
}
function Panel({ children, className = '' }: { children: ReactNode; className?: string }) { return <section className={`panel ${className}`}>{children}</section>; }
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
    : Math.min(Math.abs(d.dailyPnlPct) / d.dailyLossLimitPct * 100, 100);
  return (
    <div className="page-stack">
      <PageHeading
        eyebrow="غرفة العمليات"
        title="صباح التداول، مشغّل."
        detail="ملخص مباشر لحساب Capital.com عند نجاح الاتصال. الواجهة للقراءة فقط ولا ترسل أوامر."
        action={<button className="button button-outline" onClick={refresh}><RefreshCw size={15} /> تحديث اللوحة</button>}
      />
      <QueryState loading={dashboard.isLoading} error={dashboard.error} retry={refresh} label="لوحة التداول">
        {d ? (
          <>
            <div className="hero-strip">
              <div className="hero-intro">
                <div className="hero-kicker"><span className={`health-dot ${accountData?.state === 'connected' ? 'healthy' : 'attention'}`} /> {sourceLabel(d.dataSource)} <span className="hero-date">آخر تحقق {dateShort(accountData?.checkedAt ?? d.updatedAt)}</span></div>
                <div className="hero-equity">{moneyCurrency(accountData?.balance, accountData?.currency)}<span>رصيد الحساب من Capital.com</span></div>
                <div className="hero-sub">قراءة فقط — لن تُرسل أوامر أو تُغيّر المراكز</div>
              </div>
              <div className="hero-performance">
                <div className="hero-perf-label">الربح / الخسارة حسب حساب الوسيط</div>
                <div className={`hero-pnl ${(accountData?.profitLoss ?? 0) >= 0 ? 'positive' : 'negative'}`}>{accountData?.profitLoss == null ? '—' : `${accountData.profitLoss >= 0 ? '+' : ''}${moneyCurrency(accountData.profitLoss, accountData.currency)}`}</div>
                <div className="hero-pnl-percent">نسبة اليوم: {nullableNumber(d.dailyPnlPct)} <span>لا تتوفر نسبة موثقة</span></div>
              </div>
              <div className="hero-meta">
                <Tag tone={d.dataSource === 'unavailable' ? 'red' : 'green'}>{d.dataSource === 'unavailable' ? 'غير متصل' : 'اتصال مؤكد'}</Tag>
                <div className="hero-meta-row"><span>النمط</span><b>قراءة فقط</b></div>
                <div className="hero-meta-row"><span>المصدر</span><b>{sourceLabel(d.dataSource)}</b></div>
                <div className="hero-meta-row"><span>إصدار النموذج</span><b className="mono">{d.modelVersion}</b></div>
                <div className="hero-meta-row"><span>التداول الحقيقي</span><b className="locked-state"><LockKeyhole size={12} /> مقفل</b></div>
              </div>
            </div>
            <div className="stats-grid">
              <Stat label="مراكز Capital.com المفتوحة" value={d.openPositions} foot={<span className="muted">قراءة مباشرة من الوسيط</span>} icon={Layers3} />
              <Stat label="معدل الفوز" value="—" foot={<span className="muted">لا يوجد سجل أداء موثّق</span>} tone="sage" icon={BarChart3} />
              <Stat label="أقصى تراجع" value="—" foot={<span className="muted">لا تُحسب مقاييس دون بيانات تاريخية</span>} tone="amber" icon={TrendingDown} />
              <Stat label="أدوات الوسيط" value="—" foot={<span className="muted">تظهر في مراقبة السوق عند الاتصال</span>} icon={Radio} />
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
                   <div className="risk-scale"><span>غير محسوب</span><span>حد الخسارة غير مضبوط</span></div>
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
        <span className="footer-sep" />أرقام اللوحة محاكاة ما لم يذكر مصدر البيانات خلاف ذلك.
      </div>
    </div>
  );
}
