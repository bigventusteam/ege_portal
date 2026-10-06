import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, hataGoster } from '../api/client'
import { strings } from '../strings'
import { blobIndir, jsonBlobOlustur } from '../lib/download'
import type { LicenseDocumentResponse, SubscriptionResponse } from '../types'

function durumMetni(status: string, periodEnd: string): string {
  if (status === 'cancelled') return strings.abonelikler.durumIptal
  if (new Date(periodEnd) < new Date()) return strings.abonelikler.durumSuresiDolmus
  return strings.abonelikler.durumAktif
}

export function Subscriptions() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['subscriptions'],
    queryFn: () => api.get<SubscriptionResponse[]>('/api/v1/subscriptions'),
  })
  const [indirilenId, setIndirilenId] = useState<string | null>(null)
  const [hata, setHata] = useState<string | null>(null)

  async function lisansIndir(subscriptionId: number, licenseId: string) {
    setHata(null)
    setIndirilenId(licenseId)
    try {
      const belge = await api.get<LicenseDocumentResponse>(
        `/api/v1/subscriptions/${subscriptionId}/licenses/${licenseId}`,
      )
      blobIndir(jsonBlobOlustur(belge), `${licenseId}.json`)
    } catch (e) {
      setHata(hataGoster(e))
    } finally {
      setIndirilenId(null)
    }
  }

  return (
    <div>
      <h1>{strings.abonelikler.baslik}</h1>
      {isLoading && <p>{strings.abonelikler.yukleniyor}</p>}
      {isError && (
        <div className="ege-alert ege-alert-err" role="alert">
          {hataGoster(error)}
        </div>
      )}
      {hata && (
        <div className="ege-alert ege-alert-err" role="alert">
          {hata}
        </div>
      )}
      {data && data.length === 0 && <p>{strings.abonelikler.bos}</p>}
      {data?.map((sub) => (
        <div key={sub.id} className="ege-card">
          <h2>{sub.plan_name}</h2>
          <p>
            {strings.abonelikler.durum}: <span className="ege-badge">{durumMetni(sub.status, sub.current_period_end)}</span>
          </p>
          <p>
            {strings.abonelikler.bitisTarihi}: {new Date(sub.current_period_end).toLocaleDateString('tr-TR')}
          </p>
          <p>{strings.abonelikler.urunler}: {sub.items.map((i) => `${i.product_name} (${strings.planlar.tamSurum})`).join(', ')}</p>

          <h3>{strings.abonelikler.lisanslar}</h3>
          {sub.issued_licenses.length === 0 && <p>{strings.abonelikler.lisansYok}</p>}
          <ul>
            {sub.issued_licenses.map((lic) => (
              <li key={lic.license_id}>
                {lic.license_id} — {strings.abonelikler.verilis}: {new Date(lic.issued_at).toLocaleDateString('tr-TR')}{' '}
                · {strings.abonelikler.bitis}: {new Date(lic.expires_at).toLocaleDateString('tr-TR')}
                <button
                  className="ege-btn ege-btn-outline"
                  style={{ marginLeft: 8 }}
                  onClick={() => lisansIndir(sub.id, lic.license_id)}
                  disabled={indirilenId === lic.license_id}
                >
                  {indirilenId === lic.license_id ? strings.abonelikler.indiriliyor : strings.abonelikler.yenidenIndir}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}
