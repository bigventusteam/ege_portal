import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { AdminPendingOrders } from './AdminPendingOrders'
import { ApiError, api } from '../api/client'
import type { AdminOrderResponse } from '../types'

const ORNEK_SIPARIS: AdminOrderResponse = {
  id: 11,
  customer_id: 3,
  customer_name: 'Test Belediyesi',
  plan_id: 1,
  plan_name: 'mapEGE Abonelik',
  months: 12,
  net: '12000.00',
  vat_rate: '20.00',
  vat_amount: '2400.00',
  total: '14400.00',
  currency: '949',
  status: 'pending',
  created_at: '2026-01-01T00:00:00Z',
}

function Ekran() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AdminPendingOrders />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => vi.restoreAllMocks())

describe('AdminPendingOrders', () => {
  test('bekleyen sipariş yoksa bilgi mesajı gösterilir', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([])
    render(<Ekran />)
    expect(await screen.findByText('Bekleyen sipariş yok.')).toBeInTheDocument()
  })

  test('sipariş listelenir, tutar KDV dahil formatlı gösterilir (ham "949" YOK)', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([ORNEK_SIPARIS])
    render(<Ekran />)
    await waitFor(() => expect(screen.getByText('Test Belediyesi')).toBeInTheDocument())
    expect(screen.getByText(/14\.400,00 ₺/)).toBeInTheDocument()
    expect(screen.queryByText(/949/)).not.toBeInTheDocument()
  })

  test('"Ödendi işaretle" formu açar, tutar alanı DOLU ve DEĞİŞTİRİLEMEZ gösterilir', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'get').mockResolvedValue([ORNEK_SIPARIS])
    render(<Ekran />)

    await user.click(await screen.findByRole('button', { name: 'Ödendi İşaretle' }))

    const tutarAlani = screen.getByLabelText(/Tutar \(sipariş toplamı/) as HTMLInputElement
    expect(tutarAlani).toBeDisabled()
    expect(tutarAlani.value).toBe('14.400,00 ₺')
  })

  test('onay kutusu işaretlenmeden/referans girilmeden gönder devre dışı', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'get').mockResolvedValue([ORNEK_SIPARIS])
    render(<Ekran />)
    await user.click(await screen.findByRole('button', { name: 'Ödendi İşaretle' }))

    expect(screen.getByRole('button', { name: 'Kaydet' })).toBeDisabled()
  })

  test('geçerli formla gönderim doğru gövdeyi yollar, başarı mesajı gösterir', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'get').mockResolvedValue([ORNEK_SIPARIS])
    vi.spyOn(api, 'post').mockResolvedValue({
      payment_id: 1, order_id: 11, order_status: 'paid', amount: '14400.00',
      bank_reference: 'DEKONT-1', received_at: '2026-01-05T00:00:00Z', marked_by_user_id: 9,
    })
    render(<Ekran />)

    await user.click(await screen.findByRole('button', { name: 'Ödendi İşaretle' }))
    await user.type(screen.getByLabelText('Banka referansı (dekont/işlem no)'), 'DEKONT-1')
    await user.click(screen.getByLabelText('Banka hesabına bu tutarın geldiğini doğruladım.'))
    await user.click(screen.getByRole('button', { name: 'Kaydet' }))

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        '/api/v1/admin/orders/11/mark-paid',
        expect.objectContaining({ amount: '14400.00', bank_reference: 'DEKONT-1', note: null }),
      ),
    )
    expect(await screen.findByText('Ödeme işaretlendi, abonelik açıldı.')).toBeInTheDocument()
  })

  test('reddedilen işaretlemede erişilebilir uyarı gösterilir', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'get').mockResolvedValue([ORNEK_SIPARIS])
    vi.spyOn(api, 'post').mockRejectedValue(new ApiError(409, 'order_id=11 zaten sonuçlanmış (durum=paid, PENDING değil)'))
    render(<Ekran />)

    await user.click(await screen.findByRole('button', { name: 'Ödendi İşaretle' }))
    await user.type(screen.getByLabelText('Banka referansı (dekont/işlem no)'), 'DEKONT-1')
    await user.click(screen.getByLabelText('Banka hesabına bu tutarın geldiğini doğruladım.'))
    await user.click(screen.getByRole('button', { name: 'Kaydet' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('order_id=11 zaten sonuçlanmış')
  })

  test('vazgeç formu kapatır', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'get').mockResolvedValue([ORNEK_SIPARIS])
    render(<Ekran />)

    await user.click(await screen.findByRole('button', { name: 'Ödendi İşaretle' }))
    expect(screen.getByRole('button', { name: 'Vazgeç' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Vazgeç' }))
    expect(screen.queryByRole('button', { name: 'Vazgeç' })).not.toBeInTheDocument()
  })
})
