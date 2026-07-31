// ============================================================
// Integração do Dashboard Saldo+
// Cores da Paleta Saldo+: Navy, Cyan, Orange, Magenta
// ============================================================

const API_BASE = 'http://localhost:8000/api/v1';
const NAVY = '#002364', CYAN = '#11B2A8', ORANGE = '#F98105', MAGENTA = '#E72485';

Chart.defaults.font.family = "'Poppins', system-ui, sans-serif";
Chart.defaults.color = '#64748B';

const PALETA = [CYAN, ORANGE, MAGENTA, '#10B981', '#EAB308', NAVY];

let chartEscolas = null;
let chartTrilhas = null;
let mapaGeografico = null;
let marcadoresMapa = [];

// Funções utilitárias de formatação
const fmtInt = (num) => new Intl.NumberFormat('pt-BR').format(num || 0);
const fmtPct = (num) => (num || 0).toFixed(1) + '%';
function setKpi(id, text) { const el = document.getElementById(id); if (el) el.textContent = text; }

// --- Regiões e limites geográficos do mapa ---
// Coordenadas (lat/lng) e zoom recomendado pra cada recorte, mais os
// limites que travam o mapa dentro do Brasil.
const REGIOES_MAPA = {
    brasil: { center: [-14.235, -51.9253], zoom: 4 },
    df: { center: [-15.7939, -47.8828], zoom: 10 },
    sp: { center: [-23.5505, -46.6333], zoom: 10 },
};
// Mapeia o valor do filtro de instituição do dashboard ("todas",
// "secretaria", "cvp") pra região correspondente acima.
const INSTITUICAO_PARA_REGIAO = { todas: 'brasil', secretaria: 'df', cvp: 'sp' };

// Retângulo (SW, NE) que envolve o Brasil inteiro com uma folga — o
// mapa "rebate" se o usuário tentar arrastar pra fora disso.
const LIMITES_BRASIL = [
    [-35.0, -75.0], // sudoeste
    [6.0, -32.0],   // nordeste
];

// --- Inicialização do Mapa (Leaflet.js) ---
// Base CartoDB Positron (minimalista, tons claros) + mapa travado no
// território brasileiro (maxBounds) com zoom limitado (nem rua, nem globo).
function inicializarMapa() {
    if (!mapaGeografico) {
        mapaGeografico = L.map('mapa-escolas', {
            center: REGIOES_MAPA.brasil.center,
            zoom: REGIOES_MAPA.brasil.zoom,
            minZoom: 4,
            maxZoom: 12,
            maxBounds: LIMITES_BRASIL,
            maxBoundsViscosity: 1.0, // 1.0 = rebate de vez, não deixa "escapar" arrastando
        });

        L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
            attribution: '© OpenStreetMap contributors © CARTO',
            subdomains: 'abcd',
            maxZoom: 19
        }).addTo(mapaGeografico);
    }
}

// Move o mapa suavemente até uma região (flyTo anima o pan+zoom juntos,
// diferente de setView que troca a visão de uma vez, sem transição).
function focarRegiao(chave) {
    const regiao = REGIOES_MAPA[chave] || REGIOES_MAPA.brasil;
    mapaGeografico.flyTo(regiao.center, regiao.zoom, { duration: 1.2 });
}

function focarBrasil() { focarRegiao('brasil'); }
function focarDF() { focarRegiao('df'); }
function focarSP() { focarRegiao('sp'); }

function atualizarMapa(dadosEscolas, instituicaoId) {
    // Remove marcadores antigos
    marcadoresMapa.forEach(m => mapaGeografico.removeLayer(m));
    marcadoresMapa = [];

    // Adiciona novos marcadores (Requer lat/lng vindo do backend)
    dadosEscolas.forEach(escola => {
        if(escola.lat && escola.lng) {
            // Cor do marcador baseada no engajamento (ver legenda abaixo do mapa)
            const cor = escola.engajamento_pct > 70 ? CYAN : (escola.engajamento_pct > 40 ? ORANGE : MAGENTA);

            const circle = L.circleMarker([escola.lat, escola.lng], {
                color: cor,
                fillColor: cor,
                fillOpacity: 0.75,
                weight: 2,
                radius: 9
            }).addTo(mapaGeografico);

            circle.bindPopup(`<b>${escola.nome}</b><br>Engajamento: ${fmtPct(escola.engajamento_pct)}`);
            marcadoresMapa.push(circle);
        }
    });

    // Foca a região certa pro filtro de instituição selecionado — com
    // animação suave (focarBrasil/focarDF/focarSP), não um corte seco.
    focarRegiao(INSTITUICAO_PARA_REGIAO[instituicaoId] || 'brasil');
}

