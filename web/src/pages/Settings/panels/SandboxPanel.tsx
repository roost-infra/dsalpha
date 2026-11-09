import { useCallback, useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '@/api/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { SettingRow, SettingsGroup } from '../components/SettingsLayout';

interface SandboxCredential {
  kind: string;
  configured: boolean;
  masked_key: string | null;
  base_url: string | null;
  updated_at: string | null;
  deployment_available: boolean;
}

const PROVIDER_LABELS: Record<string, string> = { daytona: 'Daytona' };

function errorMessage(error: unknown): string {
  const e = error as { response?: { data?: { detail?: unknown } }; message?: string };
  const detail = e?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  return e?.message ?? 'Request failed';
}

/**
 * Sandbox: which account a new cloud computer runs on. The deployment's key is
 * the default; a user may save their own, which then applies to computers they
 * create from now on (existing machines keep the account they were built on).
 */
export function SandboxPanel() {
  const { t } = useTranslation();
  const keyId = useId();
  const baseUrlId = useId();
  const [providers, setProviders] = useState<SandboxCredential[] | null>(null);
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ providers: SandboxCredential[] }>(
        '/api/v1/users/me/sandbox-credentials',
      );
      setProviders(data.providers ?? []);
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async (kind: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.put(`/api/v1/users/me/sandbox-credentials/${kind}`, {
        api_key: apiKey.trim(),
        base_url: baseUrl.trim() || null,
      });
      setApiKey('');
      setBaseUrl('');
      setNotice(t('settings.sandbox.saved'));
      await load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (kind: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.delete(`/api/v1/users/me/sandbox-credentials/${kind}`);
      setNotice(t('settings.sandbox.removed'));
      await load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <SettingsGroup
        title={t('settings.sandbox.title')}
        description={t('settings.sandbox.description')}
      >
        {providers === null ? (
          <SettingRow label={t('common.loading')}>
            <span />
          </SettingRow>
        ) : (
          providers.map((provider) => (
            <SettingRow
              key={provider.kind}
              label={PROVIDER_LABELS[provider.kind] ?? provider.kind}
              description={
                provider.configured
                  ? t('settings.sandbox.yourKey', { key: provider.masked_key ?? '****' })
                  : provider.deployment_available
                    ? t('settings.sandbox.platformProvided')
                    : t('settings.sandbox.deploymentUnavailable')
              }
              wide
            >
              <div className="flex w-full flex-col gap-2 md:flex-row md:items-center">
                <Input
                  id={keyId}
                  type="password"
                  autoComplete="off"
                  aria-label={t('settings.sandbox.apiKeyLabel')}
                  placeholder={t('settings.sandbox.apiKeyPlaceholder')}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
                <Input
                  id={baseUrlId}
                  type="url"
                  aria-label={t('settings.sandbox.baseUrlLabel')}
                  placeholder={t('settings.sandbox.baseUrlPlaceholder')}
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                />
                <Button
                  size="sm"
                  disabled={busy || !apiKey.trim()}
                  onClick={() => void save(provider.kind)}
                >
                  {busy ? t('settings.sandbox.saving') : t('settings.sandbox.save')}
                </Button>
                {provider.configured && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => void remove(provider.kind)}
                  >
                    {busy ? t('settings.sandbox.removing') : t('settings.sandbox.remove')}
                  </Button>
                )}
              </div>
            </SettingRow>
          ))
        )}
      </SettingsGroup>

      <SettingsGroup>
        <SettingRow
          label={t('settings.sandbox.ssh')}
          description={t('settings.sandbox.sshDesc')}
        />
        <SettingRow
          label={t('settings.sandbox.notesTitle')}
          description={t('settings.sandbox.notes')}
        />
      </SettingsGroup>

      {(error || notice) && (
        <p role="status" className={error ? 'text-sm text-red-500' : 'text-sm'}>
          {error ?? notice}
        </p>
      )}
    </>
  );
}
