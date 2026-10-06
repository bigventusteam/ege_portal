import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { Subscriptions } from './Subscriptions'
import { ApiError, api } from '../api/client'
import type { SubscriptionResponse } from '../types'

const ORNEK_ABONELIK: SubscriptionResponse = {
  id: 7,
  plan_id: 1,
  plan_code: 'mapege',
  plan_name: 'mapEGE Abonelik',
  items: [{ product_code: 'mapege', product_name: 'mapEGE' }],
  status: 'active',
  current_period_end: new Date(Date.now() + 1000 * 60 * 60 * 24 * 30).toISOString(),
  activations: [],
  issued_licenses: [{ license_id: 'lic_abc123', issued_at: '2026-01-01T00:00:00Z', expires_at: '2026-12-31T00:00:00Z' }],
}

function Ekran() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Subscriptions />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock')
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
})

describe('Subscriptions', () => {
  test('abonelik yoksa bilgi mesajı gösterir', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([])
    render(<Ekran />)
    expect(await screen.findByText('Henüz bir aboneliğiniz yok.')).toBeInTheDocument()
  })

  test('abonelik ve verilen lisanslar listelenir', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([ORNEK_ABONELIK])
    render(<Ekran />)
    await waitFor(() => expect(screen.getByText('mapEGE Abonelik')).toBeInTheDocument())
    expect(screen.getByText(/lic_abc123/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Yeniden İndir' })).toBeInTheDocument()
  })

  test('lisans yoksa bilgilendirme gösterilir', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([{ ...ORNEK_ABONELIK, issued_licenses: [] }])
    render(<Ekran />)
    expect(await screen.findByText('Bu abonelik için henüz verilmiş bir lisans yok.')).toBeInTheDocument()
  })

  test('yeniden indir tıklanınca belge çekilir ve dosya indirme tetiklenir', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'get')
      .mockResolvedValueOnce([ORNEK_ABONELIK])
      .mockResolvedValueOnce({ payload: { license_id: 'lic_abc123' }, signature: 'sig' })
    const tiklamaSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    render(<Ekran />)

    await user.click(await screen.findByRole('button', { name: 'Yeniden İndir' }))

    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith('/api/v1/subscriptions/7/licenses/lic_abc123'),
    )
    await waitFor(() => expect(tiklamaSpy).toHaveBeenCalled())
  })

  test('yeniden indirme hatasında erişilebilir uyarı gösterilir', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'get')
      .mockResolvedValueOnce([ORNEK_ABONELIK])
      .mockRejectedValueOnce(new ApiError(404, 'lisans bulunamadı'))
    render(<Ekran />)

    await user.click(await screen.findByRole('button', { name: 'Yeniden İndir' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('lisans bulunamadı')
  })
})
