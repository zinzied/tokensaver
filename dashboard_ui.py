DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Token Saver Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#e6edf3;--dim:#8b949e;--accent:#2f81f7;--green:#3fb950;--yellow:#d29922;--red:#f85149;--orange:#db6d28}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;background:var(--bg);color:var(--text);display:flex;min-height:100vh}
.sidebar{width:240px;background:var(--card);border-right:1px solid var(--border);padding:16px 0;flex-shrink:0;overflow-y:auto}
.sidebar h2{padding:0 16px;font-size:14px;color:var(--accent);margin-bottom:12px}
.sidebar .nav-item{padding:8px 16px;cursor:pointer;font-size:13px;color:var(--dim);display:flex;align-items:center;gap:8px;transition:.15s}
.sidebar .nav-item:hover{color:var(--text);background:rgba(255,255,255,.04)}
.sidebar .nav-item.active{color:var(--text);background:rgba(47,129,247,.12);border-right:2px solid var(--accent)}
.main{flex:1;padding:24px;overflow-y:auto;max-height:100vh}
.page{display:none}.page.active{display:block}
h1{font-size:24px;margin-bottom:4px}
.sub{color:var(--dim);font-size:13px;margin-bottom:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px}
.card h2{font-size:14px;color:var(--dim);margin-bottom:12px;display:flex;align-items:center;gap:6px}
.card .row{display:flex;justify-content:space-between;padding:4px 0;font-size:13px}
.card .row .label{color:var(--dim)}
.card .row .value{font-weight:500}
.green{color:var(--green)}.yellow{color:var(--yellow)}.red{color:var(--red)}
.status-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.status-dot.green{background:var(--green)}
.status-dot.red{background:var(--red)}
.status-dot.yellow{background:var(--yellow)}
.table-wrap{overflow-x:auto;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:12px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:8px 12px;color:var(--dim);border-bottom:1px solid var(--border);font-weight:500}
td{padding:8px 12px;border-bottom:1px solid var(--border)}
tr:last-child td{border-bottom:none}
.bar-wrap{display:flex;align-items:center;gap:8px}
.bar{flex:1;height:6px;background:var(--border);border-radius:3px;overflow:hidden}
.bar-fill{height:100%;border-radius:3px;transition:width .5s}
.bar-fill.green{background:var(--green)}
.bar-fill.yellow{background:var(--yellow)}
.bar-fill.red{background:var(--red)}
.btn{background:var(--accent);color:#fff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:12px;transition:.15s}
.btn:hover{opacity:.85}
.btn-sm{padding:4px 10px;font-size:11px}
.btn-outline{background:transparent;border:1px solid var(--border);color:var(--text)}
.tabs{display:flex;gap:4px;margin-bottom:16px;border-bottom:1px solid var(--border)}
.tab{padding:8px 16px;cursor:pointer;font-size:13px;color:var(--dim);border-bottom:2px solid transparent}
.tab.active{color:var(--accent);border-bottom-color:var(--accent)}
.log-entry{padding:4px 0;font-size:12px;font-family:monospace;border-bottom:1px solid var(--border)}
.log-entry .time{color:var(--dim);margin-right:8px}
.log-entry .level{display:inline-block;width:48px;font-weight:500}
.level-LOG{color:var(--dim)}.level-INFO{color:var(--accent)}.level-WARN{color:var(--yellow)}.level-ERROR{color:var(--red)}.level-DEBUG{color:#8b5cf6}
.ml-auto{margin-left:auto}
.flex{display:flex;align-items:center;gap:8px}
.mb-8{margin-bottom:8px}
.mt-8{margin-top:8px}
.p-4{padding:4px}
.text-dim{color:var(--dim)}
.text-sm{font-size:12px}
.gap-4{gap:4px}
.w-full{width:100%}
pre{background:rgba(0,0,0,.3);padding:12px;border-radius:6px;overflow-x:auto;font-size:12px;max-height:400px}
input,select{background:var(--bg);border:1px solid var(--border);color:var(--text);padding:6px 10px;border-radius:6px;font-size:12px}
input:focus,select:focus{outline:none;border-color:var(--accent)}
label{font-size:12px;color:var(--dim);display:block;margin-bottom:4px}
.accordion{background:var(--card);border:1px solid var(--border);border-radius:8px;margin-bottom:8px;overflow:hidden}
.accordion-header{padding:12px 16px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;font-size:13px}
.accordion-header:hover{background:rgba(255,255,255,.03)}
.accordion-body{padding:0 16px 12px;display:none;font-size:13px}
.accordion.open .accordion-body{display:block}
.tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;background:rgba(47,129,247,.15);color:var(--accent)}
.tag.green{background:rgba(63,185,80,.15);color:var(--green)}
.tag.red{background:rgba(248,81,73,.15);color:var(--red)}
.tag.yellow{background:rgba(210,153,34,.15);color:var(--yellow)}
.refresh-note{color:var(--dim);font-size:11px;margin-top:8px}
</style>
</head>
<body>
<div class="sidebar">
<h2>&#9632; Token Saver</h2>
<div class="nav-item active" data-page="overview">&#9201; Overview</div>
<div class="nav-item" data-page="usage">&#128200; Usage</div>
<div class="nav-item" data-page="quota">&#128274; Quota</div>
<div class="nav-item" data-page="translator">&#128214; Translator</div>
<div class="nav-item" data-page="routing">&#128279; Routing</div>
<div class="nav-item" data-page="providers">&#127760; Providers</div>
<div class="nav-item" data-page="console">&#128424; Console Log</div>
<div class="nav-item" data-page="chat">&#128172; Chat</div>
<div class="nav-item" data-page="settings">&#9881; Settings</div>
</div>
<div class="main" id="main">

<!-- OVERVIEW -->
<div class="page active" id="page-overview">
<h1>Overview</h1>
<div class="sub" id="ov-sub">Model: <span id="ov-model">-</span> &middot; Small: <span id="ov-small">-</span> &middot; <span id="ov-ts">loading...</span></div>
<div class="grid">
<div class="card" style="border-color:var(--green)"><h2>&#127942; Total Savings</h2><div id="ov-total-saved"><div class="row"><span class="label">Loading...</span></div></div></div>
<div class="card"><h2>&#128230; Content Cache</h2><div id="ov-cache"><div class="row"><span class="label">Loading...</span></div></div></div>
<div class="card"><h2>&#128176; Savings Ledger</h2><div id="ov-savings"><div class="row"><span class="label">Loading...</span></div></div></div>
<div class="card"><h2>&#128274; Compression Proxy</h2><div id="ov-proxy"><div class="row"><span class="label">Loading...</span></div></div></div>
<div class="card"><h2>&#128200; Budget Planner</h2><div id="ov-budget"><div class="row"><span class="label">Loading...</span></div></div></div>
<div class="card"><h2>&#128451; Content Store</h2><div id="ov-store"><div class="row"><span class="label">Loading...</span></div></div></div>
<div class="card"><h2>&#128279; Fallback Chains</h2><div id="ov-fallback"><div class="row"><span class="label">Loading...</span></div></div></div>
<div class="card"><h2>&#9889; RTK Filters</h2><div id="ov-rtk"><div class="row"><span class="label">Loading...</span></div></div></div>
<div class="card"><h2>&#128202; Quota Tracking</h2><div id="ov-quota"><div class="row"><span class="label">Loading...</span></div></div></div>
</div>
<div class="refresh-note">Auto-refresh every 5s &middot; &#9432; Costs shown are estimated savings, not actual billing.</div>
</div>

<!-- USAGE -->
<div class="page" id="page-usage">
<h1>Usage</h1>
<div class="sub">Provider request volume and token consumption. "Saved" shows estimated cost of paid APIs you avoided.</div>
<div class="tabs"><div class="tab active" data-usage-tab="overview">Overview</div><div class="tab" data-usage-tab="details">Details</div></div>
<div id="usage-overview" class="usage-tab-content">
<div class="grid" id="usage-cards"></div>
</div>
<div id="usage-details" class="usage-tab-content" style="display:none">
<div class="table-wrap"><table><thead><tr><th>Provider</th><th>Model</th><th>Tokens In</th><th>Tokens Out</th><th>Saved</th><th>Requests</th><th>Last</th></tr></thead><tbody id="usage-tbody"></tbody></table></div>
<div class="refresh-note" style="color:var(--accent)">&#9432; "Saved" shows estimated cost if you used paid APIs directly. You actually pay $0 with free tiers.</div>
</div>
<div class="refresh-note">Auto-refresh every 10s</div>
</div>

<!-- QUOTA -->
<div class="page" id="page-quota">
<h1>Quota</h1>
<div class="sub">Per-provider quota usage and reset countdowns. "Saved" shows estimated cost of paid APIs.</div>
<div id="quota-cards" class="grid"></div>
<div class="refresh-note">Auto-refresh every 15s</div>
</div>

<!-- TRANSLATOR -->
<div class="page" id="page-translator">
<h1>Format Translator</h1>
<div class="sub">Inspect format translation between API formats</div>
<div class="grid">
<div class="card"><h2>Source Format</h2><div><span id="src-fmt" class="tag">-</span></div><br><textarea id="src-json" rows="6" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:6px;padding:8px;font-size:12px;font-family:monospace" placeholder='{"messages":[{"role":"user","content":"hello"}]}'></textarea></div>
<div class="card"><h2>Target Format</h2><div><span id="tgt-fmt" class="tag">-</span></div><br><pre id="tgt-json" style="min-height:100px">Select source format and translate</pre></div>
</div>
<div class="flex" style="gap:8px;margin-top:8px">
<select id="fmt-target"><option value="openai">OpenAI</option><option value="claude">Claude</option><option value="gemini">Gemini</option></select>
<button class="btn" onclick="translateFormat()">&#9654; Translate</button>
<button class="btn btn-outline" onclick="detectFormat()">&#128270; Detect</button>
</div>
</div>

<!-- ROUTING -->
<div class="page" id="page-routing">
<h1>Routing</h1>
<div class="sub">3-tier fallback chains: Subscription &rarr; Cheap &rarr; Free</div>

<div style="margin-bottom:16px">
<h2 style="font-size:16px;margin-bottom:12px">&#127919; Preset Combos</h2>
<p style="color:var(--dim);font-size:12px;margin-bottom:12px">One-click provider chains for common scenarios. Click "Apply" to activate.</p>
<div class="grid" id="preset-combos"></div>
</div>

<div>
<h2 style="font-size:16px;margin-bottom:12px">&#128279; Active Fallback Chains</h2>
<div id="routing-tiers"></div>
</div>
</div>

<!-- PROVIDERS -->
<div class="page" id="page-providers">
<h1>Providers</h1>
<div class="sub">Configured providers and their status</div>
<div id="providers-table" class="table-wrap"><table><thead><tr><th>Provider</th><th>Status</th><th>Tier</th><th>Models</th><th>Actions</th></tr></thead><tbody id="providers-tbody"></tbody></table></div>
<div class="refresh-note">Auto-refresh every 30s</div>
</div>

<!-- CONSOLE LOG -->
<div class="page" id="page-console">
<div class="flex mb-8"><h1>Console Log</h1><button class="btn btn-sm btn-outline ml-auto" onclick="clearLog()">&#128465; Clear</button></div>
<div class="sub">Real-time proxy and translation logs</div>
<div id="log-container" style="background:rgba(0,0,0,.3);border:1px solid var(--border);border-radius:8px;padding:12px;max-height:600px;overflow-y:auto;font-family:monospace;font-size:12px"></div>
</div>

<!-- CHAT -->
<div class="page" id="page-chat">
<h1>Basic Chat</h1>
<div class="sub">Test chat against a provider</div>
<div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:12px;max-height:400px;overflow-y:auto" id="chat-messages">
<div class="text-dim text-sm">Select a provider and model, then send a message.</div>
</div>
<div class="flex" style="gap:8px">
<select id="chat-provider" style="flex:1"><option value="">Select provider...</option></select>
<select id="chat-model" style="flex:1"><option value="">Select model...</option></select>
</div>
<div class="flex mt-8" style="gap:8px">
<input id="chat-input" type="text" style="flex:3" placeholder="Type a message..." onkeydown="if(event.key==='Enter')sendChat()">
<button class="btn" onclick="sendChat()">Send</button>
</div>
</div>

<!-- SETTINGS -->
<div class="page" id="page-settings">
<h1>Settings</h1>
<div class="sub">Dashboard and routing preferences</div>
<div class="grid">
<div class="card"><h2>&#128260; Proxy</h2><div id="settings-proxy"></div></div>
<div class="card"><h2>&#128200; Routing</h2><div id="settings-routing"></div></div>
<div class="card"><h2>&#9200; Refresh</h2><div id="settings-refresh"></div></div>
<div class="card"><h2>&#128190; Database</h2><div id="settings-db"></div></div>
</div>
</div>

</div>
<script>
let logs = [];
function showPage(name){
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n=>n.classList.remove('active'));
  document.getElementById('page-'+name).classList.add('active');
  document.querySelector(`.nav-item[data-page="${name}"]`).classList.add('active');
  if(name==='overview')loadOverview();
  if(name==='usage')loadUsage();
  if(name==='quota')loadQuota();
  if(name==='routing')loadRouting();
  if(name==='providers')loadProviders();
  if(name==='chat')loadChatProviders();
}
document.querySelectorAll('.nav-item').forEach(n=>n.addEventListener('click',()=>showPage(n.dataset.page)));

