# Uygulama kaydı

Onaylanan plan: Jira Data Center, tek kullanıcı, ayrı test projesi, salt okunur
explorer, Selenium + REST, YAML + Python, HTML + JSON ve öğretici örnekler.

Karar: klasör Git deposu olmadığı için worktree/commit oluşturulmayacak; mevcut
boş çalışma klasörü kullanılacak.

Karar: HTTPS zorunlu; test kaydı silme endpoint'i sunulmayacak. Explorer ham issue
verilerini değil alan metadatasını kaydedecek. Ekran görüntüleri kapalı başlayacak.

İş sırası: bağlantı → explorer/komponentler → senaryo motoru → örnekler → doğrulama.

## Tamamlananlar

- Paket/CLI, bağlantı kontrolü, bounded REST istemcisi ve Selenium oturum yönetimi.
- Standart alan komponentleri, salt okunur API/UI explorer ve browser-only fallback.
- Ayrı API/UI gözlemleri, JSON katalog, filtrelenebilir HTML ve YAML taslak indirme.
- Strict YAML doğrulama, pytest collection, fixture/transition hazırlığı ve kalıcı assertion'lar.
- 20 YAML senaryosu, 4 Python öğretici modülü (parametrik örnekle 6 test).
- Bağımsız inceleme bulguları regresyon testleriyle düzeltildi: blank CA, parent kimlik
  çakışması, list projection, screenless/form completion ve browser login cleanup.

## Doğrulama

Python 3.14.6 ile: 54 yerel birim/entegrasyon testi, gerçek Chrome 154 üzerinde
8 sentetik Selenium testi ve demo katalogla 5 YAML senaryosu geçti. 20 YAML ve
6 Python testinin offline collection kontrolü geçti. Ruff lint/format, mypy ve
sdist/wheel build başarılı. Browser testleri yerel port için sandbox dışında çalıştı.
HTML önizlemesi görsel olarak incelendi; filtre ve YAML taslak üretimi tarayıcıda sınandı.

Canlı Jira URL/hesabı verilmedi; gerçek Jira REST/DOM uyumluluğu, workflow validator'ları,
kurumsal basic auth ve source/test proje eşleşmesi canlı ortamda doğrulanmadı.
Python 3.11 alt sınırı type checker ile kontrol edildi; runtime testleri 3.14 üzerinde.
API kabul yanıtı alınan kayıtlar, ownership doğrulaması sonradan hata verse de JSON
raporunda listelenir. Ownership doğrulanana kadar bu kayıtlar yazılabilir kabul edilmez.

Dağıtılmış wheel paketi bağımsız hedef dizine kurularak CLI validate/run kontrolü
yapıldı. CLI pytest koşuları temiz bir subprocess içinde başlatılır; pytest plugin
yükleme/assertion rewrite durumu CLI sürecinden taşınmaz.
