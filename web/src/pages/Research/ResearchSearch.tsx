import { useState, type FormEvent } from 'react';
import { Search } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export function ResearchSearch({ initialSymbol = '' }: { initialSymbol?: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [value, setValue] = useState(initialSymbol);
  const [invalid, setInvalid] = useState(false);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const symbol = value.trim().toUpperCase() || 'NVDA';
    if (!/^[A-Z0-9][A-Z0-9.-]{0,11}$/.test(symbol)) {
      setInvalid(true);
      return;
    }
    void navigate(`/research/${encodeURIComponent(symbol)}`);
  }

  return (
    <form onSubmit={submit} className="flex max-w-lg flex-wrap gap-2" role="search" aria-label={t('research.title')}>
      <Input
        type="search"
        name="symbol"
        aria-label={t('research.ticker')}
        placeholder={t('research.tickerPlaceholder')}
        value={value}
        onChange={(event) => { setValue(event.target.value); setInvalid(false); }}
        aria-invalid={invalid || undefined}
        className="min-w-0 flex-1"
      />
      <Button type="submit" className="shrink-0">
        <Search aria-hidden="true" /> {t('research.title')}
      </Button>
      {invalid && <p className="basis-full text-sm text-destructive" role="alert">{t('research.invalidTicker')}</p>}
    </form>
  );
}
