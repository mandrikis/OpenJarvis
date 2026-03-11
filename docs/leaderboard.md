---
hide:
  - navigation
---

# Savings Leaderboard

See how the OpenJarvis community saves money, energy, and compute by running AI locally instead of using cloud providers.

!!! info "Win a Mac Mini!"
    Opt in to share your savings from the OpenJarvis browser app or desktop app for a chance to win a Mac Mini. Your data is fully anonymous — no email, no IP, no hardware info.

<div id="leaderboard-stats" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin:24px 0;">
  <div class="lb-stat-card">
    <div class="lb-stat-label">Community Members</div>
    <div class="lb-stat-value" id="stat-members">—</div>
  </div>
  <div class="lb-stat-card">
    <div class="lb-stat-label">Total Saved</div>
    <div class="lb-stat-value" id="stat-dollars">—</div>
  </div>
  <div class="lb-stat-card">
    <div class="lb-stat-label">Total Requests</div>
    <div class="lb-stat-value" id="stat-requests">—</div>
  </div>
  <div class="lb-stat-card">
    <div class="lb-stat-label">Total Tokens</div>
    <div class="lb-stat-value" id="stat-tokens">—</div>
  </div>
</div>

<div id="leaderboard-table-wrapper">
  <table id="leaderboard-table" class="lb-table">
    <thead>
      <tr>
        <th style="width:50px">#</th>
        <th>Name</th>
        <th style="text-align:right">$ Saved</th>
        <th style="text-align:right">Energy (Wh)</th>
        <th style="text-align:right">FLOPs</th>
        <th style="text-align:right">Requests</th>
        <th style="text-align:right">Tokens</th>
      </tr>
    </thead>
    <tbody id="leaderboard-body">
      <tr>
        <td colspan="7" style="text-align:center;padding:48px;opacity:0.5">
          Loading leaderboard...
        </td>
      </tr>
    </tbody>
  </table>
</div>

<style>
.lb-stat-card {
  background: var(--md-code-bg-color, #f5f5f5);
  border-radius: 10px;
  padding: 16px 20px;
  border: 1px solid var(--md-default-fg-color--lightest, #e0e0e0);
}
.lb-stat-label {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  opacity: 0.6;
  margin-bottom: 4px;
}
.lb-stat-value {
  font-size: 28px;
  font-weight: 700;
  font-feature-settings: "tnum";
}
.lb-table {
  width: 100%;
  border-collapse: collapse;
  font-feature-settings: "tnum";
}
.lb-table th {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 10px 12px;
  border-bottom: 2px solid var(--md-default-fg-color--lightest, #e0e0e0);
  opacity: 0.6;
}
.lb-table td {
  padding: 12px;
  border-bottom: 1px solid var(--md-default-fg-color--lightest, #e0e0e0);
}
.lb-table tbody tr:hover {
  background: var(--md-code-bg-color, #f5f5f5);
}
.lb-rank {
  font-weight: 700;
  font-size: 16px;
}
.lb-rank-1 { color: #ffd700; }
.lb-rank-2 { color: #c0c0c0; }
.lb-rank-3 { color: #cd7f32; }
.lb-name {
  font-weight: 600;
  font-size: 14px;
}
.lb-number {
  text-align: right;
  font-family: var(--md-code-font-family, monospace);
  font-size: 13px;
}
</style>

<script type="module">
const SUPABASE_URL = '';
const SUPABASE_ANON_KEY = '';

async function loadLeaderboard() {
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
    document.getElementById('leaderboard-body').innerHTML =
      '<tr><td colspan="7" style="text-align:center;padding:48px;opacity:0.5">' +
      'Leaderboard not configured yet. Set Supabase credentials to enable.</td></tr>';
    return;
  }

  try {
    const res = await fetch(
      `${SUPABASE_URL}/rest/v1/savings_entries?select=*&order=dollar_savings.desc&limit=100`,
      {
        headers: {
          apikey: SUPABASE_ANON_KEY,
          Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
        },
      }
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const rows = await res.json();

    if (!rows.length) {
      document.getElementById('leaderboard-body').innerHTML =
        '<tr><td colspan="7" style="text-align:center;padding:48px;opacity:0.5">' +
        'No entries yet. Be the first to opt in!</td></tr>';
      return;
    }

    // Aggregate stats
    const totalMembers = rows.length;
    const totalDollars = rows.reduce((s, r) => s + Number(r.dollar_savings || 0), 0);
    const totalRequests = rows.reduce((s, r) => s + Number(r.total_calls || 0), 0);
    const totalTokens = rows.reduce((s, r) => s + Number(r.total_tokens || 0), 0);

    document.getElementById('stat-members').textContent = totalMembers.toLocaleString();
    document.getElementById('stat-dollars').textContent = '$' + totalDollars.toFixed(2);
    document.getElementById('stat-requests').textContent = totalRequests.toLocaleString();
    document.getElementById('stat-tokens').textContent =
      totalTokens >= 1e6
        ? (totalTokens / 1e6).toFixed(1) + 'M'
        : totalTokens >= 1e3
          ? (totalTokens / 1e3).toFixed(1) + 'K'
          : totalTokens.toLocaleString();

    // Render table
    const tbody = document.getElementById('leaderboard-body');
    tbody.innerHTML = rows
      .map((row, i) => {
        const rank = i + 1;
        const rankClass = rank <= 3 ? ` lb-rank-${rank}` : '';
        const medal = rank === 1 ? '🥇' : rank === 2 ? '🥈' : rank === 3 ? '🥉' : '';
        return `<tr>
          <td><span class="lb-rank${rankClass}">${medal || rank}</span></td>
          <td class="lb-name">${escapeHtml(row.display_name)}</td>
          <td class="lb-number">$${Number(row.dollar_savings || 0).toFixed(4)}</td>
          <td class="lb-number">${Number(row.energy_wh_saved || 0).toFixed(2)}</td>
          <td class="lb-number">${fmtLarge(Number(row.flops_saved || 0))}</td>
          <td class="lb-number">${Number(row.total_calls || 0).toLocaleString()}</td>
          <td class="lb-number">${Number(row.total_tokens || 0).toLocaleString()}</td>
        </tr>`;
      })
      .join('');
  } catch (err) {
    document.getElementById('leaderboard-body').innerHTML =
      `<tr><td colspan="7" style="text-align:center;padding:48px;color:var(--md-accent-fg-color)">
        Failed to load leaderboard: ${escapeHtml(String(err))}</td></tr>`;
  }
}

function escapeHtml(s) {
  const el = document.createElement('span');
  el.textContent = s;
  return el.innerHTML;
}

function fmtLarge(n) {
  if (n >= 1e12) return (n / 1e12).toFixed(1) + 'T';
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return n.toLocaleString();
}

loadLeaderboard();
setInterval(loadLeaderboard, 60000);
</script>
