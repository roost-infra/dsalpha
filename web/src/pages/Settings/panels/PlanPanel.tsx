import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useUser } from '@/hooks/useUser';
import { getRoostBilling, type RoostBilling } from '@/lib/roostBilling';
import { getAccessToken } from '@/lib/authToken';
import { PLAN_URL } from '@/config/supportLinks';
import { ConsoleLink } from '../components/ConsoleLink';

type BillingCycle = 'monthly' | 'annual';

/** The subset of Console's order shape this page draws. */
interface CheckoutOrder {
  id: string;
  sku: string;
  status: string;
  amount_cents: number;
  credits: number;
  qr_url?: string;
  pay_url?: string;
}

interface CheckoutState {
  sku: string;
  order?: CheckoutOrder;
  error?: string;
}

interface PlanCard {
  code: string;
  name: string;
  monthly: number;
  credits: number;
  features: { zh: string[]; en: string[] };
  popular?: boolean;
}

/** DSAlpha's four public tiers. Kept in the client (like the console's cards)
 *  so the page can render before the wallet read finishes; the wallet and the
 *  current plan still come from Console. */
const PLANS: PlanCard[] = [
  {
    code: 'dsalpha_free',
    name: 'Free',
    monthly: 0,
    credits: 1000,
    features: {
      zh: ['1 个工作区', '1 个定时任务', '基础模型 tier 0', '1 小时沙箱'],
      en: ['1 workspace', '1 scheduled task', 'Base models (tier 0)', '1 sandbox hour'],
    },
  },
  {
    code: 'dsalpha_plus',
    name: 'Plus',
    monthly: 149,
    credits: 18000,
    features: {
      zh: ['10 个工作区', '5 个定时任务', '进阶模型 tier 1', '10 小时沙箱'],
      en: ['10 workspaces', '5 scheduled tasks', 'Advanced models (tier 1)', '10 sandbox hours'],
    },
  },
  {
    code: 'dsalpha_pro',
    name: 'Pro',
    monthly: 299,
    credits: 38000,
    popular: true,
    features: {
      zh: ['20 个工作区', '20 个定时任务', '全部前沿模型 tier 2', '30 小时沙箱', '支持 BYOK'],
      en: ['20 workspaces', '20 scheduled tasks', 'Frontier models (tier 2)', '30 sandbox hours', 'BYOK included'],
    },
  },
  {
    code: 'dsalpha_max',
    name: 'Max',
    monthly: 749,
    credits: 100000,
    features: {
      zh: ['工作区 / 定时任务不限量', '最高模型档位 tier 3', '80 小时沙箱', '支持 BYOK', '优先支持'],
      en: ['Unlimited workspaces / tasks', 'Highest model tier (tier 3)', '80 sandbox hours', 'BYOK included', 'Priority support'],
    },
  },
];

const PLAN_ORDER = ['dsalpha_free', 'dsalpha_plus', 'dsalpha_pro', 'dsalpha_max'];

function planName(code?: string | null): string {
  const found = PLANS.find((p) => p.code === code);
  return found?.name ?? (code ? code.replace('dsalpha_', '') : 'Free');
}

function money(cents: number): string {
  return `¥${(cents / 100).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`;
}

function annualPrice(monthlyCents: number): number {
  return Math.round(monthlyCents * 12 * 0.85);
}

/** Plan & usage, laid out like the public DSAlpha pricing page: a billing
 *  switch, four tier cards, then the shared Roost wallet and the two console
 *  shortcuts (usage, invoices). Checkout stays in Console, where the order,
 *  trial and annual discount are priced server-side. */
