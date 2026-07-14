"""Public dashboard — mobile-first, live feed, admin controls gated."""
from __future__ import annotations


def render_dashboard(css: str, n_strategies: int) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"/>
<meta name="theme-color" content="#06080d"/>
<title>BharatQuant — Live Agent</title>
<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
<style>{css}</style>
</head>
<body>
<header class="topbar">
  <div class="brand">
    <span class="live-pill" id="livePill"></span>
    <strong>BharatQuant</strong>
    <span class="phase-tag" id="phaseTag">PAPER</span>
  </div>
  <div class="topbar-meta">
    <span id="updatedAt" class="muted">connecting…</span>
    <a href="/admin" class="admin-link" id="adminLink">Owner login</a>
  </div>
</header>

<div id="statusStrip" class="status-strip"><span class="pill warn">Starting…</span></div>

<div class="telemetry-deck" id="telemetryDeck">
  <div class="tele-item"><span class="status-ring green" id="ringKite"></span>Kite <strong id="teleKite">—</strong></div>
  <div class="tele-item">CPU <strong id="teleCpu">—</strong></div>
  <div class="tele-item">RAM <strong id="teleRam">—</strong></div>
  <div class="tele-item">Drawdown <strong id="teleDd">—</strong></div>
  <div class="tele-item"><span class="status-ring green" id="ringLlm"></span>LLM <strong id="teleLlm">—</strong></div>
  <div class="tele-item" id="teleSlipWrap">Slippage risk <strong id="teleSlip">—</strong></div>
</div>

