import { useQuery } from '@tanstack/react-query'
import { api, hataGoster } from '../api/client'
import { tutarGoster } from '../lib/money'
import { strings } from '../strings'
import type { OrderResponse } from '../types'

function durumMetni(status: string): string {
  return strings.siparisler.durumlar[status] ?? status
}

export function Orders() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['orders'],
    queryFn: () => api.get<OrderResponse[]>('/api/v1/orders'),
  })

  if (isLoading) return <p>{strings.siparisler.yukleniyor}</p>
  if (isError)
    return (
      <div className="ege-alert ege-alert-err" role="alert">
        {hataGoster(error)}
      </div>
    )

  const siparisler = data ?? []
  const bekleyenVar = siparisler.some((o) => o.status === 'pending')

  return (
    <div>
      <h1>{strings.siparisler.baslik}</h1>
      {siparisler.length === 0 && <p>{strings.siparisler.bos}</p>}
      {bekleyenVar && <div className="ege-alert ege-alert-info">{strings.siparisler.bekleyenBilgi}</div>}
      {siparisler.map((o) => (
        <div className="ege-card" key={o.id}>
          <h2>
            {strings.siparisler.siparisNo}: {o.id}
          </h2>
          <p>
            {strings.siparisler.durum}: <span className="ege-badge">{durumMetni(o.status)}</span>
          </p>
          <p>
            {strings.siparisler.tarih}: {new Date(o.created_at).toLocaleDateString('tr-TR')} · {strings.siparisler.sure}:{' '}
            {o.months} {strings.siparisler.ay} · {strings.siparisler.adet}: {o.quantity}
          </p>
          <p>
            {strings.siparisler.net}: {tutarGoster(o.net, o.currency)} · {strings.siparisler.kdv}:{' '}
            {tutarGoster(o.vat_amount, o.currency)} ·{' '}
            <strong>
              {strings.siparisler.toplam}: {tutarGoster(o.total, o.currency)}
            </strong>
          </p>
        </div>
      ))}
    </div>
  )
}
