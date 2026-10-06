import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api, hataGoster } from '../api/client'
import { oranGoster, tutarGoster } from '../lib/money'
import { useAuthStore } from '../store/auth'
import { strings } from '../strings'
import type { Plan } from '../types'

export function Plans() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['plans'],
    queryFn: () => api.get<Plan[]>('/api/v1/plans'),
  })

  function siparisVer(planId: number, months: number) {
    if (!user) {
      navigate('/giris')
      return
    }
    navigate(`/siparis?plan_id=${planId}&months=${months}`)
  }

  return (
    <div>
      <h1>{strings.planlar.baslik}</h1>
      {isLoading && <p>{strings.planlar.yukleniyor}</p>}
      {isError && (
        <div className="ege-alert ege-alert-err" role="alert">
          {hataGoster(error)}
        </div>
      )}
      {data && data.length === 0 && <p>{strings.planlar.bos}</p>}
      {data?.map((plan) => (
        <div key={plan.id} className="ege-card">
          <h2>{plan.name}</h2>
          <div style={{ marginBottom: 12 }}>
            {plan.items.map((item) => (
              <span key={item.product_code} className="ege-badge" style={{ marginRight: 6 }}>
                {item.product_name} · {strings.planlar.tamSurum}
              </span>
            ))}
          </div>
          {plan.prices.map((price) => (
            <div
              key={price.months}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '10px 0',
                borderTop: '1px solid var(--border)',
              }}
            >
              <div>
                <strong>
                  {price.months} {strings.planlar.ay}
                </strong>
                <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>
                  {strings.planlar.netTutar}: {tutarGoster(price.net, price.currency)} · {strings.planlar.kdvOrani}: %
                  {oranGoster(price.vat_rate)}
                </div>
                <div style={{ fontSize: 14, fontWeight: 600 }}>
                  {strings.planlar.kdvDahilToplam}: {tutarGoster(price.total, price.currency)}
                </div>
              </div>
              <button className="ege-btn" onClick={() => siparisVer(plan.id, price.months)}>
                {strings.planlar.siparisVer}
              </button>
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}
