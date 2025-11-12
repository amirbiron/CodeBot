(function(){
  const grid = document.getElementById('grid');
  const empty = document.getElementById('empty');
  const search = document.getElementById('search');

  function createCard(item){
    const el = document.createElement('div');
    el.className = 'card';

    // Logo container (supports image or fallback emoji)
    const logo = document.createElement('div');
    logo.className = 'logo';
    if (item.logo_url) {
      const img = document.createElement('img');
      img.src = item.logo_url;
      img.alt = (item.title || 'logo');
      img.loading = 'lazy';
      logo.appendChild(img);
    } else {
      logo.textContent = '🤖';
    }

    const body = document.createElement('div');
    const title = document.createElement('div'); title.className='title'; title.textContent = item.title || '';
    const desc = document.createElement('div'); desc.className='desc'; desc.textContent = item.description || '';
    const tags = document.createElement('div'); tags.className='tags';
    (item.tags||[]).slice(0,5).forEach(t=>{const s=document.createElement('span');s.className='tag';s.textContent=t;tags.appendChild(s)});

    const actions = document.createElement('div'); actions.className='actions';
    const openBtn = document.createElement('a'); openBtn.className='btn'; openBtn.textContent='פתח'; openBtn.href=item.url; openBtn.target='_blank';
    const shareBtn = document.createElement('button'); shareBtn.className='btn'; shareBtn.textContent='שתף';
    shareBtn.onclick = ()=>{try{navigator.clipboard.writeText(item.url)}catch(e){}};
    actions.appendChild(openBtn); actions.appendChild(shareBtn);

    // Admin controls (Edit/Delete)
    try{
      if (window.__isAdmin && item.id){
        const edit = document.createElement('a'); edit.className='btn'; edit.textContent='✏️ ערוך'; edit.href = '/admin/community/edit?id=' + encodeURIComponent(item.id);
        const del = document.createElement('button'); del.className='btn'; del.textContent='🗑️ מחק';
        del.onclick = async ()=>{
          if (!confirm('למחוק את הפריט?')) return;
          try{ const r = await fetch('/admin/community/delete?id='+encodeURIComponent(item.id), { method:'POST' }); if (r.ok){ el.remove(); } }catch(_){ }
        };
        actions.appendChild(edit); actions.appendChild(del);
      }
    } catch(_){}

    body.appendChild(title);
    body.appendChild(desc);
    body.appendChild(tags);
    body.appendChild(actions);

    el.appendChild(logo);
    el.appendChild(body);
    return el;
  }

  async function load(){
    const q = (search.value||'').trim();
    const url = '/api/community-library' + (q? ('?q='+encodeURIComponent(q)) : '');
    const resp = await fetch(url);
    const data = await resp.json().catch(()=>({ok:false}));
    if(!data.ok){ grid.innerHTML=''; empty.style.display=''; return; }
    grid.innerHTML='';
    if(!data.items || data.items.length===0){ empty.style.display=''; return; }
    empty.style.display='none';
    data.items.forEach(it=> grid.appendChild(createCard(it)));
  }

  // Load on input change (including clearing the field)
  search.addEventListener('input', ()=>{ const v=search.value||''; if(v.length===0 || v.length>2){ load(); }});
  load();
})();