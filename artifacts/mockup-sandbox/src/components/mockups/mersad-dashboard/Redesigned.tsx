import { useState } from 'react';
import { Activity, ArrowDownLeft, BarChart3, ChevronLeft, CircleAlert, Clock3, Database, Gauge, Layers3, LockKeyhole, RefreshCw, ShieldCheck, TrendingDown } from 'lucide-react';
import './Redesigned.css';

export function Redesigned() {
  const [checked, setChecked] = useState(false);
  return <main className="md-root" dir="rtl">
    <header className="md-top">
      <div className="md-brand"><span className="md-mark"><i /><i /><i /></span><div><b>مرصاد</b><small>INTELLIGENCE TERMINAL</small></div></div>
      <div className="md-context"><span>غرفة العمليات</span><ChevronLeft size={14} /><b>ملخص الحساب</b></div>
      <div className="md-readonly"><i /> قراءة فقط <span /> لا تُرسل أوامر</div>
    </header>
    <section className="md-intro">
      <div><div className="md-eyebrow">مرصاد / لوحة العمليات <span>01—06</span></div><h1>صورة الحساب،<br /><em>كما هي.</em></h1><p>مراجعة موثّقة للحساب والمخاطر والنشاط. مرصاد للقراءة والتحليل فقط.</p></div>
      <button className="md-refresh" onClick={() => setChecked(true)}><RefreshCw size={15} />{checked ? 'تم طلب التحديث' : 'تحديث اللوحة'}</button>
    </section>
    <section className="md-equity">
      <div className="md-equity-main"><div className="md-source"><span className="md-dot muted" /> حساب Capital.com <span className="md-divider" /> <span className="md-unknown">غير مضبوط</span></div><strong>—<small>رصيد الحساب</small></strong><div className="md-footnote"><Clock3 size={13} /> لم يُتحقق من الحساب بعد</div></div>
      <div className="md-pnl"><small>الربح / الخسارة حسب الوسيط</small><b>—</b><span>لا توجد قراءة متاحة</span></div>
      <div className="md-safety"><span className="md-lock"><LockKeyhole size={14} /> تنفيذ حي مقفل</span><div><small>المصدر</small><b>غير متاح</b></div><div><small>النموذج</small><b>—</b></div><div><small>حالة المخاطر</small><b>تتطلب مراجعة</b></div></div>
    </section>
    <section className="md-stats">
      <article><div><span>مراكز مفتوحة</span><Layers3 size={16} /></div><b>—</b><small>بانتظار بيانات الوسيط</small></article>
      <article><div><span>معدل الفوز</span><BarChart3 size={16} /></div><b>—</b><small>لا تتوفر قراءة موثّقة</small></article>
      <article><div><span>أقصى تراجع</span><TrendingDown size={16} /></div><b>—</b><small>لا تتوفر قراءة موثّقة</small></article>
      <article><div><span>أدوات متتبعة</span><Gauge size={16} /></div><b>—</b><small>لا تتوفر قراءة موثّقة</small></article>
    </section>
    <section className="md-workspace">
      <article className="md-panel md-positions">
        <div className="md-panel-head"><div><small>من Capital.com</small><h2>المراكز المفتوحة</h2></div><span className="md-text-link">عرض السوق <ChevronLeft size={14} /></span></div>
        <div className="md-table-head"><span>الأداة</span><span>الاتجاه</span><span>سعر الدخول</span><span>السعر الحالي</span><span>الحجم</span><span>الربح / الخسارة</span></div>
        <div className="md-empty"><span><Database size={17} /></span><b>حساب الوسيط غير متصل</b><small>لم يُرجع Capital.com بيانات المراكز.</small></div>
      </article>
      <article className="md-panel md-risk">
        <div className="md-panel-head"><div><small>حدود الحساب</small><h2>مراقبة المخاطر</h2></div><ShieldCheck size={17} /></div>
        <div className="md-risk-meter"><div><span>استهلاك حد الخسارة اليومية</span><b>—</b></div><div className="md-track"><i /></div><small>لا يمكن الحساب دون نسبة وحدّ موثّقين</small></div>
        <div className="md-risk-lock"><ShieldCheck size={17} /><div><b>التداول للقراءة فقط</b><small>لا توجد أوامر مفعّلة في التطبيق</small></div><span>محمي</span></div>
        <div className="md-health"><span><i className="md-dot muted" /> صحة النظام</span><b>يتطلب انتباهاً</b></div>
      </article>
      <article className="md-panel md-activity">
        <div className="md-panel-head"><div><small>أحداث النظام</small><h2>سجل النشاط</h2></div><Activity size={17} /></div>
        <div className="md-empty compact"><span><CircleAlert size={16} /></span><b>لا توجد أحداث متاحة</b><small>ستظهر هنا التحديثات الموثّقة.</small></div>
      </article>
      <article className="md-gate">
        <div className="md-gate-icon"><LockKeyhole size={17} /></div><div><small>حدود التنفيذ</small><b>لا تُرسل أوامر.</b><p>الحساب للقراءة فقط. إعدادات الاتصال والجاهزية في الضوابط.</p></div><ArrowDownLeft size={17} />
      </article>
    </section>
    <footer className="md-footer"><span><i className="md-dot muted" /> الاتصال غير متحقق</span><span>مصدر كل قيمة موضح؛ لا تُستبدل البيانات غير المتاحة بتقديرات.</span><span>مرصاد · 2025</span></footer>
  </main>;
}
