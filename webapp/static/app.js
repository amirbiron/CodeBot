const state = window.__state || { page:1, per_page:50, mode:'other', selected:new Set() };
const els = {
  tabOther: document.getElementById('tab-other'),
  tabRepo: document.getElementById('tab-repo'),
  repoTag: document.getElementById('repoTag'),
  userId: document.getElementById('userId'),
  search: document.getElementById('search'),
  refresh: document.getElementById('refresh'),
  bulkDelete: document.getElementById('bulkDelete'),
  selectAll: document.getElementById('selectAll'),
  rows: document.getElementById('rows'),
  meta: document.getElementById('meta'),
  prev: document.getElementById('prev'),
  next: document.getElementById('next'),
  pageInfo: document.getElementById('pageInfo'),
  toast: document.getElementById('toast'),
};

function toast(msg){
  els.toast.textContent = msg; els.toast.classList.remove('hidden');
  setTimeout(()=> els.toast.classList.add('hidden'), 1800);
}

function setMode(mode){
  state.mode = mode; state.page = 1; state.selected = new Set();
  els.tabOther.classList.toggle('active', mode==='other');
  els.tabRepo.classList.toggle('active', mode==='repo');
  els.repoTag.classList.toggle('hidden', mode!=='repo');
  render();
}

async function fetchData(){
  const base = state.mode === 'other' ? '/api/files/other' : '/api/files/by_repo';
  const params = new URLSearchParams();
  const user = parseInt(els.userId.value||'0',10);
  if(!user){ throw new Error('User ID נדרש'); }
  params.set('user_id', String(user));
  params.set('page', String(state.page));
  params.set('per_page', String(state.per_page));
  if(state.mode==='other'){
    const q = (els.search.value||'').trim(); if(q) params.set('q', q);
  } else {
    const tag = (els.repoTag.value||'').trim(); if(!tag) throw new Error('repo:owner/name נדרש');
    params.set('repo_tag', tag);
  }
  const res = await fetch(`${base}?${params.toString()}`);
  if(!res.ok){ throw new Error('API error'); }
  return res.json();
}

function renderRows(items){
  els.rows.innerHTML = '';
  for(const it of items){
    const tr = document.createElement('tr');
    const checked = state.selected.has(it.id);
    tr.innerHTML = `
      <td><input type="checkbox" ${checked?'checked':''} data-id="${it.id}" class="rowChk"/></td>
      <td>${it.file_name||''}</td>
      <td>${it.programming_language||''}</td>
      <td>${(it.updated_at||'').toString().slice(0,19).replace('T',' ')}</td>
    `;
    els.rows.appendChild(tr);
  }
}

async function render(){
  try{
    const data = await fetchData();
    renderRows(data.items||[]);
    const total = data.total||0; const page = data.page||1; const per = data.per_page||state.per_page;
    const pages = Math.max(1, Math.ceil(total/per));
    els.pageInfo.textContent = `עמוד ${page}/${pages} • סה"כ ${total}`;
    els.prev.disabled = page<=1; els.next.disabled = page>=pages;
    els.meta.textContent = state.mode==='other' ? 'תצוגה: שאר הקבצים' : `תצוגה: לפי ריפו — ${els.repoTag.value||''}`;
    els.selectAll.checked = false;
    els.bulkDelete.disabled = state.selected.size===0;
  }catch(e){ toast(String(e.message||e)); }
}

// אירועים
els.tabOther.addEventListener('click', ()=> setMode('other'));
els.tabRepo.addEventListener('click', ()=> setMode('repo'));
els.refresh.addEventListener('click', ()=> render());
els.search.addEventListener('input', ()=> { if(state.mode==='other'){ state.page=1; render(); }});
els.prev.addEventListener('click', ()=> { if(state.page>1){ state.page--; render(); }});
els.next.addEventListener('click', ()=> { state.page++; render(); });
els.selectAll.addEventListener('change', (e)=>{
  document.querySelectorAll('.rowChk').forEach(chk=>{
    const id = chk.getAttribute('data-id');
    chk.checked = e.target.checked;
    if(e.target.checked) state.selected.add(id); else state.selected.delete(id);
  });
  els.bulkDelete.disabled = state.selected.size===0;
});

els.rows.addEventListener('change', (e)=>{
  if(e.target && e.target.classList.contains('rowChk')){
    const id = e.target.getAttribute('data-id');
    if(e.target.checked) state.selected.add(id); else state.selected.delete(id);
    els.bulkDelete.disabled = state.selected.size===0;
  }
});

els.bulkDelete.addEventListener('click', async ()=>{
  if(state.selected.size===0) return;
  if(!confirm(`למחוק ${state.selected.size} קבצים (מחיקה רכה)?`)) return;
  const user = parseInt(els.userId.value||'0',10);
  if(!user){ toast('User ID נדרש'); return; }
  const res = await fetch('/api/files/bulk_delete', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ user_id:user, ids:[...state.selected] })
  });
  if(!res.ok){ toast('שגיאה במחיקה'); return; }
  const out = await res.json();
  toast(`נמחקו ${out.deleted||0}`);
  state.selected = new Set();
  render();
});

// init
render();