// ---- OVERVIEW ----
async function loadOverview(){
  try{
    const r=await fetch('/api/stats');const d=await r.json();
    document.getElementById('ov-model').textContent=d.model.model||'-';
    document.getElementById('ov-small').textContent=d.model.small_model||'-';
    document.getElementById('ov-ts').textContent=new Date(d.timestamp).toLocaleTimeString();
    const totalSaved=(d.proxy.total_saved_tokens||0)+(d.savings.total_saved_tokens||0)+(d.cache.total_savings_tokens||0);
    setCard('ov-total-saved',[['You Paid','$0.00','green'],['Would Have Paid','$'+((d.quota?.total_cost||0)).toFixed(2)],['Tokens Saved',totalSaved.toLocaleString()+' tokens','green'],['Filters Active',d.rtk?.filters||12]]);
    setCard('ov-cache',[['Cached Files',d.cache.cached_files||0],['Total Saved',(d.cache.total_savings_tokens||0).toLocaleString()+' tokens','green'],['Compression',(d.cache.total_savings_pct||0).toFixed(1)+'%','yellow']]);
    setCard('ov-savings',[['Entries',d.savings.total_entries||0],['Total Saved',(d.savings.total_saved_tokens||0).toLocaleString()+' tokens','green'],['Compression',(d.savings.compression_pct||0)+'%','yellow']]);
    const pStat=d.proxy.running?'green':'red';const pTxt=d.proxy.running?'Running':'Stopped';
    setCard('ov-proxy',[['Status','<span class="status-dot '+pStat+'"></span>'+pTxt],['Port',d.proxy.port||'-'],['Requests',d.proxy.requests_served||0],['Tokens Saved','<span class="green">'+(d.proxy.total_saved_tokens||0).toLocaleString()+'</span>'],['FROST Saved','<span class="green">'+(d.proxy.frost_total_saved_tokens||0).toLocaleString()+'</span>']]);
    setCard('ov-budget',[['Plan Active',d.budget.has_plan?'Yes':'No'],['Budget Limit',(d.budget.budget_limit||0).toLocaleString()],['Allocated',(d.budget.total_allocated||0).toLocaleString()]]);
    setCard('ov-store',[['Entries',d.store.entries||0],['Total Bytes',(d.store.total_bytes||0).toLocaleString()]]);
    setCard('ov-fallback',[['Chains',d.fallback.chains||0]]);
    setCard('ov-rtk',[['Filters Available',d.rtk?.filters||12],['Filters Auto-Detect','<span class="green">Enabled</span>']]);
    setCard('ov-quota',[['Providers Tracked',d.quota?.tracked||0],['Rate Limited',d.quota?.rate_limited||0,'yellow']]);
  }catch(e){document.getElementById('ov-sub').textContent='Error loading stats'}
}
function setCard(id,rows){
  const el=document.getElementById(id);
  el.innerHTML=rows.map(r=>'<div class="row"><span class="label">'+r[0]+'</span><span class="value'+(r[2]?' '+r[2]:'')+'">'+r[1]+'</span></div>').join('');
}
setInterval(loadOverview,5000);

