import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { Plans } from './Plans'
import { api } from '../api/client'
import { useAuthStore } from '../store/auth'
import type { Plan } from '../types'

function KonumGoster() {
  const location = useLocation()
  return <div data-testid="konum">{location.pathname + location.search}</div>
}

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

function Ekran() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/']}>
        <KonumGoster />
        <Routes>
          <Route path="/" element={<Plans />} />
          <Route path="/giris" element={<h1>Giriş Yap</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  useAuthStore.getState().clear()
  vi.restoreAllMocks()
})

describe('Plans', () => {
  test('planlar ve KDV dahil toplam fiyat gösterilir (istemci hesaplamaz, sunucudan geldiği gibi)', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(ORNEK_PLANLAR)
    render(<Ekran />)

    await waitFor(() => expect(screen.getByText('mapEGE Abonelik')).toBeInTheDocument())
    expect(screen.getByText(/14\.400,00 ₺/)).toBeInTheDocument()
    expect(screen.queryByText(/949/)).not.toBeInTheDocument()
  })

  test('kademe gösterilmez — her ürün "Tam sürüm"', async () => {
    vi.spyOn(api, 'get').mockResolvedValue(ORNEK_PLANLAR)
    render(<Ekran />)

    expect(await screen.findByText('mapEGE · Tam sürüm')).toBeInTheDocument()
    expect(screen.queryByText(/\b(pro|standard|lite|full)\b/i)).not.toBeInTheDocument()
  })

  test('boş liste geldiğinde bilgi mesajı gösterilir', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([])
    render(<Ekran />)
    expect(await screen.findByText('Şu anda satışta bir plan yok.')).toBeInTheDocument()
  })

  test('API hatasında erişilebilir bir uyarı gösterilir', async () => {
    const { ApiError } = await import('../api/client')
    vi.spyOn(api, 'get').mockRejectedValue(new ApiError(500, 'Beklenmeyen bir hata oluştu.'))
    render(<Ekran />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Beklenmeyen bir hata oluştu.')
  })

  test('oturum açmamış kullanıcı "Sipariş Ver"e basınca /giris’e yönlendirilir', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'get').mockResolvedValue(ORNEK_PLANLAR)
    render(<Ekran />)

    await user.click(await screen.findByRole('button', { name: 'Sipariş Ver' }))
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Giriş Yap' })).toBeInTheDocument())
  })

  test('oturum açmış kullanıcı "Sipariş Ver"e basınca /siparis?plan_id=&months=’e gider', async () => {
    const user = userEvent.setup()
    useAuthStore.getState().setUser({ userId: 1, customerId: 2, email: 'a@b.com', isStaff: false })
    vi.spyOn(api, 'get').mockResolvedValue(ORNEK_PLANLAR)
    render(<Ekran />)

    await user.click(await screen.findByRole('button', { name: 'Sipariş Ver' }))
    await waitFor(() => expect(screen.getByTestId('konum')).toHaveTextContent('/siparis?plan_id=1&months=12'))
  })
})