// --- Renderização de Gráficos (Chart.js) ---
function renderizarGraficos(dadosEscolas, dadosModulos) {
    // Ranking de verdade: ordena por % de engajamento (não por
    // quantidade de inscritos, que é só o tamanho da turma) — assim o
    // gráfico mostra quem está engajando melhor, do topo pra base.
    const escolasRankeadas = [...dadosEscolas].sort((a, b) => b.engajamento_pct - a.engajamento_pct);

    // Gráfico de Ranking de Escolas
    const ctxEscolas = document.getElementById('cEngajamentoEscola');
    if (chartEscolas) chartEscolas.destroy();

    chartEscolas = new Chart(ctxEscolas, {
        type: 'bar',
        data: {
            labels: escolasRankeadas.map(e => e.nome),
            datasets: [{
                label: '% de Engajamento',
                data: escolasRankeadas.map(e => e.engajamento_pct),
                backgroundColor: escolasRankeadas.map((_, i) => PALETA[i % PALETA.length]),
                borderRadius: 8,
                maxBarThickness: 42
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { display: false } },
                y: { grid: { color: '#E5E7EB' }, beginAtZero: true, max: 100 }
            }
        }
    });

    // Gráfico de Módulos/Trilhas
    const ctxTrilhas = document.getElementById('cTrilhas');
    if (chartTrilhas) chartTrilhas.destroy();

    chartTrilhas = new Chart(ctxTrilhas, {
        type: 'doughnut',
        data: {
            labels: dadosModulos.map(m => m.nome),
            datasets: [{
                data: dadosModulos.map(m => m.total_alunos),
                backgroundColor: [NAVY, CYAN, ORANGE, MAGENTA],
                borderWidth: 2,
                borderColor: '#FFFFFF'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, padding: 14 } } }
        }
    });
}