// ---- USAGE ----
document.querySelectorAll('[data-usage-tab]').forEach(t=>t.addEventListener('click',function(){
  document.querySelectorAll('[data-usage-tab]').forEach(x=>x.classList.remove('active'));
  this.classList.add('active');
  document.querySelectorAll('.usage-tab-content').forEach(x=>x.style.display='none');
  document.getElementById('usage-'+this.dataset.usageTab).style.display='block';
  loadUsage();
}));
async function loadUsage(){
  try{
    const r=await fetch('/api/usage');const d=await r.json();
    if(d.cards){
      document.getElementById('usage-cards').innerHTML=
        Object.entries(d.cards).map(([k,v])=>'<div class="card"><h2>'+k+'</h2><div class="row"><span class="value" style="font-size:24px">'+v+'</span></div></div>').join('');
    }
    if(d.details){
      document.getElementById('usage-tbody').innerHTML=
        d.details.map(r=>'<tr><td>'+r.provider+'</td><td>'+r.model+'</td><td>'+(r.tokens_in||0).toLocaleString()+'</td><td>'+(r.tokens_out||0).toLocaleString()+'</td><td>$'+(r.cost||0).toFixed(4)+'</td><td>'+(r.requests||0)+'</td><td>'+(r.last||'')+'</td></tr>').join('');
    }
  }catch(e){}
}
setInterval(loadUsage,10000);

