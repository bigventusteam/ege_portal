import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'

// `test.globals: true` BİLEREK AÇIK DEĞİL (vitest.config.ts) — testing-library'nin
// otomatik temizliği global `afterEach`e dayanır, o olmadan her testin DOM'u
// bir SONRAKİ testin DOM'una EKLENİR (ör. iki ayrı testte "Kayıt Ol" butonu
// birden fazla eşleşir). Elle bağlanıyor.
afterEach(() => {
  cleanup()
})

// jsdom bunları HİÇ UYGULAMAZ (fonksiyon mevcut değil) — `vi.spyOn` var
// olmayan bir metodu spy'layamadığı için her testte elle stub'lanması
// gerekirdi, burada bir kez tanımlanıyor. Sayfa testleri `vi.spyOn(URL,
// 'createObjectURL')` ile kendi dönüş değerini/çağrı sayısını izleyebilir
// (spyOn artık GERÇEK bir fonksiyonun üstüne yazıyor, var olmayan bir
// metot değil).
if (!URL.createObjectURL) URL.createObjectURL = () => 'blob:mock'
if (!URL.revokeObjectURL) URL.revokeObjectURL = () => {}
