// ============================================================
// Integração do Dashboard Saldo+
// Paleta oficial (extraída do CSS publicado em osaldopositivo.com.br):
// Navy, Teal, Laranja, Rosa, Roxo
// ============================================================

const API_BASE = 'https://dados-periodicos.onrender.com/api/v1';
const NAVY = '#002364', TEAL = '#00B4AA', ORANGE = '#EC8322', PINK = '#FC027D', PURPLE = '#605BE5';

Chart.defaults.font.family = "'Poppins', system-ui, sans-serif";
Chart.defaults.color = '#6B7192';

const PALETA = [TEAL, ORANGE, PINK, PURPLE, '#10B981', NAVY];

let chartEscolas = null;
let chartTrilhas = null;
let mapaGeografico = null;
let marcadoresMapa = [];

// Funções utilitárias de formatação
const fmtInt = (num) => new Intl.NumberFormat('pt-BR').format(num || 0);
const fmtPct = (num) => (num || 0).toFixed(1) + '%';
function setKpi(id, text) { const el = document.getElementById(id); if (el) el.textContent = text; }

// O filtro superior é um único select combinando trilha + instituição
// (ex: "41:secretaria" = Trilha Saldo+ SEEDF) — a Pocket não tem
// separação por instituição hoje, só a Saldo+ precisa disso.
function lerFiltroSelecionado() {
    const [trilha, instituicao] = document.getElementById('filtro-select').value.split(':');
    return { trilha, instituicao };
}

// --- Regiões e limites geográficos do mapa ---
const REGIOES_MAPA = {
    brasil: { center: [-14.235, -51.9253], zoom: 4 },
    df: { center: [-15.7939, -47.8828], zoom: 10 },
    sp: { center: [-23.5505, -46.6333], zoom: 10 },
};
const INSTITUICAO_PARA_REGIAO = { todas: 'brasil', secretaria: 'df', cvp: 'sp' };

const LIMITES_BRASIL = [
    [-35.0, -75.0],
    [6.0, -32.0],
];

// --- Inicialização do Mapa (Leaflet.js) ---
function inicializarMapa() {
    if (!mapaGeografico) {
        mapaGeografico = L.map('mapa-escolas', {
            center: REGIOES_MAPA.brasil.center,
            zoom: REGIOES_MAPA.brasil.zoom,
            minZoom: 4,
            maxZoom: 12,
            maxBounds: LIMITES_BRASIL,
            maxBoundsViscosity: 1.0,
        });

        // CartoDB Positron (light_all) passou a exigir cadastro/API key
        // pra servir os tiles — sem ela, o CDN deles devolve um tile com
        // marca d'água "API KEY REQUIRED" no lugar do mapa. OSM padrão não
        // exige chave nenhuma.
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors',
            subdomains: 'abc',
            maxZoom: 19
        }).addTo(mapaGeografico);
    }
}

function focarRegiao(chave) {
    const regiao = REGIOES_MAPA[chave] || REGIOES_MAPA.brasil;
    mapaGeografico.flyTo(regiao.center, regiao.zoom, { duration: 1.2 });
}

