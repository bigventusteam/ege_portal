import { useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api, hataGoster } from '../api/client'
import { strings } from '../strings'
import { MAX_ACTIVATION_REQUEST_BAYT, blobIndir, jsonBlobOlustur } from '../lib/download'
import type { LicenseDocumentResponse } from '../types'

export function Trial() {
  const [dosyalar, setDosyalar] = useState<File[]>([])
  const [dosyaHatasi, setDosyaHatasi] = useState<string | null>(null)
  const [basarili, setBasarili] = useState(false)

  const mutation = useMutation({
    mutationFn: async () => {
      const form = new FormData()
      for (const dosya of dosyalar) form.append('files', dosya)
      return api.postForm<LicenseDocumentResponse>('/api/v1/trial-activation', form)
    },
    onSuccess: (belge) => {
      blobIndir(jsonBlobOlustur(belge), 'license-deneme.json')
      setBasarili(true)
    },
  })

  function dosyaSecildi(e: ChangeEvent<HTMLInputElement>) {
    const secilenler = Array.from(e.target.files ?? [])
    const cokBuyuk = secilenler.find((d) => d.size > MAX_ACTIVATION_REQUEST_BAYT)
    if (cokBuyuk) {
      setDosyaHatasi(strings.deneme.dosyaCokBuyuk(cokBuyuk.name))
      setDosyalar([])
      return
    }
    setDosyaHatasi(null)
    setDosyalar(secilenler)
    setBasarili(false)
  }

  function gonder(e: FormEvent) {
    e.preventDefault()
    mutation.mutate()
  }

  return (
    <div className="ege-card" style={{ maxWidth: 560 }}>
      <h1>{strings.deneme.baslik}</h1>
      <p>{strings.deneme.aciklama}</p>
      <form onSubmit={gonder}>
        <div className="ege-field">
          <label htmlFor="deneme-dosya">{strings.deneme.dosyaSec}</label>
          <input id="deneme-dosya" type="file" accept="application/json" multiple onChange={dosyaSecildi} />
        </div>
        {dosyaHatasi && (
          <div className="ege-alert ege-alert-err" role="alert">
            {dosyaHatasi}
          </div>
        )}
        {mutation.isError && (
          <div className="ege-alert ege-alert-err" role="alert">
            {hataGoster(mutation.error)}
          </div>
        )}
        {basarili && <div className="ege-alert ege-alert-ok">{strings.deneme.basarili}</div>}
        <button type="submit" className="ege-btn" disabled={mutation.isPending || dosyalar.length === 0}>
          {mutation.isPending ? strings.deneme.gonderiliyor : strings.deneme.gonder}
        </button>
      </form>
    </div>
  )
}
