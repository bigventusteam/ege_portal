import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { Downloads } from './Downloads'
import { ApiError, api } from '../api/client'
import type { ReleaseResponse } from '../types'

const ORNEK_SURUM: ReleaseResponse = {
  id: 3,
  product_code: 'mapege',
  product_name: 'mapEGE',
  version: '1.3.0',
  package_type: 'docker-linux',
  os: 'linux',
  arch: 'x64',
  file_name: 'mapege-1.3.0.zip',
  size_bytes: 1024 * 1024 * 5,
  sha256: 'a'.repeat(64),
  signed: true,
  notes: null,
  published_at: '2026-01-01T00:00:00Z',
}

function Ekran() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Downloads />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock')
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
})

describe('Downloads', () => {
  test('sürüm yoksa bilgi mesajı gösterilir', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([])
    render(<Ekran />)
    expect(await screen.findByText('İndirebileceğiniz bir sürüm yok.')).toBeInTheDocument()
  })

  test('sürüm boyutu/sha256 gösterilir, imzalı sürümde İMZASIZ rozeti YOK', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([ORNEK_SURUM])
    render(<Ekran />)
    await waitFor(() => expect(screen.getByText(/mapEGE 1.3.0/)).toBeInTheDocument())
    expect(screen.getByText(/5\.0 MB/)).toBeInTheDocument()
    expect(screen.getByText(new RegExp(ORNEK_SURUM.sha256))).toBeInTheDocument()
    expect(screen.queryByText('İMZASIZ (yalnız personel)')).not.toBeInTheDocument()
  })

  test('imzasız sürümde uyarı rozeti gösterilir', async () => {
    vi.spyOn(api, 'get').mockResolvedValue([{ ...ORNEK_SURUM, signed: false }])
    render(<Ekran />)
    expect(await screen.findByText('İMZASIZ (yalnız personel)')).toBeInTheDocument()
  })

  test('sha256 kopyala panoya yazar ve "Kopyalandı" gösterir', async () => {
    const user = userEvent.setup()
    // `navigator.clipboard` ortama göre değişken davranıyor (bazen tanımsız,
    // bazen test araçlarının kendi polyfill'i) — en güvenilir yol `userEvent.
    // setup()` SONRASI, teste ÖZGÜ olarak property'yi TAMAMEN yeniden
    // tanımlamak (global beforeEach'te değil, önceki/sonraki testlerle
    // etkileşmesin diye).
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })

    vi.spyOn(api, 'get').mockResolvedValue([ORNEK_SURUM])
    render(<Ekran />)

    await user.click(await screen.findByRole('button', { name: 'Kopyala' }))
    expect(writeText).toHaveBeenCalledWith(ORNEK_SURUM.sha256)
    expect(await screen.findByText('Kopyalandı')).toBeInTheDocument()
  })

  test('indir tıklanınca dosya indirme tetiklenir', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'get').mockResolvedValue([ORNEK_SURUM])
    vi.spyOn(api, 'getBlob').mockResolvedValue({ blob: new Blob(['x']), dosyaAdi: 'mapege-1.3.0.zip' })
    render(<Ekran />)

    await user.click(await screen.findByRole('button', { name: 'İndir' }))

    await waitFor(() => expect(api.getBlob).toHaveBeenCalledWith('/api/v1/downloads/3'))
    await waitFor(() => expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled())
  })

  test('indirme hatasında erişilebilir uyarı gösterilir', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'get').mockResolvedValue([ORNEK_SURUM])
    vi.spyOn(api, 'getBlob').mockRejectedValue(new ApiError(404, 'sürüm bulunamadı'))
    render(<Ekran />)

    await user.click(await screen.findByRole('button', { name: 'İndir' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('sürüm bulunamadı')
  })
})