<main class="page bento">
  <section class="hero-kpis bento-kpis">
    <article class="kpi"><span class="kpi-label">Paper equity</span><span class="kpi-val" id="kpiEquity">—</span></article>
    <article class="kpi"><span class="kpi-label">Paper PnL</span><span class="kpi-val" id="kpiPnl">—</span></article>
    <article class="kpi"><span class="kpi-label">Deployed today</span><span class="kpi-val" id="kpiDeploy">—</span></article>
    <article class="kpi"><span class="kpi-label">Open positions</span><span class="kpi-val" id="kpiPos">—</span></article>
  </section>

  <section class="panel highlight compact bento-ledger">
    <div class="panel-head">
      <h2>Today&apos;s ledger &amp; tomorrow&apos;s plan</h2>
      <span class="badge ok" id="ledgerBadge">—</span>
    </div>
    <div class="ledger-pnl" id="ledgerPnl">Loading P&amp;L…</div>
    <div class="ledger-trades" id="ledgerTrades"></div>
    <div class="ledger-plan" id="ledgerPlan">Plan loads after first feed…</div>
  </section>

  <section class="panel highlight compact bento-xai">
    <div class="panel-head">
      <h2>Agent Reasoning Protocol (XAI)</h2>
      <span class="badge warn" id="regimeBadge">—</span>
    </div>
    <div id="xaiBox" class="xai-box">Awaiting market signal evaluation…</div>
    <div class="chips" id="contextChips"></div>
  </section>

  <section class="panel compact bento-health">
    <div class="panel-head"><h2>System health</h2></div>
    <div class="health-grid">
      <div class="health-cell"><span>Kite ping</span><strong id="healthKite">—</strong></div>
      <div class="health-cell"><span>SQLite</span><strong id="healthDb">—</strong></div>
      <div class="health-cell"><span>Engine</span><strong id="healthEngine">—</strong></div>
      <div class="health-cell"><span>Circuit</span><strong id="healthCircuit">—</strong></div>
    </div>
    <div id="sandboxBox" class="xai-box" style="margin-top:0.5rem;max-height:80px;font-size:0.72rem;color:#93c5fd">Sandbox: loading…</div>
  </section>

  <section class="panel compact bento-tactical" id="adminPanel" style="display:none">
    <div class="panel-head"><h2>Tactical interceptors</h2></div>
    <div id="budgetCard" class="budget-card" style="display:none">
      <p id="budgetText"></p>
      <div class="admin-actions">
        <button type="button" class="btn" id="budgetApprove">Approve budget</button>
        <button type="button" class="btn ghost" id="budgetReject">Reject</button>
      </div>
    </div>
    <div class="admin-actions" style="flex-direction:column">
      <button type="button" class="btn ghost" id="slumberBtn">Force slumber (60m)</button>
      <button type="button" class="btn danger" id="haltBtn">Emergency flatten &amp; halt</button>
      <button type="button" class="btn ghost" id="resumeBtn">Resume trading</button>
    </div>
  </section>

  <section class="panel compact bento-activity">
    <div class="panel-head">
      <h2>Live activity</h2>
      <span class="badge ok" id="tickBadge">0 ticks/min</span>
    </div>
    <div id="activityStream" class="activity-stream" style="max-height:220px">
      <div class="empty-state">No activity yet</div>
    </div>
  </section>

  <section class="panel compact bento-corp">
    <div class="panel-head">
      <h2>Profit opportunities</h2>
      <span class="badge warn" id="corpBadge">—</span>
      <span class="badge" id="learnBadge" style="margin-left:0.35rem">learning —</span>
    </div>
    <div id="corpStream" class="corp-stream">
      <div class="empty-state">Loading insider, bulk, dividend filings…</div>
    </div>
  </section>

  <section class="panel compact bento-chart">
    <div class="panel-head">
      <h2>Market chart</h2>
      <div class="seg" id="chartSeg">
        <button type="button" class="seg-btn active" data-chart="nifty50">N50</button>
        <button type="button" class="seg-btn" data-chart="nifty100">N100</button>
      </div>
      <div class="seg" id="chartRange" style="margin-left:0.5rem">
        <button type="button" class="seg-btn active" data-period="1d" data-interval="1m">1D</button>
        <button type="button" class="seg-btn" data-period="5d" data-interval="5m">5D</button>
        <button type="button" class="seg-btn" data-period="1m" data-interval="1d">1M</button>
      </div>
    </div>
    <div class="chart-wrap" style="height:220px"><div id="mainChart" class="chart"></div></div>
    <p id="chartNote" class="muted" style="margin-top:0.35rem;font-size:0.72rem"></p>
  </section>

  <section class="panel compact bento-quotes">
    <div class="panel-head"><h2>Live quotes</h2></div>
    <div class="table-scroll">
      <table class="data">
        <thead><tr><th>Symbol</th><th>Trend</th><th>LTP</th></tr></thead>
        <tbody id="quotesBody"><tr><td colspan="3" class="muted">Waiting…</td></tr></tbody>
      </table>
    </div>
  </section>

  <section class="panel compact bento-pos">
    <div class="panel-head"><h2>Paper positions</h2><span class="muted" id="cashLabel" style="font-size:0.72rem"></span></div>
    <div class="table-scroll">
      <table class="data">
        <thead><tr><th>Symbol</th><th>Qty</th><th>PnL</th></tr></thead>
        <tbody id="posBody"><tr><td colspan="3" class="muted">No positions</td></tr></tbody>
      </table>
    </div>
  </section>

  <section class="panel compact bento-strat">
    <div class="panel-head"><h2>Strategy P&amp;L</h2></div>
    <div class="table-scroll">
      <table class="data">
        <thead><tr><th>Strategy</th><th>PnL</th></tr></thead>
        <tbody id="stratBody"><tr><td colspan="2" class="muted">No data</td></tr></tbody>
      </table>
    </div>
  </section>

  <section class="panel compact bento-trades">
    <div class="panel-head"><h2>Recent trades</h2></div>
    <div class="table-scroll">
      <table class="data">
        <thead><tr><th>Time</th><th>Side</th><th>Symbol</th><th>Amount</th><th>Why</th></tr></thead>
        <tbody id="tradesBody"><tr><td colspan="5" class="muted">No trades</td></tr></tbody>
      </table>
    </div>
  </section>

  <section class="panel" id="ownerTools" style="display:none">
    <div class="panel-head"><h2>Manual tools</h2></div>
    <div class="trade-tools">
      <input id="stockSymbol" placeholder="Symbol e.g. SBIN"/>
      <button type="button" class="btn ghost" id="lookupBtn">Quote</button>
      <button type="button" class="btn" id="buyBtn">Paper buy</button>
      <a class="btn ghost" href="/login">Kite token</a>
    </div>
    <p id="stockInfo" class="muted"></p>
  </section>

  <footer class="footer bento-kpis">
    Public read-only · {n_strategies} strategies · SSE/WS live ·
    <span id="paperReturn">paper return —</span> · <span id="transportTag">connecting</span>
  </footer>