// ---- QUOTA ----
async function loadQuota(){
  try{
    const r=await fetch('/api/quota');const d=await r.json();
    document.getElementById('quota-cards').innerHTML=(d||[]).map(q=>{
      const pct=q.total>0?(q.remaining/q.total*100).toFixed(0):0;
      const barColor=pct>50?'green':pct>20?'yellow':'red';
      return '<div class="card"><h2>'+q.provider+' <span class="tag '+(q.rate_limited?'red':'green')+'">'+(q.rate_limited?'LIMITED':'ACTIVE')+'</span></h2>'+
        '<div class="row"><span class="label">Remaining</span><span class="value">'+q.remaining+' / '+q.total+'</span></div>'+
        '<div class="row"><span class="label">Usage</span><span class="bar-wrap"><div class="bar"><div class="bar-fill '+barColor+'" style="width:'+pct+'%"></div></div><span>'+pct+'%</span></span></div>'+
        '<div class="row"><span class="label">Reset</span><span class="value text-sm">'+(q.reset_in||'N/A')+'</span></div>'+
        (q.cost?'<div class="row"><span class="label">Saved</span><span class="value green">$'+q.cost.toFixed(4)+'</span></div>':'')+'</div>';
    }).join('');
  }catch(e){}
}
setInterval(loadQuota,15000);