export function PlanPanel() {
  const { i18n } = useTranslation();
  const { user } = useUser();
  const zh = i18n.language.startsWith('zh');
  const [billing, setBilling] = useState<RoostBilling | null>(null);
  const [cycle, setCycle] = useState<BillingCycle>('monthly');
  const [checkout, setCheckout] = useState<CheckoutState | null>(null);
  const [paying, setPaying] = useState<string | null>(null);

  const refreshBilling = async () => {
    try { setBilling(await getRoostBilling()); } catch { /* keep the old view */ }
  };

  useEffect(() => {
    let alive = true;
    getRoostBilling()
      .then((next) => { if (alive) setBilling(next); })
      .catch(() => { if (alive) setBilling(null); });
    return () => { alive = false; };
  }, []);

  // Poll the order Console created. A trial is already fulfilled when the
  // POST returns; a paid order flips to fulfilled on the payment callback.
  useEffect(() => {
    if (!checkout?.order || checkout.order.status === 'fulfilled') return;
    const id = checkout.order.id;
    let alive = true;
    const tick = async () => {
      try {
        const token = await getAccessToken();
        if (!token) return;
        const res = await fetch(`/console-api/v1/billing/orders/${id}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) return;
        const body = await res.json() as { order?: CheckoutOrder };
        if (!alive || !body.order) return;
        if (body.order.status === 'fulfilled') {
          setCheckout((cur) => cur ? { ...cur, order: body.order } : cur);
          await refreshBilling();
          window.setTimeout(() => window.location.reload(), 900);
        }
      } catch { /* one poll may fail; the interval retries */ }
    };
    void tick();
    const timer = window.setInterval(tick, 3000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [checkout?.order?.id, checkout?.order?.status]);

  const startCheckout = async (sku: string) => {
    if (paying) return;
    setPaying(sku);
    setCheckout({ sku });
    try {
      const token = await getAccessToken();
      if (!token) {
        setCheckout({ sku, error: zh ? '请先登录后再订阅。' : 'Sign in before subscribing.' });
        return;
      }
      const res = await fetch('/console-api/v1/billing/orders', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ sku }),
      });
      const body = await res.json().catch(() => null) as { order?: CheckoutOrder; error?: { message?: string } } | null;
      if (!res.ok || !body?.order) {
        setCheckout({ sku, error: body?.error?.message ?? (zh ? '下单失败，请重试。' : 'Could not create the order.') });
        return;
      }
      if (body.order.status === 'fulfilled') {
        await refreshBilling();
        setCheckout({ sku, order: body.order });
        window.setTimeout(() => window.location.reload(), 1200);
      } else {
        setCheckout({ sku, order: body.order });
      }
    } catch {
      setCheckout({ sku, error: zh ? '网络错误，请重试。' : 'Network error. Try again.' });
    } finally {
      setPaying(null);
    }
  };

  const current = billing?.plan ?? user?.plan_display_name ?? 'dsalpha_free';
  const currentIndex = Math.max(0, PLAN_ORDER.indexOf(current));
  const wallet = billing?.remaining_credits;
  const limit = billing?.credit_limit;
  const used = billing?.used_credits;
  const plansUrl = PLAN_URL ?? 'https://www.roostbots.com/console/#plans';

  return (
    <div className="plan-page">
      <div className="plan-page__head">
        <div>
          <p className="plan-page__eyebrow">{zh ? '套餐方案' : 'PLANS'}</p>
          <h2 className="plan-page__title">{zh ? '选择适合你的 DSAlpha 套餐' : 'Choose your DSAlpha plan'}</h2>
          <p className="plan-page__sub">
            {zh
              ? '7 天免费试用，首月 5 折，年付 85 折。套餐额度按月发放，模型和沙箱共用。'
              : '7-day free trial, 50% off the first month, 15% off annual. One monthly allowance covers models and sandboxes.'}
          </p>
        </div>
        <div className="plan-toggle" role="group" aria-label={zh ? '计费周期' : 'Billing cycle'}>
          <button
            type="button"
            className={cycle === 'monthly' ? 'is-active' : ''}
            onClick={() => setCycle('monthly')}
          >
            {zh ? '月付' : 'Monthly'}
          </button>
          <button
            type="button"
            className={cycle === 'annual' ? 'is-active' : ''}
            onClick={() => setCycle('annual')}
          >
            {zh ? '年付' : 'Annual'} <span>{zh ? '省 15%' : 'save 15%'}</span>
          </button>
        </div>
      </div>

      <div className="plan-page__grid">
        {PLANS.map((plan, index) => {
          const isCurrent = current === plan.code;
          const isDowngrade = index < currentIndex;
          const monthlyCents = plan.monthly * 100;
          const amount = cycle === 'annual' ? annualPrice(monthlyCents) : monthlyCents;
          const perMonth = cycle === 'annual' ? Math.round(amount / 12) : monthlyCents;
          const monthlySku = `plan_${plan.code}_30d`;
          const annualSku = `plan_${plan.code}_365d`;
          const trialSku = `trial_${plan.code}_7d`;
          return (
            <article
              key={plan.code}
              className={`plan-card-ui ${plan.popular ? 'is-popular' : ''} ${isCurrent ? 'is-current' : ''}`}
            >
              {plan.popular && <span className="plan-card-ui__badge">{zh ? '最受欢迎' : 'Most popular'}</span>}
              <div className="plan-card-ui__head">
                <h3>{plan.name}</h3>
                {isCurrent && <span className="plan-card-ui__current">{zh ? '当前套餐' : 'Current'}</span>}
              </div>
              <div className="plan-card-ui__price">
                <strong>{money(amount)}</strong>
                <span>{cycle === 'annual' ? (zh ? '/年' : '/yr') : (zh ? '/月' : '/mo')}</span>
              </div>
              <p className="plan-card-ui__note">
                {plan.monthly === 0
                  ? (zh ? '永久免费' : 'Free forever')
                  : cycle === 'annual'
                    ? (zh ? `折合 ${money(perMonth)}/月` : `${money(perMonth)}/mo billed yearly`)
                    : (zh ? `首月 ${money(monthlyCents / 2)}` : `${money(monthlyCents / 2)} first month`)}
              </p>
              <p className="plan-card-ui__credits">
                {plan.credits.toLocaleString()} credits / {zh ? '月' : 'mo'}
              </p>
              <ul className="plan-card-ui__features">
                {(zh ? plan.features.zh : plan.features.en).map((feature) => (
                  <li key={feature}>{feature}</li>
                ))}
              </ul>
              {isCurrent ? (
                <a className="plan-card-ui__cta" href={plansUrl} target="_blank" rel="noreferrer">
                  {zh ? '管理套餐' : 'Manage plan'}
                </a>
              ) : plan.monthly === 0 ? (
                <span className="plan-card-ui__cta is-muted">{zh ? '免费使用' : 'Use free'}</span>
              ) : (
                <>
                  <button
                    type="button"
                    className={`plan-card-ui__cta ${plan.popular ? 'is-primary' : ''}`}
                    disabled={paying === (cycle === 'annual' ? annualSku : monthlySku)}
                    onClick={() => void startCheckout(cycle === 'annual' ? annualSku : monthlySku)}
                  >
                    {paying === (cycle === 'annual' ? annualSku : monthlySku)
                      ? (zh ? '创建订单…' : 'Creating order…')
                      : `${zh ? '立即订阅' : 'Subscribe'} · ${cycle === 'annual' ? money(amount) : money(amount)}`}
                  </button>
                  {plan.monthly > 0 && (
                    <button
                      type="button"
                      className="plan-card-ui__trial"
                      disabled={paying === trialSku}
                      onClick={() => void startCheckout(trialSku)}
                    >
                      {paying === trialSku
                        ? (zh ? '开通中…' : 'Starting…')
                        : (zh ? '先试 7 天' : 'Try 7 days')}
                    </button>
                  )}
                </>
              )}
            </article>
          );
        })}
      </div>

      <div className="plan-page__wallet">
        <div>
          <h3>{zh ? '共享 Roost 钱包' : 'Shared Roost wallet'}</h3>
          <p>
            {zh
              ? '与 dslpha、market、causal-memory 共用同一个组织钱包。套餐额度用完后，从余额继续扣。'
              : 'Shared with dslpha, market and causal-memory. Overage draws from this balance.'}
          </p>
        </div>
        <div className="plan-page__wallet-value">
          <strong>{wallet == null ? '—' : wallet.toLocaleString()}</strong>
          <span>{limit == null ? (zh ? 'credits' : 'credits') : `/ ${limit.toLocaleString()} credits`}</span>
          {used != null && <small>{zh ? '本月已用' : 'Used'} {used.toLocaleString()}</small>}
        </div>
      </div>

      <div className="plan-page__links">
        <ConsoleLink path="usage">{zh ? '查看用量' : 'View usage'}</ConsoleLink>
        <ConsoleLink path="billing">{zh ? '管理账单' : 'Manage billing'}</ConsoleLink>
        <span className="plan-page__hint">
          {zh ? `当前套餐：${planName(current)}` : `Current plan: ${planName(current)}`}
        </span>
      </div>

      {checkout && (
        <CheckoutDialog
          checkout={checkout}
          zh={zh}
          onClose={() => setCheckout(null)}
        />
      )}
    </div>
  );
}

function CheckoutDialog({ checkout, zh, onClose }: { checkout: CheckoutState; zh: boolean; onClose: () => void }) {
  const order = checkout.order;
  const paid = order?.status === 'fulfilled';
  return (
    <div className="plan-checkout" role="dialog" aria-modal="true" aria-label={zh ? '支付' : 'Payment'}>
      <div className="plan-checkout__panel">
        <button type="button" className="plan-checkout__close" onClick={onClose} aria-label={zh ? '关闭' : 'Close'}>×</button>
        <h3>{paid ? (zh ? '已开通' : 'Activated') : (zh ? '扫码支付' : 'Scan to pay')}</h3>
        {checkout.error ? (
          <p className="plan-checkout__error">{checkout.error}</p>
        ) : paid ? (
          <p>{zh ? '套餐已生效，页面即将刷新。' : 'Your plan is active. Reloading…'}</p>
        ) : order ? (
          <>
            <p className="plan-checkout__amount">{money(order.amount_cents)}</p>
            {order.qr_url ? (
              <img className="plan-checkout__qr" src={order.qr_url} alt={zh ? '支付二维码' : 'Payment QR code'} />
            ) : (
              <p>{zh ? '正在生成支付二维码…' : 'Preparing the payment QR code…'}</p>
            )}
            {order.pay_url && (
              <a className="plan-checkout__pay" href={order.pay_url} target="_blank" rel="noreferrer">
                {zh ? '打开支付页面' : 'Open payment page'}
              </a>
            )}
            <p className="plan-checkout__hint">
              {zh ? '支付完成后会自动开通，无需手动刷新。' : 'Activates automatically after payment.'}
            </p>
          </>
        ) : (
          <p>{zh ? '正在创建订单…' : 'Creating order…'}</p>
        )}
      </div>
    </div>
  );
}
