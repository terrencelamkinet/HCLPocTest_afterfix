/**
 * ProjectGate — wraps routes that require Projects Module to be enabled.
 * Redirects to dashboard if projects module is off.
 */
import { useState, useEffect } from 'react';
import { Navigate } from 'react-router-dom';
import { apiClient } from '../lib/api';

export default function ProjectGate({ children }: { children: React.ReactNode }) {
  const [checked, setChecked] = useState(false);
  const [enabled, setEnabled] = useState(true);

  useEffect(() => {
    apiClient.get('/api/v1/crm/module-settings')
      .then((list: any) => {
        const settings = Array.isArray(list) ? list : [];
        const proj = settings.find((m: any) => m.module_key === 'projects');
        setEnabled(proj ? proj.enabled === true : true);
      })
      .catch(() => {})
      .finally(() => setChecked(true));
  }, []);

  if (!checked) return null;
  if (!enabled) return <Navigate to="/dashboard" replace />;
  return <>{children}</>;
}
