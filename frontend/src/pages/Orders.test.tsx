import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { Orders } from './Orders'
import { api } from '../api/client'
import type { OrderResponse } from '../types'

const SIPARIS: OrderResponse = {
  id: 7,
  customer_id: 1,
  plan_id: 1,
  months: 12,
  quantity: 2,
  net: '24000.00',
  vat_rate: '20.00',
  vat_amount: '4800.00',
  total: '28800.00',
  currency: '949',
  status: 'pending',
  created_at: '2026-10-06T08:00:00Z',
}

function Ekran() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Orders />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => vi.restoreAllMocks())

describe('Orders (Siparişlerim)', () => {
  test('siparişler durum, adet ve sunucunun KDV kırılımıyla listelenir', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([
      SIPARIS,
      { ...SIPARIS, id: 6, status: 'paid', quantity: 1, net: '12000.00', vat_amount: '2400.00', total: '14400.00' },
    ])
    render(<Ekran />)

    expect(await screen.findByText('Sipariş No: 7')).toBeInTheDocument()
    expect(screen.getByText('Ödeme bekleniyor')).toBeInTheDocument()
    expect(screen.getByText('Ödendi')).toBeInTheDocument()
    expect(screen.getByText(/28\.800,00 ₺/)).toBeInTheDocument()
    expect(screen.getByText(/Makine adedi: 2/)).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/api/v1/orders')
    // Bekleyen sipariş varken ödeme talimatı bilgisi görünür.
    expect(screen.getByText(/ödeme talimatını sipariş numaranızla/)).toBeInTheDocument()
  })

  test('bekleyen sipariş yoksa ödeme bilgisi gösterilmez; boş listede bilgi mesajı', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([])
    render(<Ekran />)
    expect(await screen.findByText('Henüz bir siparişiniz yok.')).toBeInTheDocument()
    expect(screen.queryByText(/ödeme talimatını/)).not.toBeInTheDocument()
  })
})