</main>
<div id="toast" class="toast"></div>
<div id="confirmModal" class="modal-backdrop">
  <div class="modal-card">
    <h3 id="confirmTitle">Confirm action</h3>
    <p id="confirmMsg" class="muted"></p>
    <div class="modal-actions">
      <button type="button" class="btn ghost" id="confirmCancel">Cancel</button>
      <button type="button" class="btn danger" id="confirmOk">Confirm</button>
    </div>
  </div>
</div>

<script>
const POLL_MS = 3000;
let mainChart=null, mainSeries=null, isAdmin=false, sseSource=null, _confirmCb=null;
let chartKey='nifty50', chartPeriod='1d', chartInterval='1m', _chartPollN=0;

function $(id){{return document.getElementById(id);}}
function pnlCls(v){{return Number(v)>=0?'pos':'neg';}}
function fmtRs(v){{const n=Number(v)||0;return (n>=0?'+':'')+'₹'+Math.abs(n).toLocaleString('en-IN',{{maximumFractionDigits:0}});}}
function fmtTime(ts){{
  if(!ts) return '—';
  return new Date(ts*1000).toLocaleTimeString('en-IN',{{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:true}});
}}
function fmtChartTime(ts){{
  return new Date(ts*1000).toLocaleString('en-IN',{{timeZone:'Asia/Kolkata',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:true}});
}}
function esc(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;');}}
function toast(m){{const t=$('toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3500);}}

function setRing(el, state){{
  el.className='status-ring '+(state==='green'?'green':state==='orange'?'orange':'red');
}}

function sparkSvg(points){{
  if(!points||points.length<2) return '';
  const w=56,h=22,min=Math.min(...points),max=Math.max(...points),range=max-min||1;
  const coords=points.map((p,i)=>{{
    const x=(i/(points.length-1))*w;
    const y=h-((p-min)/range)*h;
    return x.toFixed(1)+','+y.toFixed(1);
  }}).join(' ');
  const up=points[points.length-1]>=points[0];
  const col=up?'#34d399':'#f87171';
  return '<svg class="sparkline" viewBox="0 0 '+w+' '+h+'"><polyline fill="none" stroke="'+col+'" stroke-width="1.5" points="'+coords+'"/></svg>';
}}

function confirmAction(title,msg,onOk){{
  $('confirmTitle').textContent=title;
  $('confirmMsg').textContent=msg;
  _confirmCb=onOk;
  $('confirmModal').classList.add('show');
}}
$('confirmCancel').addEventListener('click',()=>{{$('confirmModal').classList.remove('show');_confirmCb=null;}});
$('confirmOk').addEventListener('click',()=>{{$('confirmModal').classList.remove('show');if(_confirmCb)_confirmCb();_confirmCb=null;}});

async function adminFetch(url,opts={{}}){{
  const r=await fetch(url,{{credentials:'same-origin',...opts}});
  if(r.status===401){{toast('Owner login required');window.location.href='/admin';return null;}}
  return r;
}}

async function checkAdmin(){{
  try{{
    const s=await fetch('/api/admin/session',{{credentials:'same-origin'}}).then(r=>r.json());
    isAdmin=!!s.authenticated;
    $('adminPanel').style.display=isAdmin?'block':'none';
    $('ownerTools').style.display=isAdmin?'block':'none';
    $('adminLink').textContent=isAdmin?'Owner ✓':'Owner login';
  }}catch(e){{}}
}}

function renderTelemetry(t){{
  if(!t) return;
  $('teleKite').textContent=(t.kite_latency_ms!=null?t.kite_latency_ms+'ms':'—');
  $('teleCpu').textContent=(t.cpu_pct!=null?t.cpu_pct+'%':'—');
  $('teleRam').textContent=(t.ram_pct!=null?t.ram_pct+'%':'—');
  $('teleDd').textContent=(t.max_drawdown_pct!=null?t.max_drawdown_pct+'%':'—');
  $('teleLlm').textContent=(t.slumber&&t.slumber.active?'SLUMBER':(t.halted?'HALTED':'OK'));
  $('teleSlip').textContent=t.high_slippage_risk?'HIGH':'LOW';
  $('teleSlipWrap').className='tele-item'+(t.high_slippage_risk?' err':'');
  setRing($('ringKite'), t.kite_status_ring||'red');
  setRing($('ringLlm'), t.llm_status_ring||'orange');
  $('healthKite').textContent=(t.kite_latency_ms!=null?t.kite_latency_ms+' ms':'—');
  $('healthDb').textContent=t.db_ok?'OK':'DOWN';
  $('healthEngine').textContent=t.engine_status_ring==='green'?'LIVE':(t.engine_status_ring==='orange'?'DEGRADED':'DOWN');
  $('healthCircuit').textContent=t.circuit_breaker?'TRIPPED':'ARMED';
}}

function renderSandbox(sb){{
  if(!sb) return;
  const st=sb.shadow_comparison||{{}};
  $('sandboxBox').textContent='Sandbox '+sb.promote_recommendation+
    ' | stable score '+(st.stable?.score?.toFixed?.(3)??'—')+
    ' vs candidate '+(st.candidate?.score?.toFixed?.(3)??'—')+
    ' ('+(st.reason||'pending')+')';
}}

function renderStatusPills(f){{
  const pills=[];
  pills.push('<span class="pill '+(f.engine_live?'ok':'err')+'">'+(f.engine_live?'ENGINE ON':'ENGINE DOWN')+'</span>');
  pills.push('<span class="pill '+(f.ws_live?'ok':'warn')+'">'+(f.ws_live?'TICKS LIVE':'NO TICKS')+'</span>');
  pills.push('<span class="pill '+(f.kite_ok?'ok':'err')+'">'+(f.kite_ok?'KITE OK':'KITE EXPIRED')+'</span>');
  if(f.telemetry&&f.telemetry.slumber&&f.telemetry.slumber.active)
    pills.push('<span class="pill warn">SLUMBER '+Math.ceil(f.telemetry.slumber.remaining_sec/60)+'m</span>');
  $('statusStrip').innerHTML=pills.join('');
}}

function renderFeed(f){{
  try{{
  $('updatedAt').textContent='Updated '+fmtTime(f.ts);
  $('phaseTag').textContent=(f.phase||'paper').replace('_',' ').toUpperCase();
  const live=f.ws_live&&f.engine_live;
  $('livePill').className='live-pill '+(live?'on':f.engine_live?'warm':'off');
  $('tickBadge').textContent=(f.ticks_per_min||0)+' ticks/min';
  $('regimeBadge').textContent=f.regime||'NEUTRAL';
  renderTelemetry(f.telemetry);
  renderSandbox(f.sandbox);
  renderStatusPills(f);
  $('transportTag').textContent=f.transport||'poll';

  $('kpiEquity').textContent='₹'+Math.round(f.total_equity||0).toLocaleString('en-IN');
  const pnlEl=$('kpiPnl'); pnlEl.textContent=fmtRs(f.total_pnl); pnlEl.className='kpi-val '+pnlCls(f.total_pnl);
  $('kpiDeploy').textContent='₹'+Math.round(f.deployed_today||0).toLocaleString('en-IN')+' / ₹'+Math.round(f.budget_max||0).toLocaleString('en-IN');
  $('kpiPos').textContent=String(f.open_positions||0);
  $('cashLabel').textContent='Cash ₹'+Math.round(f.cash||0).toLocaleString('en-IN');
  $('paperReturn').textContent='paper return '+(f.paper_return_pct!=null?f.paper_return_pct+'%':'—');

  const xai=f.xai||{{}};
  $('xaiBox').textContent=xai.narrative||'Awaiting market signal evaluation…';

  const sess=f.session||{{}};
  const pnl=sess.pnl||{{}};
  $('ledgerBadge').textContent=(sess.trade_count||0)+' trades today';
  $('ledgerPnl').innerHTML=
    '<span class="'+pnlCls(pnl.total)+'">Total PnL '+fmtRs(pnl.total)+'</span>'+
    ' · realized '+fmtRs(pnl.realized)+' · open '+fmtRs(pnl.unrealized)+
    ' · deployed ₹'+Math.round((sess.budget||{{}}).deployed_today||0).toLocaleString('en-IN');
  const lt=sess.trades||[];
  $('ledgerTrades').innerHTML=lt.length?lt.map(t=>'<div class="ledger-row"><span class="act-time">'+fmtTime(t.ts)+'</span> '+esc(t.text)+' <span class="muted">'+esc(t.reason||'')+'</span></div>').join(''):'<div class="muted">No trades yet</div>';
  $('ledgerPlan').textContent=sess.plan_for_tomorrow||'Pre-market plan runs 08:45 IST on trading days.';

  const chips=[];
  if(f.fii_net_cr!=null) chips.push('FII '+Number(f.fii_net_cr).toFixed(0)+' cr');
  if(f.gift_pct!=null) chips.push('GIFT '+(f.gift_pct>=0?'+':'')+Number(f.gift_pct).toFixed(2)+'%');
  if(f.llm_bias!=null) chips.push('LLM '+(f.llm_bias>=0?'+':'')+Number(f.llm_bias).toFixed(2));
  if(f.india_vix!=null) chips.push('VIX '+Number(f.india_vix).toFixed(1));
  if(f.fear_greed_index!=null) chips.push('F&G '+Math.round(f.fear_greed_index)+' '+String(f.sentiment_label||''));
  if(f.session_phase) chips.push(String(f.session_phase).replace(/_/g,' '));
  if(f.nse_status) chips.push('NSE '+f.nse_status);
  chips.push('Budget '+Math.round(f.budget_used_pct||0)+'%');
  if(f.rl_strategy_note&&f.rl_strategy_note.strategy_id) chips.push(f.rl_strategy_note.strategy_id);
  $('contextChips').innerHTML=chips.map(c=>'<span class="chip">'+esc(c)+'</span>').join('');

  const now=Math.floor(Date.now()/1000);
  const act=f.activity||[];
  $('activityStream').innerHTML=act.length?act.slice(0,12).map(a=>{{
    const fresh=now-a.ts<8?' fresh':'';
    const icon=a.kind==='trade'?'💰':a.kind==='decision'?'🤖':'📡';
    return '<div class="act-row'+fresh+'"><span class="act-time">'+fmtTime(a.ts)+'</span><span class="act-msg">'+icon+' '+esc(a.text)+'</span></div>';
  }}).join(''):'<div class="empty-state">No activity</div>';

  const corp=f.corporate||{{}};
  const cc=corp.counts||{{}};
  $('corpBadge').textContent=(cc.insider||0)+' ins · '+(cc.bulk||0)+' blk · '+(cc.shareholding||0)+' shp · '+(cc.mf_flows||0)+' mf';
  const il=f.institutional_learning||{{}};
  if(il.labeled_outcomes!=null){{
    const lw=il.strategy_weights||{{}};
    const top=Object.entries(lw).slice(0,2).map(([k,v])=>k+':'+Number(v).toFixed(2)).join(' ');
    const sess=il.session_today||{{}};
    $('learnBadge').textContent=
      (sess.signals_today||0)+' sig · '+(sess.labeled_today||0)+' labeled · '+(sess.ticks_today||0)+' ticks · '+
      (il.signal_outcomes||0)+' outcomes · '+(il.promoted_rules||0)+' rules'+(top?' · '+top:'');
  }}
  const timeline=corp.timeline||[];
  $('corpStream').innerHTML=timeline.length?timeline.slice(0,10).map(c=>{{
    const tag=c.category||c.kind||'corp';
    const sym=c.symbol?'<strong>'+esc(c.symbol)+'</strong> ':'';
    const why=c.why?'<span class="corp-why">'+esc(c.why)+'</span>':'';
    return '<div class="corp-row"><span class="corp-tag">'+esc(tag)+'</span>'+sym+
      '<span class="corp-reason">'+esc(c.reason||c.title||'')+'</span>'+why+'</div>';
  }}).join(''):'<div class="empty-state">No filings in 7-day window — pollers run on market days</div>';

  const sparks=f.sparklines||{{}};
  const q=f.live_quotes||[];
  $('quotesBody').innerHTML=q.length?q.slice(0,10).map(x=>'<tr><td class="sym">'+esc(x.symbol)+'</td><td>'+sparkSvg(sparks[x.symbol])+'</td><td>₹'+Number(x.ltp).toFixed(2)+'</td></tr>').join(''):
    '<tr><td colspan="3" class="muted">Waiting…</td></tr>';

  const pos=f.positions||[];
  $('posBody').innerHTML=pos.length?pos.map(p=>{{
    const pnl=(Number(p.last_price)-Number(p.avg_price))*Number(p.qty);
    return '<tr><td class="sym">'+esc(p.symbol)+'</td><td>'+p.qty+'</td><td class="'+pnlCls(pnl)+'">'+fmtRs(pnl)+'</td></tr>';
  }}).join(''):'<tr><td colspan="3" class="muted">Flat</td></tr>';

  const sp=f.strategy_pnl||[];
  $('stratBody').innerHTML=sp.length?sp.slice(0,8).map(s=>'<tr><td>'+esc(s.strategy_id)+'</td><td class="'+pnlCls(s.realized_pnl)+'">'+fmtRs(s.realized_pnl)+'</td></tr>').join(''):
    '<tr><td colspan="2" class="muted">No data</td></tr>';

  const tr=f.trades||[];
  $('tradesBody').innerHTML=tr.length?tr.slice(0,10).map(t=>'<tr><td>'+fmtTime(t.ts)+'</td><td>'+esc(t.side)+'</td><td class="sym">'+esc(t.symbol)+'</td><td>₹'+Number(t.amount||0).toFixed(0)+'</td><td class="muted">'+esc((t.reason||'').slice(0,40))+'</td></tr>').join(''):
    '<tr><td colspan="5" class="muted">No trades</td></tr>';

  if(isAdmin&&f.budget_pending){{
    $('budgetCard').style.display='block';
    $('budgetText').textContent='Agent requests ₹'+f.budget_pending.requested_max+' — '+(f.budget_pending.reason||'');
  }} else $('budgetCard').style.display='none';
  }}catch(err){{
    console.error('renderFeed',err);
    $('statusStrip').innerHTML='<span class="pill err">Render error — hard refresh (Cmd+Shift+R)</span>';
  }}
}}

function connectSSE(){{
  if(typeof EventSource==='undefined'){{ setInterval(pollFeed,POLL_MS); return; }}
  try{{
    sseSource=new EventSource('/api/feed/stream');
    sseSource.onmessage=(ev)=>{{ try{{ renderFeed(JSON.parse(ev.data)); }}catch(e){{}} }};
    sseSource.onerror=()=>{{ sseSource.close(); setTimeout(connectSSE,5000); }};
  }}catch(e){{ setInterval(pollFeed,POLL_MS); }}
}}

async function pollFeed(){{
  $('updatedAt').textContent='Loading feed…';
  $('transportTag').textContent='loading';
  try{{
    const f=await fetch('/api/feed/fast').then(r=>{{
      if(!r.ok) throw new Error('fast feed '+r.status);
      return r.json();
    }});
    renderFeed(f);
    _chartPollN+=1;
    if(_chartPollN%5===0) loadChart();
    fetch('/api/feed/live').then(r=>r.ok?r.json():null).then(j=>{{if(j) renderFeed(j);}}).catch(()=>{{}});
  }}
  catch(e){{
    $('statusStrip').innerHTML='<span class="pill err">Feed error — retrying…</span>';
    $('updatedAt').textContent='Feed failed — check network';
  }}
}}

async function loadChart(key){{
  if(key) chartKey=key;
  const note=$('chartNote');
  if(typeof LightweightCharts==='undefined'){{note.textContent='Chart library blocked — check network';return;}}
  try{{
    const q='?period='+encodeURIComponent(chartPeriod)+'&interval='+encodeURIComponent(chartInterval);
    const data=await fetch('/api/index/ohlc/'+chartKey+q).then(r=>r.json());
    const wrap=document.querySelector('.chart-wrap');
    const el=$('mainChart');
    if(!mainChart){{
      mainChart=LightweightCharts.createChart(el,{{
        width:wrap.clientWidth,height:wrap.clientHeight,
        layout:{{background:{{color:'#06080d'}},textColor:'#7d8fa8'}},
        grid:{{vertLines:{{color:'#243044'}},horzLines:{{color:'#243044'}}}},
        rightPriceScale:{{borderColor:'#243044'}},
        timeScale:{{borderColor:'#243044',timeVisible:true,secondsVisible:chartInterval==='1m'}},
        localization:{{
          locale:'en-IN',
          timeFormatter:fmtChartTime,
          dateFormatter:(t)=>fmtChartTime(t)
        }}
      }});
      mainSeries=mainChart.addCandlestickSeries({{
        upColor:'#34d399',downColor:'#f87171',borderVisible:false,
        wickUpColor:'#34d399',wickDownColor:'#f87171'
      }});
      new ResizeObserver(()=>mainChart.applyOptions({{width:wrap.clientWidth,height:wrap.clientHeight}})).observe(wrap);
    }}
    const bars=(data.bars||[]).map(b=>({{time:b.time,open:b.open,high:b.high,low:b.low,close:b.close}}));
    if(bars.length){{
      mainSeries.setData(bars);
      mainChart.timeScale().fitContent();
      const chg=data.change_pct!=null?(data.change_pct>=0?'+':'')+Number(data.change_pct).toFixed(2)+'%':'';
      const last=data.last!=null?Number(data.last).toLocaleString('en-IN',{{maximumFractionDigits:2}}):'';
      note.textContent=(data.label||chartKey)+' '+last+' '+chg+' · '+bars.length+' bars · '+data.source+' · IST';
    }} else note.textContent='Chart data loading…';
  }}catch(e){{note.textContent='Chart: '+e.message;}}
}}

document.getElementById('chartSeg').addEventListener('click',e=>{{
  const btn=e.target.closest('.seg-btn'); if(!btn) return;
  document.querySelectorAll('#chartSeg .seg-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active'); loadChart(btn.dataset.chart);
}});
document.getElementById('chartRange').addEventListener('click',e=>{{
  const btn=e.target.closest('.seg-btn'); if(!btn) return;
  document.querySelectorAll('#chartRange .seg-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  chartPeriod=btn.dataset.period; chartInterval=btn.dataset.interval;
  loadChart();
}});

$('haltBtn').addEventListener('click',()=>{{
  confirmAction('Emergency flatten?','This will market-sell ALL paper positions and halt the engine.',async()=>{{
    const r=await adminFetch('/api/halt',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{reason:'dashboard_panic'}})}});
    if(r&&r.ok){{const j=await r.json();toast('Flattened '+(j.positions_closed||0)+' positions');pollFeed();}}
  }});
}});
$('slumberBtn').addEventListener('click',()=>{{
  confirmAction('Force slumber 60 minutes?','Agent will ignore all new BUY signals until slumber ends.',async()=>{{
    const r=await adminFetch('/api/slumber',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{minutes:60}})}});
    if(r&&r.ok){{toast('Slumber active 60m');pollFeed();}}
  }});
}});
$('resumeBtn').addEventListener('click',async()=>{{
  await adminFetch('/api/slumber/clear',{{method:'POST'}});
  const r=await adminFetch('/api/resume',{{method:'POST'}});
  if(r&&r.ok){{toast('Resumed');pollFeed();}}
}});
$('budgetApprove').addEventListener('click',()=>{{
  confirmAction('Approve budget increase?','Agent will deploy up to the requested daily cap.',async()=>{{
    const r=await adminFetch('/api/budget/approve',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:'{{}}'}});
    if(r){{const j=await r.json();if(j.ok){{toast('Approved ₹'+j.approved_max);pollFeed();}}}}
  }});
}});
$('budgetReject').addEventListener('click',()=>{{
  confirmAction('Reject budget request?','Agent continues with remaining deploy pool only.',async()=>{{
    await adminFetch('/api/budget/reject',{{method:'POST'}});toast('Rejected');pollFeed();
  }});
}});
$('lookupBtn').addEventListener('click',async()=>{{const sym=($('stockSymbol').value||'').trim().toUpperCase();if(!sym)return;const j=await fetch('/api/stock/lookup/'+sym).then(r=>r.json());$('stockInfo').textContent=sym+' LTP ₹'+(j.ltp||'?')+' · affordable '+(j.affordable_whole_shares||0)+' shares';}});
$('buyBtn').addEventListener('click',async()=>{{const sym=($('stockSymbol').value||'').trim();if(!sym)return;const r=await adminFetch('/api/stock/manual_buy',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{symbol:sym}})}});if(r){{const j=await r.json();toast(j.ok?'Bought '+j.qty+' '+j.symbol:(j.error||'failed'));pollFeed();}}}});