function atualizarMapa(dadosEscolas, instituicaoId) {
    if (!mapaGeografico) return; // inicializarMapa() falhou — resto do dashboard segue sem mapa
    marcadoresMapa.forEach(m => mapaGeografico.removeLayer(m));
    marcadoresMapa = [];

    dadosEscolas.forEach(escola => {
        if (escola.lat && escola.lng) {
            const cor = escola.engajamento_pct > 70 ? TEAL : (escola.engajamento_pct > 40 ? ORANGE : PINK);

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

    // Só reenquadra na primeira carga de cada filtro de instituição —
    // se o usuário já deu zoom/pan no mapa manualmente, trocar de trilha
    // (que não afeta a região) não deveria "chutar" a visão dele de volta.
    if (atualizarMapa._ultimaInstituicao !== instituicaoId) {
        focarRegiao(INSTITUICAO_PARA_REGIAO[instituicaoId] || 'brasil');
        atualizarMapa._ultimaInstituicao = instituicaoId;
    }
}

function alternarEstadoVazio(idCanvas, temDado) {
    const canvas = document.getElementById(idCanvas);
    const vazio = document.getElementById(`empty-${idCanvas}`);
    if (canvas) canvas.hidden = !temDado;
    if (vazio) vazio.hidden = temDado;
}

// Gera uma frase curta e honesta a partir do ranking de escolas — nunca
// inventa número, só descreve o que já está no gráfico.
function gerarInsightEscolas(escolas) {
    const el = document.getElementById('insight-escolas');
    if (!el) return;
    if (!escolas.length) { el.hidden = true; return; }

    const comEngajamento = escolas.filter(e => e.engajados > 0);
    const lider = [...escolas].sort((a, b) => b.engajamento_pct - a.engajamento_pct)[0];

    let texto;
    if (comEngajamento.length === 0) {
        texto = `Nenhuma escola tem aluno engajado ainda neste filtro — os ${escolas.length} inscritos ainda não começaram a trilha.`;
    } else if (comEngajamento.length === 1) {
        texto = `<strong>${lider.nome}</strong> concentra todo o engajamento real até agora (${fmtPct(lider.engajamento_pct)}) — as outras ${escolas.length - 1} escolas têm alunos inscritos, mas nenhum começou a trilha.`;
    } else {
        texto = `<strong>${lider.nome}</strong> lidera com ${fmtPct(lider.engajamento_pct)} de engajamento, entre ${comEngajamento.length} de ${escolas.length} escolas já com algum aluno engajado.`;
    }
    el.innerHTML = texto;
    el.hidden = false;
}

// --- Renderização de Gráficos (Chart.js) ---
function renderizarGraficos(dadosEscolas, dadosModulos) {
    alternarEstadoVazio('cEngajamentoEscola', dadosEscolas.length > 0);
    alternarEstadoVazio('cTrilhas', dadosModulos.length > 0);
    gerarInsightEscolas(dadosEscolas);

    if (chartEscolas) { chartEscolas.destroy(); chartEscolas = null; }
    if (chartTrilhas) { chartTrilhas.destroy(); chartTrilhas = null; }

    if (dadosEscolas.length) {
        const escolasRankeadas = [...dadosEscolas].sort((a, b) => b.engajamento_pct - a.engajamento_pct);
        chartEscolas = new Chart(document.getElementById('cEngajamentoEscola'), {
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
                    y: { grid: { color: '#E4E6F0' }, beginAtZero: true, max: 100 }
                }
            }
        });
    }

    if (dadosModulos.length) {
        chartTrilhas = new Chart(document.getElementById('cTrilhas'), {
            type: 'doughnut',
            data: {
                labels: dadosModulos.map(m => m.nome),
                datasets: [{
                    data: dadosModulos.map(m => m.total_alunos),
                    backgroundColor: [NAVY, TEAL, PINK, ORANGE, PURPLE],
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
}

// --- Renderização da Tabela de Turmas ---
function renderizarTabelaTurmas(turmas) {
    const tbody = document.querySelector('#tabela-turmas tbody');
    tbody.innerHTML = '';

    if (!turmas.length) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6">
                    <div class="empty-state">Nenhuma turma com dado disponível para esse filtro ainda.</div>
                </td>
            </tr>`;
        return;
    }

    turmas.forEach(t => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td style="font-weight: 700; color: ${NAVY};">${t.nome}</td>
            <td>${t.escola}</td>
            <td class="num">${fmtInt(t.total_alunos)}</td>
            <td class="num">${fmtInt(t.alunos_engajados)}</td>
            <td>
                <div class="progress-cel">
                    <div class="progress-track" style="width:100px;"><div class="progress-fill" style="width: ${t.progresso_medio}%;"></div></div>
                    <small class="num">${fmtPct(t.progresso_medio)}</small>
                </div>
            </td>
            <td><button class="btn-ver-alunos" data-turma="${t.nome}">Ver Alunos</button></td>
        `;
        tbody.appendChild(tr);
    });
}

// --- Sistema de Alertas ---
let chartAlertasEscola = null;
let chartAlertasMotivo = null;

// escolasInfo vem da mesma resposta de /dashboard já carregada (tem o
// total de inscritos por escola) — usado só pra calcular o % em alerta
// de cada escola, casando pelo nome (mesma função get_school_display_name
// dos dois lados, então o nome sempre bate).
function renderizarResumoAlertasPorEscola(porEscola, escolasInfo) {
    const inscritosPorEscola = {};
    (escolasInfo || []).forEach(e => { inscritosPorEscola[e.nome] = e.inscritos; });

    const escolasOrdenadas = Object.entries(porEscola)
        .sort((a, b) => b[1].total_em_alerta - a[1].total_em_alerta);

    alternarEstadoVazio('cAlertasEscola', escolasOrdenadas.length > 0);
    if (chartAlertasEscola) { chartAlertasEscola.destroy(); chartAlertasEscola = null; }

    const elInsight = document.getElementById('insight-alertas-escola');
    const tbody = document.querySelector('#tabela-alertas-escola tbody');

    if (!escolasOrdenadas.length) {
        if (elInsight) elInsight.hidden = true;
        tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state">Nenhum aluno em alerta para esse filtro — tudo em dia.</div></td></tr>`;
        return;
    }

    chartAlertasEscola = new Chart(document.getElementById('cAlertasEscola'), {
        type: 'bar',
        data: {
            labels: escolasOrdenadas.map(([nome]) => nome),
            datasets: [{
                data: escolasOrdenadas.map(([, r]) => r.total_em_alerta),
                backgroundColor: PINK,
                borderRadius: 8,
                maxBarThickness: 34,
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: { x: { grid: { display: false } }, y: { grid: { color: '#E4E6F0' }, beginAtZero: true } }
        }
    });

    // Insight dinâmico: a escola com mais alunos em alerta, com o
    // motivo por extenso — nunca inventa número, só descreve o pior caso.
    const [piorNome, piorResumo] = escolasOrdenadas[0];
    const totalDaEscola = inscritosPorEscola[piorNome];
    const trechoTotal = totalDaEscola ? ` de ${fmtInt(totalDaEscola)} inscritos` : '';
    if (elInsight) {
        elInsight.innerHTML = `<strong>${piorNome}</strong> é a escola com mais alertas: ${fmtInt(piorResumo.total_em_alerta)}${trechoTotal} alunos nunca acessaram ou estão sem acesso há mais de 10 dias.`;
        elInsight.hidden = false;
    }

    tbody.innerHTML = '';
    escolasOrdenadas.forEach(([nome, r]) => {
        const total = inscritosPorEscola[nome];
        const pct = total ? (100 * r.total_em_alerta / total) : null;
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td style="font-weight:700;color:${NAVY};">${nome}</td>
            <td class="num">${total !== undefined ? fmtInt(total) : '—'}</td>
            <td class="num">${fmtInt(r.total_em_alerta)}</td>
            <td class="num">${pct !== null ? fmtPct(pct) : '—'}</td>
            <td class="num">${fmtInt(r.nunca_acessou)}</td>
            <td class="num">${fmtInt(r.inativo_recente)}</td>
        `;
        tbody.appendChild(tr);
    });
}

function renderizarGraficoMotivoAlerta(totalNuncaAcessou, totalInativoRecente) {
    const temDado = (totalNuncaAcessou + totalInativoRecente) > 0;
    alternarEstadoVazio('cAlertasMotivo', temDado);
    if (chartAlertasMotivo) { chartAlertasMotivo.destroy(); chartAlertasMotivo = null; }
    if (!temDado) return;

    chartAlertasMotivo = new Chart(document.getElementById('cAlertasMotivo'), {
        type: 'doughnut',
        data: {
            labels: ['Nunca acessaram', 'Sem acesso há mais de 10 dias'],
            datasets: [{
                data: [totalNuncaAcessou, totalInativoRecente],
                backgroundColor: [PURPLE, ORANGE],
                borderWidth: 2, borderColor: '#FFFFFF',
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, padding: 14 } } }
        }
    });
}

async function carregarAlertas(instituicaoId, escolasInfo) {
    const tbody = document.querySelector('#tabela-alertas tbody');
    try {
        const res = await fetch(`${API_BASE}/alertas?instituicao=${instituicaoId}`);
        if (!res.ok) throw new Error(`Erro na API: ${res.status}`);
        const dados = await res.json();

        setKpi('alertas-total', `${fmtInt(dados.total_em_alerta)} aluno(s) em alerta`);

        const porEscola = dados.por_escola || {};
        renderizarResumoAlertasPorEscola(porEscola, escolasInfo);

        const totalNuncaAcessou = Object.values(porEscola).reduce((s, r) => s + r.nunca_acessou, 0);
        const totalInativoRecente = Object.values(porEscola).reduce((s, r) => s + r.inativo_recente, 0);
        renderizarGraficoMotivoAlerta(totalNuncaAcessou, totalInativoRecente);

        if (!dados.alertas.length) {
            tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state">Nenhum aluno em alerta para esse filtro — tudo em dia.</div></td></tr>`;
            return;
        }

        tbody.innerHTML = '';
        dados.alertas.forEach(a => {
            const tr = document.createElement('tr');
            const rotuloInstituicao = a.instituicao === 'cvp' ? 'CVP' : 'Secretaria de Educação';
            tr.innerHTML = `
                <td style="font-weight:600;">${a.nome}</td>
                <td>${a.escola}</td>
                <td>${a.turma}</td>
                <td>${rotuloInstituicao}</td>
                <td><span class="pill-status pill-alerta">${a.motivo_alerta}</span></td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error('Falha ao carregar Sistema de Alertas:', err);
        tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state">Não foi possível carregar os alertas agora.</div></td></tr>`;
    }
}

// Usuários ativos na última semana não é por trilha (last_access é o
// último login na Ludos como um todo, não num curso específico).
async function carregarUsuariosAtivos(instituicaoId) {
    try {
        const res = await fetch(`${API_BASE}/usuarios-ativos-semana?instituicao=${instituicaoId}`);
        if (!res.ok) throw new Error(`Erro na API: ${res.status}`);
        const dados = await res.json();

        setKpi('kpi-ativos-semana', fmtInt(dados.ativos_ultima_semana));

        const elVariacao = document.getElementById('kpi-ativos-semana-variacao');
        if (elVariacao) {
            if (dados.variacao_pct === null || dados.variacao_pct === undefined) {
                elVariacao.textContent = '';
            } else {
                const sinal = dados.variacao_pct >= 0 ? '+' : '';
                elVariacao.textContent = `${sinal}${dados.variacao_pct}% vs. semana anterior`;
            }
        }
    } catch (err) {
        console.error('Falha ao carregar usuários ativos na última semana:', err);
    }
}

// --- Função Principal: Buscar e Atualizar o Dashboard ---
async function carregarDashboard(instituicaoId, trilhaId) {
    // Isolado do try principal: se o Leaflet falhar por qualquer motivo
    // (ex: instabilidade no CDN), isso não pode derrubar a atualização
    // dos KPIs/tabelas/gráficos, que não dependem do mapa.
    try {
        inicializarMapa();
    } catch (err) {
        console.error('Falha ao inicializar o mapa:', err);
    }

    try {
        const res = await fetch(`${API_BASE}/dashboard?instituicao=${instituicaoId}&trilha=${trilhaId}`);

        if (!res.ok) {
            throw new Error(`Erro na API: ${res.status}`);
        }

        const dados = await res.json();

        carregarUsuariosAtivos(instituicaoId);
        carregarAlertas(instituicaoId, dados.escolas);

        setKpi('kpi-escolas', fmtInt(dados.kpis.escolas));
        setKpi('kpi-turmas', fmtInt((dados.turmas || []).length));
        setKpi('kpi-inscritos', fmtInt(dados.kpis.inscritos));
        setKpi('kpi-engajados', fmtInt(dados.kpis.engajados));
        setKpi('kpi-taxa-engajamento', fmtPct(dados.kpis.taxa_engajamento));
        setKpi('kpi-taxa-retencao', fmtPct(dados.kpis.taxa_retencao));
        setKpi('kpi-pontuacao-media', fmtInt(dados.kpis.pontuacao_media));

        const destaque = dados.destaque || {};
        setKpi('destaque-inscritos', destaque.escola_mais_inscritos || '—');
        setKpi('destaque-engajados', destaque.escola_mais_engajados || '—');
        setKpi('destaque-modulo', destaque.modulo_destaque || '—');

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

    const { trilha: trilhaId } = lerFiltroSelecionado();
    const params = `nome=${encodeURIComponent(nomeTurma)}&trilha=${encodeURIComponent(trilhaId)}`;
    document.getElementById('modal-baixar-pdf').href = `${API_BASE}/turma/relatorio/pdf?${params}`;
    document.getElementById('modal-baixar-excel').href = `${API_BASE}/turma/relatorio/excel?${params}`;

    fetch(`${API_BASE}/turma/relatorio?${params}`)
        .then(res => {
            if (!res.ok) throw new Error(`Erro na API: ${res.status}`);
            return res.json();
        })
        .then(dados => {
            document.getElementById('modal-turma-escola').textContent =
                dados.escola ? `${dados.escola} · ${dados.trilha}` : (dados.trilha || '—');
            document.getElementById('modal-resumo').innerHTML = `
                <span><strong>${fmtInt(dados.total_alunos)}</strong>alunos</span>
                <span><strong>${fmtInt(dados.engajados)}</strong>engajados</span>
                <span><strong>${fmtInt(dados.concluintes)}</strong>concluintes</span>
            `;

            const tbody = document.querySelector('#tabela-alunos-turma tbody');
            tbody.innerHTML = '';

            if (!dados.alunos.length) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="7">
                            <div class="empty-state">Nenhum aluno encontrado nesta turma.</div>
                        </td>
                    </tr>`;
                return;
            }

            dados.alunos.forEach(a => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td style="font-weight: 700; color: ${ORANGE};">${a.posicao_na_turma}º</td>
                    <td style="font-weight: 600;">${a.nome}</td>
                    <td>${a.login}</td>
                    <td>
                        <div class="progress-cel">
                            <div class="progress-track" style="width:80px;"><div class="progress-fill" style="width:${a.progresso_pct}%;"></div></div>
                            <small class="num">${fmtPct(a.progresso_pct)}</small>
                        </div>
                    </td>
                    <td class="num">${fmtInt(a.pontos)}</td>
                    <td class="num">${fmtInt(a.moedas)}</td>
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

// --- Abas ---
function ativarAba(nomePagina) {
    document.querySelectorAll('.aba-btn').forEach(b => {
        const ativa = b.dataset.pagina === nomePagina;
        b.classList.toggle('ativa', ativa);
        b.setAttribute('aria-selected', ativa ? 'true' : 'false');
    });
    document.querySelectorAll('.pagina').forEach(p => p.classList.remove('ativa'));
    const alvo = document.getElementById('pg-' + nomePagina);
    if (alvo) alvo.classList.add('ativa');
}

// Event Listeners
document.addEventListener('DOMContentLoaded', () => {
    const selectUnico = document.getElementById('filtro-select');

    const { trilha: trilhaInicial, instituicao: instituicaoInicial } = lerFiltroSelecionado();
    carregarDashboard(instituicaoInicial, trilhaInicial);

    selectUnico.addEventListener('change', () => {
        const { trilha, instituicao } = lerFiltroSelecionado();
        carregarDashboard(instituicao, trilha);
    });

    document.querySelectorAll('.aba-btn').forEach(btn => {
        btn.addEventListener('click', () => ativarAba(btn.dataset.pagina));
    });

    document.querySelector('#tabela-turmas tbody').addEventListener('click', (e) => {
        const btn = e.target.closest('.btn-ver-alunos');
        if (btn) abrirModalTurma(btn.dataset.turma);
    });

    document.getElementById('modal-fechar').addEventListener('click', fecharModalTurma);
    document.getElementById('modal-turma').addEventListener('click', (e) => {
        if (e.target.id === 'modal-turma') fecharModalTurma();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') fecharModalTurma();
    });
});
