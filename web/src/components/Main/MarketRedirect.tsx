import { Navigate, useLocation } from 'react-router';

/** Keep symbol, timeframe, workspace/thread and returnTo in legacy /market links. */
export function MarketRedirect() {
  const { search, hash } = useLocation();
  return <Navigate to={{ pathname: '/p/market', search, hash }} replace />;
}
