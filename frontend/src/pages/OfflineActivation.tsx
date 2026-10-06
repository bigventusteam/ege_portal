import { useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api, hataGoster } from '../api/client'
import { strings } from '../strings'
import { MAX_ACTIVATION_REQUEST_BAYT, blobIndir, jsonBlobOlustur } from '../lib/download'
import type { LicenseDocumentResponse, SubscriptionResponse } from '../types'

export function OfflineActivation() {
  const { data: subscriptions } = useQuery({
    queryKey: ['subscriptions'],
    queryFn: () => api.get<SubscriptionResponse[]>('/api/v1/subscriptions'),
  })
  const [subscriptionId, setSubscriptionId] = useState<number | null>(null)
  const [dosyalar, setDosyalar] = useState<File[]>([])
  const [dosyaHatasi, setDosyaHatasi] = useState<string | null>(null)
  const [basarili, setBasarili] = useState(false)

  const secilenAbonelik = subscriptions?.find((s) => s.id === subscriptionId)

  const mutation = useMutation({
    mutationFn: async () => {
      const form = new FormData()
      for (const dosya of dosyalar) form.append('files', dosya)
      return api.postForm<LicenseDocumentResponse>(`/api/v1/subscriptions/${subscriptionId}/offline-activation`, form)
    },
    onSuccess: (belge) => {
      blobIndir(jsonBlobOlustur(belge), 'license.json')
      setBasarili(true)
    },
  })

  function dosyaSecildi(e: ChangeEvent<HTMLInputElement>) {
    const secilenler = Array.from(e.target.files ?? [])
    const cokBuyuk = secilenler.find((d) => d.size > MAX_ACTIVATION_REQUEST_BAYT)
    if (cokBuyuk) {
      setDosyaHatasi(strings.aktivasyon.dosyaCokBuyuk(cokBuyuk.name))
      setDosyalar([])
      return
    }
    setDosyaHatasi(null)
    setDosyalar(secilenler)
    setBasarili(false)
  }

  function gonder(e: FormEvent) {
    e.preventDefault()
    mutation.mutate()
  }

  return (
    <div className="ege-card" style={{ maxWidth: 560 }}>
      <h1>{strings.aktivasyon.baslik}</h1>
      <p>{strings.aktivasyon.aciklama}</p>

      {subscriptions && subscriptions.length === 0 && <p>{strings.aktivasyon.abonelikYok}</p>}

      {subscriptions && subscriptions.length > 0 && (
        <form onSubmit={gonder}>
          <div className="ege-field">
            <label htmlFor="aktivasyon-abonelik">{strings.aktivasyon.abonelikSec}</label>
            <select
              id="aktivasyon-abonelik"
              value={subscriptionId ?? ''}
              onChange={(e) => setSubscriptionId(Number(e.target.value) || null)}
            >
              <option value="">—</option>
              {subscriptions.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.plan_name}
                </option>
              ))}
            </select>
          </div>

          {secilenAbonelik && (
            <p style={{ fontSize: 13, color: 'var(--text-dim)' }}>
              {strings.aktivasyon.beklenenUrunler}: {secilenAbonelik.items.map((i) => i.product_name).join(', ')}
            </p>
          )}

          <div className="ege-field">
            <label htmlFor="aktivasyon-dosya">{strings.aktivasyon.dosyaSec}</label>
            <input id="aktivasyon-dosya" type="file" accept="application/json" multiple onChange={dosyaSecildi} />
          </div>

          {dosyaHatasi && (
            <div className="ege-alert ege-alert-err" role="alert">
              {dosyaHatasi}
            </div>
          )}
          {mutation.isError && (
            <div className="ege-alert ege-alert-err" role="alert">
              {hataGoster(mutation.error)}
            </div>
          )}
          {basarili && <div className="ege-alert ege-alert-ok">{strings.aktivasyon.basarili}</div>}

          <button
            type="submit"
            className="ege-btn"
            disabled={mutation.isPending || !subscriptionId || dosyalar.length === 0}
          >
            {mutation.isPending ? strings.aktivasyon.gonderiliyor : strings.aktivasyon.gonder}
          </button>
        </form>
      )}
    </div>
  )
}
