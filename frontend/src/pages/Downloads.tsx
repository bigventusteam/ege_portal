import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, hataGoster } from '../api/client'
import { strings } from '../strings'
import { blobIndir, boyutGosterimi } from '../lib/download'
import type { ReleaseResponse } from '../types'

export function Downloads() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['downloads'],
    queryFn: () => api.get<ReleaseResponse[]>('/api/v1/downloads'),
  })
  const [indirilenId, setIndirilenId] = useState<number | null>(null)
  const [kopyalananId, setKopyalananId] = useState<number | null>(null)
  const [hata, setHata] = useState<string | null>(null)

  async function indir(release: ReleaseResponse) {
    setHata(null)
    setIndirilenId(release.id)
    try {
      const { blob, dosyaAdi } = await api.getBlob(`/api/v1/downloads/${release.id}`)
      blobIndir(blob, dosyaAdi ?? release.file_name)
    } catch (e) {
      setHata(hataGoster(e))
    } finally {
      setIndirilenId(null)
    }
  }

  async function sha256Kopyala(release: ReleaseResponse) {
    try {
      await navigator.clipboard.writeText(release.sha256)
      setKopyalananId(release.id)
      setTimeout(() => setKopyalananId((onceki) => (onceki === release.id ? null : onceki)), 2000)
    } catch {
      // Panoya erişim engellenmişse (ör. güvensiz bağlam) sessizce yok sayılır.
    }
  }

  return (
    <div>
      <h1>{strings.indirmeler.baslik}</h1>
      {isLoading && <p>{strings.indirmeler.yukleniyor}</p>}
      {isError && (
        <div className="ege-alert ege-alert-err" role="alert">
          {hataGoster(error)}
        </div>
      )}
      {hata && (
        <div className="ege-alert ege-alert-err" role="alert">
          {hata}
        </div>
      )}
      {data && data.length === 0 && <p>{strings.indirmeler.bos}</p>}
      {data?.map((release) => (
        <div key={release.id} className="ege-card">
          <h2>
            {release.product_name} {release.version}
            {!release.signed && (
              <span
                className="ege-badge"
                style={{ marginLeft: 8, background: 'color-mix(in srgb, var(--warn) 15%, transparent)', color: 'var(--warn)' }}
              >
                {strings.indirmeler.imzasiz}
              </span>
            )}
          </h2>
          <p>
            {strings.indirmeler.paketTuru}: {release.package_type}
          </p>
          <p>
            {strings.indirmeler.platform}: {release.os} / {release.arch}
          </p>
          <p>
            {strings.indirmeler.boyut}: {boyutGosterimi(release.size_bytes)}
          </p>
          <p style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: 'monospace', fontSize: 12, flexWrap: 'wrap' }}>
            <span>
              {strings.indirmeler.sha256}: {release.sha256}
            </span>
            <button className="ege-btn ege-btn-outline" onClick={() => sha256Kopyala(release)}>
              {kopyalananId === release.id ? strings.indirmeler.kopyalandi : strings.indirmeler.kopyala}
            </button>
          </p>
          <button className="ege-btn" onClick={() => indir(release)} disabled={indirilenId === release.id}>
            {indirilenId === release.id ? strings.indirmeler.indiriliyor : strings.indirmeler.indir}
          </button>
        </div>
      ))}
    </div>
  )
}