checkAdmin().then(()=>{{
  loadChart('nifty50');
  connectSSE();
  pollFeed();
  setInterval(pollFeed,POLL_MS);
}});
</script>
</body></html>"""


def render_admin_login(css: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Owner login — BharatQuant</title>
<style>{css}</style>
</head>
<body>
<div class="login-wrap">
  <div class="panel login-card">
    <h1 style="margin:0 0 0.5rem">Owner login</h1>
    <p class="muted">Public dashboard is read-only. Only you can halt, approve budget, or paper-buy.</p>
    <form id="loginForm">
      <label>Username<input name="username" id="username" autocomplete="username" required/></label>
      <label>Password<input name="password" id="password" type="password" autocomplete="current-password" required/></label>
      <button type="submit" class="btn full">Sign in</button>
    </form>
    <p id="loginErr" class="err"></p>
    <p class="muted" style="margin-top:1rem"><a href="/dashboard">← Back to public dashboard</a></p>
  </div>
</div>
<script>
function $(id){{return document.getElementById(id);}}
$('loginForm').addEventListener('submit',async e=>{{
  e.preventDefault();
  const body={{username:$('username').value,password:$('password').value}};
  const r=await fetch('/api/admin/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body),credentials:'same-origin'}});
  const j=await r.json();
  if(j.ok) window.location.href='/dashboard';
  else $('loginErr').textContent=j.error||j.detail||'Login failed';
}});
</script>
</body></html>"""
