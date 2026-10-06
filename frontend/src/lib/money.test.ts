import { describe, expect, test } from 'vitest'
import { oranGoster, tutarGoster } from './money'

describe('tutarGoster', () => {
  test('TRY (949) için Türkçe gruplama + sembol', () => {
    expect(tutarGoster('12000.00', '949')).toBe('12.000,00 ₺')
    expect(tutarGoster('14400.00', '949')).toBe('14.400,00 ₺')
  })

  test('küsuratlı tutarı iki ondalığa yuvarlar/tamamlar', () => {
    expect(tutarGoster('99.99', '949')).toBe('99,99 ₺')
    expect(tutarGoster('100', '949')).toBe('100,00 ₺')
  })

  test('bilinmeyen para birimi kodunda ÇÖKMEZ, ham kodu gösterir', () => {
    expect(tutarGoster('100.00', '978')).toBe('100,00 978')
  })

  test('ayrıştırılamayan tutarda ÇÖKMEZ, ham değeri gösterir', () => {
    expect(tutarGoster('yok', '949')).toBe('yok 949')
  })
})

describe('oranGoster', () => {
  test('gereksiz ondalığı kaldırır', () => {
    expect(oranGoster('20.00')).toBe('20')
  })

  test('anlamlı ondalığı KORUR', () => {
    expect(oranGoster('7.50')).toBe('7,5')
  })

  test('ayrıştırılamayan değerde ham veriyi döner, çökmez', () => {
    expect(oranGoster('bilinmeyen')).toBe('bilinmeyen')
  })
})
