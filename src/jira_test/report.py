"""Self-contained, escaped HTML catalogs with search and YAML template downloads."""

import html
import json
from dataclasses import asdict
from pathlib import Path

from .catalog import Catalog


def render_catalog(catalog: Catalog) -> str:
    rows = []
    for index, item in enumerate(catalog.observations):
        values = [
            item.issue_type,
            item.screen,
            item.status or "—",
            item.transition or "—",
            item.field,
            item.name,
            item.source,
            item.required,
            item.visible,
            item.editable,
        ]
        cells = "".join(
            f"<td>{html.escape(str(v if v is not None else 'unknown'))}</td>" for v in values
        )
        details = html.escape(json.dumps(asdict(item), ensure_ascii=False, indent=2))
        rows.append(
            f"<tr>{cells}<td><details><summary>Metadata</summary><pre>{details}</pre>"
            f'</details><button data-index="{index}">YAML</button></td></tr>'
        )
    gaps = "".join(
        f"<li>{html.escape(json.dumps(gap, ensure_ascii=False))}</li>" for gap in catalog.gaps
    )
    # JSON in a script element must escape HTML delimiters, even though it is inert data.
    payload = json.dumps([asdict(item) for item in catalog.observations], ensure_ascii=False)
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return (
        _HTML.replace("{{project}}", html.escape(catalog.project))
        .replace("{{created}}", html.escape(catalog.created_at))
        .replace("{{rows}}", "".join(rows))
        .replace("{{gaps}}", gaps)
        .replace("{{data}}", payload)
    )


def write_catalog_report(catalog: Catalog, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    catalog.save(directory / "catalog.json")
    (directory / "catalog.html").write_text(render_catalog(catalog), encoding="utf-8")


_HTML = """<!doctype html>
<html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Jira explorer</title>
<style>
body{font:15px system-ui;margin:2rem;background:#f6f8fa;color:#14202d}
input,select,button{padding:.5rem;margin:.3rem;border:1px solid #a8b8c8;border-radius:4px}
table{border-collapse:collapse;background:white;width:100%}td,th{padding:.5rem;text-align:left;
border-bottom:1px solid #dde3e9}th{background:#e6edf5}section{overflow:auto}li{margin:.5rem}
</style>
<h1>Jira explorer · {{project}}</h1><p>Keşif zamanı: {{created}}</p>
<p>API ve UI gözlemleri ayrı satırlardır. unknown, doğrulanmış false anlamına gelmez.
YAML düğmesi katalog sorgusu taslağı indirir; davranış testi için uyarlayın.</p>
<label>Ara <input id="search" placeholder="Alan kimliği veya adı"></label>
<label>Issue türü <select id="type"><option value="">Tümü</option></select></label>
<label>Ekran <select id="screen"><option value="">Tümü</option></select></label>
<label>Statü <select id="status"><option value="">Tümü</option></select></label>
<section><table><thead><tr><th>Tür</th><th>Ekran</th><th>Statü</th><th>Geçiş</th>
<th>Alan ID</th><th>Ad</th><th>Kaynak</th><th>Zorunlu</th><th>Görünür</th>
<th>Düzenlenebilir</th><th>Taslak</th></tr></thead><tbody>{{rows}}</tbody></table></section>
<h2>Kapsam eksikleri</h2><ul>{{gaps}}</ul>
<script type="application/json" id="metadata">{{data}}</script>
<script>
const observations=JSON.parse(document.getElementById('metadata').textContent);
const rows=[...document.querySelectorAll('tbody tr')];
const filters=[['type','issue_type'],['screen','screen'],['status','status']];
for(const [id,key] of filters){const el=document.getElementById(id);
for(const value of [...new Set(observations.map(x=>x[key]).filter(Boolean))].sort()){
const o=document.createElement('option');o.value=value;o.textContent=value;el.append(o);}}
function filter(){const text=document.getElementById('search').value.toLowerCase();
rows.forEach((row,i)=>{const x=observations[i];row.hidden=!
(row.textContent.toLowerCase().includes(text)&&filters.every(([id,key])=>
!document.getElementById(id).value||document.getElementById(id).value===x[key]));});}
document.querySelectorAll('input,select').forEach(el=>el.addEventListener('input',filter));
function q(value){return JSON.stringify(String(value));}
document.querySelectorAll('button[data-index]').forEach(button=>button.addEventListener('click',()=>{
const x=observations[Number(button.dataset.index)];
let text='id: '+q('catalog-'+x.field)+'\\nfixture:\\n  mode: none\\n  issue_type: '+q(x.issue_type)+
'\\n  catalog: artifacts/explorer/catalog.json\\nsteps: []\\nexpect:\\n'+
'  - check: catalog_exists\\n    field: '+q(x.field)+
'\\n    screen: '+q(x.screen)+'\\n    source: '+q(x.source)+'\\n    value: '+
String(x.source==='ui' ? x.visible : true)+'\\n';
if(x.status)text+='    status: '+q(x.status)+'\\n';
if(x.transition)text+='    transition: '+q(x.transition)+'\\n';
const url=URL.createObjectURL(new Blob([text],{type:'text/yaml'}));
const a=document.createElement('a');
a.href=url;a.download='catalog-test.yaml';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}));
</script></html>"""