// ---- TRANSLATOR ----
async function detectFormat(){
  const txt=document.getElementById('src-json').value;
  if(!txt)return;
  try{
    const r=await fetch('/api/translate/detect',{method:'POST',body:txt,headers:{'Content-Type':'application/json'}});
    const d=await r.json();
    document.getElementById('src-fmt').textContent=d.format||'unknown';
  }catch(e){}
}
async function translateFormat(){
  const src=document.getElementById('src-json').value;
  const tgt=document.getElementById('fmt-target').value;
  if(!src)return;
  try{
    const r=await fetch('/api/translate/'+tgt,{method:'POST',body:src,headers:{'Content-Type':'application/json'}});
    const d=await r.json();
    if(d.error){document.getElementById('tgt-json').textContent='Error: '+d.error;return;}
    document.getElementById('tgt-fmt').textContent=tgt;
    document.getElementById('tgt-json').textContent=JSON.stringify(d.result||d,null,2);
  }catch(e){}
}

// ---- ROUTING ----
const PRESET_COMBOS = [
  {
    name: "maximize-claude",
    icon: "&#128170;",
    description: "Use your Claude Pro subscription fully, with cheap backup when quota runs out.",
    monthly: "$25",
    chain: [
      {provider: "claude-code", model: "claude-opus-4-7", note: "Use subscription fully"},
      {provider: "glm", model: "glm-5.1", note: "Cheap backup when quota out"},
      {provider: "kiro", model: "claude-sonnet-4.5", note: "Free emergency fallback"}
    ],
    useCase: "Claude Pro subscribers"
  },
  {
    name: "free-forever",
    icon: "&#127808;",
    description: "Zero cost AI coding with production-ready models and RTK token savings.",
    monthly: "$0",
    chain: [
      {provider: "kiro", model: "claude-sonnet-4.5", note: "Claude 4.5 free via Kiro"},
      {provider: "kiro", model: "glm-5", note: "GLM-5 free via Kiro"},
      {provider: "opencode-free", model: "auto", note: "OpenCode Free, no auth"}
    ],
    useCase: "Zero budget"
  },
  {
    name: "always-on",
    icon: "&#9889;",
    description: "24/7 coding with 5 layers of fallback. Zero downtime guaranteed.",
    monthly: "$30-220",
    chain: [
      {provider: "claude-code", model: "claude-opus-4-7", note: "Best quality"},
      {provider: "codex", model: "gpt-5.5", note: "Second subscription"},
      {provider: "glm", model: "glm-5.1", note: "Cheap, resets daily"},
      {provider: "minimax", model: "MiniMax-M2.7", note: "Cheapest, 5h reset"},
      {provider: "kiro", model: "claude-sonnet-4.5", note: "Free via Kiro"}
    ],
    useCase: "Deadlines, no downtime"
  },
  {
    name: "openclaw-free",
    icon: "&#129302;",
    description: "Free AI for WhatsApp, Telegram, Slack, Discord, and other messaging apps.",
    monthly: "$0",
    chain: [
      {provider: "kiro", model: "claude-sonnet-4.5", note: "Claude 4.5 free"},
      {provider: "kiro", model: "glm-5", note: "GLM-5 free"},
      {provider: "kiro", model: "MiniMax-M2.5", note: "MiniMax free"}
    ],
    useCase: "Messaging apps"
  }
];

