import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { api, hataGoster } from '../api/client'
import { oranGoster, tutarGoster } from '../lib/money'
import { strings } from '../strings'
import type { OrderResponse, Plan } from '../types'

export function OrderSummary() {
  const [params] = useSearchParams()
  const planId = Number(params.get('plan_id'))
  const months = Number(params.get('months'))
  // Sunucu sınırı 1..100 (app/services/orders.py MAX_QUANTITY) — tutarı
  // istemci HESAPLAMAZ, yalnız adedi gönderir; kesin tutar sipariş yanıtından gelir.
  const [adetMetni, setAdetMetni] = useState('1')
  const quantity = Number(adetMetni)
  const adetGecerli = Number.isInteger(quantity) && quantity >= 1 && quantity <= 100
  const [odemeAcik, setOdemeAcik] = useState(false)

  const { data: plans } = useQuery({
    queryKey: ['plans'],
    queryFn: () => api.get<Plan[]>('/api/v1/plans'),
    enabled: Boolean(planId && months),
  })

  const mutation = useMutation({
    mutationFn: () => api.post<OrderResponse>('/api/v1/orders', { plan_id: planId, months, quantity }),
  })

  if (!planId || !months) {
    return <p>{strings.siparis.planBulunamadi}</p>
  }

  if (mutation.isSuccess) {
    const order = mutation.data
    return (
      <div className="ege-card">
        <h1>{strings.siparis.alindiBaslik}</h1>
        <div className="ege-alert ege-alert-ok">{strings.siparis.alindiMesaj}</div>
        <p>
          {strings.siparis.siparisNo}: {order.id}
        </p>
        <p>
          {strings.siparis.adet}: {order.quantity}
        </p>
        <p>
          {strings.siparis.net}: {tutarGoster(order.net, order.currency)}
        </p>
        <p>
          {strings.siparis.kdv}: {tutarGoster(order.vat_amount, order.currency)}
        </p>
        <p>
          <strong>
            {strings.siparis.toplam}: {tutarGoster(order.total, order.currency)}
          </strong>
        </p>
        {odemeAcik ? (
          <div className="ege-alert ege-alert-info" role="status">
            <strong>{strings.siparis.odemeBaslik}</strong>
            <p>{strings.siparis.odemeBilgi}</p>
          </div>
        ) : (
          <button className="ege-btn" onClick={() => setOdemeAcik(true)}>
            {strings.siparis.odeme}
          </button>
        )}{' '}
        <Link to="/siparislerim" className="ege-btn ege-btn-outline">
          {strings.nav.siparislerim}
        </Link>{' '}
        <Link to="/aboneliklerim" className="ege-btn ege-btn-outline">
          {strings.siparis.aboneliklereDon}
        </Link>
      </div>
    )
  }

  const plan = plans?.find((p) => p.id === planId)
  const price = plan?.prices.find((p) => p.months === months)

  if (!plan || !price) {
    return <p>{strings.siparis.planBulunamadi}</p>
  }

  return (
    <div className="ege-card" style={{ maxWidth: 480 }}>
      <h1>{strings.siparis.baslik}</h1>
      <h2>{plan.name}</h2>
      <p>
        {strings.siparis.sure}: {months} {strings.planlar.ay}
      </p>
      <label>
        {strings.siparis.adet}{' '}
        <input
          type="number"
          min={1}
          max={100}
          step={1}
          value={adetMetni}
          onChange={(e) => setAdetMetni(e.target.value)}
          aria-invalid={!adetGecerli}
        />
      </label>
      <p className="ege-muted">{strings.siparis.adetAciklama}</p>
      <p>
        <em>{strings.siparis.birimFiyat}</em>
      </p>
      <p>
        {strings.siparis.net}: {tutarGoster(price.net, price.currency)}
      </p>
      <p>
        {strings.siparis.kdv} (%{oranGoster(price.vat_rate)}): {tutarGoster(price.vat_amount, price.currency)}
      </p>
      <p>
        <strong>
          {strings.siparis.toplam}: {tutarGoster(price.total, price.currency)}
        </strong>
      </p>
      {mutation.isError && (
        <div className="ege-alert ege-alert-err" role="alert">
          {hataGoster(mutation.error)}
        </div>
      )}
      {!adetGecerli && (
        <div className="ege-alert ege-alert-err" role="alert">
          {strings.siparis.adetGecersiz}
        </div>
      )}
      <button className="ege-btn" onClick={() => mutation.mutate()} disabled={mutation.isPending || !adetGecerli}>
        {mutation.isPending ? strings.siparis.onaylaniyor : strings.siparis.onayla}
      </button>
    </div>
  )
}
