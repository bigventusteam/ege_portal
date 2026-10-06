import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { ApiError, api, hataGoster, onSessionExpired } from './client'

function sahteYanit(
  body: unknown,
  init: { status?: number; headers?: Record<string, string> } = {},
): Response {
  const status = init.status ?? 200
  const headers = new Headers(init.headers ?? { 'content-type': 'application/json' })
  return new Response(body === undefined ? null : JSON.stringify(body), { status, headers })
}

describe('api client', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    onSessionExpired(() => {})
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  test('get: credentials include ile istek atar ve JSON döner', async () => {
    const fetchMock = vi.fn().mockResolvedValue(sahteYanit({ merhaba: 'dunya' }))
    vi.stubGlobal('fetch', fetchMock)

    const sonuc = await api.get<{ merhaba: string }>('/api/v1/plans')

    expect(sonuc).toEqual({ merhaba: 'dunya' })
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/plans', expect.objectContaining({ credentials: 'include' }))
  })

  test('post: gövdeyi JSON olarak gönderir, Content-Type ekler', async () => {
    const fetchMock = vi.fn().mockResolvedValue(sahteYanit({ id: 1 }, { status: 201 }))
    vi.stubGlobal('fetch', fetchMock)

    await api.post('/api/v1/orders', { plan_id: 1, months: 12 })

    const [, init] = fetchMock.mock.calls[0]
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(JSON.parse(init.body)).toEqual({ plan_id: 1, months: 12 })
  })

  test('postForm: FormData gönderir, Content-Type elle SET ETMEZ', async () => {
    const fetchMock = vi.fn().mockResolvedValue(sahteYanit({ payload: {}, signature: 'x' }))
    vi.stubGlobal('fetch', fetchMock)

    const form = new FormData()
    form.append('files', new File(['{}'], 'a.json'))
    await api.postForm('/api/v1/trial-activation', form)

    const [, init] = fetchMock.mock.calls[0]
    expect(init.method).toBe('POST')
    expect(init.body).toBe(form)
    expect(init.headers).toBeUndefined()
  })

  test('hata gövdesi string detail taşıyorsa ApiError.message aynen onu taşır', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sahteYanit({ detail: 'abonelik bulunamadı' }, { status: 404 })))

    await expect(api.get('/api/v1/subscriptions/999')).rejects.toMatchObject({
      status: 404,
      message: 'abonelik bulunamadı',
    })
  })

  test('hata gövdesi pydantic doğrulama dizisi taşıyorsa msg alanları birleştirilir', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        sahteYanit({ detail: [{ msg: 'alan zorunlu', loc: ['body', 'email'] }] }, { status: 422 }),
      ),
    )

    await expect(api.post('/api/v1/auth/register', {})).rejects.toMatchObject({
      status: 422,
      message: 'alan zorunlu',
    })
  })

  test('hata gövdesi JSON değilse/okunamazsa genel bir mesaja düşer, çökmez', async () => {
    const bozukYanit = new Response('<html>502</html>', {
      status: 502,
      headers: { 'content-type': 'text/html' },
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(bozukYanit))

    await expect(api.get('/api/v1/plans')).rejects.toMatchObject({
      status: 502,
      message: 'Beklenmeyen bir hata oluştu.',
    })
  })

  test('401: giriş/kayıt YOLU DIŞINDA oturum düşmesi callback’i tetiklenir', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sahteYanit({ detail: 'oturum gerekli' }, { status: 401 })))
    const dustu = vi.fn()
    onSessionExpired(dustu)

    await expect(api.get('/api/v1/subscriptions')).rejects.toBeInstanceOf(ApiError)
    expect(dustu).toHaveBeenCalledTimes(1)
  })

  test('401: /auth/login kendisi 401 dönerse oturum düşmesi TETİKLENMEZ (yanlış şifre, normal form hatası)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sahteYanit({ detail: 'e-posta veya parola yanlış' }, { status: 401 })))
    const dustu = vi.fn()
    onSessionExpired(dustu)

    await expect(api.post('/api/v1/auth/login', { email: 'a@b.com', password: 'x' })).rejects.toBeInstanceOf(ApiError)
    expect(dustu).not.toHaveBeenCalled()
  })

  test('getBlob: content-disposition’dan dosya adını ayıklar', async () => {
    // jsdom'un fetch/Blob polyfili test ortamında native Blob'dan FARKLI bir
    // realm'de yaşayabiliyor (`.text()` gibi metotlar eksik görünebiliyor) —
    // bu yüzden içerik `.size` ile doğrulanıyor, `.text()`/`instanceof` ile
    // DEĞİL (ortam-bağımlı bir kırılganlık, gerçek davranışı etkilemiyor).
    const icerik = 'icerik'
    const resp = new Response(icerik, {
      status: 200,
      headers: {
        'content-disposition': 'attachment; filename="mapege-1.0.0.zip"',
        'x-checksum-sha256': 'abc123',
      },
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(resp))

    const sonuc = await api.getBlob('/api/v1/downloads/1')
    expect(sonuc.dosyaAdi).toBe('mapege-1.0.0.zip')
    expect(sonuc.blob.size).toBe(new TextEncoder().encode(icerik).length)
  })

  test('hataGoster: ApiError için mesajı, diğer hatalar için genel metni döner (ham JS hatası sızdırmaz)', () => {
    expect(hataGoster(new ApiError(404, 'abonelik bulunamadı'))).toBe('abonelik bulunamadı')
    expect(hataGoster(new TypeError('Failed to fetch at internal://secret/path.ts:42'))).toBe(
      'Beklenmeyen bir hata oluştu.',
    )
    expect(hataGoster('bilinmeyen')).toBe('Beklenmeyen bir hata oluştu.')
  })
})
