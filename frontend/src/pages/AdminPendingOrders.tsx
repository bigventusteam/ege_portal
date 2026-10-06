import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, hataGoster } from '../api/client'
import { tutarGoster } from '../lib/money'
import { strings } from '../strings'
import type { AdminOrderResponse, MarkOrderPaidResponse } from '../types'

function bugunTarihi(): string {
  return new Date().toISOString().slice(0, 10)
}

export function AdminPendingOrders() {
  const queryClient = useQueryClient()
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['admin-orders-pending'],
    queryFn: () => api.get<AdminOrderResponse[]>('/api/v1/admin/orders?status=pending'),
  })

  const [seciliId, setSeciliId] = useState<number | null>(null)
  const [onayKutusu, setOnayKutusu] = useState(false)
  const [referans, setReferans] = useState('')
  const [tarih, setTarih] = useState(bugunTarihi())
  const [not, setNot] = useState('')
  const [basariliMesaj, setBasariliMesaj] = useState<string | null>(null)

  const secili = data?.find((o) => o.id === seciliId)

  const mutation = useMutation({
    mutationFn: () =>
      api.post<MarkOrderPaidResponse>(`/api/v1/admin/orders/${seciliId}/mark-paid`, {
        amount: secili?.total,
        bank_reference: referans,
        received_at: new Date(tarih).toISOString(),
        note: not || null,
      }),
    onSuccess: () => {
      setBasariliMesaj(strings.personel.basarili)
      setSeciliId(null)
      queryClient.invalidateQueries({ queryKey: ['admin-orders-pending'] })
    },
  })

  function formuAc(order: AdminOrderResponse) {
    setBasariliMesaj(null)
    mutation.reset()
    setSeciliId(order.id)
    setOnayKutusu(false)
    setReferans('')
    setTarih(bugunTarihi())
    setNot('')
  }

  function gonder(e: FormEvent) {
    e.preventDefault()
    mutation.mutate()
  }

  return (
    <div>
      <h1>{strings.personel.baslik}</h1>
      {basariliMesaj && <div className="ege-alert ege-alert-ok">{basariliMesaj}</div>}
      {isLoading && <p>{strings.personel.yukleniyor}</p>}
      {isError && (
        <div className="ege-alert ege-alert-err" role="alert">
          {hataGoster(error)}
        </div>
      )}
      {data && data.length === 0 && <p>{strings.personel.bos}</p>}

      {data?.map((order) => (
        <div key={order.id} className="ege-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
            <div>
              <strong>{order.customer_name}</strong>
              <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>
                {strings.personel.plan}: {order.plan_name} · {strings.personel.sure}: {order.months} {strings.planlar.ay}
              </div>
              <div style={{ fontSize: 14, fontWeight: 600 }}>
                {strings.personel.toplam}: {tutarGoster(order.total, order.currency)}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                {strings.personel.olusturulma}: {new Date(order.created_at).toLocaleString('tr-TR')}
              </div>
            </div>
            <button className="ege-btn" onClick={() => formuAc(order)}>
              {strings.personel.odendiIsaretle}
            </button>
          </div>

          {seciliId === order.id && (
            <form onSubmit={gonder} style={{ marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 16 }}>
              <h3>{strings.personel.formBaslik}</h3>
              <div className="ege-field">
                <label htmlFor="personel-tutar">{strings.personel.tutarSalt}</label>
                <input id="personel-tutar" type="text" value={tutarGoster(order.total, order.currency)} disabled readOnly />
              </div>
              <div className="ege-field">
                <label htmlFor="personel-referans">{strings.personel.referans}</label>
                <input
                  id="personel-referans"
                  type="text"
                  value={referans}
                  onChange={(e) => setReferans(e.target.value)}
                />
              </div>
              <div className="ege-field">
                <label htmlFor="personel-tarih">{strings.personel.tarih}</label>
                <input
                  id="personel-tarih"
                  type="date"
                  max={bugunTarihi()}
                  value={tarih}
                  onChange={(e) => setTarih(e.target.value)}
                />
              </div>
              <div className="ege-field">
                <label htmlFor="personel-not">{strings.personel.not}</label>
                <textarea id="personel-not" value={not} onChange={(e) => setNot(e.target.value)} />
              </div>
              <div className="ege-field" style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                <input
                  id="personel-onay"
                  type="checkbox"
                  checked={onayKutusu}
                  onChange={(e) => setOnayKutusu(e.target.checked)}
                />
                <label htmlFor="personel-onay" style={{ margin: 0 }}>
                  {strings.personel.dogrulamaOnayi}
                </label>
              </div>

              {mutation.isError && (
                <div className="ege-alert ege-alert-err" role="alert">
                  {hataGoster(mutation.error)}
                </div>
              )}

              <div style={{ display: 'flex', gap: 8 }}>
                <button type="submit" className="ege-btn" disabled={!onayKutusu || !referans.trim() || mutation.isPending}>
                  {mutation.isPending ? strings.personel.gonderiliyor : strings.personel.gonder}
                </button>
                <button type="button" className="ege-btn ege-btn-outline" onClick={() => setSeciliId(null)}>
                  {strings.personel.vazgec}
                </button>
              </div>
            </form>
          )}
        </div>
      ))}
    </div>
  )
}