function renderPresets(){
  const container = document.getElementById('preset-combos');
  if(!container) return;
  container.innerHTML = PRESET_COMBOS.map(p => {
    const chainHtml = p.chain.map((c,i) => 
      '<div style="padding:4px 0;font-size:12px;border-bottom:1px solid var(--border)"><span class="tag" style="margin-right:4px">'+(i+1)+'</span> <b>'+c.provider+'</b>/'+c.model+' <span class="text-dim">('+c.note+')</span></div>'
    ).join('');
    return '<div class="card" style="cursor:pointer" onclick="showPresetDetail(\''+p.name+'\')">'+
      '<h2>'+p.icon+' '+p.name+'</h2>'+
      '<div class="row"><span class="label">Monthly</span><span class="value green">'+p.monthly+'</span></div>'+
      '<div class="row"><span class="label">For</span><span class="value">'+p.useCase+'</span></div>'+
      '<p style="color:var(--dim);font-size:12px;margin:8px 0">'+p.description+'</p>'+
      '<div style="margin-top:8px">'+chainHtml+'</div>'+
      '<button class="btn btn-sm mt-8" onclick="event.stopPropagation();applyPreset(\''+p.name+'\')">&#9654; Apply</button>'+
    '</div>';
  }).join('');
}

function showPresetDetail(name){
  const preset = PRESET_COMBOS.find(p => p.name === name);
  if(!preset) return;
  alert(preset.name.toUpperCase() + '\n\n' + preset.description + '\n\nChain:\n' + 
    preset.chain.map((c,i) => (i+1)+'. '+c.provider+'/'+c.model+' - '+c.note).join('\n') + 
    '\n\nMonthly: ' + preset.monthly);
}

