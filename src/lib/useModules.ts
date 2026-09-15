/**
 * Module settings hook — fetches tenant module enable/disable state.
 * Re-fetches on 'modules-changed' custom event (dispatched by Settings page after save).
 */
import { useState, useEffect, useCallback } from 'react';
import { apiClient } from './api';

export interface ModuleSetting {
  module_key: string;
  enabled: boolean;
}

export function useModuleSettings(): Record<string, boolean> {
  const [modules, setModules] = useState<Record<string, boolean>>({});

  const fetchModules = useCallback(async () => {
    try {
      const list: ModuleSetting[] = await apiClient.get('/api/v1/crm/module-settings');
      const map: Record<string, boolean> = {};
      (list || []).forEach(m => { map[m.module_key] = m.enabled; });
      setModules(map);
    } catch {}
  }, []);

  useEffect(() => {
    fetchModules();
    const handler = () => fetchModules();
    window.addEventListener('modules-changed', handler);
    return () => window.removeEventListener('modules-changed', handler);
  }, [fetchModules]);

  return modules;
}
