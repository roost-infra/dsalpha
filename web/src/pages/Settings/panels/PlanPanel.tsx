import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useUser } from '@/hooks/useUser';
import { getRoostBilling, type RoostBilling } from '@/lib/roostBilling';
import { ConsoleLink } from '../components/ConsoleLink';
import { SettingRow, SettingsGroup } from '../components/SettingsLayout';
import { useSettingCopy } from '../components/useSettingCopy';
import { SETTINGS } from '../sections';

/** Plan & usage: the shared Roost wallet, with the console one step away. */
export function PlanPanel() {
  const { t, i18n } = useTranslation();
  const copy = useSettingCopy();
  const { user } = useUser();
  const plan = user?.plan_display_name;
  const zh = i18n.language.startsWith('zh');
  const [billing, setBilling] = useState<RoostBilling | null>(null);

  useEffect(() => {
    let alive = true;
    getRoostBilling()
      .then((next) => { if (alive) setBilling(next); })
      .catch(() => { if (alive) setBilling(null); });
    return () => { alive = false; };
  }, []);

  const remaining = billing?.remaining_credits;
  const limit = billing?.credit_limit;
  const walletText =
    remaining == null
      ? (zh ? '暂时无法读取' : 'Unavailable')
      : `${remaining.toLocaleString()} credits${limit == null ? '' : ` / ${limit.toLocaleString()}`}`;

  return (
    <SettingsGroup>
      <SettingRow
        {...copy(SETTINGS.plan)}
        description={plan ? t('settings.planUsage.current', { plan }) : t(SETTINGS.plan.descKey)}
      >
        <ConsoleLink path="plans">{t('settings.planUsage.change')}</ConsoleLink>
      </SettingRow>
      <SettingRow
        label={zh ? '共享 Roost 钱包' : 'Shared Roost wallet'}
        description={zh
          ? '与 dslpha、market、causal-memory 共用同一个 Roost 组织钱包。'
          : 'Shared with dslpha, market and causal-memory through one Roost organization.'}
      >
        <span className="text-[0.8125rem] tabular-nums" style={{ color: 'var(--color-text-secondary)' }}>
          {walletText}
        </span>
      </SettingRow>
      <SettingRow {...copy(SETTINGS.usage)}>
        <ConsoleLink path="usage">{t('settings.planUsage.viewUsage')}</ConsoleLink>
      </SettingRow>
      <SettingRow {...copy(SETTINGS.billing)}>
        <ConsoleLink path="billing">{t('settings.planUsage.manageBilling')}</ConsoleLink>
      </SettingRow>
    </SettingsGroup>
  );
}