function applyPreset(name){
  const preset = PRESET_COMBOS.find(p => p.name === name);
  if(!preset) return;
  if(!confirm('Apply preset "'+name+'"?\n\nThis will configure your fallback chain as:\n'+preset.chain.map((c,i)=>(i+1)+'. '+c.provider+'/'+c.model).join('\n'))){
    return;
  }
  fetch('/api/routing/apply',{method:'POST',body:JSON.stringify({preset:name}),headers:{'Content-Type':'application/json'}})
    .then(r=>r.json()).then(d=>{
      if(d.error) alert('Error: '+d.error);
      else { alert('Preset "'+name+'" applied!'); loadRouting(); }
    }).catch(e=>alert('Error: '+e));
}

async function loadRouting(){
  renderPresets();
  try{
    const r=await fetch('/api/routing');const d=await r.json();
    document.getElementById('routing-tiers').innerHTML='';
    for(const [tier,providers] of Object.entries(d)){
      const tierColor=tier==='subscription'?'green':tier==='cheap'?'yellow':'red';
      const html=providers.map(p=>'<div class="accordion"><div class="accordion-header" onclick="this.parentElement.classList.toggle(\'open\')">'+p.id+' <span class="tag '+tierColor+'">'+p.tier+'</span><span class="text-dim">'+p.name+' ('+p.cost+')</span></div><div class="accordion-body">Endpoint: '+(p.endpoint||'-')+'<br>Format: '+(p.format||'-')+'</div></div>').join('');
      document.getElementById('routing-tiers').innerHTML+='<h2 style="margin:12px 0 8px;font-size:14px;text-transform:uppercase;color:var(--'+tierColor+')">'+tier+'</h2>'+html;
    }
  }catch(e){}
}

// ---- PROVIDERS ----
async function loadProviders(){
  try{
    const r=await fetch('/api/providers');const d=await r.json();
    document.getElementById('providers-tbody').innerHTML=(d||[]).map(p=>
      '<tr><td>'+p.name+'</td><td><span class="status-dot '+(p.configured?'green':'red')+'"></span>'+(p.configured?'Configured':'Missing Key')+'</td><td><span class="tag">'+p.tier+'</span></td><td>'+(p.models||0)+'</td><td><button class="btn btn-sm btn-outline" onclick="testProvider(\''+p.id+'\')">Test</button></td></tr>'
    ).join('');
  }catch(e){}
}
async function testProvider(id){
  try{
    const r=await fetch('/api/providers/test/'+id);const d=await r.json();
    alert(id+': '+(d.ok?'OK - '+d.model:'Failed - '+d.error));
  }catch(e){alert('Error testing provider')}
}
setInterval(loadProviders,30000);

