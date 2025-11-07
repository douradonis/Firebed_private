(function(){
  if (window.__char_profiles__) return;
  window.__char_profiles__ = true;

  const $ = s => document.querySelector(s);
  const $$ = s => Array.from(document.querySelectorAll(s));

  function rowTpl(key,val){
    return `
    <div class="flex items-center gap-2" data-row>
      <input type="text" class="border rounded px-2 py-1 w-40" data-key placeholder="ΦΠΑ Α/Β/Γ/Δ" value="${key||''}"/>
      <input type="text" class="border rounded px-2 py-1 flex-1" data-val placeholder="χαρακτηρισμός" list="charOpts" value="${val||''}"/>
      <button type="button" class="px-2 py-1 border rounded" data-del>🗑</button>
    </div>`;
  }

  function renderRows(map){
    const box = $('#rows'); box.innerHTML='';
    const entries = Object.entries(map||{});
    if (!entries.length){
      ['ΦΠΑ Α','ΦΠΑ Β','ΦΠΑ Γ','ΦΠΑ Δ'].forEach(k=> box.insertAdjacentHTML('beforeend', rowTpl(k,'')));
    } else {
      entries.forEach(([k,v])=> box.insertAdjacentHTML('beforeend', rowTpl(k,v)));
    }
  }

  function collectMap(){
    const m = {};
    $$('#rows [data-row]').forEach(row=>{
      const k = row.querySelector('[data-key]').value.trim();
      const v = row.querySelector('[data-val]').value.trim();
      if (k && v) m[k] = v;
    });
    return m;
  }

  function load(){
    fetch('/api/profiles', {credentials:'same-origin'})
      .then(r=>r.json()).then(j=>{
        const dl = document.getElementById('charOpts') || document.createElement('datalist');
        dl.id = 'charOpts'; dl.innerHTML='';
        (j.options || []).forEach(o=>{
          const opt = document.createElement('option'); opt.value = o; dl.appendChild(opt);
        });
        document.body.appendChild(dl);

        const list = $('#list'); list.innerHTML='';
        (j.profiles||[]).forEach(p=>{
          const el = document.createElement('div');
          el.className = 'py-2 flex items-center justify-between';
          el.innerHTML = `
            <div>
              <div class="font-medium">${p.name}</div>
              <div class="text-xs text-gray-500">${Object.keys(p.map||{}).length} κατηγορίες</div>
            </div>
            <div class="flex gap-2">
              <button data-edit="${p.id}" class="px-2 py-1 border rounded">Επεξεργασία</button>
              <button data-del="${p.id}" class="px-2 py-1 border rounded text-red-600">Διαγραφή</button>
            </div>`;
          list.appendChild(el);
        });

        list.onclick = function(e){
          const t = e.target;
          if (t.dataset.edit){
            const id = t.dataset.edit;
            const p = (j.profiles||[]).find(x=>String(x.id)===String(id));
            if (!p) return;
            $('#profName').value = p.name || '';
            $('#profName').dataset.id = p.id;
            renderRows(p.map||{});
          } else if (t.dataset.del){
            fetch('/api/profiles/delete', {method:'POST', headers:{'content-type':'application/json'}, body:JSON.stringify({id:t.dataset.del}), credentials:'same-origin'})
              .then(()=> load());
          }
        };
      });
  }

  function save(){
    const name = $('#profName').value.trim();
    if (!name){ alert('Δώσε όνομα προφίλ'); return; }
    const map = collectMap();
    fetch('/api/profiles/save', {
      method:'POST', credentials:'same-origin',
      headers:{'content-type':'application/json'},
      body: JSON.stringify({ id: $('#profName').dataset.id || null, name, map })
    }).then(r=>r.json()).then(()=>{
      $('#profName').value=''; delete $('#profName').dataset.id;
      renderRows({});
      load();
    });
  }

  document.addEventListener('DOMContentLoaded', function(){
    document.body.insertAdjacentHTML('beforeend','<datalist id="charOpts"></datalist>');
    $('#addRow').onclick = ()=> $('#rows').insertAdjacentHTML('beforeend', rowTpl('',''));
    $('#rows').onclick = e=>{ if (e.target && e.target.dataset.del){ e.target.closest('[data-row]')?.remove(); } };
    $('#saveProf').onclick = save;
    $('#newProf').onclick  = ()=>{ $('#profName').value=''; delete $('#profName').dataset.id; renderRows({}); };

    renderRows({});
    load();
  });
})();
