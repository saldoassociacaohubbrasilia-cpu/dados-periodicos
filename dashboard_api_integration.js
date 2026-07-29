// ============================================================
// Integração do dashboard Saldo+ com o backend (substitui os
// arrays fixos e os números fixos do HTML atual).
//
// COMO USAR:
// 1) No HTML, dê um id a cada valor de KPI que hoje é só texto fixo:
//      <div class="kpi b1"><div class="label">INSCRITOS</div>
//        <div class="value" id="kpi-inscritos">1.096</div></div>
//    (idem para kpi-ativacao, kpi-conclusao, kpi-retencao)
//
// 2) Remova os três `new Chart(...)` de c1, c4 e cFunil que usam
//    dados fixos (data:[1096,504,168] etc.) e troque pela chamada
//    initDashboard() no final do <script>, no lugar deles.
// ============================================================

const API_BASE = 'http://localhost:8000/api/v1'; // troque pela URL do backend em produção

async function fetchJSON(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`Erro ${res.status} ao buscar ${path}`);
  return res.json();
}

function setKpi(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

async function initDashboard() {
  try {
    const overview = await fetchJSON('/overview');

    // --- KPIs do topo ---
    setKpi('kpi-inscritos', fmtInt(overview.inscritos));
    setKpi('kpi-ativacao', fmtPct1(overview.taxa_ativacao));
    setKpi('kpi-conclusao', fmtPct1(overview.taxa_conclusao));
    setKpi('kpi-retencao', fmtPct1(overview.taxa_retencao));

    // --- Gráfico 1 · Volume por etapa ---
    new Chart(document.getElementById('c1'), {
      type: 'bar',
      data: {
        labels: ['Inscritos', 'Engajados', 'Concluintes'],
        datasets: [{
          data: [overview.inscritos, overview.engajados, overview.concluintes],
          backgroundColor: [NAVY, CYAN, ORANGE],
          borderRadius: 4
        }]
      },
      // mantenha as mesmas `options` do gráfico c1 original
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, datalabels: { display: true, anchor: 'end', align: 'end', color: NAVY, font: { size: 11, weight: 600 }, formatter: fmtInt } },
        scales: { x: { grid: { display: false }, ticks: { color: NAVY, font: { size: 11 } } }, y: { grid: { color: '#E5E7EB' }, ticks: { color: '#6B7280', font: { size: 10 } }, beginAtZero: true } }
      }
    });

    // --- Gráfico 4 · Painel de taxas-chave ---
    new Chart(document.getElementById('c4'), {
      type: 'bar',
      data: {
        labels: ['Ativação', 'Conclusão', 'Retenção'],
        datasets: [{
          data: [overview.taxa_ativacao, overview.taxa_conclusao, overview.taxa_retencao],
          backgroundColor: [NAVY, ORANGE, MAGENTA],
          borderRadius: 4
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, datalabels: { display: true, anchor: 'end', align: 'end', color: NAVY, font: { size: 11, weight: 600 }, formatter: fmtPct1 } },
        scales: { x: { grid: { display: false }, ticks: { color: NAVY, font: { size: 11 } } }, y: { min: 0, max: 60, grid: { color: '#E5E7EB' }, ticks: { color: '#6B7280', font: { size: 10 } } } }
      }
    });

    // --- % de estudantes por trilha/módulo (requisito 3) ---
    // Adicione um <canvas id="cTrilhas"> em algum card do HTML para usar isso.
    const trails = await fetchJSON('/trails');
    const cTrilhas = document.getElementById('cTrilhas');
    if (cTrilhas) {
      new Chart(cTrilhas, {
        type: 'bar',
        data: {
          labels: trails.map(t => t.trilha),
          datasets: [{ data: trails.map(t => t.percentual), backgroundColor: CYAN, borderRadius: 4 }]
        },
        options: {
          indexAxis: 'y', responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false }, datalabels: { display: true, anchor: 'end', align: 'end', color: NAVY, font: { size: 10, weight: 600 }, formatter: fmtPct1 } },
          scales: { x: { min: 0, max: 100, grid: { color: '#E5E7EB' }, ticks: { color: '#6B7280', font: { size: 10 } } }, y: { grid: { display: false }, ticks: { color: NAVY, font: { size: 10 } } } }
        }
      });
    }

  } catch (err) {
    console.error('Falha ao carregar dados do backend Saldo+:', err);
    // opcional: mostrar um aviso amigável no lugar dos gráficos
  }
}

document.addEventListener('DOMContentLoaded', initDashboard);

// Opcional — só relê o que já está no banco (não bate na Ludos de novo),
// então é seguro reatualizar a tela com mais frequência que o sync real:
// setInterval(initDashboard, 15 * 60 * 1000);
