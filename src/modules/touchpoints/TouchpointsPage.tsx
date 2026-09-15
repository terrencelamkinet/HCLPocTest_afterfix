import { useState, useEffect } from 'react'
import GenericListPage from '../GenericListPage'
import touchpointConfig from './config'
import { apiClient } from '../../lib/api'

export default function TouchpointsPage() {
  const [contacts, setContacts] = useState<{ id: string; name: string }[]>([])
  const [companies, setCompanies] = useState<{ id: string; name: string }[]>([])

  useEffect(() => {
    Promise.all([
      // 2026-09-11: CRM list endpoints take limit/offset — page_size 係靜默被忽略，
      // 所以舊 page_size=500 實際只回 50 個 contact，picker 搵唔到其餘 170+ 個
      //（用戶：「還是不能搜尋」）。跟 backend crm.py list_contacts/list_companies 用 limit。
      apiClient.get<{ items: { id: string; name: string }[] }>('/api/v1/crm/contacts?limit=1000').then(r => setContacts(r.items || [])).catch(() => {}),
      apiClient.get<{ items: { id: string; name: string }[] }>('/api/v1/crm/companies?limit=1000').then(r => setCompanies(r.items || [])).catch(() => {}),
    ])
  }, [])

  return (
    <GenericListPage
      config={touchpointConfig}
      extraData={{ contacts, companies }}
    />
  )
}
