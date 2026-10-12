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
    code: 'mapege',
    name: 'mapEGE Abonelik',
    items: [{ product_code: 'mapege', product_name: 'mapEGE' }],
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
    await waitFor(() => expect(screen.getByText('mapEGE Abonelik')).toBeInTheDocument())
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

  test('eklenti planında birden çok colEGE aboneliği varsa bağlanacak abonelik seçilmeden sipariş verilemez', async () => {
    const user = userEvent.setup()
    const gelecek = new Date(Date.now() + 1000 * 60 * 60 * 24 * 90).toISOString()
    const colegeAbonelik = (id: number, ad: string) => ({
      id,
      plan_id: id,
      plan_code: ad,
      plan_name: ad,
      items: [{ product_code: 'colege', product_name: 'colEGE' }],
      status: 'active',
      current_period_end: gelecek,
      activations: [],
      issued_licenses: [],
    })
    vi.spyOn(api, 'get').mockImplementation(async (url: string) => {
      if (url === '/api/v1/subscriptions') return [colegeAbonelik(3, 'colEGE Yıllık'), colegeAbonelik(4, 'colEGE Paket')]
      return [
        {
          id: 1,
          code: 'colege-soru-yillik',
          name: 'colEGE Soru Sor',
          is_addon: true,
          items: [
            { product_code: 'colege_soru', product_name: 'colEGE Soru Sor', requires_product_code: 'colege', requires_product_name: 'colEGE' },
          ],
          prices: [{ months: 12, net: '1000.00', vat_rate: '20.00', vat_amount: '200.00', total: '1200.00', currency: '949' }],
        },
      ]
    })
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      ...ORNEK_SIPARIS,
      net: '273.97',
      base_subscription_id: 4,
      addon_period_end: gelecek,
      prorated_days: 90,
      addons: [],
    })
    render(Ekran())

    expect(await screen.findByText(/AYNI gün biter/)).toBeInTheDocument()
    const onay = await screen.findByRole('button', { name: 'Siparişi Onayla' })
    await waitFor(() => expect(screen.getByLabelText('Bağlanacak colEGE aboneliği')).toBeInTheDocument())
    expect(onay).toBeDisabled()

    await user.selectOptions(screen.getByLabelText('Bağlanacak colEGE aboneliği'), '4')
    await user.click(onay)
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith('/api/v1/orders', { plan_id: 1, months: 12, quantity: 1, base_subscription_id: 4 }),
    )
    expect(await screen.findByText(/90 güne orantılı/)).toBeInTheDocument()
  })
})