// ---- CONSOLE LOG ----
async function loadLogs(){
  try{
    const r=await fetch('/api/logs');const data=await r.json();
    const container=document.getElementById('log-container');
    if(data.lines){
      for(const line of data.lines){
        const div=document.createElement('div');div.className='log-entry';
        div.innerHTML='<span class="time">'+line.time+'</span><span class="level level-'+line.level+'">'+line.level+'</span>'+line.message;
        container.appendChild(div);
      }
      container.scrollTop=container.scrollHeight;
    }
  }catch(e){}
}
function clearLog(){
  document.getElementById('log-container').innerHTML='';
  fetch('/api/logs/clear',{method:'POST'});
}
setInterval(loadLogs,3000);

// ---- CHAT ----
async function loadChatProviders(){
  try{
    const r=await fetch('/api/providers');const d=await r.json();
    const sel=document.getElementById('chat-provider');
    sel.innerHTML='<option value="">Select provider...</option>'+(d||[]).map(p=>'<option value="'+p.id+'">'+p.name+'</option>').join('');
  }catch(e){}
}
async function sendChat(){
  const provider=document.getElementById('chat-provider').value;
  const model=document.getElementById('chat-model').value;
  const msg=document.getElementById('chat-input').value;
  if(!provider||!msg)return;
  const container=document.getElementById('chat-messages');
  container.innerHTML+='<div style="margin:4px 0;color:var(--accent)"><b>You:</b> '+msg+'</div>';
  document.getElementById('chat-input').value='';
  try{
    const r=await fetch('/api/chat',{method:'POST',body:JSON.stringify({provider,model,message:msg}),headers:{'Content-Type':'application/json'}});
    const d=await r.json();
    container.innerHTML+='<div style="margin:4px 0;color:var(--green)"><b>'+provider+':</b> '+(d.response||d.error||'No response')+'</div>';
    container.scrollTop=container.scrollHeight;
  }catch(e){container.innerHTML+='<div style="color:var(--red)">Error: '+e.message+'</div>'}
}

// ---- SETTINGS ----
async function loadSettings(){
  try{
    const r=await fetch('/api/settings');const d=await r.json()||{};
    document.getElementById('settings-proxy').innerHTML=
      '<div class="row"><span class="label">Status</span><span class="value">'+(d.proxyRunning?'<span class="green">Running</span>':'<span class="red">Stopped</span>')+'</span></div>'+
      '<div class="row"><span class="label">Port</span><span class="value">'+(d.proxyPort||8199)+'</span></div>'+
      '<div class="row"><span class="label">Requests</span><span class="value">'+(d.proxyRequests||0)+'</span></div>'+
      '<div class="row"><span class="label">Tokens Saved</span><span class="value green">'+(d.proxySaved||0).toLocaleString()+'</span></div>';
    document.getElementById('settings-routing').innerHTML=
      '<div class="row"><span class="label">Fallback Chains</span><span class="value">'+(d.fallbackChains||0)+'</span></div>'+
      '<div class="row"><span class="label">Accounts</span><span class="value">'+(d.accounts||0)+'</span></div>';
    document.getElementById('settings-refresh').innerHTML=
      '<div class="row"><span class="label">Overview</span><span class="value">5s</span></div>'+
      '<div class="row"><span class="label">Usage</span><span class="value">10s</span></div>'+
      '<div class="row"><span class="label">Quota</span><span class="value">15s</span></div>'+
      '<div class="row"><span class="label">Providers</span><span class="value">30s</span></div>';
    document.getElementById('settings-db').innerHTML=
      '<div class="row"><span class="label">Cache Entries</span><span class="value">'+(d.cacheEntries||0)+'</span></div>'+
      '<div class="row"><span class="label">Ledger Entries</span><span class="value">'+(d.ledgerEntries||0)+'</span></div>'+
      '<button class="btn btn-sm mt-8" onclick="fetch(\'/api/settings/export\').then(r=>r.blob()).then(b=>{const a=document.createElement(\'a\');a.href=URL.createObjectURL(b);a.download=\'token-saver-backup.json\';a.click()})">Export Backup</button>';
  }catch(e){}
}

// ---- INIT ----
loadOverview();loadUsage();loadRouting();loadSettings();loadLogs();
</script>
</body>
</html>"""
