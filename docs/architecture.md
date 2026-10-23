# Mimari ve genişletme

Paket `src/jira_test` altında sorumluluklarına göre ayrılmıştır:

| Parça | Sorumluluk |
|---|---|
| config, errors | Ortam ayarları, güvenli hata sınıfları |
| client | REST v2, sayfalama, çalıştırmaya ait kayıtların yazma sınırı |
| browser, session | Playwright yaşam döngüsü ve tek hesap bağlamı |
| components, ui | Alan adaptörleri ve issue işlem ekranları |
| explorer, ui_discovery | Salt okunur API/UI keşfi ve sınırlı browser fallback |
| catalog, report | Kaynakları ayrı tutan snapshot ve escaped HTML |
| scenario, runner | Deklaratif şema doğrulama ve gerçek işlem/assertion yürütme |
| pytest_plugin, cli | YAML collection, Python fixture ve komutlar |

```mermaid
flowchart LR
    Config --> Session
    Session --> API[Jira REST]
    Session --> Browser[Playwright]
    API --> Explorer
    Browser --> Components
    Components --> Explorer
    Explorer --> Catalog[JSON ve HTML katalog]
    YAML --> Validator
    Validator --> Runner
    Runner --> API
    Runner --> Components
    Runner --> Results[pytest ve JSON sonuçları]
```

Komponent seçimi `schema.custom`, `schema.system` ve `schema.type` üzerinden yapılır.
Yerleşik Jira custom field anahtarları açık allowlist ile tanınır. Standart alan
komponenti, alan ID'sine göre seçilmiş DOM elementini kullanır; karmaşık widget için
locator input/iframe/konteyneri göstermelidir.

## Locator uyarlaması

Yapılandırma CSS selector override'ları kabul eder:

```yaml
locators:
  edit.description: 'iframe[id="description-wysiwyg"]'
  edit.customfield_10012: '#custom-widget-input'
  edit.customfield_10012.error: '#custom-widget-error'
  transition.31.button: '#action_id_31'
  transition.root: '#issue-workflow-transition'
```

Önce güvenilir ID, ardından sabit data attribute tercih edin. Locator override ile
project/type/parent kontrollerini etkisizleştirmeyin. Form değişimi DOM gözleminden
anlaşılmalıdır; statik sleep ve global implicit wait kullanılmaz.

## Adaptör ekleme

Yeni alan sınıfı `FieldComponent` veya uygun mevcut komponentten türetilir; `fill`,
`clear` ve gerekiyorsa `read` metodlarını gerçek widget davranışına göre uygular.
`jira_session.registry.register(schema_key, ComponentClass)` çağrısıyla tarayıcıyı
başlatmadan önce kaydedilir. Session registry nesnesi UI ile paylaşılır.

Tam örnek `examples/python/test_04_custom_adapter.py` dosyasında bulunur. Örnekteki
`vendor:uppercase-text` hayali bir şemadır; gerçek eklentinizin anahtarını ve widget
uygulamasını kullanın. Basit benzerlikler için yeni inheritance katmanları eklemeyin.

## Davranış ve operasyon sınırları

Test hazırlığı API kullanır; sınanan eylem Playwright kullanır. Geçiş koşulları,
validator'lar ve farklı statüler açık senaryolarla doğrulanır. Explorer ekranları
kaydetmeden inceler; daha önce gözlenmeyen statülere geçmek için mutasyon yapmaz.

Issue kimlikleri yalnız mevcut çalıştırmada oluşturulduktan ve proje/summary marker
REST ile doğrulandıktan sonra yazılabilir kabul edilir. Taşıma, reparent ve delete
işlemleri sunulmaz. HTTP redirect ve yazma retry kapalıdır. Kayıtlar otomatik
silinmez; izinli temizlik ayrı bir operasyon olarak ele alınmalıdır.

İlk sürüm seri çalışır; xdist/çoklu kullanıcı için oturum ve rapor izolasyonu ayrıca
uyarlanmalıdır. Fixture hazırlık hatası kalan test kayıtlarını geri almaz; çalıştırma
raporunda kayıtlar gösterilir. Kaynak ve test projesi eşitliği otomatik kanıtlanmaz;
Jira yöneticisinin yapılandırma eşlemesi ve test projesi keşfi gereklidir.

## Playwright yaşam döngüsü

Senkron Playwright API kullanılır. Browser, ayrı BrowserContext ve Page sahipliğini
yönetir; oturum seri çalışır ve context yeniden kullanılmaz. Locator nesneleri
DOM yenilendiğinde elementi yeniden bulur. CSS override sözleşmesi korunur.
Alan adaptörleri `FieldComponent(element: Locator, schema=None)` alır; Selenium
bekleme nesnesi yoktur. UI eylemleri Playwright otomatik beklemelerini kullanır;
REST kalıcılık ve birleşik UI/API sonuçları sınırlı, monotonic polling ile beklenir.
Formun kaybolması başarı sayılmaz: görünür issue kimliği ve REST yazma kanıtı gerekir.

## Masaüstü uygulaması

`jira_test.gui.app` Tk ekranlarını birleştirir; ana thread yalnız UI olaylarını işler.
`jobs.JobController` her işlem için taze Python worker başlatır. İlk stdin mesajı
istek/kimlik bilgilerini, sonraki mesajlar güvenli iptal isteğini taşır; stdout JSONL
olayları queue + `after` ile arayüze aktarılır. Aynı anda tek iş çalışır.

`services` CLI ve GUI için bağlantı kontrolü/keşfi paylaşır. `pytest_bridge` mevcut
pytest eklentisini gözlemler; koşu seçimi ve rapor bağlantıları GUI katmanındadır.
Runner ve Explorer opsiyonel olay/iptal callback’leri sunar. CLI davranışı korunur.
`document` Tk bağımsız doğrulama/atomik kayıt modelidir. Her koşu ayrı artifact
klasöründe senaryo/katalog kopyaları ve kaynak bağlantılarıyla saklanır.
