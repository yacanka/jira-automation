# Jira test otomasyonu

Jira Data Center projelerini keşfeden ve kullanıcı davranışlarını Selenium ile
sınayan modüler Python sistemi. Yeni testler YAML ile yazılır; özel ihtiyaçlar
aynı komponentleri kullanan pytest testleriyle genişletilir.

## Kurulum

Python 3.11+ ve Chrome veya Firefox gerekir.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp config.example.yaml config.local.yaml
```

`config.local.yaml` içine Jira adresini, kaynak ve ayrı test projesini yazın.
Kimlik bilgilerini dosyaya yazmadan terminalde alın (zsh):

```sh
read 'JIRA_USERNAME?Jira kullanıcı adı: '
read -s 'JIRA_PASSWORD?Jira parolası: '
export JIRA_USERNAME JIRA_PASSWORD
```

Bash kullanıyorsanız `read -r -p ...` ve parola için `read -r -s -p ...` kullanın.
CI'da aynı değişkenleri secret store'dan sağlayın. Selenium Manager gerekirse
sürücü indirir; internetsiz ortamda uyumlu sürücüyü `driver_path` ile belirtin.
Kurum CA sertifikası REST için `verify_tls` üzerinden, tarayıcı için işletim
sistemi/tarayıcı güven deposundan tanımlanır; TLS kontrolü kapatılamaz.

## Hızlı başlangıç

```sh
jira-test doctor --config config.local.yaml
jira-test explore --config config.local.yaml --project DEMO
jira-test query --catalog artifacts/explorer/catalog.json --field summary --screen create
```

`artifacts/explorer/catalog.html` dosyasını tarayıcıda açın. Alan, ekran, issue türü
ve statüye göre filtreleyin; YAML düğmesi katalog assertion taslağı indirir.
API ve UI gözlemleri farklı satırlardadır. `unknown` gözlemlenemeyen bağlamdır.
Explorer kayıt oluşturmaz, kaydetmez veya workflow geçişi gerçekleştirmez.

Örnekleri önce kendi çalışma dizininize kopyalayın ve kimlikleri uyarlayın:

```sh
cp -R examples/yaml my-scenarios
jira-test validate --suite my-scenarios
jira-test run --suite my-scenarios/09_edit_text.yaml \
  --config config.local.yaml --test-project AUTOTEST
```

Bir klasördeki tüm senaryoları çalıştırmak için `--suite my-scenarios` kullanın.
Her senaryo bağımsız fixture kullanır. Gerçek veri setini uyarlamadan 20 örneği
birden çalıştırmayın: bazı örnekler özel workflow/validator önkoşulları gerektirir.
Test kayıtları otomatik silinmez; çalıştırma kimliği summary önekinde ve
`artifacts/test-results.json` dosyasında bulunur.

## Jira bağlantısı olmadan deneyin

```sh
jira-test validate --suite examples/yaml
jira-test query --catalog examples/demo-catalog.json --field summary --source api
jira-test run --suite examples/yaml/05_required_metadata.yaml \
  --catalog examples/demo-catalog.json
```

Demo katalog sentetiktir; canlı Jira hakkında kanıt oluşturmaz. Ayrıca
`python -m jira_test ...` biçimiyle CLI çalıştırılabilir.

## Belgeler ve örnekler

- [Kullanım ve senaryo referansı](docs/usage.md)
- [20 YAML örneğinin önkoşulları ve beklenen sonuçları](examples/README.md)
- [Komponent geliştirme ve mimari](docs/architecture.md)
- [4 Python örneği](examples/python/)
- [Yerel doğrulama kaydı](docs/implementation.md)

## Doğrulama

```sh
pytest
ruff check src tests examples/python
ruff format --check src tests examples/python
mypy src/jira_test
python -m build --no-isolation
```

Canlı Jira testleri yerel birim testlerine dahil değildir. Python örneklerini
çalıştırmak için `pytest examples/python --jira-config config.local.yaml` kullanın.
YAML örnekleri `pytest examples/yaml --jira-suite examples/yaml --jira-config
config.local.yaml` ile de toplanır. `--collect-only` canlı bağlantı kurmadan
koleksiyonu kontrol eder.

## Sınırlar

İlk sürüm modern Data Center REST v2 oluşturma metadatası uçlarını kullanır
(Jira 8.4+). Sürümünüze veya temanıza göre locator override gerekebilir. SSO/MFA
ve CAPTCHA otomasyonu desteklenmez; kurumsal politika REST basic authentication'ı
engellerse explorer sınırlı tarayıcı keşfine geçer, davranış testleri engellenir.

Standart Jira alan komponentleri hazırdır. ScriptRunner veya başka eklentilerin
özel widget'ları için adaptör gerekir. Dinamik zorunluluklar ve validator'lar
salt metadata ile kanıtlanmaz; koşulları içeren canlı test gerekir. Keşif,
örnek issue'ların ve kullanıcı yetkilerinin erişebildiği bağlamlarla sınırlıdır.
Test projesi sonuçları, kaynak projenin alan/ekran/workflow/izin yapılandırmaları
eşleştiği ölçüde kaynak projeyi temsil eder.
