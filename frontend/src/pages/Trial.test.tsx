import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { Trial } from './Trial'
import { ApiError, api } from '../api/client'

function Ekran() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Trial />
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
  vi.spyOn(api, 'get').mockResolvedValue({ days: 10 })
})

describe('Trial', () => {
  test('müşteriye tanımlı deneme süresi sunucudan gösterilir', async () => {
    render(<Ekran />)
    expect(await screen.findByText('Size tanımlı deneme süresi: 10 gün.')).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/api/v1/trial-settings')
  })

  test('dosya seçilmeden gönder devre dışı', () => {
    render(<Ekran />)
    expect(screen.getByRole('button', { name: 'Deneme Lisansı Üret' })).toBeDisabled()
  })

  test('16 KB’tan büyük dosya seçilirse hata gösterilir', async () => {
    const user = userEvent.setup()
    render(<Ekran />)
    await user.upload(screen.getByLabelText(/activation_request\.json dosyaları/), cokBuyukDosya())
    expect(await screen.findByText(/çok büyük/)).toBeInTheDocument()
  })

  test('geçerli dosyayla gönderim deneme license.json indirir', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'postForm').mockResolvedValue({ payload: { license_type: 'trial' }, signature: 'sig' })
    render(<Ekran />)

    await user.upload(screen.getByLabelText(/activation_request\.json dosyaları/), kucukDosya())
    await user.click(screen.getByRole('button', { name: 'Deneme Lisansı Üret' }))

    await waitFor(() => expect(api.postForm).toHaveBeenCalledWith('/api/v1/trial-activation', expect.any(FormData)))
    expect(await screen.findByText('Deneme license.json indirildi.')).toBeInTheDocument()
  })

  test('aynı kurulum başka müşteride deneme almışsa backend hatası gösterilir', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'postForm').mockRejectedValue(
      new ApiError(409, "'mapege': bu kurulum (instance_id) başka bir müşteride deneme almış"),
    )
    render(<Ekran />)

    await user.upload(screen.getByLabelText(/activation_request\.json dosyaları/), kucukDosya())
    await user.click(screen.getByRole('button', { name: 'Deneme Lisansı Üret' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('başka bir müşteride deneme almış')
  })
})
