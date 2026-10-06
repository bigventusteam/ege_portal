import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { OrderSummary } from './OrderSummary'
import { ApiError, api } from '../api/client'
import type { OrderResponse, Plan } from '../types'

const ORNEK_PLANLAR: Plan[] = [
  {
    id: 1,
    code: 'mapege-pro',
    name: 'mapEGE Pro',
    items: [{ product_code: 'mapege', product_name: 'mapEGE', tier: 'pro' }],
    prices: [
      { months: 12, net: '12000.00', vat_rate: '20.00', vat_amount: '2400.00', total: '14400.00', currency: '949' },
    ],
  },
]

const ORNEK_SIPARIS: OrderResponse = {
  id: 42,
  customer_id: 1,
  plan_id: 1,
  months: 12,
  quantity: 1,
  net: '12000.00',
  vat_rate: '20.00',
  vat_amount: '2400.00',
  total: '14400.00',
  currency: '949',
  status: 'pending',
  created_at: '2026-01-01T00:00:00Z',
}

function Ekran(initialPath = '/siparis?plan_id=1&months=12') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/siparis" element={<OrderSummary />} />
          <Route path="/aboneliklerim" element={<h1>Aboneliklerim</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => vi.restoreAllMocks())

describe('OrderSummary', () => {
  test('plan_id/months eksikse bulunamadı mesajı gösterilir', () => {
    render(Ekran('/siparis'))
    expect(screen.getByText(/bulunamadı/)).toBeInTheDocument()
  })

  test('önizleme KDV kırılımını sunucudan geldiği gibi gösterir (istemci hesaplamaz)', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(ORNEK_PLANLAR)
    render(Ekran())
    await waitFor(() => expect(screen.getByText('mapEGE Pro')).toBeInTheDocument())
    expect(screen.getByText(/14\.400,00 ₺/)).toBeInTheDocument()
    expect(screen.queryByText(/949/)).not.toBeInTheDocument()
  })

  test('onaylayınca sipariş oluşturulur, "alındı" mesajı gösterilir — ödeme formu YOKTUR', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'get').mockResolvedValue(ORNEK_PLANLAR)
    vi.spyOn(api, 'post').mockResolvedValue(ORNEK_SIPARIS)
    render(Ekran())

    await user.click(await screen.findByRole('button', { name: 'Siparişi Onayla' }))

    expect(await screen.findByText('Siparişiniz alındı.')).toBeInTheDocument()
    expect(screen.getByText(/Sipariş No.*42/)).toBeInTheDocument()
    expect(api.post).toHaveBeenCalledWith('/api/v1/orders', { plan_id: 1, months: 12, quantity: 1 })

    // Ödeme adımı KULLANICI kararıyla ERTELENDİ — kart verisi toplayan
    // HİÇBİR form bulunmamalı.
    expect(document.querySelector('input[type="text"]')).toBeNull()
    expect(screen.queryByLabelText(/kart/i)).not.toBeInTheDocument()
  })

  test('makine adedi siparişe gönderilir ve yanıttaki adet gösterilir', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'get').mockResolvedValue(ORNEK_PLANLAR)
    vi.spyOn(api, 'post').mockResolvedValue({ ...ORNEK_SIPARIS, quantity: 3, net: '36000.00', vat_amount: '7200.00', total: '43200.00' })
    render(Ekran())

    const adet = await screen.findByRole('spinbutton', { name: /makine/i })
    await user.clear(adet)
    await user.type(adet, '3')
    await user.click(screen.getByRole('button', { name: 'Siparişi Onayla' }))

    expect(api.post).toHaveBeenCalledWith('/api/v1/orders', { plan_id: 1, months: 12, quantity: 3 })
    expect(await screen.findByText('Makine (kurulum) adedi: 3')).toBeInTheDocument()
    // Toplam sunucunun döndürdüğü — istemci çarpmaz.
    expect(screen.getByText(/43.200,00 ₺/)).toBeInTheDocument()
  })

  test('geçersiz adette uyarı gösterilir ve onay kapalıdır', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'get').mockResolvedValue(ORNEK_PLANLAR)
    const post = vi.spyOn(api, 'post')
    render(Ekran())

    const adet = await screen.findByRole('spinbutton', { name: /makine/i })
    await user.clear(adet)
    await user.type(adet, '101')

    expect(screen.getByRole('alert')).toHaveTextContent('1 ile 100 arasında')
    expect(screen.getByRole('button', { name: 'Siparişi Onayla' })).toBeDisabled()
    expect(post).not.toHaveBeenCalled()
  })

  test('Ödeme düğmesi yalnız "altyapı yakında" bilgisini gösterir, ödeme akışı/form yok', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'get').mockResolvedValue(ORNEK_PLANLAR)
    const post = vi.spyOn(api, 'post').mockResolvedValue(ORNEK_SIPARIS)
    render(Ekran())

    await user.click(await screen.findByRole('button', { name: 'Siparişi Onayla' }))
    await user.click(await screen.findByRole('button', { name: 'Ödeme' }))

    expect(screen.getByRole('status')).toHaveTextContent('Ödeme altyapısı yakında')
    expect(post).toHaveBeenCalledTimes(1) // yalnız sipariş; ödeme isteği YOK
    expect(document.querySelector('input')).toBeNull()
  })

  test('sipariş oluşturma hatasında erişilebilir uyarı gösterilir', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'get').mockResolvedValue(ORNEK_PLANLAR)
    vi.spyOn(api, 'post').mockRejectedValue(new ApiError(404, 'plan_id=1 bulunamadı ya da aktif değil'))
    render(Ekran())

    await user.click(await screen.findByRole('button', { name: 'Siparişi Onayla' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('plan_id=1 bulunamadı ya da aktif değil')
  })
})
