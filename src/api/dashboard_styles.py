"""Dashboard CSS — single-brace valid stylesheet (never use {{ in CSS)."""

DASHBOARD_CSS = """
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;1,9..40,400&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --bg: #06080d;
  --surface: #0f1419;
  --surface2: #161d27;
  --border: #243044;
  --text: #f0f4f8;
  --muted: #7d8fa8;
  --accent: #4d9fff;
  --green: #34d399;
  --red: #f87171;
  --amber: #fbbf24;
  --radius: 14px;
  --shadow: 0 4px 24px rgba(0,0,0,0.35);
}

*, *::before, *::after { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  font-family: 'DM Sans', system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  line-height: 1.5;
  background-image: radial-gradient(ellipse 80% 50% at 50% -20%, rgba(77,159,255,0.12), transparent);
}

a { color: var(--accent); text-decoration: none; font-weight: 500; }
a:hover { text-decoration: underline; }

/* Header */
.topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  padding: 0.85rem 1.25rem;
  background: rgba(15,20,25,0.92);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 100;
}
.brand { display: flex; align-items: center; gap: 0.6rem; }
.brand strong { font-size: 1.15rem; font-weight: 700; letter-spacing: -0.02em; }
.live-pill {
  width: 10px; height: 10px; border-radius: 50%;
  background: var(--muted); display: inline-block;
  box-shadow: 0 0 0 2px rgba(125,143,168,0.3);
}
.live-pill.on {
  background: var(--green);
  box-shadow: 0 0 12px var(--green), 0 0 0 2px rgba(52,211,153,0.4);
  animation: livepulse 1.5s ease-in-out infinite;
}
.live-pill.warm { background: var(--amber); box-shadow: 0 0 8px var(--amber); }
.live-pill.off { background: var(--red); }
@keyframes livepulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.7; transform: scale(0.92); }
}
.phase-tag {
  font-size: 0.65rem; font-weight: 700; letter-spacing: 0.06em;
  padding: 0.2rem 0.55rem; border-radius: 6px;
  background: rgba(77,159,255,0.15); color: var(--accent);
  border: 1px solid rgba(77,159,255,0.25);
}
.topbar-meta { display: flex; align-items: center; gap: 1rem; font-size: 0.8rem; }
.admin-link {
  padding: 0.35rem 0.75rem; border-radius: 8px;
  background: var(--surface2); border: 1px solid var(--border);
}
.admin-link:hover { text-decoration: none; border-color: var(--accent); }

.status-strip {
  padding: 0.55rem 1.25rem;
  font-size: 0.78rem;
  color: var(--muted);
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.75rem;
  align-items: center;
}
.pill {
  display: inline-flex; align-items: center; gap: 0.35rem;
  padding: 0.2rem 0.55rem; border-radius: 999px;
  font-size: 0.68rem; font-weight: 600; letter-spacing: 0.03em;
  background: var(--surface2); border: 1px solid var(--border);
}
.pill.ok { color: var(--green); border-color: rgba(52,211,153,0.35); background: rgba(52,211,153,0.08); }
.pill.warn { color: var(--amber); border-color: rgba(251,191,36,0.35); }
.pill.err { color: var(--red); border-color: rgba(248,113,113,0.35); }

.page { max-width: 1440px; margin: 0 auto; padding: 0.75rem 1rem 2rem; }

/* Telemetry command bar */
.telemetry-deck {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.5rem;
  padding: 0.65rem 1rem;
  background: linear-gradient(180deg, rgba(15,20,25,0.98), rgba(15,20,25,0.85));
  border-bottom: 1px solid var(--border);
}
@media (min-width: 900px) {
  .telemetry-deck { grid-template-columns: repeat(6, 1fr); }
}
.tele-item {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-size: 0.72rem;
  color: var(--muted);
  padding: 0.35rem 0.5rem;
  border-radius: 8px;
  background: rgba(22,29,39,0.6);
  border: 1px solid rgba(36,48,68,0.5);
}
.tele-item strong { color: var(--text); font-variant-numeric: tabular-nums; }
.tele-item.warn { border-color: rgba(251,191,36,0.45); color: var(--amber); }
.tele-item.err { border-color: rgba(248,113,113,0.45); animation: flashwarn 1.2s ease-in-out infinite; }
@keyframes flashwarn { 0%,100%{opacity:1} 50%{opacity:0.65} }

.status-ring {
  width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0;
  box-shadow: 0 0 8px currentColor;
}
.status-ring.green { background: var(--green); color: var(--green); animation: livepulse 1.5s infinite; }
.status-ring.orange { background: var(--amber); color: var(--amber); }
.status-ring.red { background: var(--red); color: var(--red); box-shadow: 0 0 10px var(--red); }

/* Bento grid — high density single-screen */
.bento {
  display: grid;
  gap: 0.65rem;
  grid-template-columns: 1fr;
}
@media (min-width: 1024px) {
  .bento {
    grid-template-columns: repeat(12, 1fr);
    grid-template-rows: auto auto auto minmax(180px, 1fr) auto;
  }
  .bento-kpis { grid-column: 1 / -1; }
  .bento-ledger { grid-column: 1 / -1; }
  .bento-xai { grid-column: span 6; }
  .bento-health { grid-column: span 3; }
  .bento-tactical { grid-column: span 3; }
  .bento-activity { grid-column: span 4; max-height: 280px; }
  .bento-corp { grid-column: span 4; max-height: 280px; }
  .bento-chart { grid-column: span 4; }
  .bento-quotes { grid-column: span 3; max-height: 280px; }
  .bento-pos { grid-column: span 4; }
  .bento-strat { grid-column: span 4; }
  .bento-trades { grid-column: span 4; }
}
.bento .panel { margin-bottom: 0; }
.panel.compact { padding: 0.75rem 0.9rem; }
.panel.compact .panel-head { margin-bottom: 0.5rem; }
.panel.compact .panel-head h2 { font-size: 0.82rem; }

/* XAI reasoner */
.xai-box {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.78rem;
  line-height: 1.55;
  color: #6ee7b7;
  background: #030712;
  border: 1px solid rgba(52,211,153,0.2);
  border-radius: 10px;
  padding: 0.75rem 0.85rem;
  max-height: 140px;
  overflow-y: auto;
}
.health-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.45rem;
  font-size: 0.78rem;
}
.health-cell {
  padding: 0.45rem 0.55rem;
  background: var(--bg);
  border-radius: 8px;
  border: 1px solid var(--border);
}
.health-cell span { display: block; color: var(--muted); font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.05em; }
.health-cell strong { font-size: 0.95rem; }

.sparkline { width: 56px; height: 22px; vertical-align: middle; }

/* Confirm modal */
.modal-backdrop {
  position: fixed; inset: 0; background: rgba(0,0,0,0.72);
  display: none; align-items: center; justify-content: center; z-index: 300;
}
.modal-backdrop.show { display: flex; }
.modal-card {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 1.25rem;
  max-width: 360px;
  width: 90vw;
  box-shadow: var(--shadow);
}
.modal-card h3 { margin: 0 0 0.5rem; font-size: 1rem; }
.modal-actions { display: flex; gap: 0.5rem; margin-top: 1rem; justify-content: flex-end; }

/* KPI row */
.hero-kpis {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.75rem;
  margin-bottom: 1rem;
}
@media (min-width: 640px) { .hero-kpis { grid-template-columns: repeat(4, 1fr); } }
.kpi {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1rem 1.1rem;
  box-shadow: var(--shadow);
}
.kpi-label {
  display: block;
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.kpi-val {
  display: block;
  font-size: 1.35rem;
  font-weight: 700;
  margin-top: 0.35rem;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}
.kpi-val.pos { color: var(--green); }
.kpi-val.neg { color: var(--red); }

/* Panels */
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1rem 1.15rem;
  margin-bottom: 1rem;
  box-shadow: var(--shadow);
}
.panel.highlight {
  border-color: rgba(77,159,255,0.4);
  background: linear-gradient(135deg, var(--surface) 0%, rgba(77,159,255,0.06) 100%);
}
.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.85rem;
  flex-wrap: wrap;
}
.panel-head h2 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 700;
  letter-spacing: -0.01em;
}
.badge {
  display: inline-block;
  padding: 0.25rem 0.65rem;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.04em;
}
.badge.ok { background: rgba(52,211,153,0.15); color: var(--green); }
.badge.warn { background: rgba(251,191,36,0.15); color: var(--amber); }
.badge.err { background: rgba(248,113,113,0.15); color: var(--red); }

/* Decision hero */
.decision-hero { padding: 0.25rem 0; }
.dec-action {
  font-size: 1.5rem;
  font-weight: 800;
  letter-spacing: -0.03em;
  margin-bottom: 0.35rem;
}
.dec-action.pos { color: var(--green); }
.dec-action.neg { color: var(--red); }
.dec-main { font-size: 1.05rem; font-weight: 600; margin: 0.4rem 0; }
.dec-reason {
  color: var(--muted);
  font-size: 0.88rem;
  padding: 0.65rem 0.85rem;
  background: var(--bg);
  border-radius: 8px;
  border-left: 3px solid var(--border);
  margin-top: 0.5rem;
}
.dec-action.neg + .dec-main + .dec-reason { border-left-color: var(--red); }
.dec-time { color: var(--muted); font-size: 0.75rem; margin-top: 0.5rem; font-family: 'JetBrains Mono', monospace; }

.chips { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.75rem; }
.chip {
  font-size: 0.72rem;
  font-weight: 500;
  padding: 0.3rem 0.65rem;
  border-radius: 999px;
  background: var(--surface2);
  border: 1px solid var(--border);
  color: var(--muted);
}

/* Activity stream */
.activity-stream {
  max-height: 320px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
.act-row {
  display: grid;
  grid-template-columns: 5.2rem 1fr;
  gap: 0.15rem 0.75rem;
  padding: 0.65rem 0.5rem;
  border-bottom: 1px solid var(--border);
  font-size: 0.84rem;
  align-items: start;
}
.act-row:last-child { border-bottom: none; }
.act-row.fresh { background: rgba(52,211,153,0.06); border-radius: 8px; }
.corp-stream {
  max-height: 240px;
  overflow-y: auto;
  font-size: 0.78rem;
  scrollbar-width: thin;
}
.corp-row {
  padding: 0.45rem 0.35rem;
  border-bottom: 1px solid var(--border);
  line-height: 1.4;
}
.corp-row:last-child { border-bottom: none; }
.corp-tag {
  display: inline-block;
  font-size: 0.62rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #93c5fd;
  margin-right: 0.35rem;
}
.corp-reason { color: var(--text); }
.corp-why {
  display: block;
  color: var(--muted);
  font-size: 0.68rem;
  margin-top: 0.15rem;
}
.ledger-pnl {
  font-size: 1.05rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
}
.ledger-trades {
  max-height: 120px;
  overflow-y: auto;
  font-size: 0.78rem;
  margin-bottom: 0.5rem;
  border-bottom: 1px solid var(--border);
  padding-bottom: 0.4rem;
}
.ledger-row {
  padding: 0.25rem 0;
  border-bottom: 1px solid rgba(36,48,68,0.5);
}
.ledger-plan {
  font-size: 0.8rem;
  line-height: 1.5;
  color: #93c5fd;
  max-height: 100px;
  overflow-y: auto;
}
.act-time {
  color: var(--muted);
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.72rem;
  white-space: nowrap;
}
.act-msg { font-weight: 500; word-break: break-word; }
.act-detail {
  grid-column: 2;
  color: var(--muted);
  font-size: 0.78rem;
  line-height: 1.4;
}

/* Layout split */
.split { display: grid; gap: 1rem; margin-bottom: 1rem; }
@media (min-width: 900px) { .split { grid-template-columns: 1.35fr 0.65fr; } }

.chart-wrap {
  position: relative;
  width: 100%;
  height: 260px;
  min-height: 220px;
  border-radius: 10px;
  overflow: hidden;
  background: var(--bg);
  border: 1px solid var(--border);
}
@media (min-width: 640px) { .chart-wrap { height: 300px; } }
.chart { width: 100%; height: 100%; }

.seg { display: flex; gap: 0.35rem; }
.seg-btn {
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--muted);
  padding: 0.35rem 0.7rem;
  border-radius: 8px;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
}
.seg-btn.active {
  border-color: var(--accent);
  color: var(--accent);
  background: rgba(77,159,255,0.1);
}

/* Tables */
.table-scroll {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin: 0 -0.25rem;
  padding: 0 0.25rem;
}
table.data {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
  min-width: 300px;
}
table.data th {
  color: var(--muted);
  font-weight: 600;
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.5rem 0.6rem;
  border-bottom: 1px solid var(--border);
  text-align: left;
  white-space: nowrap;
}
table.data td {
  padding: 0.55rem 0.6rem;
  border-bottom: 1px solid rgba(36,48,68,0.6);
  font-variant-numeric: tabular-nums;
}
table.data tr:hover td { background: rgba(77,159,255,0.04); }
table.data .sym { font-weight: 600; }
.pos { color: var(--green) !important; font-weight: 600; }
.neg { color: var(--red) !important; font-weight: 600; }
.muted { color: var(--muted); font-size: 0.85rem; }

/* Buttons */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--accent);
  color: #fff;
  border: none;
  padding: 0.55rem 1.1rem;
  border-radius: 10px;
  font-size: 0.88rem;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  text-decoration: none;
}
.btn:hover { filter: brightness(1.08); text-decoration: none; }
.btn.danger { background: var(--red); }
.btn.ghost {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text);
}
.btn.full { width: 100%; }

.footer {
  text-align: center;
  color: var(--muted);
  font-size: 0.75rem;
  padding: 1.5rem 0 0.5rem;
  border-top: 1px solid var(--border);
  margin-top: 0.5rem;
}

.admin-actions, .trade-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.75rem;
}
.trade-tools input {
  flex: 1;
  min-width: 140px;
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 0.55rem 0.75rem;
  border-radius: 10px;
  font-family: inherit;
}
.budget-card {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.85rem;
  background: rgba(251,191,36,0.08);
  border: 1px solid rgba(251,191,36,0.3);
  border-radius: 10px;
  margin-bottom: 0.75rem;
}

.toast {
  position: fixed;
  bottom: 1.25rem;
  left: 50%;
  transform: translateX(-50%);
  padding: 0.75rem 1.25rem;
  border-radius: 10px;
  background: var(--surface2);
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
  display: none;
  z-index: 200;
  font-size: 0.88rem;
  max-width: 90vw;
}
.toast.show { display: block; }

.login-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.25rem;
}
.login-card { max-width: 400px; width: 100%; }
.login-card label {
  display: block;
  margin: 0.85rem 0 0.35rem;
  font-size: 0.85rem;
  color: var(--muted);
  font-weight: 500;
}
.login-card input {
  width: 100%;
  padding: 0.65rem 0.85rem;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text);
  font-family: inherit;
}
.err { color: var(--red); font-size: 0.85rem; margin-top: 0.5rem; }

.empty-state {
  text-align: center;
  padding: 1.5rem;
  color: var(--muted);
  font-size: 0.88rem;
}
"""
