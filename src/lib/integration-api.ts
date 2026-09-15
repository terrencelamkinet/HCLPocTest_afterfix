/**
 * Integration API — per-user, per-tenant.
 * Every call carries the JWT via the apiClient wrapper.
 */
import { apiClient } from './api';

export interface IntegrationRecord {
  id: string;
  tenant_id: string;
  user_id: string;
  provider: string;
  provider_display: string;
  status: 'disconnected' | 'connecting' | 'active' | 'error';
  config: Record<string, unknown>;
  metadata_: Record<string, unknown>;
  last_sync_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface OAuthStartResponse {
  state: string;
  oauth_url: string;
  provider: string;
}

export async function fetchIntegrations(): Promise<IntegrationRecord[]> {
  return apiClient.get('/api/v1/integrations');
}

export async function getIntegration(id: string): Promise<IntegrationRecord> {
  return apiClient.get(`/api/v1/integrations/${id}`);
}

export async function startOAuth(provider: string): Promise<OAuthStartResponse> {
  return apiClient.post('/api/v1/integrations/oauth/start', { provider, origin: window.location.origin });
}

export async function completeOAuth(code: string, state: string): Promise<IntegrationRecord> {
  return apiClient.post('/api/v1/integrations/oauth/callback', { code, state });
}

export async function disconnectIntegration(id: string): Promise<void> {
  return apiClient.delete(`/api/v1/integrations/${id}`);
}

export async function createIntegration(data: {
  provider: string;
  provider_display: string;
  status?: string;
  config: Record<string, unknown>;
  metadata_?: Record<string, unknown>;
}): Promise<IntegrationRecord> {
  return apiClient.post('/api/v1/integrations', data);
}

export interface GoogleCalendarInfo {
  id: string;
  summary: string;
  primary: boolean;
  access_role: string;
}

export async function fetchGoogleCalendars(): Promise<GoogleCalendarInfo[]> {
  return apiClient.get('/api/v1/integrations/google-calendar/calendars');
}

export async function saveGoogleCalendarSetting(calendarIds: string[], calendarNames: Record<string, string>): Promise<IntegrationRecord> {
  return apiClient.put('/api/v1/integrations/google-calendar/settings', {
    calendar_ids: calendarIds,
    calendar_names: calendarNames,
  });
}

/** Force an immediate calendar sync (bypasses the 15-min interval). */
export async function syncIntegrationNow(integrationId: string): Promise<{ status: string; stats: Record<string, number> }> {
  return apiClient.post(`/api/v1/integrations/${integrationId}/sync`);
}
