import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { OfflineActivation } from './OfflineActivation'
import { ApiError, api } from '../api/client'
import type { SubscriptionResponse } from '../types'

const ORNEK_ABONELIK: SubscriptionResponse = {
  id: 7,
  plan_id: 1,
  plan_code: 'mapege-pro',
  plan_name: 'mapEGE Pro',
  items: [{ product_code: 'mapege', product_name: 'mapEGE', tier: 'pro' }],
  status: 'active',
  current_period_end: '2027-01-01T00:00:00Z',
  activations: [],
  issued_licenses: [],
}

function Ekran() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <OfflineActivation />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

function kucukDosya(ad = 'activation_request.json') {
  return new File(['{"product":"mapege"}'], ad, { type: 'application/json' })
}

function cokBuyukDosya(ad = 'buyuk.json') {
  return new File([new Uint8Array(17 * 1024)], ad, { type: 'application/json' })
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock')
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
})

describe('OfflineActivation', () => {
  test('abonelik yoksa bilgilendirme gösterilir, form hiç render edilmez', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([])
    render(<Ekran />)
    expect(await screen.findByText('Önce bir abonelik satın almalısınız.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Lisans Üret' })).not.toBeInTheDocument()
  })

  test('16 KB’tan büyük dosya seçilirse hata gösterilir, gönder devre dışı kalır', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'get').mockResolvedValue([ORNEK_ABONELIK])
    render(<Ekran />)

    await user.selectOptions(await screen.findByLabelText('Abonelik seçin'), '7')
    await user.upload(screen.getByLabelText(/activation_request\.json dosyaları/), cokBuyukDosya())

    expect(await screen.findByText(/çok büyük/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Lisans Üret' })).toBeDisabled()
  })

  test('geçerli dosyayla gönderim license.json indirir ve başarı mesajı gösterir', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'get').mockResolvedValue([ORNEK_ABONELIK])
    vi.spyOn(api, 'postForm').mockResolvedValue({ payload: { license_id: 'lic_x' }, signature: 'sig' })
    render(<Ekran />)

    await user.selectOptions(await screen.findByLabelText('Abonelik seçin'), '7')
    await user.upload(screen.getByLabelText(/activation_request\.json dosyaları/), kucukDosya())
    await user.click(screen.getByRole('button', { name: 'Lisans Üret' }))

    await waitFor(() => expect(api.postForm).toHaveBeenCalledWith('/api/v1/subscriptions/7/offline-activation', expect.any(FormData)))
    expect(await screen.findByText('license.json indirildi.')).toBeInTheDocument()
  })

  test('abonelik süresi dolmuşsa backend hatası gösterilir', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'get').mockResolvedValue([ORNEK_ABONELIK])
    vi.spyOn(api, 'postForm').mockRejectedValue(new ApiError(409, 'subscription_id=7 aktif değil (süresi dolmuş)'))
    render(<Ekran />)

    await user.selectOptions(await screen.findByLabelText('Abonelik seçin'), '7')
    await user.upload(screen.getByLabelText(/activation_request\.json dosyaları/), kucukDosya())
    await user.click(screen.getByRole('button', { name: 'Lisans Üret' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('subscription_id=7 aktif değil')
  })
})