// --- Renderização da Tabela de Turmas ---
function renderizarTabelaTurmas(turmas) {
    const tbody = document.querySelector('#tabela-turmas tbody');
    tbody.innerHTML = ''; // Limpa a tabela

    turmas.forEach(t => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td style="font-weight: 600; color: ${NAVY};">${t.nome}</td>
            <td>${t.escola}</td>
            <td>${fmtInt(t.total_alunos)}</td>
            <td>${fmtInt(t.alunos_engajados)}</td>
            <td>
                <div class="progress-track">
                    <div class="progress-fill" style="width: ${t.progresso_medio}%;"></div>
                </div>
                <small>${fmtPct(t.progresso_medio)}</small>
            </td>
            <td><button class="btn-ver-alunos" data-turma="${t.nome}">Ver Alunos</button></td>
        `;
        tbody.appendChild(tr);
    });
}

// --- Função Principal: Buscar e Atualizar o Dashboard ---
async function carregarDashboard(instituicaoId, trilhaId) {
    try {
        // Inicializa o mapa vazio na primeira carga
        inicializarMapa();

        // Bate na API real do seu backend Python!
        const res = await fetch(`${API_BASE}/dashboard?instituicao=${instituicaoId}&trilha=${trilhaId}`);

        if (!res.ok) {
            throw new Error(`Erro na API: ${res.status}`);
        }

        const dados = await res.json();

        // Atualiza KPIs com os dados reais do banco
        setKpi('kpi-escolas', fmtInt(dados.kpis.escolas));
        setKpi('kpi-inscritos', fmtInt(dados.kpis.inscritos));
        setKpi('kpi-engajados', fmtInt(dados.kpis.engajados));
        setKpi('kpi-taxa-engajamento', fmtPct(dados.kpis.taxa_engajamento));
        setKpi('kpi-taxa-retencao', fmtPct(dados.kpis.taxa_retencao));
        setKpi('kpi-pontuacao-media', fmtInt(dados.kpis.pontuacao_media));

        // Atualiza os destaques (concentração de alunos e módulo mais avançado)
        const destaque = dados.destaque || {};
        setKpi('destaque-inscritos', destaque.escola_mais_inscritos || '—');
        setKpi('destaque-engajados', destaque.escola_mais_engajados || '—');
        setKpi('destaque-modulo', destaque.modulo_destaque || '—');

        // Atualiza Mapa, Gráficos e Tabelas
        atualizarMapa(dados.escolas, instituicaoId);
        renderizarGraficos(dados.escolas, dados.modulos);
        renderizarTabelaTurmas(dados.turmas);

    } catch (err) {
        console.error('Falha ao carregar dados reais do backend:', err);
    }
}

// --- Modal: Relatório detalhado por turma ---
function abrirModalTurma(nomeTurma) {
    const modal = document.getElementById('modal-turma');
    modal.hidden = false;

    document.getElementById('modal-turma-nome').textContent = nomeTurma;
    document.getElementById('modal-turma-escola').textContent = 'Carregando...';
    document.getElementById('modal-resumo').innerHTML = '';
    document.querySelector('#tabela-alunos-turma tbody').innerHTML =
        '<tr><td colspan="4">Carregando alunos...</td></tr>';

    const params = `nome=${encodeURIComponent(nomeTurma)}`;
    document.getElementById('modal-baixar-pdf').href = `${API_BASE}/turma/relatorio/pdf?${params}`;
    document.getElementById('modal-baixar-excel').href = `${API_BASE}/turma/relatorio/excel?${params}`;

    fetch(`${API_BASE}/turma/relatorio?${params}`)
        .then(res => {
            if (!res.ok) throw new Error(`Erro na API: ${res.status}`);
            return res.json();
        })
        .then(dados => {
            document.getElementById('modal-turma-escola').textContent = dados.escola || '—';
            document.getElementById('modal-resumo').innerHTML = `
                <span><strong>${fmtInt(dados.total_alunos)}</strong>alunos</span>
                <span><strong>${fmtInt(dados.engajados)}</strong>engajados</span>
                <span><strong>${fmtInt(dados.concluintes)}</strong>concluintes</span>
            `;

            const tbody = document.querySelector('#tabela-alunos-turma tbody');
            tbody.innerHTML = '';

            if (!dados.alunos.length) {
                tbody.innerHTML = '<tr><td colspan="4">Nenhum aluno encontrado nesta turma.</td></tr>';
                return;
            }

            dados.alunos.forEach(a => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td style="font-weight: 600; color: ${ORANGE};">${a.posicao_na_turma}º</td>
                    <td style="font-weight: 600;">${a.nome}</td>
                    <td>${a.login}</td>
                    <td>
                        <div class="progress-track"><div class="progress-fill" style="width:${a.progresso_pct}%;"></div></div>
                        <small>${fmtPct(a.progresso_pct)}</small>
                    </td>
                    <td>${fmtInt(a.pontos)}</td>
                    <td>${fmtInt(a.moedas)}</td>
                    <td>${a.status}</td>
                `;
                tbody.appendChild(tr);
            });
        })
        .catch(err => {
            document.getElementById('modal-turma-escola').textContent = 'Não foi possível carregar os dados.';
            document.querySelector('#tabela-alunos-turma tbody').innerHTML = '';
            console.error('Falha ao carregar relatório da turma:', err);
        });
}

function fecharModalTurma() {
    document.getElementById('modal-turma').hidden = true;
}

// Event Listeners
document.addEventListener('DOMContentLoaded', () => {
    const selectFiltro = document.getElementById('instituicao-select');
    const selectTrilha = document.getElementById('trilha-select');

    // Carrega o painel inicialmente com os valores padrão dos filtros
    carregarDashboard(selectFiltro.value, selectTrilha.value);

    // Reage à mudança de qualquer um dos dois filtros
    selectFiltro.addEventListener('change', (e) => {
        carregarDashboard(e.target.value, selectTrilha.value);
    });
    selectTrilha.addEventListener('change', (e) => {
        carregarDashboard(selectFiltro.value, e.target.value);
    });

    // Delegação de clique: os botões "Ver Alunos" são recriados a cada carregamento
    document.querySelector('#tabela-turmas tbody').addEventListener('click', (e) => {
        const btn = e.target.closest('.btn-ver-alunos');
        if (btn) abrirModalTurma(btn.dataset.turma);
    });

    document.getElementById('modal-fechar').addEventListener('click', fecharModalTurma);
    document.getElementById('modal-turma').addEventListener('click', (e) => {
        if (e.target.id === 'modal-turma') fecharModalTurma(); // clique fora do card fecha o modal
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') fecharModalTurma();
    });
});