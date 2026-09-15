/**
 * SalesGate — wraps routes that require Sales Module to be enabled.
 * Redirects to dashboard if sales module is off.
 */
import { useState, useEffect } from 'react';
import { Navigate } from 'react-router-dom';
import { apiClient } from '../lib/api';

export default function SalesGate({ children }: { children: React.ReactNode }) {
  const [checked, setChecked] = useState(false);
  const [enabled, setEnabled] = useState(true);

  useEffect(() => {
    apiClient.get('/api/v1/crm/module-settings')
      .then((list: any) => {
        const settings = Array.isArray(list) ? list : [];
        const sales = settings.find((m: any) => m.module_key === 'sales');
        setEnabled(sales ? sales.enabled === true : true);
      })
      .catch(() => {})
      .finally(() => setChecked(true));
  }, []);

  if (!checked) return null;
  if (!enabled) return <Navigate to="/dashboard" replace />;
  return <>{children}</>;
}
