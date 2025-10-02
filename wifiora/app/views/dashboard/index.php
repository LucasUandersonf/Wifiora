<?php require __DIR__ . '/../partials/header.php'; ?>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

<style>
   

    main {
        padding: 20px;
    }

    .overview h1 {
        text-align: center;
        margin-top: 30px;
        color: #333;
    }

    .stats-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 20px;
        padding: 30px 0;
    }

    .card {
        background: #fff;
        border-radius: 10px;
        box-shadow: 0 4px 8px #0000000d;
        padding: 20px;
        text-align: center;
        transition: transform 0.2s;
    }

    .card:hover {
        transform: translateY(-5px);
    }

    .card h2 {
        font-size: 1rem;
        color: #666;
        margin-bottom: 10px;
    }

    .card .value {
        font-size: 2rem;
        font-weight: bold;
        color: #007bff;
    }

    .charts {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
        gap: 30px;
        padding: 0 0 50px;
    }

    .chart-card {
        background: #fff;
        border-radius: 10px;
        padding: 20px;
        box-shadow: 0 4px 8px rgba(0,0,0,0.05);
    }

    .chart-card h3 {
        margin-bottom: 20px;
        color: #333;
        text-align: center;
    }

    canvas {
        width: 100% !important;
        height: auto !important;
    }
</style>

<main>
    <section class="overview">
        <h1>📊 Visão Geral</h1>
        <div class="stats-grid">
            <div class="card">
                <h2>👥 Visitantes Online</h2>
                <p class="value"><?= $online_count ?></p>
            </div>
            <div class="card">
                <h2>📝 Visitantes Cadastrados</h2>
                <p class="value"><?= $registered_count ?></p>
            </div>
            <div class="card">
                <h2>📅 Visitas Hoje</h2>
                <p class="value"><?= $today_visits_count ?></p>
            </div>
            <div class="card">
                <h2>📡 Pontos de Acesso</h2>
                <p class="value"><?= $access_points_count ?></p>
            </div>
        </div>
    </section>

    <section class="charts">
        <div class="chart-card">
            <h3>📈 Visitas nos Últimos 7 Dias</h3>
            <canvas id="visitsChart"></canvas>
        </div>

        <div class="chart-card">
            <h3>🔌 Acessos por Local</h3>
            <canvas id="accessChart"></canvas>
        </div>
    </section>
</main>

<script>
    // Dados PHP -> JS
    const visitsData = <?= $visitsByDayJson ?>;
    const accessLabels = <?= $accessLabelsJson ?>;
    const accessCounts = <?= $accessCountsJson ?>;

    // Gráfico 1: Visitas por dia
    new Chart(document.getElementById('visitsChart'), {
        type: 'line',
        data: {
            labels: ['6 dias atrás', '5', '4', '3', '2', 'Ontem', 'Hoje'],
            datasets: [{
                label: 'Visitas',
                data: visitsData,
                borderColor: '#007bff',
                backgroundColor: 'rgba(0,123,255,0.2)',
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            plugins: { legend: { display: false } },
            scales: { y: { beginAtZero: true } }
        }
    });

    // Gráfico 2: Acessos por local
    new Chart(document.getElementById('accessChart'), {
        type: 'doughnut',
        data: {
            labels: accessLabels,
            datasets: [{
                data: accessCounts,
                backgroundColor: ['#28a745', '#ffc107', '#17a2b8', '#dc3545', '#6f42c1', '#fd7e14']
            }]
        },
        options: {
            responsive: true,
            plugins: { legend: { position: 'bottom' } }
        }
    });
</script>

<?php require __DIR__ . '/../partials/footer.php'; ?>
